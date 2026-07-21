"""Focused Helm regression coverage for Kafka SASL environment wiring."""

import json
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CHART = _REPOSITORY_ROOT / "infra" / "k8s" / "helm"
_SECRET_NAME = "kafka-sasl-credentials"
_INVENTORY = _REPOSITORY_ROOT / "scripts" / "ci" / "image_inventory.json"
_FIRST_PARTY_PREFIX = "ghcr.io/mchar7/nohiki-monorepo/"
_TLS_ENV_SUFFIXES = (
    "KAFKA__SECURITY__TLS__CA_LOCATION",
    "KAFKA__SECURITY__TLS__CERTIFICATE_LOCATION",
    "KAFKA__SECURITY__TLS__KEY_LOCATION",
    "KAFKA__SECURITY__TLS__KEY_PASSWORD",
)
_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"
_SOURCE_CONNECTOR_NAMES = {
    "bff-service-outbox",
    "doc-template-service-outbox",
    "job-correlation-evaluation-service-wal",
    "job-ingest-discovery-service-outbox",
    "job-ingest-enrichment-service-outbox",
    "job-query-composition-service-outbox",
    "job-storage-service-outbox",
    "notification-service-outbox",
    "skill-graph-service-outbox",
    "user-auth-service-outbox",
    "user-entitlement-service-outbox",
    "user-pref-service-outbox",
    "user-upload-service-outbox",
}
_WAL_NAME = "job-correlation-evaluation-service-wal"
_WAL_CONFIG = {
    "topic.prefix": "job_correlation_wal",
    "schema.include.list": "job_correlation_schema",
    "table.include.list": "job_correlation_schema.processed_events",
    "slot.name": "job_correlation_wal_slot",
    "publication.name": "job_correlation_wal_pub",
    "publication.autocreate.mode": "filtered",
    "message.prefix.include.list": ".*",
    "transforms": "walRoute",
    "transforms.walRoute.type": "ai.nohiki.kafka.connect.transforms.NohikiWalRouterSmt",
    "key.converter": "org.apache.kafka.connect.storage.StringConverter",
    "value.converter": "io.debezium.converters.BinaryDataConverter",
    "value.converter.delegate.converter.type": "org.apache.kafka.connect.json.JsonConverter",
    "value.converter.delegate.converter.type.schemas.enable": "false",
    "errors.deadletterqueue.topic.name": "job_correlation.dlq.wal.v1",
}


def _digest_values(tmp_path: Path) -> Path:
    entries = cast(
        list[dict[str, str]],
        json.loads(_INVENTORY.read_text(encoding="utf-8"))["images"],
    )
    digests = {
        f"{_FIRST_PARTY_PREFIX}{entry['name']}": f"sha256:{index + 1:064x}" for index, entry in enumerate(entries)
    }
    path = tmp_path / "values.prod.digests.yaml"
    path.write_text(yaml.safe_dump({"global": {"imageDigests": digests}}), encoding="utf-8")
    return path


def _render_connectors(values_name: str, tmp_path: Path) -> tuple[dict[str, Any], ...]:
    environment = values_name.removeprefix("values.").removesuffix(".yaml")
    command = [
        "helm",
        "template",
        "nohiki",
        str(_CHART),
        "--namespace",
        f"nohiki-{environment}",
        "--values",
        str(_CHART / values_name),
        "--set",
        "kafkaConnect.enabled=true",
        "--show-only",
        "templates/strimzi-kafka-connectors.yaml",
    ]
    if values_name == "values.prod.yaml":
        command.extend(
            (
                "--values",
                str(_IDENTITY),
                "--values",
                str(_NETWORK),
                "--values",
                str(_digest_values(tmp_path)),
            )
        )
    elif values_name in {"values.dev.yaml", "values.staging.yaml"}:
        command.extend(("--values", str(_IDENTITY)))
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return tuple(
        document
        for document in yaml.safe_load_all(result.stdout)
        if isinstance(document, dict) and document.get("kind") == "KafkaConnector"
    )


def _source_connectors(
    documents: tuple[dict[str, Any], ...],
) -> dict[str, dict[str, Any]]:
    return {
        document["metadata"]["name"]: document
        for document in documents
        if document["spec"]["class"] == "io.debezium.connector.postgresql.PostgresConnector"
    }


def test_synthetic_production_render_wires_every_kafka_app_to_event_hubs_secret(
    tmp_path: Path,
) -> None:
    identity = tmp_path / "values.prod.identity.yaml"
    identity.write_text(
        yaml.safe_dump(
            {
                "global": {
                    "azure": {
                        "managedIdentityClientId": "00000000-0000-0000-0000-000000000001",
                        "tenantId": "00000000-0000-0000-0000-000000000002",
                    },
                    "eso": {
                        "azure": {
                            "keyVaultUrl": "https://synthetic-prod.vault.azure.net",
                            "clientId": "00000000-0000-0000-0000-000000000001",
                            "tenantId": "00000000-0000-0000-0000-000000000002",
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "helm",
            "template",
            "nohiki",
            str(_CHART),
            "--namespace",
            "nohiki-prod",
            "--values",
            str(_CHART / "values.prod.yaml"),
            "--values",
            str(identity),
            "--values",
            str(_digest_values(tmp_path)),
            "--values",
            str(Path(__file__).parent / "fixtures" / "values.prod.network.yaml"),
            "--set",
            "global.environment=test",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    documents = tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))

    kafka_containers: list[tuple[str, list[dict[str, Any]]]] = []
    for document in documents:
        pod_spec = document.get("spec", {}).get("template", {}).get("spec")
        if not pod_spec:
            continue
        for container in pod_spec.get("containers", ()):
            env = cast(list[dict[str, Any]], container.get("env") or [])
            if any(item["name"].endswith("KAFKA__DSN") for item in env):
                kafka_containers.append((document["metadata"]["name"], env))

    assert kafka_containers, "production render must contain Kafka-enabled applications"
    for workload_name, entries in kafka_containers:
        env = {item["name"]: item for item in entries}
        dsn_name = next(name for name in env if name.endswith("KAFKA__DSN"))
        prefix = dsn_name.removesuffix("KAFKA__DSN")
        assert env[f"{prefix}KAFKA__SECURITY__PROTOCOL"]["value"] == "SASL_SSL", workload_name
        assert env[f"{prefix}KAFKA__SECURITY__SASL__MECHANISM"]["value"] == "PLAIN", workload_name
        for suffix, key in (
            ("KAFKA__SECURITY__SASL__USERNAME", "username"),
            ("KAFKA__SECURITY__SASL__PASSWORD", "password"),
        ):
            assert env[f"{prefix}{suffix}"]["valueFrom"]["secretKeyRef"] == {
                "name": _SECRET_NAME,
                "key": key,
            }, workload_name
        assert not any(f"{prefix}{suffix}" in env for suffix in _TLS_ENV_SUFFIXES), workload_name


@pytest.mark.parametrize(
    "values_name",
    ["values.local.yaml", "values.dev.yaml", "values.staging.yaml", "values.prod.yaml"],
)
def test_every_environment_renders_only_correlation_through_the_wal_smt(
    values_name: str,
    tmp_path: Path,
) -> None:
    connectors = _source_connectors(_render_connectors(values_name, tmp_path))

    assert set(connectors) == _SOURCE_CONNECTOR_NAMES
    wal = connectors[_WAL_NAME]["spec"]["config"]
    assert {key: wal[key] for key in _WAL_CONFIG} == _WAL_CONFIG
    assert not any(key == "transforms.outbox" or key.startswith("transforms.outbox.") for key in wal)
    assert all(
        connector["spec"]["config"]["transforms"] == "outbox"
        for name, connector in connectors.items()
        if name != _WAL_NAME
    )
    assert "job-correlation-evaluation-service-outbox" not in connectors
    assert "nohiki-outbox-job_correlation" not in connectors


def test_rendered_wal_connector_exactly_matches_the_manual_registration_template(
    tmp_path: Path,
) -> None:
    connector = _source_connectors(_render_connectors("values.local.yaml", tmp_path))[_WAL_NAME]
    manual = yaml.safe_load(
        (_REPOSITORY_ROOT / "infra/k8s/kafka-connect/connectors/wal-connector-template.json").read_text(
            encoding="utf-8"
        )
    )
    replacements = {
        "SERVICE_NAME": "job-correlation-evaluation-service",
        "DB_PREFIX": "job_correlation",
        "RESOURCE_PREFIX": "job_correlation",
        "SCHEMA_NAME": "job_correlation_schema",
        "DATABASE_HOST": "nohiki-pg-rw",
        "DATABASE_PORT": "5432",
        "DATABASE_USER": "${file:/mnt/secrets/job-correlation-evaluation-service-debezium/username}",
        "DATABASE_PASSWORD": "${file:/mnt/secrets/job-correlation-evaluation-service-debezium/password}",
        "DATABASE_NAME": "job_correlation_evaluation_db",
    }

    def substitute(value: object) -> object:
        if isinstance(value, str):
            for marker, replacement in replacements.items():
                value = value.replace(marker, replacement)
            return value
        if isinstance(value, dict):
            return {key: substitute(item) for key, item in value.items()}
        if isinstance(value, list):
            return [substitute(item) for item in value]
        return value

    rendered_manual = cast(dict[str, Any], substitute(manual))
    manual_config = cast(dict[str, Any], rendered_manual["config"]).copy()
    assert connector["metadata"]["name"] == rendered_manual["name"]
    assert connector["spec"]["class"] == manual_config.pop("connector.class")
    assert str(connector["spec"]["tasksMax"]) == manual_config.pop("tasks.max")
    assert connector["spec"]["config"] == manual_config
