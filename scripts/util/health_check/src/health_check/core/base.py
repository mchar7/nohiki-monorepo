"""Abstract base class for all health checks."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from health_check.core.models import (
    CheckCategory,
    CheckEvidence,
    CheckMetadata,
    CheckResult,
    CheckStatus,
    FixResult,
    FixStatus,
)
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform


class HealthCheck(ABC):
    """Abstract base class for all health checks.

    Subclasses MUST implement:
    - ``metadata`` property: static check identity and constraints.
    - ``execute()`` method: the actual check logic.

    Subclasses MAY override for fix support (scaffolding only -- no CLI exposure yet):
    - ``supports_fix``: return True when a fix is implemented.
    - ``fix_timeout``: custom timeout for the fix operation.
    - ``fix_platforms``: restrict fix to specific platforms.
    - ``fix()``: the remediation logic.

    Use ``_make_result()`` as a convenience factory to build ``CheckResult``
    without repeating ``check_id``, ``name``, and ``category`` in every return.
    """

    @property
    @abstractmethod
    def metadata(self) -> CheckMetadata:
        """Static metadata describing this check's identity and constraints."""
        ...

    @abstractmethod
    async def execute(self, platform: Platform) -> CheckResult:
        """Execute the health check and return the result.

        Args:
            platform: Unified platform interface for container/k8s operations.

        Returns:
            ``CheckResult`` capturing pass/fail, summary, details, and timing.
        """
        ...

    # ── Fix scaffolding ────────────────────────────────────────────────────────
    # No concrete fix implementations exist yet. The framework is designed so
    # that future implementations only need to override these three properties
    # and the fix() method -- no changes to the runner or CLI required.

    @property
    def supports_fix(self) -> bool:
        """Return True if this check has an automated remediation implementation."""
        return False

    @property
    def fix_timeout(self) -> float:
        """Timeout in seconds for the fix operation."""
        return 60.0

    @property
    def fix_platforms(self) -> frozenset[PlatformTarget]:
        """Platforms on which the fix is available (defaults to check's platforms)."""
        return self.metadata.platforms

    async def fix(self, _platform: Platform, _check_result: CheckResult) -> FixResult:
        """Attempt automated remediation for a failed check result.

        Override this method and set ``supports_fix = True`` to provide a fix.

        Args:
            platform: Unified platform interface for remediation operations.
            check_result: The failed result providing context for the fix.

        Returns:
            ``FixResult`` describing what was attempted and whether it succeeded.
        """
        return FixResult(
            check_id=self.metadata.check_id,
            status=FixStatus.NOT_SUPPORTED,
            summary="No automated fix available for this check",
        )

    def _make_result(
        self,
        status: CheckStatus,
        summary: str,
        *,
        details: tuple[str, ...] = (),
        error: str | None = None,
        remediation_hint: str | None = None,
        duration_ms: float = 0.0,
        platform: PlatformTarget | None = None,
        category: CheckCategory | None = None,
        evidence: CheckEvidence | None = None,
    ) -> CheckResult:
        """Build a ``CheckResult`` pre-filled with this check's identity metadata.

        Saves every check implementation from repeating ``check_id``, ``name``,
        and ``category`` in each ``return CheckResult(...)`` call.

        Args:
            status: Outcome of the check.
            summary: Brief one-line description, e.g. ``"3/3 connectors running"``.
            details: Verbose per-issue lines for ``--verbose`` output.
            error: Raw exception text if the check itself raised an error.
            remediation_hint: Actionable next step shown in the issues panel.
            duration_ms: Wall-clock execution time in milliseconds.
            platform: Which platform was checked (filled by runner if omitted).
            category: Override category (uses metadata.category if omitted).
            evidence: Optional schema-versioned machine-readable evidence.

        Returns:
            Fully populated ``CheckResult``.
        """
        return CheckResult(
            check_id=self.metadata.check_id,
            name=self.metadata.name,
            category=category if category is not None else self.metadata.category,
            status=status,
            summary=summary,
            details=details,
            error=error,
            remediation_hint=remediation_hint,
            duration_ms=duration_ms,
            platform=platform,
            evidence=evidence,
        )

    def _start_timer(self) -> float:
        """Return a monotonic start timestamp for duration measurement."""
        return time.monotonic()

    def _elapsed_ms(self, start: float) -> float:
        """Return milliseconds elapsed since ``start``."""
        return (time.monotonic() - start) * 1000.0
