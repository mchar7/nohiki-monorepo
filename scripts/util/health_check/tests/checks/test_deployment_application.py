"""Focused tests for deployment-facing application health checks."""

from __future__ import annotations

from health_check.checks.application.llm_workload_readiness import LLMWorkloadReadinessCheck
from health_check.checks.application.pipeline_progress import PipelineProgressCheck
from health_check.core.models import CheckStatus
from health_check.platform.kubernetes import KubernetesPlatform
from health_check.platform.models import PlatformTarget, ServiceInfo, ServiceStatus

from tests.conftest import MockPlatform


class _ApplicationK8sPlatform(KubernetesPlatform):
    """Kubernetes adapter with deterministic workload and log observations."""

    def __init__(
        self,
        statuses: dict[str, ServiceInfo],
        logs: dict[str, str] | None = None,
    ) -> None:
        super().__init__(namespace="test", local_mode=True)
        self._statuses = statuses
        self._logs = logs or {}

    def get_service_statuses(self) -> dict[str, ServiceInfo]:
        return self._statuses

    def get_logs(self, canonical_name: str, lines: int = 50) -> str:
        assert lines == 80
        return self._logs.get(canonical_name, "")


def _service(name: str, *, ready: bool = True, status: ServiceStatus = ServiceStatus.HEALTHY) -> ServiceInfo:
    return ServiceInfo(name=name, status=status, ready=ready)


def _assert_no_topology(details: tuple[str, ...]) -> None:
    rendered = "\n".join(details)
    for private_value in (
        "https://provider.internal.example:9443/v1",
        "provider.internal.example",
        "10.42.0.19",
        ":9443",
        "sk-live-secret",
    ):
        assert private_value not in rendered


class TestLLMWorkloadReadinessCheck:
    async def test_passes_when_all_llm_workloads_are_ready(self) -> None:
        platform = _ApplicationK8sPlatform(
            {
                "doc-content-service": _service("doc-content-service"),
                "job-ingest-enrichment-service": _service("job-ingest-enrichment-service"),
            }
        )

        result = await LLMWorkloadReadinessCheck().execute(platform)

        assert result.status is CheckStatus.PASSED

    async def test_fails_with_redacted_provider_failure(self) -> None:
        provider_log = (
            "API key is invalid: sk-live-secret; endpoint https://provider.internal.example:9443/v1 at 10.42.0.19"
        )
        platform = _ApplicationK8sPlatform(
            {
                "doc-content-service": _service("doc-content-service", ready=False, status=ServiceStatus.CRASHED),
                "job-ingest-enrichment-service": _service("job-ingest-enrichment-service"),
            },
            {"doc-content-service": provider_log},
        )

        result = await LLMWorkloadReadinessCheck().execute(platform)

        assert result.status is CheckStatus.FAILED
        assert result.details == ("doc-content-service: LLM provider authentication failed",)
        _assert_no_topology(result.details)

    async def test_fails_for_missing_workload_without_echoing_topology(self) -> None:
        platform = _ApplicationK8sPlatform(
            {"doc-content-service": _service("doc-content-service")},
            {"job-ingest-enrichment-service": "connect refused at 10.42.0.19:9443"},
        )

        result = await LLMWorkloadReadinessCheck().execute(platform)

        assert result.status is CheckStatus.FAILED
        assert result.details == ("job-ingest-enrichment-service: workload is missing",)
        _assert_no_topology(result.details)

    async def test_errors_when_workloads_cannot_be_inspected(self) -> None:
        result = await LLMWorkloadReadinessCheck().execute(_ApplicationK8sPlatform({}))

        assert result.status is CheckStatus.ERROR

    async def test_skips_compose(self) -> None:
        result = await LLMWorkloadReadinessCheck().execute(MockPlatform(target=PlatformTarget.COMPOSE))

        assert result.status is CheckStatus.SKIPPED


class TestPipelineProgressCheck:
    async def test_passes_for_fresh_pending_aggregates(self) -> None:
        platform = MockPlatform(_psql_result=(0, "3|0|120|2|0|599\n", ""))

        result = await PipelineProgressCheck().execute(platform)

        assert result.status is CheckStatus.PASSED
        assert len(result.details) == 2
        _assert_no_topology(result.details)

    async def test_fails_for_stale_pipeline_aggregates(self) -> None:
        platform = MockPlatform(_psql_result=(0, "4|2|901|1|1|700\n", ""))

        result = await PipelineProgressCheck().execute(platform)

        assert result.status is CheckStatus.FAILED
        assert "3" in result.summary
        assert {detail.split(":", 1)[0] for detail in result.details} == {
            "listing ingest",
            "enrichment embedding",
        }
        _assert_no_topology(result.details)

    async def test_skips_when_aggregate_has_no_pending_work(self) -> None:
        result = await PipelineProgressCheck().execute(MockPlatform(_psql_result=(0, "0|0|0|0|0|0\n", "")))

        assert result.status is CheckStatus.SKIPPED

    async def test_errors_when_aggregate_inspection_fails_without_echoing_stderr(self) -> None:
        private_error = "connection to https://provider.internal.example:9443/v1 using sk-live-secret failed"
        result = await PipelineProgressCheck().execute(MockPlatform(_psql_result=(1, "", private_error)))

        assert result.status is CheckStatus.ERROR
        _assert_no_topology(result.details)
        assert private_error not in result.summary

    async def test_errors_for_malformed_or_negative_aggregate(self) -> None:
        malformed = MockPlatform(_psql_result=(0, "1|0|5|not-an-int|0|0", ""))
        negative = MockPlatform(_psql_result=(0, "1|-1|5|0|0|0", ""))

        malformed_result = await PipelineProgressCheck().execute(malformed)
        negative_result = await PipelineProgressCheck().execute(negative)

        assert malformed_result.status is CheckStatus.ERROR
        assert negative_result.status is CheckStatus.ERROR
