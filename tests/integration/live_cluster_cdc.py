#!/usr/bin/env python3
"""Prove CDC delivery through the already-reconciled local Kubernetes cluster."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Never

CONNECT_NAME = "nohiki-connect"
CONNECT_DEPLOYMENT = "nohiki-connect-connect"
DEBEZIUM_CONNECTOR = "user-pref-service-outbox"
DEBEZIUM_CREDENTIALS_RESOURCE = "user-pref-service-debezium-credentials"
DEBEZIUM_MOUNT = "/mnt/secrets/user-pref-service-debezium"
KAFKA_BOOTSTRAP_SERVICE = "nohiki-kafka-kafka-bootstrap"
POSTGRES_CLUSTER = "nohiki-pg"
POSTGRES_SERVICE = "nohiki-pg-rw"
TABLE_NAME = "events"
EVIDENCE_SCHEMA_VERSION = 1
ABSENT_DEPLOYMENT_MESSAGE = (
    "CDC_DEPLOYMENT_ABSENT: required deployed CDC resources are absent; reconcile the local platform first"
)
DELIVERY_TIMEOUT_MESSAGE = (
    "CDC_DELIVERY_TIMEOUT: deployed CDC resources were present but no correlated Kafka message arrived"
)


class CdcProofError(RuntimeError):
    """Base error for a failed live CDC proof."""


class CdcDeploymentAbsentError(CdcProofError):
    """The stable deployed CDC surface does not exist."""


class CdcDeliveryTimeoutError(CdcProofError):
    """The deployed CDC surface did not deliver the probe record."""


@dataclass(frozen=True)
class Probe:
    token: str
    correlation: str
    password: str

    @classmethod
    def create(cls) -> Probe:
        return cls(
            token=secrets.token_hex(6),
            correlation=secrets.token_hex(16),
            password=secrets.token_urlsafe(24),
        )

    @property
    def writer_role(self) -> str:
        return f"cdc_acceptance_{self.token}_writer"

    @property
    def database(self) -> str:
        return f"cdc_acceptance_{self.token}"

    @property
    def schema(self) -> str:
        return f"cdc_probe_{self.token}"

    @property
    def connector(self) -> str:
        return f"cdc-acceptance-{self.token}"

    @property
    def slot(self) -> str:
        return f"cdc_acceptance_{self.token}_slot"

    @property
    def publication(self) -> str:
        return f"cdc_acceptance_{self.token}_pub"

    @property
    def topic_prefix(self) -> str:
        return f"cdc_acceptance_{self.token}"

    @property
    def topic(self) -> str:
        return f"{self.topic_prefix}.{self.schema}.{TABLE_NAME}"

    @property
    def row_id(self) -> str:
        return f"00000000-0000-4000-8000-{self.token}"


@dataclass
class Mutations:
    role_created: bool = False
    database_created: bool = False
    table_created: bool = False
    connector_created: bool = False


@dataclass
class CleanupEvidence:
    row_deleted: bool = False
    connector_deleted: bool = False
    table_dropped: bool = False
    database_dropped: bool = False
    role_dropped: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Observation:
    value_bytes: int


def _run(
    command: list[str],
    *,
    input_text: str | None = None,
    timeout: float | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        message = f"CDC_PROOF_FAILED: {command[0]} command timed out"
        raise CdcProofError(message) from exc
    if check and result.returncode != 0:
        detail = next((line.strip() for line in result.stderr.splitlines() if line.strip()), "no error detail")
        message = f"CDC_PROOF_FAILED: {command[0]} command failed: {detail}"
        raise CdcProofError(message)
    return result


def _kubectl(
    namespace: str,
    *args: str,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(["kubectl", "--namespace", namespace, *args], input_text=input_text, check=check)


def _require_deployed_resource(namespace: str, resource: str) -> None:
    result = _kubectl(namespace, "get", resource, "--output=name", check=False)
    if result.returncode == 0:
        return
    detail = result.stderr.lower()
    if "notfound" in detail or "not found" in detail or "doesn't have a resource type" in detail:
        message = f"{ABSENT_DEPLOYMENT_MESSAGE}: {resource}"
        raise CdcDeploymentAbsentError(message)
    message = f"CDC_PROOF_FAILED: unable to discover deployed resource {resource}"
    raise CdcProofError(message)


def require_cdc_deployment(namespace: str) -> None:
    """Fail before database mutation when a stable deployed CDC resource is absent."""
    for resource in (
        f"kafkaconnect.kafka.strimzi.io/{CONNECT_NAME}",
        f"kafkaconnector.kafka.strimzi.io/{DEBEZIUM_CONNECTOR}",
        f"deployment.apps/{CONNECT_DEPLOYMENT}",
        f"secret/{DEBEZIUM_CREDENTIALS_RESOURCE}",
        f"service/{KAFKA_BOOTSTRAP_SERVICE}",
        f"cluster.postgresql.cnpg.io/{POSTGRES_CLUSTER}",
    ):
        _require_deployed_resource(namespace, resource)
    result = _kubectl(namespace, "get", "kafkaconnectors.kafka.strimzi.io", "--output=name", check=False)
    if result.returncode != 0 and (
        "not found" in result.stderr.lower() or "doesn't have a resource type" in result.stderr.lower()
    ):
        message = f"{ABSENT_DEPLOYMENT_MESSAGE}: KafkaConnector CRD"
        raise CdcDeploymentAbsentError(message)
    if result.returncode != 0:
        message = "CDC_PROOF_FAILED: unable to discover KafkaConnector resources"
        raise CdcProofError(message)


def _debezium_principal(namespace: str) -> str:
    result = _kubectl(
        namespace,
        "get",
        f"secret/{DEBEZIUM_CREDENTIALS_RESOURCE}",
        "--output=jsonpath={.data.username}",
    )
    try:
        principal = base64.b64decode(result.stdout, validate=True).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        message = "CDC_PROOF_FAILED: deployed Debezium username is invalid"
        raise CdcProofError(message) from exc
    if re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", principal) is None:
        message = "CDC_PROOF_FAILED: deployed Debezium username is not a safe PostgreSQL identifier"
        raise CdcProofError(message)
    return principal


def _first_pod(namespace: str, selector: str) -> str | None:
    result = _kubectl(namespace, "get", "pods", "--selector", selector, "--output=json")
    document = json.loads(result.stdout)
    names = sorted(
        item["metadata"]["name"]
        for item in document.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("metadata"), dict) and item["metadata"].get("name")
    )
    return names[0] if names else None


def _primary_pod(namespace: str) -> str:
    pod = _first_pod(namespace, f"cnpg.io/cluster={POSTGRES_CLUSTER},role=primary")
    if pod is None:
        message = "CDC_PROOF_FAILED: CloudNativePG primary pod is unavailable"
        raise CdcProofError(message)
    return pod


def _admin_sql(namespace: str, pod: str, database: str, sql: str, *, check: bool = True) -> bool:
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
        input_text=sql,
        check=check,
    )
    return result.returncode == 0


def _role_sql(namespace: str, pod: str, probe: Probe, sql: str, *, check: bool = True) -> bool:
    session = (
        f"\\setenv PGPASSWORD {probe.password}\n"
        f"\\connect postgresql://{probe.writer_role}@{POSTGRES_SERVICE}:5432/{probe.database}?sslmode=disable\n"
        f"{sql}"
    )
    result = _kubectl(
        namespace,
        "exec",
        "--stdin",
        pod,
        "--",
        "psql",
        "--dbname",
        "postgres",
        "--set=ON_ERROR_STOP=1",
        "--no-psqlrc",
        input_text=session,
        check=check,
    )
    return result.returncode == 0


def create_fixture(
    namespace: str,
    pod: str,
    probe: Probe,
    debezium_principal: str,
    mutations: Mutations,
) -> None:
    """Create one isolated database, writer role, schema, table, and publication."""
    _admin_sql(
        namespace,
        pod,
        "postgres",
        f"CREATE ROLE {probe.writer_role} LOGIN PASSWORD '{probe.password}' NOREPLICATION "
        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;\n",
    )
    mutations.role_created = True
    _admin_sql(
        namespace,
        pod,
        "postgres",
        f"CREATE DATABASE {probe.database} OWNER postgres TEMPLATE template0;\n"
        f"REVOKE ALL ON DATABASE {probe.database} FROM PUBLIC;\n"
        f"GRANT CONNECT ON DATABASE {probe.database} TO {probe.writer_role};\n"
        f"GRANT CONNECT ON DATABASE {probe.database} TO {debezium_principal};\n",
    )
    mutations.database_created = True
    _admin_sql(
        namespace,
        pod,
        probe.database,
        f"REVOKE ALL ON SCHEMA public FROM PUBLIC;\n"
        f"CREATE SCHEMA {probe.schema} AUTHORIZATION postgres;\n"
        f"REVOKE ALL ON SCHEMA {probe.schema} FROM PUBLIC;\n"
        f"CREATE TABLE {probe.schema}.{TABLE_NAME} ("
        "id uuid PRIMARY KEY, correlation_id text NOT NULL, payload text NOT NULL);\n"
        f"REVOKE ALL ON TABLE {probe.schema}.{TABLE_NAME} FROM PUBLIC;\n"
        f"GRANT USAGE ON SCHEMA {probe.schema} TO {probe.writer_role};\n"
        f"GRANT INSERT, DELETE ON TABLE {probe.schema}.{TABLE_NAME} TO {probe.writer_role};\n"
        f"GRANT USAGE ON SCHEMA {probe.schema} TO {debezium_principal};\n"
        f"GRANT SELECT ON TABLE {probe.schema}.{TABLE_NAME} TO {debezium_principal};\n"
        f"CREATE PUBLICATION {probe.publication} FOR TABLE {probe.schema}.{TABLE_NAME};\n"
        f"ALTER ROLE {probe.writer_role} SET search_path TO {probe.schema};\n",
    )
    mutations.table_created = True


def _connector_document(probe: Probe, namespace: str) -> dict[str, object]:
    return {
        "apiVersion": "kafka.strimzi.io/v1",
        "kind": "KafkaConnector",
        "metadata": {
            "name": probe.connector,
            "namespace": namespace,
            "labels": {"strimzi.io/cluster": CONNECT_NAME},
        },
        "spec": {
            "class": "io.debezium.connector.postgresql.PostgresConnector",
            "tasksMax": 1,
            "config": {
                "database.hostname": POSTGRES_SERVICE,
                "database.port": "5432",
                "database.dbname": probe.database,
                "database.user": f"${{file:{DEBEZIUM_MOUNT}/username}}",
                "database.password": f"${{file:{DEBEZIUM_MOUNT}/password}}",
                "database.sslmode": "disable",
                "topic.prefix": probe.topic_prefix,
                "schema.include.list": probe.schema,
                "table.include.list": f"{probe.schema}.{TABLE_NAME}",
                "plugin.name": "pgoutput",
                "slot.name": probe.slot,
                "publication.name": probe.publication,
                "publication.autocreate.mode": "disabled",
                "snapshot.mode": "initial",
                "tombstones.on.delete": "false",
                "include.schema.changes": "false",
                "key.converter": "org.apache.kafka.connect.json.JsonConverter",
                "key.converter.schemas.enable": "false",
                "value.converter": "org.apache.kafka.connect.json.JsonConverter",
                "value.converter.schemas.enable": "false",
                "topic.creation.enable": "true",
                "topic.creation.default.replication.factor": "1",
                "topic.creation.default.partitions": "1",
            },
        },
    }


def create_connector(namespace: str, probe: Probe, mutations: Mutations) -> None:
    manifest = json.dumps(_connector_document(probe, namespace), separators=(",", ":"))
    mutations.connector_created = True
    _kubectl(namespace, "apply", "--filename=-", input_text=manifest)


def insert_probe(namespace: str, pod: str, probe: Probe) -> None:
    """Mutate only the dedicated table and authenticate as its throwaway role."""
    _role_sql(
        namespace,
        pod,
        probe,
        f"INSERT INTO {probe.schema}.{TABLE_NAME} (id, correlation_id, payload) VALUES "  # noqa: S608
        f"('{probe.row_id}', '{probe.correlation}', 'live-cluster-cdc');\n",
    )


def _assert_correlation(consumer_output: str, correlation: str) -> Observation | None:
    """Adapt the POC consumer assertion to a Debezium table-change envelope."""
    for line in consumer_output.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        payload = record.get("payload", record)
        if not isinstance(payload, dict):
            continue
        after = payload.get("after")
        if isinstance(after, dict) and after.get("correlation_id") == correlation:
            return Observation(value_bytes=len(line.encode()))
    return None


def consume_correlated(namespace: str, probe: Probe, timeout_seconds: float) -> Observation:
    """Consume the real Kafka record from inside the deployed Connect pod."""
    connect_pod = _first_pod(namespace, f"strimzi.io/cluster={CONNECT_NAME}")
    if connect_pod is None:
        message = "CDC_PROOF_FAILED: deployed Kafka Connect pod is unavailable for consumer execution"
        raise CdcProofError(message)
    timeout_ms = max(1, int(timeout_seconds * 1000))
    result = _run(
        [
            "kubectl",
            "--namespace",
            namespace,
            "exec",
            connect_pod,
            "--",
            "/opt/kafka/bin/kafka-console-consumer.sh",
            "--bootstrap-server",
            f"{KAFKA_BOOTSTRAP_SERVICE}:9092",
            "--topic",
            probe.topic,
            "--from-beginning",
            "--timeout-ms",
            str(timeout_ms),
            "--max-messages",
            "1",
            "--consumer-property",
            f"group.id=cdc-acceptance-{probe.token}",
        ],
        timeout=timeout_seconds + 15,
        check=False,
    )
    timeout_markers = ("TimeoutException", "Processed a total of 0 messages")
    if result.returncode != 0 and not any(marker in result.stderr for marker in timeout_markers):
        message = "CDC_PROOF_FAILED: Kafka consumer command failed before a delivery assertion was possible"
        raise CdcProofError(message)
    observation = _assert_correlation(result.stdout, probe.correlation)
    if observation is None:
        message = f"{DELIVERY_TIMEOUT_MESSAGE} within {timeout_seconds:g}s"
        raise CdcDeliveryTimeoutError(message)
    return observation


def _cleanup(namespace: str, pod: str | None, probe: Probe, mutations: Mutations) -> CleanupEvidence:
    evidence = CleanupEvidence()

    def record(name: str, completed: bool) -> None:
        setattr(evidence, name, completed)
        if not completed:
            evidence.errors.append(name)

    if mutations.table_created and pod is not None:
        record(
            "row_deleted",
            _role_sql(
                namespace,
                pod,
                probe,
                f"DELETE FROM {probe.schema}.{TABLE_NAME} WHERE id = '{probe.row_id}';\n",  # noqa: S608
                check=False,
            ),
        )
    if mutations.connector_created:
        result = _kubectl(
            namespace,
            "delete",
            f"kafkaconnector.kafka.strimzi.io/{probe.connector}",
            "--ignore-not-found=true",
            "--wait=true",
            check=False,
        )
        record("connector_deleted", result.returncode == 0)
        if result.returncode != 0:
            return evidence
        time.sleep(2)
    if mutations.table_created and pod is not None:
        record(
            "table_dropped",
            _admin_sql(
                namespace,
                pod,
                probe.database,
                f"DROP TABLE IF EXISTS {probe.schema}.{TABLE_NAME};\nDROP SCHEMA IF EXISTS {probe.schema};\n",
                check=False,
            ),
        )
    if mutations.database_created and pod is not None:
        _admin_sql(
            namespace,
            pod,
            "postgres",
            f"SELECT pg_terminate_backend(active_pid) FROM pg_replication_slots "  # noqa: S608
            f"WHERE slot_name = '{probe.slot}' AND active_pid IS NOT NULL;\n",
            check=False,
        )
        time.sleep(1)
        _admin_sql(
            namespace,
            pod,
            "postgres",
            f"SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots "  # noqa: S608
            f"WHERE slot_name = '{probe.slot}' AND active_pid IS NULL;\n",
            check=False,
        )
        record(
            "database_dropped",
            _admin_sql(
                namespace,
                pod,
                "postgres",
                f"DROP DATABASE IF EXISTS {probe.database} WITH (FORCE);\n",
                check=False,
            ),
        )
    if mutations.role_created and pod is not None:
        record(
            "role_dropped",
            _admin_sql(
                namespace,
                pod,
                "postgres",
                f"DROP ROLE IF EXISTS {probe.writer_role};\n",
                check=False,
            ),
        )
    return evidence


def _failure_class(error: CdcProofError | None) -> str | None:
    if isinstance(error, CdcDeploymentAbsentError):
        return "absent-deployment"
    if isinstance(error, CdcDeliveryTimeoutError):
        return "delivery-timeout"
    if error is not None:
        return "proof-error"
    return None


def _write_evidence(
    path: Path,
    probe: Probe,
    error: CdcProofError | None,
    observation: Observation | None,
    cleanup: CleanupEvidence,
) -> None:
    document = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "check": "live-cluster-cdc",
        "status": "failed" if error is not None else "passed",
        "failure_class": _failure_class(error),
        "topic": probe.topic,
        "correlation_sha256": hashlib.sha256(probe.correlation.encode()).hexdigest(),
        "observed": None
        if observation is None
        else {"correlated_message_count": 1, "value_bytes": observation.value_bytes},
        "cleanup": {
            "row_deleted": cleanup.row_deleted,
            "connector_deleted": cleanup.connector_deleted,
            "table_dropped": cleanup.table_dropped,
            "database_dropped": cleanup.database_dropped,
            "role_dropped": cleanup.role_dropped,
            "errors": cleanup.errors[:5],
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(path)


def run(namespace: str, evidence_path: Path, timeout_seconds: float) -> None:
    probe = Probe.create()
    mutations = Mutations()
    pod: str | None = None
    observation: Observation | None = None
    error: CdcProofError | None = None
    cause: Exception | None = None
    cleanup = CleanupEvidence()
    try:
        require_cdc_deployment(namespace)
        pod = _primary_pod(namespace)
        debezium_principal = _debezium_principal(namespace)
        create_fixture(namespace, pod, probe, debezium_principal, mutations)
        create_connector(namespace, probe, mutations)
        insert_probe(namespace, pod, probe)
        observation = consume_correlated(namespace, probe, timeout_seconds)
    except CdcProofError as exc:
        error = exc
    except Exception as exc:
        cause = exc
        error = CdcProofError(f"CDC_PROOF_FAILED: unexpected {type(exc).__name__}")
    finally:
        cleanup = _cleanup(namespace, pod, probe, mutations)
        if error is None and cleanup.errors:
            error = CdcProofError("CDC_PROOF_FAILED: probe delivered but cleanup was incomplete")
        _write_evidence(evidence_path, probe, error, observation, cleanup)
    if error is not None:
        if cause is not None:
            raise error from cause
        raise error


def _positive_seconds(value: str) -> float:
    seconds = float(value)
    if seconds <= 0:
        message = "must be greater than zero"
        raise argparse.ArgumentTypeError(message)
    return seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="nohiki")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=_positive_seconds, default=120.0)
    args = parser.parse_args(argv)
    try:
        run(args.namespace, args.evidence, args.timeout_seconds)
    except CdcProofError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write("Live cluster CDC proof consumed the uniquely correlated Kafka record.\n")
    return 0


def _entrypoint() -> Never:
    raise SystemExit(main())


if __name__ == "__main__":
    _entrypoint()
