#!/usr/bin/env python3
"""Prove a production CDC path through the reconciled local Kubernetes cluster."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Never
from uuid import UUID

_TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from api.client import NohikiClient  # noqa: E402

BFF_DATABASE = "bff_db"
BFF_POD_SELECTOR = "app.kubernetes.io/name=bff-service"
BFF_SCHEMA = "bff_schema"
CANONICAL_TOPIC = "user-auth.cdc.account-updated.v1"
CONNECT_DEPLOYMENT = "nohiki-connect-connect"
CONNECT_NAME = "nohiki-connect"
CONNECTOR_NAME = "user-auth-service-outbox"
DEBEZIUM_CREDENTIALS_RESOURCE = "user-auth-service-debezium-credentials"
DEBEZIUM_MOUNT = "/mnt/secrets/user-auth-service-debezium"
EVIDENCE_SCHEMA_VERSION = 2
KAFKA_BOOTSTRAP_SERVICE = "nohiki-kafka-kafka-bootstrap"
POSTGRES_CLUSTER = "nohiki-pg"
PROJECTION_TABLE = "account_projections"
SERVICE_CREDENTIALS_RESOURCE = "user-auth-service-db-credentials"

ABSENT_DEPLOYMENT_MESSAGE = (
    "CDC_DEPLOYMENT_ABSENT: required deployed CDC resources are absent; reconcile the local platform first"
)
DELIVERY_TIMEOUT_MESSAGE = "CDC_DELIVERY_TIMEOUT: the canonical connector did not deliver the correlated service event"
PROJECTION_TIMEOUT_MESSAGE = (
    "CDC_PROJECTION_TIMEOUT: the registered BFF consumer did not durably project the correlated service event"
)


class CdcProofError(RuntimeError):
    """Base error for a failed live CDC proof."""


class CdcDeploymentAbsentError(CdcProofError):
    """The stable deployed CDC surface does not exist."""


class CdcDeliveryTimeoutError(CdcProofError):
    """The stable connector did not deliver a correlated canonical record."""


class CdcConsumerExecutionError(CdcProofError):
    """The in-cluster canonical consumer could not execute."""


class CdcProjectionTimeoutError(CdcProofError):
    """The registered downstream consumer did not persist its projection."""


def _error[E: Exception](error_type: type[E], message: str) -> E:
    return error_type(message)


@dataclass(frozen=True, slots=True)
class AccountProbe:
    phase: str
    token: str
    email: str
    password: str
    display_name: str

    @classmethod
    def create(cls, phase: str) -> AccountProbe:
        token = secrets.token_hex(8)
        return cls(
            phase=phase,
            token=token,
            email=f"cdc-{phase}-{token}@example.invalid",
            password=secrets.token_urlsafe(24),
            display_name=f"CDC {phase} {token}",
        )


@dataclass(frozen=True, slots=True)
class CanonicalObservation:
    phase: str
    topic: str
    partition: int
    offset: int
    value_bytes: int
    key_sha256: str
    event_id: str
    source_service: str


@dataclass(frozen=True, slots=True)
class ProjectionObservation:
    phase: str
    row_count: int
    user_id_sha256: str


@dataclass(slots=True)
class RestartEvidence:
    deployment: str = CONNECT_DEPLOYMENT
    completed: bool = False
    connector_running: bool = False


@dataclass(slots=True)
class CleanupEvidence:
    accounts_deleted: int = 0
    projections_deleted: int = 0
    errors: list[str] = field(default_factory=list)


def _run(
    args: list[str],
    *,
    input_text: str | None = None,
    timeout: float = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            input=input_text,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        message = f"CDC_PROOF_FAILED: command execution failed: {args[0]}"
        raise _error(CdcProofError, message) from exc
    if check and result.returncode != 0:
        message = f"CDC_PROOF_FAILED: command returned {result.returncode}: {args[0]}"
        raise _error(CdcProofError, message)
    return result


def _kubectl(
    namespace: str,
    *args: str,
    input_text: str | None = None,
    timeout: float = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(
        ["kubectl", "--namespace", namespace, *args],
        input_text=input_text,
        timeout=timeout,
        check=check,
    )


def _require_deployed_resource(namespace: str, resource: str) -> None:
    result = _kubectl(namespace, "get", resource, "--output=name", check=False)
    if result.returncode == 0 and result.stdout.strip():
        return
    raise _error(CdcDeploymentAbsentError, ABSENT_DEPLOYMENT_MESSAGE)


def _decode_secret_username(namespace: str, resource: str) -> str:
    result = _kubectl(namespace, "get", f"secret/{resource}", "--output=json")
    document = json.loads(result.stdout)
    encoded = document.get("data", {}).get("username")
    if not isinstance(encoded, str):
        message = f"CDC_PROOF_FAILED: {resource} has no mounted principal username"
        raise _error(CdcProofError, message)
    try:
        return base64.b64decode(encoded, validate=True).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        message = f"CDC_PROOF_FAILED: {resource} has an invalid principal username"
        raise _error(CdcProofError, message) from exc


def _validate_connector_document(document: dict[str, object]) -> None:
    spec = document.get("spec")
    if not isinstance(spec, dict):
        raise _error(CdcProofError, "CDC_PROOF_FAILED: canonical connector has no spec")
    config = spec.get("config")
    if not isinstance(config, dict):
        raise _error(CdcProofError, "CDC_PROOF_FAILED: canonical connector has no config")
    expected_user = f"${{file:{DEBEZIUM_MOUNT}/username}}"
    expected_password = f"${{file:{DEBEZIUM_MOUNT}/password}}"
    if config.get("database.user") != expected_user or config.get("database.password") != expected_password:
        raise _error(CdcProofError, "CDC_PROOF_FAILED: canonical connector bypasses mounted replication credentials")
    if config.get("table.include.list") != "user_auth_schema.outbox":
        raise _error(CdcProofError, "CDC_PROOF_FAILED: canonical connector is not scoped to the service outbox")
    if config.get("transforms.outbox.route.by.field") != "type":
        raise _error(CdcProofError, "CDC_PROOF_FAILED: canonical connector does not route canonical event topics")


def require_cdc_deployment(namespace: str) -> None:
    """Require the production connector, services, and separate database principals."""
    for resource in (
        f"kafkaconnect.kafka.strimzi.io/{CONNECT_NAME}",
        f"deployment.apps/{CONNECT_DEPLOYMENT}",
        f"kafkaconnector.kafka.strimzi.io/{CONNECTOR_NAME}",
        f"service/{KAFKA_BOOTSTRAP_SERVICE}",
        "deployment.apps/nohiki-user-auth-service",
        "deployment.apps/nohiki-bff-service",
        f"cluster.postgresql.cnpg.io/{POSTGRES_CLUSTER}",
        f"secret/{SERVICE_CREDENTIALS_RESOURCE}",
        f"secret/{DEBEZIUM_CREDENTIALS_RESOURCE}",
    ):
        _require_deployed_resource(namespace, resource)

    connector = _kubectl(
        namespace,
        "get",
        f"kafkaconnector.kafka.strimzi.io/{CONNECTOR_NAME}",
        "--output=json",
    )
    _validate_connector_document(json.loads(connector.stdout))
    writer_principal = _decode_secret_username(namespace, SERVICE_CREDENTIALS_RESOURCE)
    replication_principal = _decode_secret_username(namespace, DEBEZIUM_CREDENTIALS_RESOURCE)
    if writer_principal == replication_principal:
        raise _error(CdcProofError, "CDC_PROOF_FAILED: service DML and replication principals are not separated")


def _first_pod(namespace: str, selector: str) -> str | None:
    result = _kubectl(namespace, "get", "pods", "--selector", selector, "--output=json")
    document = json.loads(result.stdout)
    names = [
        item["metadata"]["name"]
        for item in document.get("items", [])
        if item.get("status", {}).get("phase") == "Running"
    ]
    return names[0] if names else None


def _primary_pod(namespace: str) -> str:
    pod = _first_pod(namespace, f"cnpg.io/cluster={POSTGRES_CLUSTER},role=primary")
    if pod is None:
        raise _error(CdcProofError, "CDC_PROOF_FAILED: PostgreSQL primary pod is unavailable")
    return pod


def _admin_query(namespace: str, pod: str, database: str, sql: str) -> str:
    result = _kubectl(
        namespace,
        "exec",
        "--stdin",
        pod,
        "--",
        "psql",
        "--dbname",
        database,
        "--set=ON_ERROR_STOP=1",
        "--no-psqlrc",
        "--tuples-only",
        "--no-align",
        input_text=sql,
    )
    return result.stdout.strip()


def _projection_count(namespace: str, pod: str, user_id: UUID, probe: AccountProbe) -> int:
    sql = (
        f"SELECT count(*) FROM {BFF_SCHEMA}.{PROJECTION_TABLE} "  # noqa: S608
        f"WHERE id = '{user_id}'::uuid AND email = '{probe.email}' "
        f"AND display_name = '{probe.display_name}';\n"
    )
    output = _admin_query(namespace, pod, BFF_DATABASE, sql)
    try:
        return int(output)
    except ValueError as exc:
        raise _error(CdcProofError, "CDC_PROOF_FAILED: projection cardinality query returned invalid output") from exc


def _wait_projection_count(
    namespace: str,
    pod: str,
    user_id: UUID,
    probe: AccountProbe,
    expected: int,
    timeout_seconds: float,
) -> int:
    deadline = time.monotonic() + timeout_seconds
    while True:
        count = _projection_count(namespace, pod, user_id, probe)
        if count == expected:
            return count
        if time.monotonic() >= deadline:
            raise _error(CdcProjectionTimeoutError, PROJECTION_TIMEOUT_MESSAGE)
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


def _consumer_script(user_id: UUID, probe: AccountProbe, group_id: str, timeout_seconds: float) -> str:
    expected = json.dumps(
        {
            "display_name": probe.display_name,
            "email": probe.email,
            "group_id": group_id,
            "timeout": timeout_seconds,
            "user_id": str(user_id),
        },
        separators=(",", ":"),
    )
    return f"""import asyncio
import hashlib
import json
from aiokafka import AIOKafkaConsumer
from nohiki.user.auth.v1 import AccountUpdated

EXPECTED = json.loads({expected!r})
TOPIC = {CANONICAL_TOPIC!r}
BOOTSTRAP = {f"{KAFKA_BOOTSTRAP_SERVICE}:9092"!r}

async def main():
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP,
        group_id=EXPECTED["group_id"],
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + EXPECTED["timeout"]
        while loop.time() < deadline:
            remaining_ms = max(1, min(1000, int((deadline - loop.time()) * 1000)))
            batches = await consumer.getmany(timeout_ms=remaining_ms, max_records=100)
            for records in batches.values():
                for record in records:
                    event = AccountUpdated().parse(record.value)
                    snapshot = event.account_snapshot
                    if event.user_id != EXPECTED["user_id"]:
                        continue
                    if snapshot is None:
                        raise RuntimeError("canonical account event omitted its snapshot")
                    if snapshot.id != EXPECTED["user_id"] or snapshot.email != EXPECTED["email"]:
                        raise RuntimeError("canonical account snapshot identity mismatch")
                    if snapshot.display_name != EXPECTED["display_name"]:
                        raise RuntimeError("canonical account snapshot state mismatch")
                    key = (record.key or b"").decode()
                    print(json.dumps({{
                        "status": "delivered",
                        "topic": record.topic,
                        "partition": record.partition,
                        "offset": record.offset,
                        "value_bytes": len(record.value),
                        "key": key,
                        "event_id": event.metadata.event_id if event.metadata else "",
                        "source_service": event.metadata.source_service if event.metadata else "",
                    }}, separators=(",", ":")))
                    return
        print('{{"status":"timeout"}}')
    finally:
        await consumer.stop()

asyncio.run(main())
"""


def _validate_canonical_observation(
    document: dict[str, object],
    *,
    user_id: UUID,
    phase: str,
) -> CanonicalObservation:
    if document.get("status") == "timeout":
        raise _error(CdcDeliveryTimeoutError, DELIVERY_TIMEOUT_MESSAGE)
    if document.get("status") != "delivered":
        raise _error(CdcConsumerExecutionError, "CDC_CONSUMER_FAILED: consumer returned an invalid result")
    if document.get("topic") != CANONICAL_TOPIC:
        raise _error(CdcConsumerExecutionError, "CDC_CONSUMER_FAILED: consumer observed a non-canonical topic")
    if document.get("key") != str(user_id):
        raise _error(
            CdcConsumerExecutionError,
            "CDC_CONSUMER_FAILED: canonical record key did not match the service entity",
        )
    if document.get("source_service") != "user-auth-service" or not document.get("event_id"):
        raise _error(CdcConsumerExecutionError, "CDC_CONSUMER_FAILED: canonical record metadata was incomplete")
    partition = document.get("partition")
    offset = document.get("offset")
    value_bytes = document.get("value_bytes")
    if not isinstance(partition, int) or not isinstance(offset, int) or not isinstance(value_bytes, int):
        raise _error(
            CdcConsumerExecutionError,
            "CDC_CONSUMER_FAILED: canonical record coordinates were invalid",
        )
    return CanonicalObservation(
        phase=phase,
        topic=CANONICAL_TOPIC,
        partition=partition,
        offset=offset,
        value_bytes=value_bytes,
        key_sha256=hashlib.sha256(str(user_id).encode()).hexdigest(),
        event_id=str(document["event_id"]),
        source_service="user-auth-service",
    )


def consume_canonical_account_event(
    namespace: str,
    user_id: UUID,
    probe: AccountProbe,
    timeout_seconds: float,
) -> CanonicalObservation:
    """Consume and parse the canonical protobuf event from an independent in-cluster group."""
    bff_pod = _first_pod(namespace, BFF_POD_SELECTOR)
    if bff_pod is None:
        raise _error(CdcConsumerExecutionError, "CDC_CONSUMER_FAILED: no BFF pod is available")
    group_id = f"cdc-acceptance-{probe.token}-{probe.phase}"
    result = _kubectl(
        namespace,
        "exec",
        "--stdin",
        bff_pod,
        "--",
        "python",
        "-",
        input_text=_consumer_script(user_id, probe, group_id, timeout_seconds),
        timeout=timeout_seconds + 30,
        check=False,
    )
    if result.returncode != 0:
        raise _error(CdcConsumerExecutionError, "CDC_CONSUMER_FAILED: in-cluster canonical consumer execution failed")
    try:
        document = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise _error(
            CdcConsumerExecutionError,
            "CDC_CONSUMER_FAILED: in-cluster consumer returned invalid output",
        ) from exc
    if not isinstance(document, dict):
        raise _error(CdcConsumerExecutionError, "CDC_CONSUMER_FAILED: in-cluster consumer returned invalid output")
    return _validate_canonical_observation(document, user_id=user_id, phase=probe.phase)


def _connector_is_running(document: dict[str, object]) -> bool:
    status = document.get("status")
    if not isinstance(status, dict):
        return False
    connector_status = status.get("connectorStatus")
    if not isinstance(connector_status, dict):
        return False
    connector = connector_status.get("connector")
    tasks = connector_status.get("tasks")
    if not isinstance(connector, dict) or connector.get("state") != "RUNNING":
        return False
    return (
        isinstance(tasks, list)
        and bool(tasks)
        and all(isinstance(task, dict) and task.get("state") == "RUNNING" for task in tasks)
    )


def _wait_connector_running(namespace: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        result = _kubectl(
            namespace,
            "get",
            f"kafkaconnector.kafka.strimzi.io/{CONNECTOR_NAME}",
            "--output=json",
            check=False,
        )
        if result.returncode == 0:
            document = json.loads(result.stdout)
            if _connector_is_running(document):
                return
        if time.monotonic() >= deadline:
            raise _error(CdcProofError, "CDC_PROOF_FAILED: canonical connector did not recover after Connect restart")
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def restart_connect(namespace: str, timeout_seconds: float) -> RestartEvidence:
    """Restart the actual Connect deployment and wait for the canonical connector to recover."""
    evidence = RestartEvidence()
    _kubectl(namespace, "rollout", "restart", f"deployment.apps/{CONNECT_DEPLOYMENT}")
    _kubectl(
        namespace,
        "rollout",
        "status",
        f"deployment.apps/{CONNECT_DEPLOYMENT}",
        f"--timeout={max(1, int(timeout_seconds))}s",
        timeout=timeout_seconds + 30,
    )
    evidence.completed = True
    _wait_connector_running(namespace, timeout_seconds)
    evidence.connector_running = True
    return evidence


def _register_account(client: NohikiClient, probe: AccountProbe) -> UUID:
    try:
        response = client.register(probe.email, probe.password, probe.display_name)
    except Exception as exc:
        raise _error(CdcProofError, "CDC_PROOF_FAILED: real user-auth registration transaction failed") from exc
    if response is None or not isinstance(response.get("id"), str):
        raise _error(CdcProofError, "CDC_PROOF_FAILED: real user-auth registration returned no account identity")
    try:
        return UUID(response["id"])
    except ValueError as exc:
        raise _error(
            CdcProofError,
            "CDC_PROOF_FAILED: real user-auth registration returned an invalid identity",
        ) from exc


def _cleanup_accounts(
    namespace: str,
    pod: str | None,
    accounts: list[tuple[AccountProbe, NohikiClient, UUID]],
    timeout_seconds: float,
) -> CleanupEvidence:
    evidence = CleanupEvidence()
    for probe, client, user_id in reversed(accounts):
        try:
            client.delete_account()
            evidence.accounts_deleted += 1
        except Exception:
            evidence.errors.append(f"{probe.phase}-account-delete")
            continue
        if pod is None:
            evidence.errors.append(f"{probe.phase}-projection-delete")
            continue
        try:
            _wait_projection_count(namespace, pod, user_id, probe, 0, timeout_seconds)
            evidence.projections_deleted += 1
        except CdcProofError:
            evidence.errors.append(f"{probe.phase}-projection-delete")
    return evidence


def _failure_class(error: CdcProofError | None) -> str | None:
    if isinstance(error, CdcDeploymentAbsentError):
        return "absent-deployment"
    if isinstance(error, CdcDeliveryTimeoutError):
        return "delivery-timeout"
    if isinstance(error, CdcConsumerExecutionError):
        return "consumer-execution"
    if isinstance(error, CdcProjectionTimeoutError):
        return "projection-timeout"
    if error is not None:
        return "proof-error"
    return None


def _write_evidence(
    path: Path,
    error: CdcProofError | None,
    observations: list[CanonicalObservation],
    projections: list[ProjectionObservation],
    restart: RestartEvidence,
    cleanup: CleanupEvidence,
) -> None:
    document = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "check": "live-cluster-cdc",
        "status": "failed" if error is not None else "passed",
        "failure_class": _failure_class(error),
        "canonical_topic": CANONICAL_TOPIC,
        "connector": CONNECTOR_NAME,
        "observed": [asdict(observation) for observation in observations],
        "projections": [asdict(projection) for projection in projections],
        "restart": asdict(restart),
        "cleanup": asdict(cleanup),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(path)


def run(namespace: str, base_url: str, evidence_path: Path, timeout_seconds: float) -> None:
    """Execute two real service transactions around a Kafka Connect restart."""
    accounts: list[tuple[AccountProbe, NohikiClient, UUID]] = []
    observations: list[CanonicalObservation] = []
    projections: list[ProjectionObservation] = []
    restart = RestartEvidence()
    cleanup = CleanupEvidence()
    pod: str | None = None
    error: CdcProofError | None = None
    cause: Exception | None = None
    try:
        require_cdc_deployment(namespace)
        pod = _primary_pod(namespace)
        for phase in ("before-restart", "after-restart"):
            if phase == "after-restart":
                restart = restart_connect(namespace, timeout_seconds)
            probe = AccountProbe.create(phase)
            client = NohikiClient(base_url)
            user_id = _register_account(client, probe)
            accounts.append((probe, client, user_id))
            observations.append(consume_canonical_account_event(namespace, user_id, probe, timeout_seconds))
            count = _wait_projection_count(namespace, pod, user_id, probe, 1, timeout_seconds)
            projections.append(
                ProjectionObservation(
                    phase=phase,
                    row_count=count,
                    user_id_sha256=hashlib.sha256(str(user_id).encode()).hexdigest(),
                )
            )
        for probe, _client, user_id in accounts:
            _wait_projection_count(namespace, pod, user_id, probe, 1, 0.001)
    except CdcProofError as exc:
        error = exc
    except Exception as exc:
        cause = exc
        error = CdcProofError(f"CDC_PROOF_FAILED: unexpected {type(exc).__name__}")
    finally:
        cleanup = _cleanup_accounts(namespace, pod, accounts, timeout_seconds)
        if error is None and cleanup.errors:
            error = CdcProofError("CDC_PROOF_FAILED: service cleanup was incomplete")
        _write_evidence(evidence_path, error, observations, projections, restart, cleanup)
    if error is not None:
        if cause is not None:
            raise error from cause
        raise error


def _positive_seconds(value: str) -> float:
    seconds = float(value)
    if seconds <= 0:
        raise _error(argparse.ArgumentTypeError, "must be greater than zero")
    return seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="nohiki")
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", "http://nohiki.localhost:8080"))
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=_positive_seconds, default=120.0)
    args = parser.parse_args(argv)
    run(args.namespace, args.base_url, args.evidence, args.timeout_seconds)
    return 0


def _entrypoint() -> Never:
    raise SystemExit(main())


if __name__ == "__main__":
    _entrypoint()
