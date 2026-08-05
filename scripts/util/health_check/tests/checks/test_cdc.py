"""Tests for CDC health checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from health_check.checks.cdc.debezium_connectors import DebeziumConnectorsCheck
from health_check.checks.cdc.outbox_processing import OutboxProcessingCheck
from health_check.checks.cdc.publication import PublicationCheck
from health_check.checks.cdc.replication_slot import ReplicationSlotCheck
from health_check.config.kafka import (
    SUPERSEDED_COMPOSE_CONNECTOR_NAMES,
    cdc_connectors_for,
    connector_names_for,
)
from health_check.core.models import CheckStatus, FixStatus
from health_check.platform.models import PlatformTarget

from .._helpers import MockPlatform

_TARGETS = (PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES)
_COMPOSE_CDC_CONNECTORS = cdc_connectors_for(PlatformTarget.COMPOSE)
_COMPOSE_SLOT_NAMES = tuple(connector.slot_name for connector in _COMPOSE_CDC_CONNECTORS)
_COMPOSE_CONNECTOR_NAMES = connector_names_for(PlatformTarget.COMPOSE)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]


def test_health_and_recipe_superseded_connector_inventories_match() -> None:
    registration = (
        _REPOSITORY_ROOT / "infra" / "k8s" / "kafka-connect" / "scripts" / "register-connectors.sh"
    ).read_text(encoding="utf-8")
    array = re.search(
        r"SUPERSEDED_COMPOSE_OUTBOX_CONNECTORS=\(\n(?P<entries>.*?)\n\)",
        registration,
        re.DOTALL,
    )
    assert array is not None
    assert frozenset(re.findall(r'"([^"]+)"', array.group("entries"))) == SUPERSEDED_COMPOSE_CONNECTOR_NAMES


def _connector_response(state: str = "RUNNING", task_state: str = "RUNNING") -> str:
    return json.dumps(
        {
            "connector": {"state": state},
            "tasks": [{"id": 0, "state": task_state}],
        }
    )


def _slot_rows(
    target: PlatformTarget = PlatformTarget.COMPOSE,
    *,
    inactive: str | None = None,
) -> str:
    slot_names = tuple(connector.slot_name for connector in cdc_connectors_for(target))
    return "\n".join(f"{name}|{'f' if name == inactive else 't'}" for name in slot_names)


def _publication_names(target: PlatformTarget = PlatformTarget.COMPOSE) -> str:
    return "\n".join(connector.publication_name for connector in cdc_connectors_for(target))


class TestDebeziumConnectorsCheck:
    @pytest.mark.parametrize("target", _TARGETS)
    async def test_passes_when_all_running(self, target: PlatformTarget) -> None:
        names = connector_names_for(target)
        responses = iter(
            [
                (0, json.dumps(list(names)), ""),
                *((0, _connector_response(), "") for _ in names),
            ]
        )

        class _MultiCurlPlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                return next(responses)

        result = await DebeziumConnectorsCheck().execute(_MultiCurlPlatform(target=target))
        assert result.status == CheckStatus.PASSED

    async def test_error_when_api_unreachable(self) -> None:
        platform = MockPlatform(_curl_result=(1, "", "connection refused"))
        result = await DebeziumConnectorsCheck().execute(platform)
        assert result.status == CheckStatus.ERROR

    async def test_fails_when_no_connectors(self) -> None:
        call_count = 0

        class _EmptyListPlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                nonlocal call_count
                call_count += 1
                return (0, "[]", "")

        result = await DebeziumConnectorsCheck().execute(_EmptyListPlatform())
        assert result.status == CheckStatus.FAILED
        assert "No connectors" in result.summary

    async def test_reports_superseded_compose_connector_with_reconciliation_path(self) -> None:
        names = [*_COMPOSE_CONNECTOR_NAMES, "nohiki-outbox-user_auth"]
        platform = MockPlatform(_curl_result=(0, json.dumps(names), ""))

        result = await DebeziumConnectorsCheck().execute(platform)

        assert result.status == CheckStatus.FAILED
        assert "nohiki-outbox-user_auth: unexpected connector" in result.details
        assert result.remediation_hint is not None
        assert "just connect-reconcile-compose-cdc" in result.remediation_hint

    async def test_requires_manual_remediation_for_unknown_compose_connector(self) -> None:
        names = [*_COMPOSE_CONNECTOR_NAMES, "third-party-source"]
        platform = MockPlatform(_curl_result=(0, json.dumps(names), ""))

        result = await DebeziumConnectorsCheck().execute(platform)

        assert result.status == CheckStatus.FAILED
        assert result.remediation_hint is not None
        assert "manually" in result.remediation_hint
        assert "just connect-reconcile-compose-cdc" not in result.remediation_hint

    async def test_fails_when_connector_failed(self) -> None:
        names_body = json.dumps(["conn-a"])
        status_body = _connector_response(state="FAILED")
        call_count = 0

        class _FailedConnPlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                nonlocal call_count
                call_count += 1
                return (0, names_body if call_count == 1 else status_body, "")

        result = await DebeziumConnectorsCheck().execute(_FailedConnPlatform())
        assert result.status == CheckStatus.FAILED

    async def test_fails_when_one_connector_task_failed_with_evidence(self) -> None:
        connector = next(iter(_COMPOSE_CONNECTOR_NAMES))
        responses = iter(
            [
                (0, json.dumps(list(_COMPOSE_CONNECTOR_NAMES)), ""),
                *[
                    (0, _connector_response(task_state="FAILED" if name == connector else "RUNNING"), "")
                    for name in _COMPOSE_CONNECTOR_NAMES
                ],
            ]
        )

        class _FailedTaskPlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                return next(responses)

        result = await DebeziumConnectorsCheck().execute(_FailedTaskPlatform())

        assert result.status == CheckStatus.FAILED
        assert any("task 0" in detail and "FAILED" in detail for detail in result.details)
        assert result.remediation_hint is not None

    def test_metadata_check_id(self) -> None:
        assert DebeziumConnectorsCheck().metadata.check_id == "debezium_connectors"

    def test_depends_on_kafka_and_postgres(self) -> None:
        deps = DebeziumConnectorsCheck().metadata.depends_on
        assert "kafka_broker" in deps
        assert "postgres_connectivity" in deps

    def test_fix_support_metadata(self) -> None:
        check = DebeziumConnectorsCheck()
        assert check.supports_fix is True
        assert check.fix_timeout == 10.0

    async def test_fix_restarts_first_canonical_failed_connector_once(self) -> None:
        canonical = tuple(_COMPOSE_CONNECTOR_NAMES)
        failed = canonical[1]
        responses = iter(
            [
                (0, json.dumps(list(reversed(canonical))), ""),
                *(
                    (0, _connector_response(state="FAILED" if name in {failed, canonical[-1]} else "RUNNING"), "")
                    for name in canonical
                ),
            ]
        )

        class _Platform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                return next(responses)

        platform = _Platform()
        action = await DebeziumConnectorsCheck().fix(platform, await DebeziumConnectorsCheck().execute(MockPlatform()))
        assert action.status == FixStatus.SUCCESS
        assert action.action_id == "kafka_connect.restart_failed"
        assert platform.restart_kafka_connector_calls == [(failed, 10)]

    async def test_fix_restarts_failed_task(self) -> None:
        canonical = tuple(_COMPOSE_CONNECTOR_NAMES)
        responses = iter(
            [
                (0, json.dumps(list(canonical)), ""),
                *(
                    (0, _connector_response(task_state="FAILED" if name == canonical[0] else "RUNNING"), "")
                    for name in canonical
                ),
            ]
        )

        class _Platform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                return next(responses)

        platform = _Platform()
        action = await DebeziumConnectorsCheck().fix(platform, await DebeziumConnectorsCheck().execute(MockPlatform()))
        assert action.status == FixStatus.SUCCESS
        assert platform.restart_kafka_connector_calls == [(canonical[0], 10)]

    async def test_fix_does_not_restart_unsafe_states_or_inventory(self) -> None:
        canonical = tuple(_COMPOSE_CONNECTOR_NAMES)
        cases = [
            [(1, "", "unreachable")],
            [(0, "[]", "")],
            [(0, json.dumps([*canonical, "unexpected-connector"]), "")],
            [
                (0, json.dumps(list(canonical)), ""),
                *((0, _connector_response(state="UNASSIGNED"), "") for _ in canonical),
            ],
        ]
        for response_list in cases:

            class _Platform(MockPlatform):
                responses = iter(response_list)

                def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                    return next(self.responses)

            platform = _Platform()
            action = await DebeziumConnectorsCheck().fix(
                platform, await DebeziumConnectorsCheck().execute(MockPlatform())
            )
            assert action.status in {FixStatus.NOT_SUPPORTED, FixStatus.NO_ACTION}
            assert platform.restart_kafka_connector_calls is None

    async def test_fix_maps_platform_failure_without_retry(self) -> None:
        canonical = tuple(_COMPOSE_CONNECTOR_NAMES)
        responses = iter(
            [
                (0, json.dumps(list(canonical)), ""),
                *(
                    (0, _connector_response(state="FAILED" if name == canonical[0] else "RUNNING"), "")
                    for name in canonical
                ),
            ]
        )

        class _Platform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                return next(responses)

        platform = _Platform(_restart_kafka_connector_result=(22, "", "HTTP 500"))
        action = await DebeziumConnectorsCheck().fix(platform, await DebeziumConnectorsCheck().execute(MockPlatform()))
        assert action.status == FixStatus.FAILED
        assert action.details == ("HTTP 500",)
        assert platform.restart_kafka_connector_calls == [(canonical[0], 10)]


class TestOutboxProcessingCheck:
    @pytest.mark.parametrize("target", _TARGETS)
    async def test_passes_when_connectors_healthy_no_inactive_slots(self, target: PlatformTarget) -> None:
        status_body = _connector_response()

        class _HealthyPlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                return (0, status_body, "")

            def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
                return (0, _slot_rows(target), "")

        result = await OutboxProcessingCheck().execute(_HealthyPlatform(target=target))
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_connector_unreachable(self) -> None:
        class _UnreachablePlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                return (1, "", "error")

            def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
                return (0, _slot_rows(), "")

        result = await OutboxProcessingCheck().execute(_UnreachablePlatform())
        assert result.status == CheckStatus.FAILED

    async def test_fails_when_inactive_slots(self) -> None:
        status_body = _connector_response()

        class _InactiveSlotPlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                return (0, status_body, "")

            def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
                return (0, _slot_rows(inactive=_COMPOSE_SLOT_NAMES[1]), "")

        result = await OutboxProcessingCheck().execute(_InactiveSlotPlatform())
        assert result.status == CheckStatus.FAILED
        assert any("inactive" in d for d in result.details)

    def test_metadata_check_id(self) -> None:
        assert OutboxProcessingCheck().metadata.check_id == "outbox_processing"


class TestReplicationSlotCheck:
    @pytest.mark.parametrize("target", _TARGETS)
    async def test_passes_when_exact_target_slots_are_active(self, target: PlatformTarget) -> None:
        platform = MockPlatform(target=target, _psql_result=(0, _slot_rows(target), ""))
        result = await ReplicationSlotCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_no_slots(self) -> None:
        platform = MockPlatform(_psql_result=(0, "", ""))
        result = await ReplicationSlotCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    async def test_reports_superseded_compose_slot_with_reconciliation_path(self) -> None:
        rows = f"{_slot_rows()}\nnohiki_outbox_slot_user_auth|f"
        platform = MockPlatform(_psql_result=(0, rows, ""))

        result = await ReplicationSlotCheck().execute(platform)

        assert result.status == CheckStatus.FAILED
        assert "nohiki_outbox_slot_user_auth: unexpected slot" in result.details
        assert result.remediation_hint is not None
        assert "just connect-reconcile-compose-cdc" in result.remediation_hint

    async def test_requires_manual_remediation_for_unknown_compose_slot(self) -> None:
        rows = f"{_slot_rows()}\nthird_party_slot|f"
        platform = MockPlatform(_psql_result=(0, rows, ""))

        result = await ReplicationSlotCheck().execute(platform)

        assert result.status == CheckStatus.FAILED
        assert result.remediation_hint is not None
        assert "manually" in result.remediation_hint
        assert "just connect-reconcile-compose-cdc" not in result.remediation_hint

    async def test_error_when_psql_fails(self) -> None:
        platform = MockPlatform(_psql_result=(1, "", "error"))
        result = await ReplicationSlotCheck().execute(platform)
        assert result.status == CheckStatus.ERROR

    def test_metadata_check_id(self) -> None:
        assert ReplicationSlotCheck().metadata.check_id == "replication_slot"


class TestPublicationCheck:
    @pytest.mark.parametrize("target", _TARGETS)
    async def test_passes_when_exact_target_publications_and_tables_exist(self, target: PlatformTarget) -> None:
        connectors = cdc_connectors_for(target)

        class _PubPlatform(MockPlatform):
            def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
                if "FROM pg_publication ORDER BY" in query:
                    return (0, _publication_names(target), "")
                connector = next(item for item in connectors if item.publication_name in query)
                return (0, connector.table_name, "")

        result = await PublicationCheck().execute(_PubPlatform(target=target))
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_no_publication(self) -> None:
        platform = MockPlatform(_psql_result=(0, "", ""))
        result = await PublicationCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    async def test_reports_superseded_compose_publication_with_reconciliation_path(self) -> None:
        publications = f"{_publication_names()}\nnohiki_outbox_pub_user_auth"
        connectors = cdc_connectors_for(PlatformTarget.COMPOSE)

        class _PubPlatform(MockPlatform):
            def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
                if "FROM pg_publication ORDER BY" in query:
                    return (0, publications, "")
                connector = next(item for item in connectors if item.publication_name in query)
                return (0, connector.table_name, "")

        result = await PublicationCheck().execute(_PubPlatform())

        assert result.status == CheckStatus.FAILED
        assert "nohiki_outbox_pub_user_auth: unexpected publication" in result.details
        assert result.remediation_hint is not None
        assert "just connect-reconcile-compose-cdc" in result.remediation_hint

    async def test_withholds_recipe_when_current_publication_has_unexpected_table(self) -> None:
        publications = f"{_publication_names()}\nnohiki_outbox_pub_user_auth"
        connectors = cdc_connectors_for(PlatformTarget.COMPOSE)
        affected = connectors[0]

        class _PubPlatform(MockPlatform):
            def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
                if "FROM pg_publication ORDER BY" in query:
                    return (0, publications, "")
                connector = next(item for item in connectors if item.publication_name in query)
                table = "third_party_schema.events" if connector is affected else connector.table_name
                return (0, table, "")

        result = await PublicationCheck().execute(_PubPlatform())

        assert result.status == CheckStatus.FAILED
        assert any("third_party_schema.events" in detail for detail in result.details)
        assert result.remediation_hint is not None
        assert "manually" in result.remediation_hint
        assert "just connect-reconcile-compose-cdc" not in result.remediation_hint

    async def test_requires_manual_remediation_for_unknown_compose_publication(self) -> None:
        publications = f"{_publication_names()}\nthird_party_publication"
        platform = MockPlatform(_psql_result=(0, publications, ""))

        result = await PublicationCheck().execute(platform)

        assert result.status == CheckStatus.FAILED
        assert result.remediation_hint is not None
        assert "manually" in result.remediation_hint
        assert "just connect-reconcile-compose-cdc" not in result.remediation_hint

    async def test_error_when_psql_fails(self) -> None:
        platform = MockPlatform(_psql_result=(1, "", "error"))
        result = await PublicationCheck().execute(platform)
        assert result.status == CheckStatus.ERROR

    def test_metadata_check_id(self) -> None:
        assert PublicationCheck().metadata.check_id == "publication"
