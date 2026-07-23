"""ML model readiness recurrence detector."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Final

from health_check.config.thresholds import HTTP_CHECK_TIMEOUT_SECONDS
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final = CheckMetadata(
    check_id="model_readiness",
    name="Model Readiness",
    category=CheckCategory.APPLICATION,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"runtime_artifacts"}),
    description="Verify the ML compute readiness gate reports warmed inference models.",
)


class ModelReadinessCheck(HealthCheck):
    """Probe the model-backed readiness gate without user content."""

    metadata = _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Validate the model readiness endpoint response."""
        probe = (
            "import urllib.request; "
            f"print(urllib.request.urlopen('http://localhost:8000/readyz', "
            f"timeout={HTTP_CHECK_TIMEOUT_SECONDS}).read().decode())"
        )
        code, stdout, _ = await asyncio.to_thread(
            platform.exec_in_service,
            "ml-compute-service",
            ["python", "-c", probe],
            timeout=int(HTTP_CHECK_TIMEOUT_SECONDS) + 1,
        )
        if code != 0:
            return self._make_result(
                CheckStatus.FAILED,
                "ML inference models are not ready",
                details=("ml-compute-service readiness probe failed",),
                remediation_hint="Inspect ml-compute model cache/download and warm-up logs",
            )
        response = stdout.strip()
        if not response:
            return self._make_result(
                CheckStatus.FAILED,
                "ML readiness response is empty",
                details=("ml-compute-service returned an empty readiness response",),
                remediation_hint="Inspect ml-compute model cache/download and warm-up logs",
            )
        try:
            payload = json.loads(response)
        except json.JSONDecodeError:
            return self._make_result(
                CheckStatus.FAILED,
                "ML readiness response is invalid JSON",
                details=("ml-compute-service returned invalid readiness data",),
                remediation_hint="Inspect ml-compute model cache/download and warm-up logs",
            )
        raw_state = payload.get("state", payload.get("status")) if isinstance(payload, dict) else None
        if not isinstance(raw_state, str) or not raw_state.strip():
            return self._make_result(
                CheckStatus.FAILED,
                "ML readiness state is missing or invalid",
                details=("ml-compute-service readiness state is missing",),
                remediation_hint="Inspect ml-compute model cache/download and warm-up logs",
            )
        state = raw_state.strip().lower()
        if state not in {"ready", "ok", "healthy"}:
            return self._make_result(
                CheckStatus.FAILED,
                "ML readiness state is not ready",
                details=("ml-compute-service reported a non-ready state",),
                remediation_hint="Inspect ml-compute model warm-up failures",
            )
        return self._make_result(CheckStatus.PASSED, f"ML inference readiness state={state}")
