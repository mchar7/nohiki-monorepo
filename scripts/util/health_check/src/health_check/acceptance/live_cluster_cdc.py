"""Prove a production CDC path through the reconciled local Kubernetes cluster."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Never, TypeGuard
from uuid import UUID

import httpx

BFF_DATABASE = "bff_db"
BFF_POD_SELECTOR = "app.kubernetes.io/name=bff-service"
BFF_SCHEMA = "bff_schema"
CANONICAL_TOPIC = "user-auth.cdc.account-updated.v1"
CONNECT_DEPLOYMENT = "nohiki-connect-connect"
CONNECT_NAME = "nohiki-connect"
CONNECTOR_NAME = "user-auth-service-outbox"
DEBEZIUM_CREDENTIALS_RESOURCE = "user-auth-service-debezium-credentials"
DEBEZIUM_MOUNT = "/mnt/secrets/user-auth-service-debezium"
EVIDENCE_SCHEMA_VERSION = 3
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
ACCEPTED_PRIVILEGE_LIMITATION = (
    "Debezium's distinct login is an attribution and independent-revocation control, but it inherits "
    "application-owner privilege so filtered publication autocreation works. This accepted limitation "
    "exits by pre-creating publications and granting table-scoped SELECT through an ordered, reversible "
    "database migration."
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
    """One service-owned account transaction phase."""

    phase: str
    token: str
    email: str
    password: str
    display_name: str

    @classmethod
    def create(cls, phase: str) -> AccountProbe:
        """Create randomized credentials for the initial registration."""
        token = secrets.token_hex(8)
        return cls(
            phase=phase,
            token=token,
            email=f"cdc-{phase}-{token}@example.invalid",
            password=secrets.token_urlsafe(24),
            display_name=f"CDC {phase} {token}",
        )

    def updated(self) -> AccountProbe:
        """Return the same account identity with post-restart mutable state."""
        return AccountProbe(
            phase="after-restart",
            token=self.token,
            email=self.email,
            password=self.password,
            display_name=f"CDC after-restart {self.token}",
        )


@dataclass(frozen=True, slots=True)
class CanonicalObservation:
    """Canonical record coordinates and explicitly committed acceptance offset."""

    phase: str
    topic: str
    partition: int
    offset: int
    committed_offset: int
    consumer_group: str
    value_bytes: int
    key_sha256: str
    event_id: str
    source_service: str


@dataclass(frozen=True, slots=True)
class ProjectionObservation:
    """Durable BFF projection cardinality for one phase."""

    phase: str
    row_count: int
    user_id_sha256: str


@dataclass(frozen=True, slots=True)
class RegisteredGroupObservation:
    """Committed position of the production BFF projection consumer group."""

    phase: str
    consumer_group: str
    partition: int
    committed_offset: int


@dataclass(frozen=True, slots=True)
class ConnectPodIdentity:
    """Stable identity fields for one running Kafka Connect pod."""

    name: str
    uid: str
    start_time: str


@dataclass(frozen=True, slots=True)
class ContinuityEvidence:
    """Cross-restart offset and registered-consumer continuity proof."""

    consumer_group: str
    registered_consumer_group: str
    partition: int
    before_offset: int
    committed_offset: int
    after_offset: int
    before_event_id: str
    after_event_id: str
    registered_before_committed_offset: int
    registered_after_committed_offset: int
    same_partition: bool
    offset_increased: bool
    event_id_changed: bool
    no_replay: bool
    registered_group_caught_up: bool
    registered_group_advanced: bool


@dataclass(slots=True)
class RestartEvidence:
    """Before/after identity proof for the Kafka Connect rollout."""

    deployment: str = CONNECT_DEPLOYMENT
    before: ConnectPodIdentity | None = None
    after: ConnectPodIdentity | None = None
    completed: bool = False
    connector_running: bool = False
    identity_changed: bool = False


@dataclass(slots=True)
class CleanupEvidence:
    """Service and projection cleanup outcome."""

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
    """Require production CDC resources and distinct database login identities."""
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
        raise _error(CdcProofError, "CDC_PROOF_FAILED: service DML and replication logins are not distinct")


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
        f"SELECT count(*) FROM {BFF_SCHEMA}.{PROJECTION_TABLE} "
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


def _consumer_script(
    user_id: UUID,
    probe: AccountProbe,
    group_id: str,
    timeout_seconds: float,
    resume_from: CanonicalObservation | None,
) -> str:
    expected = json.dumps(
        {
            "display_name": probe.display_name,
            "email": probe.email,
            "group_id": group_id,
            "minimum_offset": resume_from.committed_offset if resume_from else None,
            "partition": resume_from.partition if resume_from else None,
            "timeout": timeout_seconds,
            "user_id": str(user_id),
        },
        separators=(",", ":"),
    )
    return f"""import asyncio
import hashlib
import json
from aiokafka import AIOKafkaConsumer
from aiokafka.structs import OffsetAndMetadata, TopicPartition
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
                    if EXPECTED["partition"] is not None and record.partition != EXPECTED["partition"]:
                        raise RuntimeError("canonical account key moved partitions after restart")
                    if EXPECTED["minimum_offset"] is not None and record.offset < EXPECTED["minimum_offset"]:
                        raise RuntimeError("canonical account event replayed before the committed position")
                    if snapshot is None:
                        raise RuntimeError("canonical account event omitted its snapshot")
                    if snapshot.id != EXPECTED["user_id"] or snapshot.email != EXPECTED["email"]:
                        raise RuntimeError("canonical account snapshot identity mismatch")
                    if snapshot.display_name != EXPECTED["display_name"]:
                        raise RuntimeError("canonical account snapshot state mismatch")
                    committed_offset = record.offset + 1
                    await consumer.commit({{
                        TopicPartition(record.topic, record.partition):
                            OffsetAndMetadata(committed_offset, "")
                    }})
                    key = (record.key or b"").decode()
                    print(json.dumps({{
                        "status": "delivered",
                        "topic": record.topic,
                        "partition": record.partition,
                        "offset": record.offset,
                        "committed_offset": committed_offset,
                        "consumer_group": EXPECTED["group_id"],
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
    group_id: str,
    resume_from: CanonicalObservation | None = None,
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
    committed_offset = document.get("committed_offset")
    value_bytes = document.get("value_bytes")
    if (
        not isinstance(partition, int)
        or not isinstance(offset, int)
        or not isinstance(committed_offset, int)
        or not isinstance(value_bytes, int)
    ):
        raise _error(
            CdcConsumerExecutionError,
            "CDC_CONSUMER_FAILED: canonical record coordinates were invalid",
        )
    if document.get("consumer_group") != group_id or committed_offset != offset + 1:
        raise _error(CdcConsumerExecutionError, "CDC_CONSUMER_FAILED: canonical offset was not explicitly committed")
    if resume_from is not None and (partition != resume_from.partition or offset < resume_from.committed_offset):
        raise _error(
            CdcConsumerExecutionError,
            "CDC_CONSUMER_FAILED: post-restart delivery replayed or changed partitions",
        )
    return CanonicalObservation(
        phase=phase,
        topic=CANONICAL_TOPIC,
        partition=partition,
        offset=offset,
        committed_offset=committed_offset,
        consumer_group=group_id,
        value_bytes=value_bytes,
        key_sha256=hashlib.sha256(str(user_id).encode()).hexdigest(),
        event_id=str(document["event_id"]),
        source_service="user-auth-service",
    )


def consume_canonical_account_event(
    namespace: str,
    user_id: UUID,
    probe: AccountProbe,
    group_id: str,
    timeout_seconds: float,
    *,
    resume_from: CanonicalObservation | None = None,
) -> CanonicalObservation:
    """Consume and commit a canonical event from the stable acceptance group."""
    bff_pod = _first_pod(namespace, BFF_POD_SELECTOR)
    if bff_pod is None:
        raise _error(CdcConsumerExecutionError, "CDC_CONSUMER_FAILED: no BFF pod is available")
    result = _kubectl(
        namespace,
        "exec",
        "--stdin",
        bff_pod,
        "--",
        "python",
        "-",
        input_text=_consumer_script(user_id, probe, group_id, timeout_seconds, resume_from),
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
    return _validate_canonical_observation(
        document,
        user_id=user_id,
        phase=probe.phase,
        group_id=group_id,
        resume_from=resume_from,
    )


def _registered_group_script(partition: int) -> str:
    return f"""import asyncio
import json
from aiokafka import AIOKafkaConsumer
from aiokafka.structs import TopicPartition
from bff_service.events.projections._constants import projection_priority_group_id

TOPIC = {CANONICAL_TOPIC!r}
BOOTSTRAP = {f"{KAFKA_BOOTSTRAP_SERVICE}:9092"!r}
PARTITION = {partition}

async def main():
    consumer = AIOKafkaConsumer(
        bootstrap_servers=BOOTSTRAP,
        group_id=projection_priority_group_id,
        enable_auto_commit=False,
    )
    await consumer.start()
    try:
        offset = await consumer.committed(TopicPartition(TOPIC, PARTITION))
        print(json.dumps({{
            "consumer_group": projection_priority_group_id,
            "partition": PARTITION,
            "committed_offset": offset,
        }}, separators=(",", ":")))
    finally:
        await consumer.stop()

asyncio.run(main())
"""


def _registered_group_offset(
    namespace: str,
    bff_pod: str,
    phase: str,
    partition: int,
    timeout_seconds: float,
) -> RegisteredGroupObservation:
    result = _kubectl(
        namespace,
        "exec",
        "--stdin",
        bff_pod,
        "--",
        "python",
        "-",
        input_text=_registered_group_script(partition),
        timeout=timeout_seconds + 30,
        check=False,
    )
    if result.returncode != 0:
        raise _error(
            CdcConsumerExecutionError,
            "CDC_CONSUMER_FAILED: registered BFF group offset query failed",
        )
    try:
        document = json.loads(result.stdout.strip().splitlines()[-1])
        consumer_group = document.get("consumer_group")
        observed_partition = document.get("partition")
        committed_offset = document.get("committed_offset")
    except (AttributeError, IndexError, json.JSONDecodeError) as exc:
        raise _error(
            CdcConsumerExecutionError,
            "CDC_CONSUMER_FAILED: registered BFF group offset query returned invalid output",
        ) from exc
    if (
        not isinstance(consumer_group, str)
        or not consumer_group
        or observed_partition != partition
        or not isinstance(committed_offset, int)
    ):
        raise _error(
            CdcConsumerExecutionError,
            "CDC_CONSUMER_FAILED: registered BFF group committed position was invalid",
        )
    return RegisteredGroupObservation(
        phase=phase,
        consumer_group=consumer_group,
        partition=partition,
        committed_offset=committed_offset,
    )


def _wait_registered_group_past(
    namespace: str,
    phase: str,
    partition: int,
    event_offset: int,
    timeout_seconds: float,
) -> RegisteredGroupObservation:
    bff_pod = _first_pod(namespace, BFF_POD_SELECTOR)
    if bff_pod is None:
        raise _error(CdcConsumerExecutionError, "CDC_CONSUMER_FAILED: no BFF pod is available")
    deadline = time.monotonic() + timeout_seconds
    while True:
        observation = _registered_group_offset(
            namespace,
            bff_pod,
            phase,
            partition,
            timeout_seconds,
        )
        if observation.committed_offset > event_offset:
            return observation
        if time.monotonic() >= deadline:
            raise _error(
                CdcProjectionTimeoutError,
                "CDC_PROJECTION_TIMEOUT: registered BFF group did not commit beyond the canonical event",
            )
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


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


def _connect_pod_identity(namespace: str) -> ConnectPodIdentity:
    result = _kubectl(
        namespace,
        "get",
        "pods",
        "--selector",
        f"strimzi.io/name={CONNECT_DEPLOYMENT}",
        "--output=json",
    )
    try:
        document = json.loads(result.stdout)
        items = document.get("items")
    except (AttributeError, json.JSONDecodeError) as exc:
        raise _error(CdcProofError, "CDC_PROOF_FAILED: Connect pod inventory was invalid") from exc
    candidates: list[ConnectPodIdentity] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata")
            status = item.get("status")
            if not isinstance(metadata, dict) or not isinstance(status, dict):
                continue
            name = metadata.get("name")
            uid = metadata.get("uid")
            start_time = status.get("startTime")
            if (
                status.get("phase") == "Running"
                and not metadata.get("deletionTimestamp")
                and isinstance(name, str)
                and isinstance(uid, str)
                and isinstance(start_time, str)
                and name
                and uid
                and start_time
            ):
                candidates.append(ConnectPodIdentity(name=name, uid=uid, start_time=start_time))
    if not candidates:
        raise _error(CdcProofError, "CDC_PROOF_FAILED: no running Connect pod identity was available")
    return max(candidates, key=lambda identity: (identity.start_time, identity.name))


def restart_connect(
    namespace: str,
    timeout_seconds: float,
    evidence: RestartEvidence | None = None,
) -> RestartEvidence:
    """Restart Connect and prove that its running pod identity changed."""
    if evidence is None:
        evidence = RestartEvidence()
    evidence.before = _connect_pod_identity(namespace)
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
    evidence.after = _connect_pod_identity(namespace)
    evidence.identity_changed = (
        evidence.before.uid != evidence.after.uid and evidence.before.start_time != evidence.after.start_time
    )
    if not evidence.identity_changed:
        raise _error(
            CdcProofError,
            "CDC_PROOF_FAILED: Connect rollout did not replace the running pod UID and startTime",
        )
    _wait_connector_running(namespace, timeout_seconds)
    evidence.connector_running = True
    return evidence


def _register_account(client: httpx.Client, probe: AccountProbe) -> UUID:
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": probe.email,
                "password": probe.password,
                "display_name": probe.display_name,
            },
        )
        response.raise_for_status()
        document = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise _error(CdcProofError, "CDC_PROOF_FAILED: real user-auth registration transaction failed") from exc
    if not isinstance(document, dict) or not isinstance(document.get("id"), str):
        raise _error(CdcProofError, "CDC_PROOF_FAILED: real user-auth registration returned no account identity")
    try:
        return UUID(document["id"])
    except ValueError as exc:
        raise _error(
            CdcProofError,
            "CDC_PROOF_FAILED: real user-auth registration returned an invalid identity",
        ) from exc


def _update_account(client: httpx.Client, probe: AccountProbe) -> None:
    try:
        response = client.patch("/api/v1/account", json={"display_name": probe.display_name})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise _error(CdcProofError, "CDC_PROOF_FAILED: real user-auth account update failed") from exc


def _cleanup_accounts(
    namespace: str,
    pod: str | None,
    accounts: list[tuple[AccountProbe, httpx.Client, UUID]],
    timeout_seconds: float,
) -> CleanupEvidence:
    evidence = CleanupEvidence()
    for probe, client, user_id in reversed(accounts):
        deleted = False
        try:
            response = client.delete("/api/v1/account")
            response.raise_for_status()
            evidence.accounts_deleted += 1
            deleted = True
        except httpx.HTTPError, RuntimeError:
            evidence.errors.append(f"{probe.phase}-account-delete")
        try:
            client.close()
        except RuntimeError:
            evidence.errors.append(f"{probe.phase}-client-close")
        if not deleted:
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


def _prove_continuity(
    observations: list[CanonicalObservation],
    registered_groups: list[RegisteredGroupObservation],
) -> ContinuityEvidence:
    if len(observations) != 2 or len(registered_groups) != 2:
        raise _error(CdcProofError, "CDC_PROOF_FAILED: restart continuity observations were incomplete")
    before, after = observations
    registered_before, registered_after = registered_groups
    same_partition = before.partition == after.partition
    offset_increased = after.offset >= before.committed_offset
    event_id_changed = before.event_id != after.event_id
    no_replay = offset_increased
    registered_group_caught_up = (
        registered_before.partition == before.partition
        and registered_after.partition == after.partition
        and registered_before.committed_offset > before.offset
        and registered_after.committed_offset > after.offset
    )
    registered_group_advanced = (
        registered_before.consumer_group == registered_after.consumer_group
        and registered_after.committed_offset > registered_before.committed_offset
    )
    if not (
        before.consumer_group == after.consumer_group
        and before.key_sha256 == after.key_sha256
        and same_partition
        and offset_increased
        and event_id_changed
        and no_replay
        and registered_group_caught_up
        and registered_group_advanced
    ):
        raise _error(
            CdcProofError,
            "CDC_PROOF_FAILED: post-restart delivery did not preserve acceptance and registered-group continuity",
        )
    return ContinuityEvidence(
        consumer_group=before.consumer_group,
        registered_consumer_group=registered_before.consumer_group,
        partition=before.partition,
        before_offset=before.offset,
        committed_offset=before.committed_offset,
        after_offset=after.offset,
        before_event_id=before.event_id,
        after_event_id=after.event_id,
        registered_before_committed_offset=registered_before.committed_offset,
        registered_after_committed_offset=registered_after.committed_offset,
        same_partition=same_partition,
        offset_increased=offset_increased,
        event_id_changed=event_id_changed,
        no_replay=no_replay,
        registered_group_caught_up=registered_group_caught_up,
        registered_group_advanced=registered_group_advanced,
    )


def _is_record(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_record_pair(value: object) -> TypeGuard[list[dict[str, object]]]:
    return isinstance(value, list) and len(value) == 2 and all(_is_record(item) for item in value)


def evidence_is_valid(document: object) -> bool:
    """Return whether a redacted document proves the complete live CDC contract."""
    if not isinstance(document, dict):
        return False
    schema_version = document.get("schema_version")
    if (
        type(schema_version) is not int
        or schema_version < EVIDENCE_SCHEMA_VERSION
        or document.get("check") != "live-cluster-cdc"
        or document.get("status") != "passed"
        or document.get("failure_class") is not None
        or document.get("failure_message") is not None
        or document.get("canonical_topic") != CANONICAL_TOPIC
        or document.get("connector") != CONNECTOR_NAME
    ):
        return False

    observed = document.get("observed")
    registered = document.get("registered_group_offsets")
    projections = document.get("projections")
    restart = document.get("restart")
    continuity = document.get("continuity")
    identity_control = document.get("database_identity_control")
    cleanup = document.get("cleanup")
    if not (
        _is_record_pair(observed)
        and _is_record_pair(registered)
        and _is_record_pair(projections)
        and _is_record(restart)
        and _is_record(continuity)
        and _is_record(identity_control)
        and _is_record(cleanup)
    ):
        return False

    before, after = observed
    registered_before, registered_after = registered
    before_offset = before.get("offset")
    before_committed = before.get("committed_offset")
    after_offset = after.get("offset")
    partition = before.get("partition")
    consumer_group = before.get("consumer_group")
    registered_group = registered_before.get("consumer_group")
    registered_before_offset = registered_before.get("committed_offset")
    registered_after_offset = registered_after.get("committed_offset")
    if (
        type(before_offset) is not int
        or type(before_committed) is not int
        or type(after_offset) is not int
        or type(registered_before_offset) is not int
        or type(registered_after_offset) is not int
    ):
        return False
    event_ids_changed = (
        isinstance(before.get("event_id"), str)
        and bool(before["event_id"])
        and isinstance(after.get("event_id"), str)
        and bool(after["event_id"])
        and before["event_id"] != after["event_id"]
    )
    canonical_continuity = (
        before.get("phase") == "before-restart"
        and after.get("phase") == "after-restart"
        and isinstance(consumer_group, str)
        and bool(consumer_group)
        and after.get("consumer_group") == consumer_group
        and type(partition) is int
        and after.get("partition") == partition
        and type(before_offset) is int
        and type(before_committed) is int
        and before_committed == before_offset + 1
        and type(after_offset) is int
        and after_offset >= before_committed
        and before.get("key_sha256") == after.get("key_sha256")
        and event_ids_changed
    )
    registered_continuity = (
        registered_before.get("phase") == "before-restart"
        and registered_after.get("phase") == "after-restart"
        and isinstance(registered_group, str)
        and bool(registered_group)
        and registered_after.get("consumer_group") == registered_group
        and registered_before.get("partition") == partition
        and registered_after.get("partition") == partition
        and type(registered_before_offset) is int
        and type(registered_after_offset) is int
        and registered_before_offset > before_offset
        and registered_after_offset > after_offset
        and registered_after_offset > registered_before_offset
    )

    before_identity = restart.get("before")
    after_identity = restart.get("after")
    restart_proved = (
        restart.get("deployment") == CONNECT_DEPLOYMENT
        and _is_record(before_identity)
        and _is_record(after_identity)
        and all(
            isinstance(identity.get(field_name), str) and bool(identity[field_name])
            for identity in (before_identity, after_identity)
            for field_name in ("name", "uid", "start_time")
        )
        and before_identity["uid"] != after_identity["uid"]
        and before_identity["start_time"] != after_identity["start_time"]
        and restart.get("completed") is True
        and restart.get("connector_running") is True
        and restart.get("identity_changed") is True
    )
    continuity_matches = (
        continuity.get("consumer_group") == consumer_group
        and continuity.get("registered_consumer_group") == registered_group
        and continuity.get("partition") == partition
        and continuity.get("before_offset") == before_offset
        and continuity.get("committed_offset") == before_committed
        and continuity.get("after_offset") == after_offset
        and continuity.get("before_event_id") == before.get("event_id")
        and continuity.get("after_event_id") == after.get("event_id")
        and continuity.get("registered_before_committed_offset") == registered_before_offset
        and continuity.get("registered_after_committed_offset") == registered_after_offset
        and all(
            continuity.get(field_name) is True
            for field_name in (
                "same_partition",
                "offset_increased",
                "event_id_changed",
                "no_replay",
                "registered_group_caught_up",
                "registered_group_advanced",
            )
        )
    )
    projections_proved = (
        [projection.get("phase") for projection in projections] == ["before-restart", "after-restart"]
        and all(projection.get("row_count") == 1 for projection in projections)
        and projections[0].get("user_id_sha256") == projections[1].get("user_id_sha256")
    )
    accepted_identity_limitation = (
        identity_control.get("kind") == "distinct-identity"
        and identity_control.get("supports") == ["attribution", "independent-revocation"]
        and identity_control.get("inherited_owner_privilege") is True
        and identity_control.get("accepted_limitation") == ACCEPTED_PRIVILEGE_LIMITATION
    )
    cleanup_proved = (
        cleanup.get("accounts_deleted") == 1 and cleanup.get("projections_deleted") == 1 and cleanup.get("errors") == []
    )
    return (
        canonical_continuity
        and registered_continuity
        and restart_proved
        and continuity_matches
        and projections_proved
        and accepted_identity_limitation
        and cleanup_proved
    )


def _write_evidence(
    path: Path,
    error: CdcProofError | None,
    observations: list[CanonicalObservation],
    projections: list[ProjectionObservation],
    registered_groups: list[RegisteredGroupObservation],
    restart: RestartEvidence,
    continuity: ContinuityEvidence | None,
    cleanup: CleanupEvidence,
) -> None:
    document = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "check": "live-cluster-cdc",
        "status": "failed" if error is not None else "passed",
        "failure_class": _failure_class(error),
        "failure_message": str(error) if error is not None else None,
        "canonical_topic": CANONICAL_TOPIC,
        "connector": CONNECTOR_NAME,
        "observed": [asdict(observation) for observation in observations],
        "projections": [asdict(projection) for projection in projections],
        "registered_group_offsets": [asdict(observation) for observation in registered_groups],
        "restart": asdict(restart),
        "continuity": asdict(continuity) if continuity is not None else None,
        "database_identity_control": {
            "kind": "distinct-identity",
            "supports": ["attribution", "independent-revocation"],
            "inherited_owner_privilege": True,
            "accepted_limitation": ACCEPTED_PRIVILEGE_LIMITATION,
        },
        "cleanup": asdict(cleanup),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(path)


def run(namespace: str, base_url: str, evidence_path: Path, timeout_seconds: float) -> None:
    """Prove one account's delivery and registered projection across a Connect restart."""
    accounts: list[tuple[AccountProbe, httpx.Client, UUID]] = []
    observations: list[CanonicalObservation] = []
    projections: list[ProjectionObservation] = []
    registered_groups: list[RegisteredGroupObservation] = []
    restart = RestartEvidence()
    continuity: ContinuityEvidence | None = None
    cleanup = CleanupEvidence()
    pod: str | None = None
    error: CdcProofError | None = None
    cause: Exception | None = None
    try:
        require_cdc_deployment(namespace)
        pod = _primary_pod(namespace)
        group_id = f"cdc-acceptance-{secrets.token_hex(8)}"
        before_probe = AccountProbe.create("before-restart")
        client = httpx.Client(base_url=base_url, timeout=30, follow_redirects=True)
        try:
            user_id = _register_account(client, before_probe)
        except CdcProofError:
            client.close()
            raise
        accounts.append((before_probe, client, user_id))

        before = consume_canonical_account_event(
            namespace,
            user_id,
            before_probe,
            group_id,
            timeout_seconds,
        )
        observations.append(before)
        before_count = _wait_projection_count(namespace, pod, user_id, before_probe, 1, timeout_seconds)
        projections.append(
            ProjectionObservation(
                phase=before_probe.phase,
                row_count=before_count,
                user_id_sha256=hashlib.sha256(str(user_id).encode()).hexdigest(),
            )
        )
        registered_groups.append(
            _wait_registered_group_past(
                namespace,
                before_probe.phase,
                before.partition,
                before.offset,
                timeout_seconds,
            )
        )

        restart_connect(namespace, timeout_seconds, restart)
        after_probe = before_probe.updated()
        _update_account(client, after_probe)
        accounts[0] = (after_probe, client, user_id)
        after = consume_canonical_account_event(
            namespace,
            user_id,
            after_probe,
            group_id,
            timeout_seconds,
            resume_from=before,
        )
        observations.append(after)
        after_count = _wait_projection_count(namespace, pod, user_id, after_probe, 1, timeout_seconds)
        projections.append(
            ProjectionObservation(
                phase=after_probe.phase,
                row_count=after_count,
                user_id_sha256=hashlib.sha256(str(user_id).encode()).hexdigest(),
            )
        )
        registered_groups.append(
            _wait_registered_group_past(
                namespace,
                after_probe.phase,
                after.partition,
                after.offset,
                timeout_seconds,
            )
        )
        continuity = _prove_continuity(observations, registered_groups)
    except CdcProofError as exc:
        error = exc
    except Exception as exc:  # noqa: BLE001 - the CLI boundary records unexpected failures in evidence.
        cause = exc
        error = CdcProofError(f"CDC_PROOF_FAILED: unexpected {type(exc).__name__}")
    finally:
        cleanup = _cleanup_accounts(namespace, pod, accounts, timeout_seconds)
        if error is None and cleanup.errors:
            error = CdcProofError("CDC_PROOF_FAILED: service cleanup was incomplete")
        _write_evidence(
            evidence_path,
            error,
            observations,
            projections,
            registered_groups,
            restart,
            continuity,
            cleanup,
        )
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
    """Run the fail-closed live CDC acceptance command."""
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
