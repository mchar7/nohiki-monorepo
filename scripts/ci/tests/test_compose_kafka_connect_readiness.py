"""Compose Kafka Connect registration and CDC-resource readiness contracts."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[3]
_COMPOSE = _REPO / "infra" / "compose" / "docker-compose.yml"
_HEALTHCHECK = _REPO / "infra" / "compose" / "scripts" / "kafka_connect_healthcheck.py"
_CONNECT_ROOT = _REPO / "infra" / "k8s" / "kafka-connect"
_CONFIG_DIR = _CONNECT_ROOT / "connectors"
_REGISTRATION = _CONNECT_ROOT / "scripts" / "register-connectors.sh"
_ENTRYPOINT = _REGISTRATION.with_name("entrypoint.sh")
_CDC_RESOURCES = {
    "bff-service-outbox": ("bff_outbox_slot", "bff_outbox_pub"),
    "doc-template-service-outbox": ("doc_template_outbox_slot", "doc_template_outbox_pub"),
    "job-correlation-evaluation-service-wal": ("job_correlation_wal_slot", "job_correlation_wal_pub"),
    "job-ingest-enrichment-service-outbox": (
        "job_ingest_enrichment_outbox_slot",
        "job_ingest_enrichment_outbox_pub",
    ),
    "job-query-composition-service-outbox": (
        "job_query_composition_outbox_slot",
        "job_query_composition_outbox_pub",
    ),
    "job-storage-service-outbox": ("job_storage_outbox_slot", "job_storage_outbox_pub"),
    "notification-service-outbox": ("notification_outbox_slot", "notification_outbox_pub"),
    "skill-graph-service-outbox": ("skill_graph_outbox_slot", "skill_graph_outbox_pub"),
    "user-auth-service-outbox": ("user_auth_outbox_slot", "user_auth_outbox_pub"),
    "user-entitlement-service-outbox": (
        "user_entitlement_outbox_slot",
        "user_entitlement_outbox_pub",
    ),
    "user-pref-service-outbox": ("user_pref_outbox_slot", "user_pref_outbox_pub"),
    "user-upload-service-outbox": ("user_upload_outbox_slot", "user_upload_outbox_pub"),
}
_REQUIRED_CONNECTORS = tuple(_CDC_RESOURCES)


def _connector_payload() -> dict[str, object]:
    return {
        name: {
            "info": {
                "config": {
                    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
                    "slot.name": slot,
                    "publication.name": publication,
                }
            },
            "status": {"connector": {"state": "RUNNING"}, "tasks": [{"id": 0, "state": "RUNNING"}]},
        }
        for name, (slot, publication) in _CDC_RESOURCES.items()
    }


@contextmanager
def _connect_api(payload: dict[str, object]) -> Iterator[str]:
    encoded = json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/connectors?expand=status&expand=info":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _run_healthcheck(
    tmp_path: Path,
    payload: dict[str, object],
    omitted_resource: str = "",
    registration_script: Path = _REGISTRATION,
) -> subprocess.CompletedProcess[str]:
    secrets = tmp_path / "secrets" / "database"
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / "dsn").write_text(
        "postgresql+asyncpg://svc:pw@db.internal:5432/nohiki_db\n",
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    psql = bin_dir / "psql"
    psql.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "query = sys.argv[-1]\n"
        "key = 'PSQL_SLOTS' if 'pg_replication_slots' in query else 'PSQL_PUBLICATIONS'\n"
        "sys.stdout.write(os.environ[key])\n",
        encoding="utf-8",
    )
    psql.chmod(psql.stat().st_mode | stat.S_IEXEC)

    with _connect_api(payload) as connect_url:
        return subprocess.run(
            [sys.executable, str(_HEALTHCHECK)],
            capture_output=True,
            check=False,
            env=os.environ
            | {
                "CONNECT_CONFIG_DIR": str(_CONFIG_DIR),
                "CONNECT_REGISTRATION_SCRIPT": str(registration_script),
                "CONNECT_URL": connect_url,
                "PSQL_PUBLICATIONS": "\n".join(
                    publication for _slot, publication in _CDC_RESOURCES.values() if publication != omitted_resource
                ),
                "PSQL_SLOTS": "\n".join(
                    slot for slot, _publication in _CDC_RESOURCES.values() if slot != omitted_resource
                ),
                "PATH": os.pathsep.join((str(bin_dir), os.environ["PATH"])),
                "SECRETS_DIR": str(tmp_path / "secrets"),
            },
            text=True,
        )


def _connector_config(payload: dict[str, object], name: str) -> dict[str, object]:
    details = payload[name]
    assert isinstance(details, dict)
    info = details["info"]
    assert isinstance(info, dict)
    config = info["config"]
    assert isinstance(config, dict)
    return config


def test_compose_health_depends_on_image_registration_and_gates_dependents() -> None:
    compose = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    connect = compose["services"]["nohiki-cp-kafka-connect"]

    assert connect.get("entrypoint") is None, "Compose must retain the image entrypoint that registers connectors"
    entrypoint = _ENTRYPOINT.read_text(encoding="utf-8")
    assert re.search(r'register-connectors\.sh["\']?\s+register\b', entrypoint)
    assert connect["depends_on"]["nohiki-cp-kafka-init"] == {"condition": "service_completed_successfully"}
    assert "./scripts/kafka_connect_healthcheck.py:/kafka/scripts/compose-healthcheck.py:ro" in connect["volumes"]
    assert connect["healthcheck"]["test"] == ["CMD", "python3", "/kafka/scripts/compose-healthcheck.py"]
    kafka_ui_dependencies = compose["services"]["nohiki-cp-kafka-ui"]["depends_on"]
    assert kafka_ui_dependencies["nohiki-cp-kafka-connect"] == {"condition": "service_healthy"}


@pytest.mark.parametrize("missing", _REQUIRED_CONNECTORS)
def test_readiness_checks_every_current_connector_identity(tmp_path: Path, missing: str) -> None:
    payload = _connector_payload()
    del payload[missing]

    result = _run_healthcheck(tmp_path, payload)

    assert result.returncode == 1
    assert f"missing connector {missing}" in result.stderr


@pytest.mark.parametrize("unexpected", ["nohiki-outbox-user_auth", "qdrant-embedding-sink"])
def test_readiness_rejects_unexpected_or_legacy_identities(tmp_path: Path, unexpected: str) -> None:
    payload = _connector_payload()
    payload[unexpected] = {
        "info": {"config": {"connector.class": "example.UnexpectedConnector"}},
        "status": {"connector": {"state": "RUNNING"}, "tasks": [{"id": 0, "state": "RUNNING"}]},
    }

    result = _run_healthcheck(tmp_path, payload)

    assert result.returncode == 1
    assert f"unexpected connector {unexpected}" in result.stderr


@pytest.mark.parametrize("failed_component", ["connector", "task"])
def test_readiness_requires_connectors_and_tasks_to_be_running(tmp_path: Path, failed_component: str) -> None:
    payload = _connector_payload()
    target = payload["user-auth-service-outbox"]
    assert isinstance(target, dict)
    status = target["status"]
    assert isinstance(status, dict)
    if failed_component == "connector":
        status["connector"] = {"state": "FAILED"}
    else:
        status["tasks"] = [{"id": 0, "state": "FAILED"}]

    result = _run_healthcheck(tmp_path, payload)

    assert result.returncode == 1
    assert "user-auth-service-outbox" in result.stderr
    assert "not RUNNING" in result.stderr


@pytest.mark.parametrize(
    ("field", "incorrect"),
    [
        ("connector.class", "example.WrongConnector"),
        ("slot.name", "wrong_slot"),
        ("publication.name", "wrong_publication"),
    ],
)
def test_readiness_requires_exact_registered_config(tmp_path: Path, field: str, incorrect: str) -> None:
    payload = _connector_payload()
    _connector_config(payload, "user-auth-service-outbox")[field] = incorrect

    result = _run_healthcheck(tmp_path, payload)

    assert result.returncode == 1
    assert f"user-auth-service-outbox has unexpected {field}" in result.stderr


@pytest.mark.parametrize("resource", ["slot", "publication"])
def test_readiness_waits_for_cdc_replication_resources(tmp_path: Path, resource: str) -> None:
    payload = _connector_payload()
    config = _connector_config(payload, "user-auth-service-outbox")
    key = "slot.name" if resource == "slot" else "publication.name"
    omitted = config[key]
    assert isinstance(omitted, str)

    result = _run_healthcheck(tmp_path, payload, omitted)

    assert result.returncode == 1
    label = "replication slot" if resource == "slot" else "publication"
    assert f"missing {label} {omitted}" in result.stderr


@pytest.mark.parametrize(
    "unsupported",
    [
        "    $DYNAMIC_CONNECTOR",
        '    "user-auth-service:user_auth_schema" extra',
        "    source /tmp/connectors",
        "    user-auth-service:user_auth_schema",
    ],
)
def test_registration_array_parser_rejects_unsupported_entries(tmp_path: Path, unsupported: str) -> None:
    registration = tmp_path / "register-connectors.sh"
    source = _REGISTRATION.read_text(encoding="utf-8")
    registration.write_text(
        source.replace("OUTBOX_CONNECTORS=(\n", f"OUTBOX_CONNECTORS=(\n{unsupported}\n", 1), encoding="utf-8"
    )

    result = _run_healthcheck(tmp_path, _connector_payload(), registration_script=registration)

    assert result.returncode == 1
    assert "unsupported OUTBOX_CONNECTORS entry" in result.stderr


def test_absent_optional_qdrant_config_is_not_required(tmp_path: Path) -> None:
    assert not (_CONFIG_DIR / "qdrant-embedding-sink.json").exists()

    result = _run_healthcheck(tmp_path, _connector_payload())

    assert result.returncode == 0, result.stderr
