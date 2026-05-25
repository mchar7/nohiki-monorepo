"""Tests for observability health checks."""

from __future__ import annotations

import json

from health_check.checks.observability.stack_health import (
    ObservabilityStackCheck,
    _check_grafana_dashboards,
    _check_grafana_datasources,
    _health_endpoints,
)
from health_check.config.services import (
    GRAFANA_EXPECTED_DASHBOARD_UIDS,
    GRAFANA_EXPECTED_DATASOURCES,
    OBSERVABILITY_CONTAINER_NAMES,
)
from health_check.core.models import CheckStatus
from health_check.platform.models import PlatformTarget, ServiceInfo, ServiceStatus

from tests.conftest import MockPlatform, make_service_info


def _obs_statuses(
    status: ServiceStatus = ServiceStatus.HEALTHY,
) -> dict[str, ServiceInfo]:
    """Build service statuses with all observability containers at the given status."""
    return {name: make_service_info(name=name, status=status) for name in OBSERVABILITY_CONTAINER_NAMES}


def _all_datasources_json() -> str:
    return json.dumps([{"name": ds} for ds in GRAFANA_EXPECTED_DATASOURCES])


def _all_dashboards_json() -> str:
    return json.dumps([{"uid": uid} for uid in GRAFANA_EXPECTED_DASHBOARD_UIDS])


class TestCheckGrafanaDatasources:
    async def test_returns_empty_when_all_present(self) -> None:
        platform = MockPlatform(_curl_result=(0, _all_datasources_json(), ""))
        result = await _check_grafana_datasources(platform)
        assert result == []

    async def test_reports_missing_datasource(self) -> None:
        partial = json.dumps([{"name": "Prometheus"}])
        platform = MockPlatform(_curl_result=(0, partial, ""))
        result = await _check_grafana_datasources(platform)
        missing = {r for r in result if "not provisioned" in r}
        assert len(missing) == len(GRAFANA_EXPECTED_DATASOURCES) - 1

    async def test_returns_error_when_api_unreachable(self) -> None:
        platform = MockPlatform(_curl_result=(1, "", "connection refused"))
        result = await _check_grafana_datasources(platform)
        assert len(result) == 1
        assert "cannot query datasources" in result[0]

    async def test_returns_error_on_invalid_json(self) -> None:
        platform = MockPlatform(_curl_result=(0, "not-json", ""))
        result = await _check_grafana_datasources(platform)
        assert len(result) == 1
        assert "cannot parse" in result[0]

    async def test_handles_non_dict_items_in_list(self) -> None:
        broken = json.dumps([None, 42, *({"name": name} for name in GRAFANA_EXPECTED_DATASOURCES)])
        platform = MockPlatform(_curl_result=(0, broken, ""))
        result = await _check_grafana_datasources(platform)
        assert result == []


class TestCheckGrafanaDashboards:
    async def test_returns_empty_when_all_present(self) -> None:
        platform = MockPlatform(_curl_result=(0, _all_dashboards_json(), ""))
        result = await _check_grafana_dashboards(platform)
        assert result == []

    async def test_reports_missing_dashboard(self) -> None:
        partial = json.dumps([{"uid": "nohiki-overview"}])
        platform = MockPlatform(_curl_result=(0, partial, ""))
        result = await _check_grafana_dashboards(platform)
        assert len(result) == len(GRAFANA_EXPECTED_DASHBOARD_UIDS) - 1

    async def test_returns_error_when_api_unreachable(self) -> None:
        platform = MockPlatform(_curl_result=(1, "", "connection refused"))
        result = await _check_grafana_dashboards(platform)
        assert len(result) == 1
        assert "cannot query dashboards" in result[0]

    async def test_returns_error_on_invalid_json(self) -> None:
        platform = MockPlatform(_curl_result=(0, "{bad}", ""))
        result = await _check_grafana_dashboards(platform)
        assert len(result) == 1
        assert "cannot parse" in result[0]

    async def test_handles_non_dict_items_in_list(self) -> None:
        boards = [{"uid": uid} for uid in GRAFANA_EXPECTED_DASHBOARD_UIDS]
        boards.append(None)
        platform = MockPlatform(_curl_result=(0, json.dumps(boards), ""))
        result = await _check_grafana_dashboards(platform)
        assert result == []


class TestObservabilityStackCheck:
    def test_metadata_check_id(self) -> None:
        assert ObservabilityStackCheck().metadata.check_id == "observability_stack"

    def test_metadata_depends_on_infra(self) -> None:
        assert "infra_services" in ObservabilityStackCheck().metadata.depends_on

    async def test_skipped_when_no_obs_containers(self) -> None:
        platform = MockPlatform(
            _service_statuses={},
            _curl_result=(0, _all_datasources_json(), ""),
        )
        result = await ObservabilityStackCheck().execute(platform)
        assert result.status == CheckStatus.SKIPPED
        assert "not deployed" in result.summary

    async def test_fails_closed_when_only_one_required_container_is_present(
        self,
    ) -> None:
        name = next(iter(OBSERVABILITY_CONTAINER_NAMES))
        statuses = {name: make_service_info(name=name, status=ServiceStatus.HEALTHY)}

        result = await ObservabilityStackCheck().execute(MockPlatform(_service_statuses=statuses))

        assert result.status == CheckStatus.FAILED
        assert len(result.details) == len(OBSERVABILITY_CONTAINER_NAMES) - 1
        assert set(result.details) == {
            f"{missing_name}: missing" for missing_name in OBSERVABILITY_CONTAINER_NAMES - {name}
        }

    async def test_fails_closed_with_exact_unhealthy_container_evidence(self) -> None:
        result = await ObservabilityStackCheck().execute(
            MockPlatform(_service_statuses=_obs_statuses(ServiceStatus.UNHEALTHY))
        )

        assert result.status == CheckStatus.FAILED
        assert set(result.details) == {
            f"{name}: {ServiceStatus.UNHEALTHY.value}" for name in OBSERVABILITY_CONTAINER_NAMES
        }

    async def test_passes_when_everything_healthy(self) -> None:
        class _MultiMockPlatform(MockPlatform):
            """Platform that returns datasources or dashboards based on URL."""

            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                if "datasources" in url:
                    return (0, _all_datasources_json(), "")
                if "search" in url:
                    return (0, _all_dashboards_json(), "")
                return (0, "ok", "")

        result = await ObservabilityStackCheck().execute(_MultiMockPlatform(_service_statuses=_obs_statuses()))
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_endpoint_unreachable(self) -> None:
        class _FailFirstEndpoint(MockPlatform):
            _call_count: int = 0

            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                if "prometheus" in url or "9090" in url:
                    return (1, "", "connection refused")
                if "datasources" in url:
                    return (0, _all_datasources_json(), "")
                if "search" in url:
                    return (0, _all_dashboards_json(), "")
                return (0, "ok", "")

        result = await ObservabilityStackCheck().execute(_FailFirstEndpoint(_service_statuses=_obs_statuses()))
        assert result.status == CheckStatus.FAILED
        assert any("Prometheus" in d for d in result.details)

    async def test_fails_when_datasource_missing(self) -> None:
        class _MissingDatasource(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                if "datasources" in url:
                    return (0, json.dumps([{"name": "Prometheus"}]), "")
                if "search" in url:
                    return (0, _all_dashboards_json(), "")
                return (0, "ok", "")

        result = await ObservabilityStackCheck().execute(_MissingDatasource(_service_statuses=_obs_statuses()))
        assert result.status == CheckStatus.FAILED
        assert any("datasource" in d for d in result.details)

    async def test_fails_when_dashboard_missing(self) -> None:
        class _MissingDashboard(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                if "datasources" in url:
                    return (0, _all_datasources_json(), "")
                if "search" in url:
                    return (0, json.dumps([{"uid": "nohiki-overview"}]), "")
                return (0, "ok", "")

        result = await ObservabilityStackCheck().execute(_MissingDashboard(_service_statuses=_obs_statuses()))
        assert result.status == CheckStatus.FAILED
        assert any("dashboard" in d for d in result.details)

    async def test_failure_count_in_summary(self) -> None:
        class _AllFailing(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                return (1, "", "error")

        result = await ObservabilityStackCheck().execute(_AllFailing(_service_statuses=_obs_statuses()))
        assert result.status == CheckStatus.FAILED
        assert "issue(s)" in result.summary


async def test_kubernetes_observability_queries_all_required_signals_without_phoenix() -> None:
    class _RecordingPlatform(MockPlatform):
        def __init__(self) -> None:
            super().__init__(target=PlatformTarget.KUBERNETES)
            self.urls: list[str] = []

        def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
            self.urls.append(url)
            if url.endswith("/api/datasources"):
                return 0, _all_datasources_json(), ""
            if "/api/search?type=dash-db" in url:
                return 0, _all_dashboards_json(), ""
            return 0, "{}", ""

    platform = _RecordingPlatform()
    result = await ObservabilityStackCheck().execute(platform)
    urls = "\n".join(platform.urls).lower()

    assert result.status == CheckStatus.PASSED
    assert "/api/v1/query?query=up" in urls
    assert "/loki/api/v1/query_range?" in urls
    assert "namespace%3d%22nohiki%22" in urls
    assert "/api/search?limit=1" in urls
    assert "/metrics" in urls
    assert "/api/datasources" in urls
    assert "/api/search?type=dash-db" in urls
    assert "phoenix" not in urls
    assert "localhost" not in urls
    assert "phoenix disabled" in result.summary.lower()


def test_kubernetes_observability_health_endpoints_are_service_dns() -> None:
    endpoints = _health_endpoints(PlatformTarget.KUBERNETES)

    assert {endpoint.description for endpoint in endpoints} == {
        "Prometheus",
        "Grafana",
        "Tempo",
        "Mimir",
        "Loki",
        "Pyroscope",
    }
    assert all("localhost" not in endpoint.url for endpoint in endpoints)
    assert all("phoenix" not in endpoint.description.lower() for endpoint in endpoints)
