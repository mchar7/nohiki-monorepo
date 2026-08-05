"""Contracts for the required live-cluster CDC acceptance proof."""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Protocol
from uuid import UUID

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_ADAPTER = _ROOT / "tests" / "integration" / "live_cluster_cdc.py"
_LIFECYCLE = _ROOT / "infra" / "k8s" / "local" / "lifecycle.sh"


def _load_adapter() -> ModuleType:
    name = "live_cluster_cdc_contract"
    spec = importlib.util.spec_from_file_location(name, _ADAPTER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _connector_document(adapter: ModuleType) -> dict[str, object]:
    return {
        "spec": {
            "config": {
                "database.user": f"${{file:{adapter.DEBEZIUM_MOUNT}/username}}",
                "database.password": f"${{file:{adapter.DEBEZIUM_MOUNT}/password}}",
                "table.include.list": "user_auth_schema.outbox",
                "transforms.outbox.route.by.field": "type",
            }
        },
        "status": {
            "connectorStatus": {
                "connector": {"state": "RUNNING"},
                "tasks": [{"id": 0, "state": "RUNNING"}],
            }
        },
    }


def test_lifecycle_starts_gateway_before_required_cdc_proof() -> None:
    source = _LIFECYCLE.read_text(encoding="utf-8")
    verify = source[source.index("verify() {") : source.index("\ndiagnostics() {")]

    gateway_start = verify.index('uv run --no-sync python "$gateway_helper" start')
    adapter = verify.index('uv run --no-sync --project tests python "$cdc_adapter"')
    migration = verify.index("ci-checks migration-truth")
    jobs = verify.index("uv run --no-sync python scripts/infra/verify-k8s-jobs.py")
    gateway_stop = verify.index('uv run --no-sync python "$gateway_helper" stop', gateway_start + 1)

    assert gateway_start < adapter < migration < jobs < gateway_stop
    assert '--evidence "$evidence_dir/live-cdc.json"' in verify


def test_deployment_precheck_requires_canonical_connector_and_separate_principals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    required: list[str] = []
    connector = _connector_document(adapter)

    monkeypatch.setattr(adapter, "_require_deployed_resource", lambda _namespace, resource: required.append(resource))
    monkeypatch.setattr(
        adapter,
        "_kubectl",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["kubectl"], 0, json.dumps(connector), ""),
    )
    monkeypatch.setattr(
        adapter,
        "_decode_secret_username",
        lambda _namespace, resource: (
            "user_auth_svc" if resource == adapter.SERVICE_CREDENTIALS_RESOURCE else "user_auth_debezium"
        ),
    )

    adapter.require_cdc_deployment("nohiki")

    assert f"kafkaconnector.kafka.strimzi.io/{adapter.CONNECTOR_NAME}" in required
    assert "deployment.apps/nohiki-user-auth-service" in required
    assert "deployment.apps/nohiki-bff-service" in required
    assert f"secret/{adapter.SERVICE_CREDENTIALS_RESOURCE}" in required
    assert f"secret/{adapter.DEBEZIUM_CREDENTIALS_RESOURCE}" in required


def test_deployment_precheck_rejects_shared_dml_and_replication_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    connector = _connector_document(adapter)
    monkeypatch.setattr(adapter, "_require_deployed_resource", lambda *_args: None)
    monkeypatch.setattr(
        adapter,
        "_kubectl",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["kubectl"], 0, json.dumps(connector), ""),
    )
    monkeypatch.setattr(adapter, "_decode_secret_username", lambda *_args: "shared_role")

    with pytest.raises(adapter.CdcProofError, match="principals are not separated"):
        adapter.require_cdc_deployment("nohiki")


def test_secret_username_decode_never_reads_password(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter()
    document = {
        "data": {
            "username": base64.b64encode(b"user_auth_debezium").decode(),
            "password": base64.b64encode(b"do-not-read").decode(),
        }
    }
    monkeypatch.setattr(
        adapter,
        "_kubectl",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["kubectl"], 0, json.dumps(document), ""),
    )

    assert adapter._decode_secret_username("nohiki", "credentials") == "user_auth_debezium"


def test_canonical_observation_requires_topic_key_snapshot_metadata() -> None:
    adapter = _load_adapter()
    user_id = UUID("11111111-1111-4111-8111-111111111111")
    document = {
        "status": "delivered",
        "topic": adapter.CANONICAL_TOPIC,
        "partition": 1,
        "offset": 42,
        "value_bytes": 512,
        "key": str(user_id),
        "event_id": "22222222-2222-4222-8222-222222222222",
        "source_service": "user-auth-service",
    }

    observation = adapter._validate_canonical_observation(document, user_id=user_id, phase="before-restart")

    assert observation.topic == "user-auth.cdc.account-updated.v1"
    assert observation.partition == 1
    assert observation.offset == 42
    assert len(observation.key_sha256) == 64

    wrong = document | {"key": "33333333-3333-4333-8333-333333333333"}
    with pytest.raises(adapter.CdcConsumerExecutionError, match="record key"):
        adapter._validate_canonical_observation(wrong, user_id=user_id, phase="before-restart")


def test_consumer_execution_failure_is_distinct_from_non_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _load_adapter()
    probe = adapter.AccountProbe.create("before-restart")
    user_id = UUID("11111111-1111-4111-8111-111111111111")
    monkeypatch.setattr(adapter, "_first_pod", lambda *_args: "nohiki-bff-service-pod")
    monkeypatch.setattr(
        adapter,
        "_kubectl",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["kubectl"], 7, "", "consumer crashed"),
    )

    with pytest.raises(adapter.CdcConsumerExecutionError, match="execution failed") as failed:
        adapter.consume_canonical_account_event("nohiki", user_id, probe, 1)
    assert not isinstance(failed.value, adapter.CdcDeliveryTimeoutError)

    monkeypatch.setattr(
        adapter,
        "_kubectl",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["kubectl"], 0, '{"status":"timeout"}\n', ""),
    )
    with pytest.raises(adapter.CdcDeliveryTimeoutError, match="CDC_DELIVERY_TIMEOUT"):
        adapter.consume_canonical_account_event("nohiki", user_id, probe, 1)


def test_connector_running_requires_connector_and_every_task() -> None:
    adapter = _load_adapter()
    running = _connector_document(adapter)

    assert adapter._connector_is_running(running)

    failed_task = json.loads(json.dumps(running))
    failed_task["status"]["connectorStatus"]["tasks"][0]["state"] = "FAILED"
    assert not adapter._connector_is_running(failed_task)


def test_restart_rolls_actual_connect_deployment_before_waiting_for_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    calls: list[tuple[str, ...]] = []

    def capture(_namespace: str, *args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(["kubectl"], 0, "", "")

    monkeypatch.setattr(adapter, "_kubectl", capture)
    monkeypatch.setattr(
        adapter, "_wait_connector_running", lambda namespace, timeout: calls.append((namespace, str(timeout)))
    )

    evidence = adapter.restart_connect("nohiki", 30)

    assert calls[0] == ("rollout", "restart", f"deployment.apps/{adapter.CONNECT_DEPLOYMENT}")
    assert calls[1][:3] == ("rollout", "status", f"deployment.apps/{adapter.CONNECT_DEPLOYMENT}")
    assert calls[2] == ("nohiki", "30")
    assert evidence.completed
    assert evidence.connector_running


def test_run_repeats_real_transaction_after_restart_and_proves_projection_cardinality(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = _load_adapter()
    user_ids = iter(
        (
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        )
    )
    restart_position: list[int] = []
    registered: list[tuple[str, str, str]] = []

    class FakeClient:
        def __init__(self, _base_url: str) -> None:
            self.user_id: UUID | None = None
            self.email = ""
            self.display_name = ""

        def register(self, email: str, _password: str, display_name: str) -> dict[str, str]:
            self.user_id = next(user_ids)
            self.email = email
            self.display_name = display_name
            registered.append((email, display_name, str(self.user_id)))
            return {"id": str(self.user_id)}

        def delete_account(self) -> None:
            assert self.user_id is not None

    class PhaseProbe(Protocol):
        phase: str

    def observe(_namespace: str, user_id: UUID, probe: PhaseProbe, _timeout: float) -> object:
        return adapter.CanonicalObservation(
            phase=probe.phase,
            topic=adapter.CANONICAL_TOPIC,
            partition=0,
            offset=len(registered),
            value_bytes=256,
            key_sha256="a" * 64,
            event_id=str(user_id),
            source_service="user-auth-service",
        )

    monkeypatch.setattr(adapter, "NohikiClient", FakeClient)
    monkeypatch.setattr(adapter, "require_cdc_deployment", lambda _namespace: None)
    monkeypatch.setattr(adapter, "_primary_pod", lambda _namespace: "postgres-primary")
    monkeypatch.setattr(adapter, "consume_canonical_account_event", observe)
    monkeypatch.setattr(adapter, "_wait_projection_count", lambda *_args: _args[4])
    monkeypatch.setattr(adapter, "_projection_count", lambda *_args: 1)
    monkeypatch.setattr(
        adapter,
        "restart_connect",
        lambda _namespace, _timeout: (
            restart_position.append(len(registered)) or adapter.RestartEvidence(completed=True, connector_running=True)
        ),
    )
    evidence_path = tmp_path / "live-cdc.json"

    adapter.run("nohiki", "http://127.0.0.1:8000", evidence_path, 5)

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert restart_position == [1]
    assert len(registered) == 2
    assert evidence["status"] == "passed"
    assert [item["phase"] for item in evidence["observed"]] == ["before-restart", "after-restart"]
    assert [item["row_count"] for item in evidence["projections"]] == [1, 1]
    assert evidence["cleanup"]["accounts_deleted"] == 2
    assert evidence["cleanup"]["projections_deleted"] == 2


def test_evidence_redacts_account_credentials_and_raw_identifiers(tmp_path: Path) -> None:
    adapter = _load_adapter()
    path = tmp_path / "live-cdc.json"
    observation = adapter.CanonicalObservation(
        phase="before-restart",
        topic=adapter.CANONICAL_TOPIC,
        partition=0,
        offset=1,
        value_bytes=128,
        key_sha256="a" * 64,
        event_id="event-id",
        source_service="user-auth-service",
    )
    projection = adapter.ProjectionObservation("before-restart", 1, "b" * 64)

    adapter._write_evidence(
        path,
        None,
        [observation],
        [projection],
        adapter.RestartEvidence(
            deployment=adapter.CONNECT_DEPLOYMENT,
            completed=True,
            connector_running=True,
        ),
        adapter.CleanupEvidence(1, 1),
    )

    raw = path.read_text(encoding="utf-8")
    evidence = json.loads(raw)
    assert "password" not in raw.lower()
    assert "@example.invalid" not in raw
    assert evidence["canonical_topic"] == "user-auth.cdc.account-updated.v1"
    assert evidence["restart"]["connector_running"] is True
    assert path.stat().st_mode & 0o777 == 0o644


def test_adapter_uses_production_service_and_connector_surfaces_only() -> None:
    source = _ADAPTER.read_text(encoding="utf-8")

    assert "client.register(" in source
    assert "_wait_projection_count(" in source
    assert '"rollout", "restart"' in source
    assert "AccountUpdated().parse(record.value)" in source
    assert "user-auth.cdc.account-updated.v1" in source
    assert '"apply", "--filename=-"' not in source
    assert "CREATE ROLE" not in source
    assert "CREATE PUBLICATION" not in source
