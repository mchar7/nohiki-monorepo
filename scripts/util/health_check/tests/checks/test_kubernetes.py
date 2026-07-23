"""Tests for Kubernetes-specific health checks."""

from __future__ import annotations

from health_check.checks.kubernetes.excessive_restarts import K8sExcessiveRestartsCheck
from health_check.checks.kubernetes.oom_killed import K8sOomKilledCheck
from health_check.checks.kubernetes.pending_pods import K8sPendingPodsCheck
from health_check.core.models import CheckStatus
from health_check.platform.kubernetes import KubernetesPlatform
from health_check.platform.models import PlatformTarget, ServiceInfo, ServiceStatus

from .._helpers import MockPlatform


class _FakeK8sPlatform(KubernetesPlatform):
    """Minimal KubernetesPlatform subclass for unit testing check logic.

    Bypasses kubectl entirely; callers supply return values directly.
    The isinstance check inside each check's execute() method requires an
    actual KubernetesPlatform instance, which MockPlatform cannot satisfy.
    """

    def __init__(
        self,
        *,
        pending_pods: list[tuple[str, str]] | None = None,
        oom_pods: list[str] | None = None,
        service_statuses: dict[str, ServiceInfo] | None = None,
    ) -> None:
        """Initialise with preset return values (no kubectl calls)."""
        self._namespace = "test"
        self._local_mode = False
        self._pending = pending_pods or []
        self._oom = oom_pods or []
        self._statuses = service_statuses or {}

    def check_pending_pods(self) -> list[tuple[str, str]]:
        """Return the preset pending-pod list."""
        return self._pending

    def check_oom_killed(self) -> list[str]:
        """Return the preset OOMKilled-pod list."""
        return self._oom

    def get_service_statuses(self) -> dict[str, ServiceInfo]:
        """Return the preset service-status mapping."""
        return self._statuses


class TestK8sPendingPodsCheck:
    """Tests for K8sPendingPodsCheck."""

    async def test_passes_when_no_pending_pods(self) -> None:
        platform = _FakeK8sPlatform(pending_pods=[])
        result = await K8sPendingPodsCheck().execute(platform)
        assert result.status == CheckStatus.PASSED
        assert "No pending" in result.summary

    async def test_fails_when_single_pending_pod(self) -> None:
        platform = _FakeK8sPlatform(pending_pods=[("nohiki-svc-bff-abc123", "Insufficient memory")])
        result = await K8sPendingPodsCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert "1" in result.summary
        assert len(result.details) == 1
        assert "Insufficient memory" in result.details[0]

    async def test_fails_when_multiple_pending_pods(self) -> None:
        platform = _FakeK8sPlatform(
            pending_pods=[
                ("nohiki-svc-bff-abc", "Insufficient memory"),
                ("nohiki-svc-ml-gateway-def", "Unschedulable: 0/3 nodes available"),
            ]
        )
        result = await K8sPendingPodsCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert "2" in result.summary
        assert len(result.details) == 2

    async def test_detail_lines_contain_pod_name_and_reason(self) -> None:
        platform = _FakeK8sPlatform(pending_pods=[("my-pod-xyz", "PodUnschedulable")])
        result = await K8sPendingPodsCheck().execute(platform)
        assert any("my-pod-xyz" in d for d in result.details)
        assert any("PodUnschedulable" in d for d in result.details)

    async def test_skipped_on_compose_platform(self) -> None:
        platform = MockPlatform(target=PlatformTarget.COMPOSE)
        result = await K8sPendingPodsCheck().execute(platform)
        assert result.status == CheckStatus.SKIPPED

    async def test_remediation_hint_present_on_failure(self) -> None:
        platform = _FakeK8sPlatform(pending_pods=[("pod-x", "reason")])
        result = await K8sPendingPodsCheck().execute(platform)
        assert result.remediation_hint is not None
        assert "kubectl" in result.remediation_hint

    def test_metadata_k8s_only(self) -> None:
        meta = K8sPendingPodsCheck().metadata
        assert PlatformTarget.KUBERNETES in meta.platforms
        assert PlatformTarget.COMPOSE not in meta.platforms

    def test_metadata_check_id(self) -> None:
        assert K8sPendingPodsCheck().metadata.check_id == "k8s_pending_pods"

    def test_metadata_depends_on_infra(self) -> None:
        assert "infra_services" in K8sPendingPodsCheck().metadata.depends_on

    def test_metadata_has_description(self) -> None:
        assert K8sPendingPodsCheck().metadata.description != ""


class TestK8sOomKilledCheck:
    """Tests for K8sOomKilledCheck."""

    async def test_passes_when_no_oom_pods(self) -> None:
        platform = _FakeK8sPlatform(oom_pods=[])
        result = await K8sOomKilledCheck().execute(platform)
        assert result.status == CheckStatus.PASSED
        assert "No OOMKilled" in result.summary

    async def test_fails_when_single_oom_pod(self) -> None:
        platform = _FakeK8sPlatform(oom_pods=["nohiki-svc-ml-compute: OOMKilled (limit: 2Gi)"])
        result = await K8sOomKilledCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert "1" in result.summary

    async def test_fails_when_multiple_oom_pods(self) -> None:
        platform = _FakeK8sPlatform(
            oom_pods=[
                "nohiki-svc-ml-compute: OOMKilled (limit: 2Gi, last seen: 5m ago)",
                "nohiki-svc-doc-content: OOMKilled (limit: 1Gi, last seen: 2m ago)",
            ]
        )
        result = await K8sOomKilledCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert "2" in result.summary
        assert len(result.details) == 2

    async def test_detail_lines_contain_pod_description(self) -> None:
        desc = "nohiki-svc-bff: OOMKilled (limit: 512Mi)"
        platform = _FakeK8sPlatform(oom_pods=[desc])
        result = await K8sOomKilledCheck().execute(platform)
        assert desc in result.details

    async def test_skipped_on_compose_platform(self) -> None:
        platform = MockPlatform(target=PlatformTarget.COMPOSE)
        result = await K8sOomKilledCheck().execute(platform)
        assert result.status == CheckStatus.SKIPPED

    async def test_remediation_hint_mentions_memory_limits(self) -> None:
        platform = _FakeK8sPlatform(oom_pods=["pod: OOMKilled"])
        result = await K8sOomKilledCheck().execute(platform)
        assert result.remediation_hint is not None
        assert "memory" in result.remediation_hint.lower()

    def test_metadata_k8s_only(self) -> None:
        meta = K8sOomKilledCheck().metadata
        assert PlatformTarget.KUBERNETES in meta.platforms
        assert PlatformTarget.COMPOSE not in meta.platforms

    def test_metadata_check_id(self) -> None:
        assert K8sOomKilledCheck().metadata.check_id == "k8s_oom_killed"

    def test_metadata_depends_on_infra(self) -> None:
        assert "infra_services" in K8sOomKilledCheck().metadata.depends_on

    def test_metadata_has_description(self) -> None:
        assert K8sOomKilledCheck().metadata.description != ""


def _make_service_info(name: str, restarts: int) -> ServiceInfo:
    """Build a ServiceInfo with the given restart count."""
    return ServiceInfo(
        name=name,
        status=ServiceStatus.HEALTHY,
        ready=True,
        restarts=restarts,
    )


class TestK8sExcessiveRestartsCheck:
    """Tests for K8sExcessiveRestartsCheck."""

    async def test_passes_when_no_services(self) -> None:
        platform = _FakeK8sPlatform(service_statuses={})
        result = await K8sExcessiveRestartsCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_passes_when_restarts_at_threshold(self) -> None:
        from health_check.config.thresholds import K8S_RESTART_THRESHOLD

        platform = _FakeK8sPlatform(
            service_statuses={
                "bff-service": _make_service_info("bff-service", K8S_RESTART_THRESHOLD),
            }
        )
        result = await K8sExcessiveRestartsCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_restarts_exceed_threshold(self) -> None:
        from health_check.config.thresholds import K8S_RESTART_THRESHOLD

        platform = _FakeK8sPlatform(
            service_statuses={
                "bff-service": _make_service_info("bff-service", K8S_RESTART_THRESHOLD + 5),
                "user-auth-service": _make_service_info("user-auth-service", 1),
            }
        )
        result = await K8sExcessiveRestartsCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert "1" in result.summary
        assert len(result.details) == 1

    async def test_fails_all_services_over_threshold(self) -> None:
        from health_check.config.thresholds import K8S_RESTART_THRESHOLD

        platform = _FakeK8sPlatform(
            service_statuses={
                f"svc-{i}": _make_service_info(f"svc-{i}", K8S_RESTART_THRESHOLD + i + 1) for i in range(3)
            }
        )
        result = await K8sExcessiveRestartsCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert "3" in result.summary

    async def test_detail_line_contains_service_name_and_count(self) -> None:
        from health_check.config.thresholds import K8S_RESTART_THRESHOLD

        platform = _FakeK8sPlatform(
            service_statuses={
                "bff-service": _make_service_info("bff-service", K8S_RESTART_THRESHOLD + 10),
            }
        )
        result = await K8sExcessiveRestartsCheck().execute(platform)
        assert any("bff-service" in d for d in result.details)

    async def test_skipped_on_compose_platform(self) -> None:
        platform = MockPlatform(target=PlatformTarget.COMPOSE)
        result = await K8sExcessiveRestartsCheck().execute(platform)
        assert result.status == CheckStatus.SKIPPED

    async def test_remediation_hint_mentions_logs(self) -> None:
        from health_check.config.thresholds import K8S_RESTART_THRESHOLD

        platform = _FakeK8sPlatform(
            service_statuses={
                "svc": _make_service_info("svc", K8S_RESTART_THRESHOLD + 1),
            }
        )
        result = await K8sExcessiveRestartsCheck().execute(platform)
        assert result.remediation_hint is not None
        assert "kubectl" in result.remediation_hint

    def test_metadata_k8s_only(self) -> None:
        meta = K8sExcessiveRestartsCheck().metadata
        assert PlatformTarget.KUBERNETES in meta.platforms
        assert PlatformTarget.COMPOSE not in meta.platforms

    def test_metadata_check_id(self) -> None:
        assert K8sExcessiveRestartsCheck().metadata.check_id == "k8s_excessive_restarts"

    def test_metadata_depends_on_infra(self) -> None:
        assert "infra_services" in K8sExcessiveRestartsCheck().metadata.depends_on

    def test_description_mentions_threshold(self) -> None:
        from health_check.config.thresholds import K8S_RESTART_THRESHOLD

        assert str(K8S_RESTART_THRESHOLD) in K8sExcessiveRestartsCheck().metadata.description
