"""Tests for application services health checks."""

from __future__ import annotations

import pytest
from health_check.checks.services.core_services import CoreServicesCheck
from health_check.checks.services.service_dependencies import ServiceDependenciesCheck
from health_check.checks.services.stale_services import StaleServicesCheck
from health_check.config.services import CORE_SERVICES
from health_check.core.models import CheckStatus
from health_check.platform.models import ServiceStatus

from .._helpers import MockPlatform, make_service_info


class TestCoreServicesCheck:
    async def test_passes_when_all_healthy_clean_logs(self) -> None:
        statuses = {svc: make_service_info() for svc in CORE_SERVICES}
        platform = MockPlatform(_service_statuses=statuses, _logs=dict.fromkeys(CORE_SERVICES, "all good"))
        result = await CoreServicesCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_service_missing(self) -> None:
        platform = MockPlatform(_service_statuses={})
        result = await CoreServicesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    async def test_fails_when_service_unhealthy(self) -> None:
        svc = next(iter(CORE_SERVICES))
        statuses = {
            s: make_service_info(status=ServiceStatus.UNHEALTHY if s == svc else ServiceStatus.HEALTHY)
            for s in CORE_SERVICES
        }
        platform = MockPlatform(_service_statuses=statuses)
        result = await CoreServicesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert any(svc in detail and "unhealthy" in detail for detail in result.details)
        assert result.remediation_hint is not None

    async def test_fails_when_module_not_found_in_logs(self) -> None:
        svc = next(iter(CORE_SERVICES))
        statuses = {s: make_service_info() for s in CORE_SERVICES}
        platform = MockPlatform(
            _service_statuses=statuses,
            _logs={svc: "ModuleNotFoundError: No module named 'nohiki_db_utils'"},
        )
        result = await CoreServicesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    async def test_fails_when_excessive_restarts(self) -> None:
        from health_check.config.thresholds import K8S_RESTART_THRESHOLD

        svc = next(iter(CORE_SERVICES))
        statuses = {s: make_service_info(restarts=K8S_RESTART_THRESHOLD + 1 if s == svc else 0) for s in CORE_SERVICES}
        platform = MockPlatform(_service_statuses=statuses)
        result = await CoreServicesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert any(svc in detail and str(K8S_RESTART_THRESHOLD + 1) in detail for detail in result.details)
        assert result.remediation_hint is not None

    async def test_fails_when_db_error_in_logs(self) -> None:
        from health_check.config.kafka import DB_ERROR_PATTERNS

        svc = next(iter(CORE_SERVICES))
        statuses = {s: make_service_info() for s in CORE_SERVICES}
        pattern = next(iter(DB_ERROR_PATTERNS))
        platform = MockPlatform(
            _service_statuses=statuses,
            _logs={svc: f"FATAL: {pattern} occurred"},
        )
        result = await CoreServicesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert any("database" in d.lower() for d in result.details)

    async def test_fails_when_db_type_mismatch_in_logs(self) -> None:
        svc = next(iter(CORE_SERVICES))
        statuses = {s: make_service_info() for s in CORE_SERVICES}
        platform = MockPlatform(
            _service_statuses=statuses,
            _logs={svc: "invalid input syntax for type integer, column value"},
        )
        result = await CoreServicesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert any("DATABASE TYPE" in d for d in result.details)

    async def test_fails_when_validation_error_in_logs(self) -> None:
        svc = next(iter(CORE_SERVICES))
        statuses = {s: make_service_info() for s in CORE_SERVICES}
        platform = MockPlatform(
            _service_statuses=statuses,
            _logs={svc: "pydantic.ValidationError: 1 validation error for MyModel"},
        )
        result = await CoreServicesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert any("validation" in d.lower() for d in result.details)

    async def test_fails_when_kafka_error_in_non_consumer_service_logs(self) -> None:
        from health_check.config.kafka import KAFKA_ERROR_PATTERNS
        from health_check.config.services import KAFKA_CONSUMER_SERVICES

        non_consumers = [s for s in CORE_SERVICES if s not in KAFKA_CONSUMER_SERVICES]
        if not non_consumers:
            pytest.skip("No non-consumer core services configured")

        svc = non_consumers[0]
        statuses = {s: make_service_info() for s in CORE_SERVICES}
        pattern = next(iter(KAFKA_ERROR_PATTERNS - {"heartbeat failed", "coordinator"}), None)
        if pattern is None:
            pytest.skip("No suitable non-transient error pattern available")

        platform = MockPlatform(
            _service_statuses=statuses,
            _logs={svc: f"ERROR: {pattern} in broker"},
        )
        result = await CoreServicesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    async def test_passes_when_kafka_transient_error_but_group_has_members(self) -> None:
        from health_check.config.kafka import KAFKA_SUBSCRIPTION_INDICATORS
        from health_check.config.services import KAFKA_CONSUMER_SERVICES

        consumers = list(KAFKA_CONSUMER_SERVICES)
        if not consumers:
            pytest.skip("No Kafka consumer services configured")

        svc = consumers[0]
        statuses = {s: make_service_info() for s in CORE_SERVICES}
        indicator = next(iter(KAFKA_SUBSCRIPTION_INDICATORS))
        platform = MockPlatform(
            _service_statuses=statuses,
            _logs={svc: f"heartbeat failed: coordinator unavailable -- {indicator}"},
            _kafka_cmd_result=(0, "CONSUMER-GROUP   TOPIC   PARTITION\nconsumer-group   topic-1   0", ""),
        )
        result = await CoreServicesCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    def test_depends_on_infra(self) -> None:
        assert "infra_services" in CoreServicesCheck().metadata.depends_on


class TestServiceDependenciesCheck:
    async def test_passes_when_all_importable(self) -> None:
        platform = MockPlatform(_exec_in_service_result=(0, "", ""))
        result = await ServiceDependenciesCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_import_fails(self) -> None:
        platform = MockPlatform(_exec_in_service_result=(1, "", "ModuleNotFoundError"))
        result = await ServiceDependenciesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    def test_metadata_check_id(self) -> None:
        assert ServiceDependenciesCheck().metadata.check_id == "service_dependencies"

    def test_depends_on_core_services(self) -> None:
        assert "core_services" in ServiceDependenciesCheck().metadata.depends_on


class TestStaleServicesCheck:
    async def test_passes_when_all_services_fresh(self) -> None:
        from health_check.config.services import KAFKA_CONSUMER_SERVICES
        from health_check.config.thresholds import STALE_SERVICE_THRESHOLD_HOURS

        statuses = {
            svc: make_service_info(uptime_seconds=(STALE_SERVICE_THRESHOLD_HOURS - 1) * 3600)
            for svc in KAFKA_CONSUMER_SERVICES
        }
        platform = MockPlatform(_service_statuses=statuses)
        result = await StaleServicesCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_passes_when_old_but_no_kafka_issues_in_logs(self) -> None:
        from health_check.config.services import KAFKA_CONSUMER_SERVICES
        from health_check.config.thresholds import STALE_SERVICE_THRESHOLD_HOURS

        statuses = {
            svc: make_service_info(uptime_seconds=(STALE_SERVICE_THRESHOLD_HOURS + 1) * 3600)
            for svc in KAFKA_CONSUMER_SERVICES
        }
        platform = MockPlatform(
            _service_statuses=statuses,
            _logs=dict.fromkeys(KAFKA_CONSUMER_SERVICES, "all normal"),
        )
        result = await StaleServicesCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_fails_stale_service_with_kafka_issues_and_no_members(self) -> None:
        from health_check.config.services import KAFKA_CONSUMER_SERVICES
        from health_check.config.thresholds import STALE_SERVICE_THRESHOLD_HOURS

        svc = next(iter(KAFKA_CONSUMER_SERVICES))
        statuses = {svc: make_service_info(uptime_seconds=(STALE_SERVICE_THRESHOLD_HOURS + 1) * 3600)}
        log_content = "heartbeat failed: coordinator unavailable"
        platform = MockPlatform(
            _service_statuses=statuses,
            _logs={svc: log_content},
            _kafka_cmd_result=(1, "", "error"),
        )
        result = await StaleServicesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    def test_metadata_check_id(self) -> None:
        assert StaleServicesCheck().metadata.check_id == "stale_services"
