"""Health check: long-running services have not silently lost Kafka connectivity."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.checks._utils import any_group_has_members
from health_check.config.kafka import KAFKA_TRANSIENT_ERROR_PATTERNS
from health_check.config.services import KAFKA_CONSUMER_GROUPS, KAFKA_CONSUMER_SERVICES
from health_check.config.thresholds import STALE_SERVICE_THRESHOLD_HOURS
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="stale_services",
    name="Stale Services",
    category=CheckCategory.SERVICES,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"core_services"}),
    timeout_seconds=60.0,
    description=(
        f"Detect services running >{STALE_SERVICE_THRESHOLD_HOURS:.0f}h that "
        "show Kafka heartbeat failures with no active consumer group."
    ),
)

_STALE_LOG_LINES: Final[int] = 300


def _kafka_issues_in_logs(logs_lower: str) -> list[str]:
    """Return Kafka transient-error patterns found in log content."""
    return [p for p in KAFKA_TRANSIENT_ERROR_PATTERNS if p in logs_lower]


async def _is_stale(
    svc: str,
    uptime_hours: float,
    platform: Platform,
) -> str | None:
    """Return a failure message if the service is stale, or None if healthy.

    A service is considered stale when it has been running beyond the threshold,
    shows Kafka coordinator issues in recent logs, AND none of its consumer groups
    have active members -- indicating it lost its Kafka connection and needs restart.

    Args:
        svc: Canonical service name.
        uptime_hours: Current service uptime in hours.
        platform: Active platform for log and Kafka queries.

    Returns:
        Failure message string, or ``None`` if the service is healthy.
    """
    if uptime_hours < STALE_SERVICE_THRESHOLD_HOURS:
        return None

    logs = await asyncio.to_thread(platform.get_logs, svc, _STALE_LOG_LINES)
    kafka_issues = _kafka_issues_in_logs(logs.lower())
    if not kafka_issues:
        return None

    group_ids = KAFKA_CONSUMER_GROUPS.get(svc) or ()
    if await any_group_has_members(platform, tuple(group_ids)):
        return None

    issues_str = ", ".join(kafka_issues)
    return f"{svc}: STALE ({uptime_hours:.0f}h uptime) with Kafka issues: {issues_str}"


class StaleServicesCheck(HealthCheck):
    """Detect Kafka consumer services that have silently lost broker connectivity."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the stale services check."""
        statuses = await asyncio.to_thread(platform.get_service_statuses)

        candidates = {
            svc: info.uptime_seconds / 3600.0
            for svc in KAFKA_CONSUMER_SERVICES
            if (info := statuses.get(svc)) is not None
        }

        async with asyncio.TaskGroup() as tg:
            tasks = {svc: tg.create_task(_is_stale(svc, uptime_h, platform)) for svc, uptime_h in candidates.items()}

        failures = [msg for t in tasks.values() if (msg := t.result()) is not None]

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} service(s) need restart (stale Kafka connections)",
                details=tuple(failures),
                remediation_hint="Restart affected services: just restart <service>",
            )
        return self._make_result(CheckStatus.PASSED, "No stale services detected")
