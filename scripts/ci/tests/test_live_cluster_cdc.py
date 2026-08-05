"""Contracts for the required live-cluster CDC acceptance proof."""

from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_ADAPTER = _ROOT / "tests" / "integration" / "live_cluster_cdc.py"
_EXISTING_CDC_TEST = _ROOT / "tests" / "integration" / "test_debezium_cdc.py"
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


def test_verify_requires_live_cdc_after_flux_convergence_with_bounded_evidence() -> None:
    source = _LIFECYCLE.read_text(encoding="utf-8")
    verify = source[source.index("verify() {") : source.index("\ndiagnostics() {")]
    convergence = verify.index("verify_flux_observation")
    adapter = verify.index('uv run --project tests python "$cdc_adapter"')
    later_acceptance = verify.index("uv run --package ci-checks ci-checks migration-truth")
    adapter_invocation = verify[adapter : verify.index("\n    inventory=", adapter)]

    assert convergence < adapter < later_acceptance
    assert '--namespace "$namespace" --evidence "$evidence_dir/live-cdc.json"' in verify
    assert 'require_file "$cdc_adapter"' in verify
    assert "|| true" not in adapter_invocation


def test_fixture_role_and_connector_are_scoped_to_one_throwaway_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    probe = adapter.Probe(
        token=adapter.Probe.create().token,
        correlation="correlation",
        password=adapter.Probe.create().password,
    )
    mutations = adapter.Mutations()
    statements: list[tuple[str, str]] = []

    def capture_sql(_namespace: str, _pod: str, database: str, sql: str, *, check: bool = True) -> bool:
        assert check
        statements.append((database, sql))
        return True

    monkeypatch.setattr(adapter, "_admin_sql", capture_sql)
    debezium_principal = "user_pref_service_debezium"
    adapter.create_fixture("nohiki", "postgres-primary", probe, debezium_principal, mutations)
    sql = "\n".join(statement for _database, statement in statements)
    connector = adapter._connector_document(probe, "nohiki")
    config = connector["spec"]["config"]

    assert "NOREPLICATION NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT" in sql
    assert f"REVOKE ALL ON DATABASE {probe.database} FROM PUBLIC" in sql
    assert f"REVOKE ALL ON SCHEMA {probe.schema} FROM PUBLIC" in sql
    assert f"REVOKE ALL ON TABLE {probe.schema}.events FROM PUBLIC" in sql
    assert f"GRANT USAGE ON SCHEMA {probe.schema} TO {probe.writer_role}" in sql
    assert f"GRANT INSERT, DELETE ON TABLE {probe.schema}.events TO {probe.writer_role}" in sql
    assert f"GRANT USAGE ON SCHEMA {probe.schema} TO {debezium_principal}" in sql
    assert f"GRANT SELECT ON TABLE {probe.schema}.events TO {debezium_principal}" in sql
    assert f"GRANT SELECT ON TABLE {probe.schema}.events TO {probe.writer_role}" not in sql
    assert "GRANT ALL" not in sql
    assert connector["kind"] == "KafkaConnector"
    assert connector["metadata"]["labels"] == {"strimzi.io/cluster": "nohiki-connect"}
    assert config["database.dbname"] == probe.database
    assert config["database.user"] == "${file:/mnt/secrets/user-pref-service-debezium/username}"
    assert config["database.password"] == "${file:/mnt/secrets/user-pref-service-debezium/password}"
    assert probe.password not in json.dumps(connector)
    assert config["schema.include.list"] == probe.schema
    assert config["table.include.list"] == f"{probe.schema}.events"
    assert config["publication.autocreate.mode"] == "disabled"
    assert mutations == adapter.Mutations(role_created=True, database_created=True, table_created=True)


def test_probe_insert_authenticates_as_throwaway_role_and_targets_only_probe_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    probe = adapter.Probe(
        token=adapter.Probe.create().token,
        correlation="exact-correlation",
        password=adapter.Probe.create().password,
    )
    calls: list[tuple[object, ...]] = []

    def capture_role_sql(*args: object, **kwargs: object) -> bool:
        calls.append((*args, kwargs))
        return True

    monkeypatch.setattr(adapter, "_role_sql", capture_role_sql)
    adapter.insert_probe("nohiki", "postgres-primary", probe)

    assert len(calls) == 1
    assert calls[0][2] is probe
    statement = calls[0][3]
    assert isinstance(statement, str)
    assert statement.startswith(f"INSERT INTO {probe.schema}.events")
    assert probe.correlation in statement


def test_writer_password_travels_only_over_stdin_not_command_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    probe = adapter.Probe.create()
    captured: dict[str, object] = {}

    def capture_kubectl(
        _namespace: str,
        *args: str,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        captured.update(args=list(args), input_text=input_text, check=check)
        return subprocess.CompletedProcess(["kubectl"], 0, "", "")

    monkeypatch.setattr(adapter, "_kubectl", capture_kubectl)
    assert adapter._role_sql("nohiki", "postgres-primary", probe, "SELECT 1;\n")
    captured_args = captured["args"]
    assert isinstance(captured_args, list)
    assert all(isinstance(argument, str) for argument in captured_args)
    command = " ".join(argument for argument in captured_args if isinstance(argument, str))
    captured_input = captured["input_text"]
    assert isinstance(captured_input, str)
    assert probe.password not in command
    assert f"\\setenv PGPASSWORD {probe.password}" in captured_input
    assert f"@nohiki-pg-rw:5432/{probe.database}" in captured_input


def test_consumer_assertion_requires_exact_correlation_in_an_actual_debezium_record() -> None:
    adapter = _load_adapter()
    expected = "correlation-expected"
    actual = json.dumps({"before": None, "after": {"correlation_id": expected, "payload": "live-cluster-cdc"}})
    wrong = json.dumps({"before": None, "after": {"correlation_id": f"prefix-{expected}"}})

    observation = adapter._assert_correlation(f"not-json\n{actual}\n", expected)

    assert observation is not None
    assert observation.value_bytes == len(actual.encode())
    assert adapter._assert_correlation(wrong, expected) is None
    source = inspect.getsource(adapter.consume_correlated)
    assert "kafka-console-consumer.sh" in source
    assert "--topic" in source
    assert "_assert_correlation" in source
    assert "connector status" not in source.lower()


def test_existing_debezium_test_skips_only_absence_and_fails_stalled_delivery() -> None:
    source = _EXISTING_CDC_TEST.read_text(encoding="utf-8")
    absence_fixture = source[source.index("@pytest.fixture") : source.index("\n\nclass TestDebeziumConnector")]
    delivery_test = source[
        source.index("    async def test_cdc_captures_outbox_insert") : source.index("\n\nclass TestTopicRouting")
    ]

    assert "pytest.skip(reason)" in absence_fixture
    assert "pytest.skip" not in delivery_test
    assert "assert message_found" in delivery_test
    assert "CDC_DELIVERY_TIMEOUT" in delivery_test


def test_absent_cdc_resource_fails_before_mutation_with_distinct_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()

    def missing(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["kubectl"], 1, "", "Error from server (NotFound): not found")

    monkeypatch.setattr(adapter, "_kubectl", missing)
    with pytest.raises(adapter.CdcDeploymentAbsentError, match="CDC_DEPLOYMENT_ABSENT"):
        adapter.require_cdc_deployment("nohiki")


def test_present_but_not_delivering_fails_with_distinct_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    probe = adapter.Probe(
        token=adapter.Probe.create().token,
        correlation="never-arrives",
        password=adapter.Probe.create().password,
    )
    monkeypatch.setattr(adapter, "_first_pod", lambda *_args: "nohiki-connect-pod")
    monkeypatch.setattr(
        adapter,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["kubectl"],
            1,
            "",
            "TimeoutException: consumer timed out",
        ),
    )

    with pytest.raises(adapter.CdcDeliveryTimeoutError, match="CDC_DELIVERY_TIMEOUT"):
        adapter.consume_correlated("nohiki", probe, 1)


def test_consumer_tool_failure_is_not_misreported_as_delivery_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    probe = adapter.Probe.create()
    monkeypatch.setattr(adapter, "_first_pod", lambda *_args: "nohiki-connect-pod")
    monkeypatch.setattr(
        adapter,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["kubectl"], 127, "", "executable not found"),
    )

    with pytest.raises(adapter.CdcProofError, match="CDC_PROOF_FAILED") as raised:
        adapter.consume_correlated("nohiki", probe, 1)
    assert not isinstance(raised.value, adapter.CdcDeliveryTimeoutError)


def test_evidence_redacts_credentials_and_raw_correlation(tmp_path: Path) -> None:
    adapter = _load_adapter()
    probe = adapter.Probe(
        token=adapter.Probe.create().token,
        correlation="secret-correlation",
        password=adapter.Probe.create().password,
    )
    path = tmp_path / "live-cdc.json"

    adapter._write_evidence(
        path,
        probe,
        None,
        adapter.Observation(value_bytes=123),
        adapter.CleanupEvidence(
            row_deleted=True,
            connector_deleted=True,
            table_dropped=True,
            database_dropped=True,
            role_dropped=True,
        ),
    )
    raw = path.read_text(encoding="utf-8")
    evidence = json.loads(raw)

    assert probe.password not in raw
    assert probe.correlation not in raw
    assert evidence["observed"] == {"correlated_message_count": 1, "value_bytes": 123}
    assert len(evidence["correlation_sha256"]) == 64
    assert path.stat().st_size < 2048


def test_failed_connector_deletion_stops_destructive_database_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    probe = adapter.Probe.create()
    monkeypatch.setattr(adapter, "_role_sql", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        adapter,
        "_kubectl",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["kubectl"], 1, "", "delete failed"),
    )

    def forbidden_admin_sql(*_args: object, **_kwargs: object) -> bool:
        pytest.fail("database teardown ran underneath a live connector")

    monkeypatch.setattr(adapter, "_admin_sql", forbidden_admin_sql)
    cleanup = adapter._cleanup(
        "nohiki",
        "postgres-primary",
        probe,
        adapter.Mutations(role_created=True, database_created=True, table_created=True, connector_created=True),
    )

    assert cleanup.row_deleted
    assert not cleanup.connector_deleted
    assert cleanup.errors == ["connector_deleted"]
    assert not cleanup.table_dropped
    assert not cleanup.database_dropped
    assert not cleanup.role_dropped


def test_adapter_creates_no_kubernetes_job_and_cleans_every_mutation() -> None:
    source = _ADAPTER.read_text(encoding="utf-8")

    assert '"kind": "Job"' not in source
    assert "kubectl create job" not in source
    assert "DELETE FROM" in source
    assert "kafkaconnector.kafka.strimzi.io/" in source
    assert "DROP TABLE IF EXISTS" in source
    assert "DROP DATABASE IF EXISTS" in source
    assert "DROP ROLE IF EXISTS" in source
    assert "PGPASSWORD={probe.password}" not in source
    assert '"database.password": probe.password' not in source
