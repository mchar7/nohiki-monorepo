"""Contracts for the required live-cluster CDC acceptance proof."""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast
from uuid import UUID

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_ADAPTER = _ROOT / "scripts" / "util" / "health_check" / "src" / "health_check" / "acceptance" / "live_cluster_cdc.py"
_SHIM = _ROOT / "tests" / "integration" / "live_cluster_cdc.py"
_LIFECYCLE = _ROOT / "infra" / "k8s" / "local" / "lifecycle.sh"


class _Observation(Protocol):
    phase: str
    consumer_group: str
    partition: int
    committed_offset: int


class _Probe(Protocol):
    phase: str


class _Restart(Protocol):
    before: object | None
    after: object | None
    completed: bool
    connector_running: bool
    identity_changed: bool


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


def _observation(
    adapter: ModuleType,
    phase: str,
    offset: int,
    event_id: str,
    group_id: str = "cdc-acceptance-stable",
) -> _Observation:
    return adapter.CanonicalObservation(
        phase=phase,
        topic=adapter.CANONICAL_TOPIC,
        partition=2,
        offset=offset,
        committed_offset=offset + 1,
        consumer_group=group_id,
        value_bytes=256,
        key_sha256="a" * 64,
        event_id=event_id,
        source_service="user-auth-service",
    )


def _write_valid_evidence(adapter: ModuleType, path: Path) -> dict[str, object]:
    before = _observation(adapter, "before-restart", 10, "event-before")
    after = _observation(adapter, "after-restart", 20, "event-after")
    registered = [
        adapter.RegisteredGroupObservation("before-restart", "bff-runtime-group", 2, 11),
        adapter.RegisteredGroupObservation("after-restart", "bff-runtime-group", 2, 21),
    ]
    projections = [
        adapter.ProjectionObservation("before-restart", 1, "b" * 64),
        adapter.ProjectionObservation("after-restart", 1, "b" * 64),
    ]
    restart = adapter.RestartEvidence(
        before=adapter.ConnectPodIdentity("connect-old", "uid-old", "2026-08-05T00:00:00Z"),
        after=adapter.ConnectPodIdentity("connect-new", "uid-new", "2026-08-05T00:01:00Z"),
        completed=True,
        connector_running=True,
        identity_changed=True,
    )
    continuity = adapter._prove_continuity([before, after], registered)
    adapter._write_evidence(
        path,
        None,
        [before, after],
        projections,
        registered,
        restart,
        continuity,
        adapter.CleanupEvidence(accounts_deleted=1, projections_deleted=1),
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_packaged_adapter_is_the_lifecycle_entrypoint() -> None:
    shim = _SHIM.read_text(encoding="utf-8")
    lifecycle = _LIFECYCLE.read_text(encoding="utf-8")
    verify = lifecycle[lifecycle.index("verify() {") :]

    assert "from health_check.acceptance.live_cluster_cdc import main" in shim
    assert 'cdc_adapter_module="health_check.acceptance.live_cluster_cdc"' in lifecycle
    assert 'python -m "$cdc_adapter_module"' in verify
    assert '--evidence "$CDC_ACCEPTANCE_EVIDENCE"' in verify


def test_deployment_precheck_requires_canonical_connector_and_distinct_identities(
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
            "user_auth_service" if resource == adapter.SERVICE_CREDENTIALS_RESOURCE else "user_auth_debezium"
        ),
    )

    adapter.require_cdc_deployment("nohiki")

    assert f"kafkaconnector.kafka.strimzi.io/{adapter.CONNECTOR_NAME}" in required
    assert f"deployment.apps/{adapter.CONNECT_DEPLOYMENT}" in required
    assert f"secret/{adapter.DEBEZIUM_CREDENTIALS_RESOURCE}" in required


def test_deployment_precheck_rejects_reused_database_login(
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
    monkeypatch.setattr(adapter, "_decode_secret_username", lambda *_args: "inherited-owner-login")

    with pytest.raises(adapter.CdcProofError, match="not distinct"):
        adapter.require_cdc_deployment("nohiki")


def test_distinct_identity_control_records_accepted_inherited_owner_limitation(tmp_path: Path) -> None:
    adapter = _load_adapter()
    document = _write_valid_evidence(adapter, tmp_path / "live-cdc.json")
    raw = json.dumps(document)
    control = cast("dict[str, object]", document["database_identity_control"])

    assert control["kind"] == "distinct-identity"
    assert control["supports"] == ["attribution", "independent-revocation"]
    assert control["inherited_owner_privilege"] is True
    limitation = control["accepted_limitation"]
    assert isinstance(limitation, str)
    assert "accepted limitation" in limitation.lower()
    assert "filtered publication autocreation" in limitation
    assert "table-scoped SELECT" in limitation
    assert "least privilege" not in raw.lower()
    assert "separation of duties" not in raw.lower()


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


def test_canonical_observation_requires_explicit_commit_and_resume_position() -> None:
    adapter = _load_adapter()
    user_id = UUID("11111111-1111-4111-8111-111111111111")
    group_id = "cdc-acceptance-stable"
    document: dict[str, object] = {
        "status": "delivered",
        "topic": adapter.CANONICAL_TOPIC,
        "partition": 2,
        "offset": 42,
        "committed_offset": 43,
        "consumer_group": group_id,
        "value_bytes": 512,
        "key": str(user_id),
        "event_id": "22222222-2222-4222-8222-222222222222",
        "source_service": "user-auth-service",
    }

    before = adapter._validate_canonical_observation(
        document,
        user_id=user_id,
        phase="before-restart",
        group_id=group_id,
    )
    assert before.committed_offset == before.offset + 1

    replay = document | {"offset": 41, "committed_offset": 42, "event_id": "event-after"}
    with pytest.raises(adapter.CdcConsumerExecutionError, match="replayed"):
        adapter._validate_canonical_observation(
            replay,
            user_id=user_id,
            phase="after-restart",
            group_id=group_id,
            resume_from=before,
        )


def test_consumer_reuses_one_group_and_commits_without_touching_registered_group() -> None:
    adapter = _load_adapter()
    probe = adapter.AccountProbe.create("before-restart")
    user_id = UUID("11111111-1111-4111-8111-111111111111")
    before = _observation(adapter, "before-restart", 42, "event-before")

    first = adapter._consumer_script(user_id, probe, before.consumer_group, 1, None)
    second = adapter._consumer_script(user_id, probe.updated(), before.consumer_group, 1, before)
    registered = adapter._registered_group_script(before.partition)

    assert 'group_id=EXPECTED["group_id"]' in first
    assert 'group_id=EXPECTED["group_id"]' in second
    assert "await consumer.commit" in first
    assert '"minimum_offset":43' in second
    assert "projection_priority_group_id" in registered
    assert "consumer.subscribe" not in registered
    assert "await consumer.committed" in registered


def test_connect_pod_identity_reads_running_pod_uid_and_start_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    pods = {
        "items": [
            {
                "metadata": {"name": "connect-0", "uid": "pod-uid"},
                "status": {"phase": "Running", "startTime": "2026-08-05T00:00:00Z"},
            }
        ]
    }
    monkeypatch.setattr(
        adapter,
        "_kubectl",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["kubectl"], 0, json.dumps(pods), ""),
    )

    identity = adapter._connect_pod_identity("nohiki")

    assert identity.name == "connect-0"
    assert identity.uid == "pod-uid"
    assert identity.start_time == "2026-08-05T00:00:00Z"


def test_restart_records_actual_pod_identity_and_rejects_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    before = adapter.ConnectPodIdentity("connect-old", "uid-old", "2026-08-05T00:00:00Z")
    after = adapter.ConnectPodIdentity("connect-new", "uid-new", "2026-08-05T00:01:00Z")
    identities = iter((before, after))
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(adapter, "_connect_pod_identity", lambda _namespace: next(identities))
    monkeypatch.setattr(
        adapter,
        "_kubectl",
        lambda _namespace, *args, **_kwargs: calls.append(args) or subprocess.CompletedProcess(["kubectl"], 0, "", ""),
    )
    monkeypatch.setattr(adapter, "_wait_connector_running", lambda *_args: None)

    evidence = adapter.restart_connect("nohiki", 30)

    assert evidence.before == before
    assert evidence.after == after
    assert evidence.identity_changed
    assert calls[0] == ("rollout", "restart", f"deployment.apps/{adapter.CONNECT_DEPLOYMENT}")
    assert calls[1][:3] == ("rollout", "status", f"deployment.apps/{adapter.CONNECT_DEPLOYMENT}")

    for replacement in (
        adapter.ConnectPodIdentity("connect-new", before.uid, after.start_time),
        adapter.ConnectPodIdentity("connect-new", after.uid, before.start_time),
    ):
        no_op = iter((before, replacement))
        monkeypatch.setattr(adapter, "_connect_pod_identity", lambda _namespace, identities=no_op: next(identities))
        with pytest.raises(adapter.CdcProofError, match="did not replace"):
            adapter.restart_connect("nohiki", 30)


def test_continuity_requires_same_partition_new_event_and_registered_group_progress() -> None:
    adapter = _load_adapter()
    before = _observation(adapter, "before-restart", 10, "event-before")
    after = _observation(adapter, "after-restart", 20, "event-after")
    registered = [
        adapter.RegisteredGroupObservation("before-restart", "bff-runtime-group", 2, 11),
        adapter.RegisteredGroupObservation("after-restart", "bff-runtime-group", 2, 21),
    ]

    continuity = adapter._prove_continuity([before, after], registered)

    assert continuity.consumer_group == before.consumer_group == after.consumer_group
    assert continuity.registered_consumer_group == "bff-runtime-group"
    assert continuity.same_partition
    assert continuity.after_offset >= continuity.committed_offset
    assert continuity.event_id_changed
    assert continuity.no_replay
    assert continuity.registered_group_caught_up
    assert continuity.registered_group_advanced

    replay = _observation(adapter, "after-restart", 10, "event-after")
    with pytest.raises(adapter.CdcProofError, match="continuity"):
        adapter._prove_continuity([before, replay], registered)


def test_run_updates_one_registered_account_and_writes_valid_redacted_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = _load_adapter()
    user_id = UUID("11111111-1111-4111-8111-111111111111")
    requests: list[tuple[str, str, object]] = []
    groups: list[str] = []

    class FakeResponse:
        def __init__(self, document: dict[str, str] | None = None) -> None:
            self.document = document or {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return self.document

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def post(self, path: str, *, json: object) -> FakeResponse:
            requests.append(("POST", path, json))
            return FakeResponse({"id": str(user_id)})

        def patch(self, path: str, *, json: object) -> FakeResponse:
            requests.append(("PATCH", path, json))
            return FakeResponse()

        def delete(self, path: str) -> FakeResponse:
            requests.append(("DELETE", path, None))
            return FakeResponse()

        def close(self) -> None:
            return None

    def observe(
        _namespace: str,
        observed_user_id: UUID,
        probe: _Probe,
        group_id: str,
        _timeout: float,
        *,
        resume_from: _Observation | None = None,
    ) -> _Observation:
        assert observed_user_id == user_id
        groups.append(group_id)
        if resume_from is None:
            return _observation(adapter, probe.phase, 10, "event-before", group_id)
        assert resume_from.committed_offset == 11
        return _observation(adapter, probe.phase, 20, "event-after", group_id)

    def restart(_namespace: str, _timeout: float, evidence: _Restart) -> _Restart:
        evidence.before = adapter.ConnectPodIdentity("connect-old", "uid-old", "2026-08-05T00:00:00Z")
        evidence.after = adapter.ConnectPodIdentity("connect-new", "uid-new", "2026-08-05T00:01:00Z")
        evidence.completed = True
        evidence.connector_running = True
        evidence.identity_changed = True
        return evidence

    def registered(
        _namespace: str,
        phase: str,
        partition: int,
        event_offset: int,
        _timeout: float,
    ) -> object:
        return adapter.RegisteredGroupObservation(phase, "bff-runtime-group", partition, event_offset + 1)

    monkeypatch.setattr(adapter.httpx, "Client", FakeClient)
    monkeypatch.setattr(adapter, "require_cdc_deployment", lambda _namespace: None)
    monkeypatch.setattr(adapter, "_primary_pod", lambda _namespace: "postgres-primary")
    monkeypatch.setattr(adapter, "consume_canonical_account_event", observe)
    monkeypatch.setattr(adapter, "_wait_projection_count", lambda *_args: _args[4])
    monkeypatch.setattr(adapter, "_wait_registered_group_past", registered)
    monkeypatch.setattr(adapter, "restart_connect", restart)
    evidence_path = tmp_path / "live-cdc.json"

    adapter.run("nohiki", "http://nohiki.localhost:8080", evidence_path, 5)

    document = json.loads(evidence_path.read_text(encoding="utf-8"))
    raw = evidence_path.read_text(encoding="utf-8")
    assert [method for method, _path, _body in requests] == ["POST", "PATCH", "DELETE"]
    assert requests[1][1] == "/api/v1/account"
    update_body = requests[1][2]
    assert isinstance(update_body, dict)
    update_document = cast("dict[str, object]", update_body)
    assert str(update_document["display_name"]).startswith("CDC after-restart ")
    assert groups[0] == groups[1]
    assert document["observed"][0]["partition"] == document["observed"][1]["partition"]
    assert document["observed"][1]["offset"] > document["observed"][0]["offset"]
    assert document["observed"][0]["event_id"] != document["observed"][1]["event_id"]
    assert adapter.evidence_is_valid(document)
    assert str(user_id) not in raw
    assert "@example.invalid" not in raw
    assert "password" not in raw.lower()
    assert evidence_path.stat().st_mode & 0o777 == 0o644


def test_evidence_validator_rejects_noop_restart_replay_and_missing_registered_group(tmp_path: Path) -> None:
    adapter = _load_adapter()
    document = _write_valid_evidence(adapter, tmp_path / "live-cdc.json")
    assert adapter.evidence_is_valid(document)
    advanced_schema = deepcopy(document)
    advanced_schema["schema_version"] = adapter.EVIDENCE_SCHEMA_VERSION + 1
    assert adapter.evidence_is_valid(advanced_schema)

    no_op = deepcopy(document)
    no_op_restart = cast("dict[str, object]", no_op["restart"])
    no_op_after = cast("dict[str, object]", no_op_restart["after"])
    no_op_before = cast("dict[str, object]", no_op_restart["before"])
    no_op_after["uid"] = no_op_before["uid"]
    assert not adapter.evidence_is_valid(no_op)

    replay = deepcopy(document)
    replay_observed = cast("list[dict[str, object]]", replay["observed"])
    replay_observed[1]["offset"] = replay_observed[0]["offset"]
    assert not adapter.evidence_is_valid(replay)

    missing_registered = deepcopy(document)
    missing_registered["registered_group_offsets"] = []
    assert not adapter.evidence_is_valid(missing_registered)


def test_absent_cluster_resource_fails_closed_and_writes_diagnostic_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = _load_adapter()
    monkeypatch.setattr(
        adapter,
        "_kubectl",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["kubectl"], 1, "", "not found"),
    )
    evidence_path = tmp_path / "live-cdc.json"

    with pytest.raises(adapter.CdcDeploymentAbsentError, match="CDC_DEPLOYMENT_ABSENT"):
        adapter.main(["--namespace", "nohiki", "--evidence", str(evidence_path)])

    document = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert document["status"] == "failed"
    assert document["failure_class"] == "absent-deployment"
    assert "CDC_DEPLOYMENT_ABSENT" in document["failure_message"]
    assert not adapter.evidence_is_valid(document)


def test_adapter_uses_only_production_service_and_connector_surfaces() -> None:
    source = _ADAPTER.read_text(encoding="utf-8")

    assert "httpx.Client" in source
    assert 'client.patch("/api/v1/account"' in source
    assert "NohikiClient" not in source
    assert "AccountUpdated().parse(record.value)" in source
    assert "CREATE ROLE" not in source
    assert "CREATE PUBLICATION" not in source
