"""Tests for infrastructure checks."""

from __future__ import annotations

import pytest
from health_check.checks.infrastructure.infra_services import InfraServicesCheck
from health_check.checks.infrastructure.kafka_broker import KafkaBrokerCheck
from health_check.checks.infrastructure.platform_services import PlatformServicesCheck
from health_check.checks.infrastructure.postgres_connectivity import (
    PostgresConnectivityCheck,
)
from health_check.checks.infrastructure.redis_health import RedisHealthCheck
from health_check.config.thresholds import QDRANT_PORT, RUSTFS_HOST_PORT
from health_check.core.models import CheckStatus
from health_check.platform.kubernetes import resolve_kubernetes_service_name
from health_check.platform.models import PlatformTarget, ServiceStatus

from .._helpers import MockPlatform, make_service_info


class TestInfraServicesCheck:
    async def test_passes_when_all_healthy(self) -> None:
        from health_check.config.services import INFRASTRUCTURE_SERVICES

        statuses = {svc: make_service_info() for svc in INFRASTRUCTURE_SERVICES}
        platform = MockPlatform(_service_statuses=statuses)
        result = await InfraServicesCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_service_missing(self) -> None:
        platform = MockPlatform(_service_statuses={})
        result = await InfraServicesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert "not found" in " ".join(result.details)

    async def test_fails_when_service_unhealthy(self) -> None:
        from health_check.config.services import INFRASTRUCTURE_SERVICES

        statuses = {
            svc: make_service_info(status=ServiceStatus.UNHEALTHY if i == 0 else ServiceStatus.HEALTHY)
            for i, svc in enumerate(INFRASTRUCTURE_SERVICES)
        }
        platform = MockPlatform(_service_statuses=statuses)
        result = await InfraServicesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    async def test_k8s_host_mode_uses_port_probes(self) -> None:
        platform = MockPlatform(target=PlatformTarget.KUBERNETES, _is_infra_managed=False, _port_open=True)
        result = await InfraServicesCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_k8s_host_mode_fails_when_port_closed(self) -> None:
        platform = MockPlatform(target=PlatformTarget.KUBERNETES, _is_infra_managed=False, _port_open=False)
        result = await InfraServicesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    def test_metadata_platforms(self) -> None:
        meta = InfraServicesCheck().metadata
        assert PlatformTarget.COMPOSE in meta.platforms
        assert PlatformTarget.KUBERNETES in meta.platforms


class TestPostgresConnectivityCheck:
    async def test_passes_when_pg_isready_succeeds(self) -> None:
        platform = MockPlatform(_exec_in_service_result=(0, "/var/run/postgresql:5432 - accepting connections", ""))
        result = await PostgresConnectivityCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_pg_isready_fails(self) -> None:
        platform = MockPlatform(_exec_in_service_result=(1, "", "no response"))
        result = await PostgresConnectivityCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    async def test_k8s_host_mode_uses_port_probe(self) -> None:
        platform = MockPlatform(target=PlatformTarget.KUBERNETES, _is_infra_managed=False, _port_open=True)
        result = await PostgresConnectivityCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_k8s_host_mode_fails_when_port_closed(self) -> None:
        platform = MockPlatform(target=PlatformTarget.KUBERNETES, _is_infra_managed=False, _port_open=False)
        result = await PostgresConnectivityCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    def test_metadata_check_id(self) -> None:
        assert PostgresConnectivityCheck().metadata.check_id == "postgres_connectivity"


class TestKafkaBrokerCheck:
    async def test_passes_when_port_open(self) -> None:
        platform = MockPlatform(_port_open=True)
        result = await KafkaBrokerCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_port_closed(self) -> None:
        platform = MockPlatform(_port_open=False)
        result = await KafkaBrokerCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    def test_metadata_check_id(self) -> None:
        assert KafkaBrokerCheck().metadata.check_id == "kafka_broker"


class TestRedisHealthCheck:
    async def test_passes_when_pong_received(self) -> None:
        platform = MockPlatform(_exec_in_service_result=(0, "PONG", ""))
        result = await RedisHealthCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_redis_unreachable(self) -> None:
        platform = MockPlatform(_exec_in_service_result=(1, "", "Connection refused"))
        result = await RedisHealthCheck().execute(platform)
        assert result.status in {CheckStatus.FAILED, CheckStatus.ERROR}

    async def test_fails_when_redis_loading_dataset(self) -> None:
        loading_info = "loading:1\nrdb_changes_since_last_save:500000"
        platform = MockPlatform(_exec_in_service_result=(0, loading_info, ""))
        result = await RedisHealthCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert any("loading" in d.lower() for d in result.details)

    async def test_fails_when_service_log_shows_redis_loading(self) -> None:
        platform = MockPlatform(
            _exec_in_service_result=(0, "server:1\n", ""),
            _logs={"bff-service": "redis is loading the dataset in memory"},
        )
        result = await RedisHealthCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert any("loading" in d.lower() for d in result.details)

    async def test_fails_when_service_log_shows_dns_failure(self) -> None:
        platform = MockPlatform(
            _exec_in_service_result=(0, "server:1\n", ""),
            _logs={"bff-service": "name or service not known (redis)"},
        )
        result = await RedisHealthCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert any("dns" in d.lower() for d in result.details)

    async def test_k8s_host_mode_passes_when_port_open(self) -> None:
        platform = MockPlatform(
            target=PlatformTarget.KUBERNETES,
            _is_infra_managed=False,
            _port_open=True,
        )
        result = await RedisHealthCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_k8s_host_mode_fails_when_port_closed(self) -> None:
        platform = MockPlatform(
            target=PlatformTarget.KUBERNETES,
            _is_infra_managed=False,
            _port_open=False,
        )
        result = await RedisHealthCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert "port" in result.summary.lower()

    def test_metadata_check_id(self) -> None:
        assert RedisHealthCheck().metadata.check_id == "redis_health"

    def test_depends_on_infra_services(self) -> None:
        assert "infra_services" in RedisHealthCheck().metadata.depends_on


class TestPlatformServicesCheck:
    async def test_passes_when_all_healthy(self) -> None:
        # Both curl (4 services) and exec_in_service (Docling) must succeed
        platform = MockPlatform(
            _curl_result=(0, "", ""),
            _exec_in_service_result=(0, "", ""),
        )
        result = await PlatformServicesCheck().execute(platform)

        assert result.status == CheckStatus.PASSED
        assert "5" in result.summary

    async def test_accepts_expected_rustfs_forbidden_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        platform = MockPlatform()

        def curl(url: str, *, timeout: int = 10) -> tuple[int, str, str]:
            del timeout
            if url == f"http://localhost:{RUSTFS_HOST_PORT}/":
                return 22, "", "curl: (22) The requested URL returned error: 403"
            return 0, "", ""

        monkeypatch.setattr(platform, "curl", curl)
        result = await PlatformServicesCheck().execute(platform)

        assert result.status == CheckStatus.PASSED

    async def test_accepts_expected_rustfs_forbidden_response_from_kubernetes_httpx(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        platform = MockPlatform(target=PlatformTarget.KUBERNETES)

        rustfs_url = f"http://{resolve_kubernetes_service_name('rustfs')}:9000/"

        def curl(url: str, *, timeout: int = 10) -> tuple[int, str, str]:
            del timeout
            if url == rustfs_url:
                return 1, "", f"Client error '403 Forbidden' for url '{rustfs_url}'"
            return 0, "", ""

        monkeypatch.setattr(platform, "curl", curl)
        result = await PlatformServicesCheck().execute(platform)

        assert result.status == CheckStatus.PASSED

    async def test_rejects_forbidden_response_from_other_services(self, monkeypatch: pytest.MonkeyPatch) -> None:
        platform = MockPlatform()

        def curl(url: str, *, timeout: int = 10) -> tuple[int, str, str]:
            del timeout
            if url == f"http://localhost:{QDRANT_PORT}/readyz":
                return 22, "", "curl: (22) The requested URL returned error: 403"
            return 0, "", ""

        monkeypatch.setattr(platform, "curl", curl)
        result = await PlatformServicesCheck().execute(platform)

        assert result.status == CheckStatus.FAILED
        assert len(result.details) == 1
        assert "Qdrant" in result.details[0]

    async def test_fails_when_all_unhealthy(self) -> None:
        platform = MockPlatform(
            _curl_result=(1, "", "Connection refused"),
            _exec_in_service_result=(1, "", "Connection refused"),
        )
        result = await PlatformServicesCheck().execute(platform)

        assert result.status == CheckStatus.FAILED
        assert len(result.details) == 5

    async def test_fails_when_exec_service_unhealthy(self) -> None:
        platform = MockPlatform(
            _curl_result=(1, "", "Connection refused"),
            _exec_in_service_result=(1, "", "Connection refused"),
        )
        result = await PlatformServicesCheck().execute(platform)

        assert result.status == CheckStatus.FAILED
        assert any("Docling" in d for d in result.details)

    async def test_failure_details_mention_service_names(self) -> None:
        platform = MockPlatform(
            _curl_result=(1, "", ""),
            _exec_in_service_result=(1, "", ""),
        )
        result = await PlatformServicesCheck().execute(platform)

        expected_names = {"RustFS", "Qdrant", "Gotenberg", "Docling", "Kafka Connect"}
        found_names = {name for name in expected_names if any(name in d for d in result.details)}
        assert found_names == expected_names

    async def test_failure_details_include_url(self) -> None:
        platform = MockPlatform(
            _curl_result=(1, "", ""),
            _exec_in_service_result=(1, "", ""),
        )
        result = await PlatformServicesCheck().execute(platform)

        assert all("http://" in d for d in result.details)

    def test_metadata_check_id(self) -> None:
        assert PlatformServicesCheck().metadata.check_id == "platform_services"

    def test_metadata_platforms(self) -> None:
        meta = PlatformServicesCheck().metadata

        assert PlatformTarget.COMPOSE in meta.platforms
        assert PlatformTarget.KUBERNETES in meta.platforms

    def test_metadata_has_no_dependencies(self) -> None:
        assert PlatformServicesCheck().metadata.depends_on == frozenset()
