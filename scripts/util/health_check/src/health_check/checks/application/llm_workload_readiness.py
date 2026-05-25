"""Kubernetes LLM workload readiness and startup-failure detection."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.kubernetes import KubernetesPlatform
from health_check.platform.models import PlatformTarget, ServiceStatus

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="llm_workload_readiness",
    name="LLM Workload Readiness",
    category=CheckCategory.APPLICATION,
    platforms=frozenset({PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"core_services"}),
    timeout_seconds=20.0,
    description="Verify LLM-backed workloads are ready and free of known provider startup failures.",
)
_LLM_SERVICES: Final[tuple[str, ...]] = (
    "doc-content-service",
    "job-ingest-enrichment-service",
)
_LOG_LINES: Final[int] = 80
_FAILURE_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    ("llm startup timeout", "LLM provider startup timed out"),
    ("llm unavailable after", "LLM provider remained unavailable"),
    ("api key is invalid", "LLM provider authentication failed"),
    ("api key not configured", "LLM provider authentication is not configured"),
    ("api key is required", "LLM provider authentication is not configured"),
    ("no health check for provider", "LLM provider is unsupported"),
    ("unsupported provider", "LLM provider is unsupported"),
    ("unknown provider", "LLM provider is unsupported"),
    ("model not found", "Configured LLM model is unavailable"),
    ("model does not exist", "Configured LLM model is unavailable"),
    ("invalid response from openrouter", "Configured LLM model or provider route is unavailable"),
    ("provider returned an unavailable or null-field response", "Configured LLM model is unavailable"),
)


def _known_startup_failure(logs: str) -> str | None:
    """Return a safe failure class without echoing provider logs."""
    normalized = logs.casefold()
    return next((reason for pattern, reason in _FAILURE_PATTERNS if pattern in normalized), None)


class LLMWorkloadReadinessCheck(HealthCheck):
    """Detect unavailable Kubernetes workloads blocked on LLM startup."""

    metadata = _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Inspect workload state and bounded recent logs."""
        if not isinstance(platform, KubernetesPlatform):
            return self._make_result(CheckStatus.SKIPPED, "Not applicable (compose mode)")

        statuses = await asyncio.to_thread(platform.get_service_statuses)
        if not statuses:
            return self._make_result(
                CheckStatus.ERROR,
                "Unable to inspect Kubernetes workload status",
                remediation_hint="Verify cluster access and namespace availability",
            )

        failures: list[str] = []
        for service in _LLM_SERVICES:
            info = statuses.get(service)
            if info is not None and info.ready and info.status is ServiceStatus.HEALTHY:
                continue
            logs = await asyncio.to_thread(platform.get_logs, service, lines=_LOG_LINES)
            reason = _known_startup_failure(logs)
            if reason is not None:
                failures.append(f"{service}: {reason}")
            elif info is None:
                failures.append(f"{service}: workload is missing")
            elif info.status is ServiceStatus.STARTING:
                failures.append(f"{service}: workload is not ready")
            else:
                failures.append(f"{service}: workload is {info.status.value}")

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} LLM-backed workload(s) unavailable",
                details=tuple(failures),
                remediation_hint="Inspect the named workload's provider/model configuration and recent startup logs",
            )
        return self._make_result(CheckStatus.PASSED, "All LLM-backed workloads are ready")
