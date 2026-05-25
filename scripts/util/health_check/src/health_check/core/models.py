"""Core data models for health check results, metadata, and fix outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from health_check.platform.models import PlatformTarget

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class CheckEvidence:
    """Machine-readable evidence emitted by a health check."""

    schema: str
    data: JsonObject


class CheckStatus(StrEnum):
    """Health check outcome status."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class FixStatus(StrEnum):
    """Automated remediation attempt outcome status."""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    NO_ACTION = "no_action"
    NOT_SUPPORTED = "not_supported"


class CheckCategory(StrEnum):
    """Logical category for grouping and filtering health checks."""

    INFRASTRUCTURE = "infrastructure"
    SERVICES = "services"
    DATABASE = "database"
    MESSAGING = "messaging"
    CDC = "cdc"
    VECTORS = "vectors"
    APPLICATION = "application"
    KUBERNETES = "kubernetes"
    OBSERVABILITY = "observability"


@dataclass(frozen=True, slots=True)
class CheckMetadata:
    """Static metadata describing a health check's identity and execution constraints.

    This dataclass is defined once per check class and never changes at runtime.
    The runner uses it for filtering, dependency resolution, and timeout enforcement.

    Attributes:
        check_id: Unique snake_case identifier, e.g. ``"postgres_connectivity"``.
        name: Human-readable display name, e.g. ``"PostgreSQL Connectivity"``.
        category: Logical grouping for filtering and display.
        platforms: Deployment targets this check applies to.
        depends_on: Frozenset of ``check_id`` values that must pass before this
            check runs. If any dependency fails, this check is skipped.
        timeout_seconds: Maximum seconds allowed for ``execute()``.
        description: One-sentence description for ``health-check info`` and help text.
    """

    check_id: str
    name: str
    category: CheckCategory
    platforms: frozenset[PlatformTarget]
    depends_on: frozenset[str] = field(default_factory=frozenset)
    timeout_seconds: float = 30.0
    description: str = ""


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Complete result of a single health check execution.

    Attributes:
        check_id: Correlates to ``CheckMetadata.check_id``.
        name: Display name copied from metadata.
        category: Grouping category copied from metadata.
        status: Outcome of the check.
        summary: Brief one-line status, e.g. ``"3/3 connectors running"``.
        details: Verbose per-issue lines shown in ``--verbose`` or issues panel.
        error: Raw exception message/traceback if the check itself crashed.
        remediation_hint: Actionable next step, e.g. ``"Run: just kafka-connect-register"``.
        duration_ms: Wall-clock execution time in milliseconds.
        platform: Which deployment target was checked.
        evidence: Optional schema-versioned machine-readable check evidence.
    """

    check_id: str
    name: str
    category: CheckCategory
    status: CheckStatus
    summary: str
    details: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None
    remediation_hint: str | None = None
    duration_ms: float = 0.0
    platform: PlatformTarget | None = None
    evidence: CheckEvidence | None = None

    @property
    def passed(self) -> bool:
        """Return True when status is PASSED."""
        return self.status == CheckStatus.PASSED

    @property
    def failed(self) -> bool:
        """Return True when status is FAILED or ERROR."""
        return self.status in {CheckStatus.FAILED, CheckStatus.ERROR}


@dataclass(frozen=True, slots=True)
class FixResult:
    """Complete result of an automated remediation attempt.

    Mirrors ``CheckResult`` structure for consistency. Not exposed in the
    CLI until individual fix implementations are added to check classes.

    Attributes:
        check_id: The check this fix was applied for.
        status: Outcome of the fix attempt.
        summary: Brief one-line result, e.g. ``"Connector restarted successfully"``.
        details: Verbose details of actions taken.
        error: Raw exception message if the fix itself crashed.
        duration_ms: Wall-clock execution time in milliseconds.
    """

    check_id: str
    status: FixStatus
    summary: str
    action_id: str | None = None
    details: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None
    duration_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class RemediationResult:
    """Immutable audit envelope for one remediation attempt."""

    check_id: str
    before: CheckResult
    action: FixResult
    after: CheckResult


@dataclass(frozen=True, slots=True)
class CheckSuiteResult:
    """Aggregate result of a complete health check suite run.

    Attributes:
        results: All check results in execution order.
        total_duration_ms: Wall-clock time for the entire suite.
        platform: Deployment target that was checked.
    """

    results: tuple[CheckResult, ...]
    total_duration_ms: float
    platform: PlatformTarget
    remediations: tuple[RemediationResult, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """Return True when no checks failed or errored."""
        return all(r.passed or r.status == CheckStatus.SKIPPED for r in self.results)

    @property
    def passed_count(self) -> int:
        """Count of checks with PASSED status."""
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        """Count of checks with FAILED or ERROR status."""
        return sum(1 for r in self.results if r.failed)

    @property
    def skipped_count(self) -> int:
        """Count of checks with SKIPPED status."""
        return sum(1 for r in self.results if r.status == CheckStatus.SKIPPED)

    @property
    def error_count(self) -> int:
        """Count of checks with ERROR status (check itself crashed)."""
        return sum(1 for r in self.results if r.status == CheckStatus.ERROR)
