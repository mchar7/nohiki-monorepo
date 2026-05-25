"""Tests for CDC health checks."""

from __future__ import annotations

import json
from unittest.mock import patch

from health_check.checks.cdc.cdc_end_to_end import CdcEndToEndCheck
from health_check.checks.cdc.debezium_connectors import DebeziumConnectorsCheck
from health_check.checks.cdc.outbox_processing import OutboxProcessingCheck
from health_check.checks.cdc.publication import PublicationCheck
from health_check.checks.cdc.replication_slot import ReplicationSlotCheck
from health_check.config.kafka import OUTBOX_CONNECTOR_NAMES
from health_check.core.models import CheckStatus, FixStatus

from tests.conftest import MockPlatform


def _connector_response(state: str = "RUNNING", task_state: str = "RUNNING") -> str:
    return json.dumps(
        {
            "connector": {"state": state},
            "tasks": [{"id": 0, "state": task_state}],
        }
    )


_KNOWN_UUID: str = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class TestCdcEndToEndCheck:
    def test_metadata_check_id(self) -> None:
        assert CdcEndToEndCheck().metadata.check_id == "cdc_end_to_end"

    def test_depends_on_debezium_and_postgres(self) -> None:
        deps = CdcEndToEndCheck().metadata.depends_on
        assert "debezium_connectors" in deps
        assert "postgres_connectivity" in deps

    async def test_passes_when_pipeline_delivers(self) -> None:
        class _DeliveredPlatform(MockPlatform):
            def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
                return (0, "", "")

            def exec_kafka_cmd(self, args: list[str], *, timeout: int = 15) -> tuple[int, str, str]:
                return (0, f"{_KNOWN_UUID}\t{{}}", "")

        with patch(
            "health_check.checks.cdc.cdc_end_to_end.uuid.uuid4",
            return_value=_KNOWN_UUID,
        ):
            result = await CdcEndToEndCheck().execute(_DeliveredPlatform())

        assert result.status == CheckStatus.PASSED
        assert "end-to-end" in result.summary

    async def test_error_when_insert_fails(self) -> None:
        class _InsertFailPlatform(MockPlatform):
            def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
                return (1, "", "permission denied")

        result = await CdcEndToEndCheck().execute(_InsertFailPlatform())
        assert result.status == CheckStatus.ERROR
        assert "user_pref_schema" in result.summary

    async def test_fails_when_kafka_times_out(self) -> None:
        class _NoDeliveryPlatform(MockPlatform):
            def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
                return (0, "", "")

        with patch(
            "health_check.checks.cdc.cdc_end_to_end.CDC_END_TO_END_MAX_WAIT_SECONDS",
            -1.0,
        ):
            result = await CdcEndToEndCheck().execute(_NoDeliveryPlatform())

        assert result.status == CheckStatus.FAILED
        assert "not delivered" in result.summary


class TestDebeziumConnectorsCheck:
    async def test_passes_when_all_running(self) -> None:
        responses = iter(
            [
                (0, json.dumps(list(OUTBOX_CONNECTOR_NAMES)), ""),
                *((0, _connector_response(), "") for _ in OUTBOX_CONNECTOR_NAMES),
            ]
        )

        class _MultiCurlPlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                return next(responses)

        result = await DebeziumConnectorsCheck().execute(_MultiCurlPlatform())
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
        connector = next(iter(OUTBOX_CONNECTOR_NAMES))
        responses = iter(
            [
                (0, json.dumps(list(OUTBOX_CONNECTOR_NAMES)), ""),
                *[
                    (0, _connector_response(task_state="FAILED" if name == connector else "RUNNING"), "")
                    for name in OUTBOX_CONNECTOR_NAMES
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
        canonical = tuple(OUTBOX_CONNECTOR_NAMES)
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
        canonical = tuple(OUTBOX_CONNECTOR_NAMES)
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
        canonical = tuple(OUTBOX_CONNECTOR_NAMES)
        cases = [
            [(1, "", "unreachable")],
            [(0, "[]", "")],
            [(0, json.dumps([*canonical, "nohiki-legacy"]), "")],
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
        canonical = tuple(OUTBOX_CONNECTOR_NAMES)
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
    async def test_passes_when_connectors_healthy_no_inactive_slots(self) -> None:
        status_body = _connector_response()

        class _HealthyPlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                return (0, status_body, "")

            def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
                return (0, "", "")

        result = await OutboxProcessingCheck().execute(_HealthyPlatform())
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_connector_unreachable(self) -> None:
        class _UnreachablePlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                return (1, "", "error")

            def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
                return (0, "", "")

        result = await OutboxProcessingCheck().execute(_UnreachablePlatform())
        assert result.status == CheckStatus.FAILED

    async def test_fails_when_inactive_slots(self) -> None:
        status_body = _connector_response()

        class _InactiveSlotPlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                return (0, status_body, "")

            def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
                return (0, "nohiki_outbox_user_pref_slot", "")

        result = await OutboxProcessingCheck().execute(_InactiveSlotPlatform())
        assert result.status == CheckStatus.FAILED
        assert any("inactive" in d for d in result.details)

    def test_metadata_check_id(self) -> None:
        assert OutboxProcessingCheck().metadata.check_id == "outbox_processing"


class TestReplicationSlotCheck:
    async def test_passes_when_active_slot_exists(self) -> None:
        platform = MockPlatform(_psql_result=(0, "nohiki_slot|t", ""))
        result = await ReplicationSlotCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_no_slots(self) -> None:
        platform = MockPlatform(_psql_result=(0, "", ""))
        result = await ReplicationSlotCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    async def test_error_when_psql_fails(self) -> None:
        platform = MockPlatform(_psql_result=(1, "", "error"))
        result = await ReplicationSlotCheck().execute(platform)
        assert result.status == CheckStatus.ERROR

    def test_metadata_check_id(self) -> None:
        assert ReplicationSlotCheck().metadata.check_id == "replication_slot"


class TestPublicationCheck:
    async def test_passes_when_publication_and_tables_exist(self) -> None:
        call_count = 0

        class _PubPlatform(MockPlatform):
            def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return (0, "nohiki_publication", "")
                return (0, "outbox_schema.outbox", "")

        result = await PublicationCheck().execute(_PubPlatform())
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_no_publication(self) -> None:
        platform = MockPlatform(_psql_result=(0, "", ""))
        result = await PublicationCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    async def test_error_when_psql_fails(self) -> None:
        platform = MockPlatform(_psql_result=(1, "", "error"))
        result = await PublicationCheck().execute(platform)
        assert result.status == CheckStatus.ERROR

    def test_metadata_check_id(self) -> None:
        assert PublicationCheck().metadata.check_id == "publication"
