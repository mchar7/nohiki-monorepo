"""Schedule tick publication continuity invariant."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final = CheckMetadata(
    check_id="schedule_tick_continuity",
    name="Schedule Tick Continuity",
    category=CheckCategory.MESSAGING,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"postgres_connectivity", "kafka_consumers"}),
    description="Verify due active schedules continue publishing deterministic tick events.",
)
_QUERY: Final = """
SELECT
 (SELECT count(*) FROM job_schedule_schema.ingestion_schedules WHERE is_active),
 (SELECT count(*) FROM job_schedule_schema.ingestion_schedules WHERE is_active AND next_run_at <= now()),
 COALESCE(
  EXTRACT(
   EPOCH FROM (
    now()
    - (
     SELECT max(last_run_at)
     FROM job_schedule_schema.ingestion_schedules
     WHERE is_active AND next_run_at <= now()
    )
   )
  )::bigint,
  -1
 )
"""
_MAX_STALE_SECONDS: Final = 900


class ScheduleTickContinuityCheck(HealthCheck):
    """Detect a stalled schedule publisher without failing a fresh empty system."""

    metadata = _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Validate continuity for active overdue schedules."""
        code, stdout, stderr = await asyncio.to_thread(platform.exec_psql, _QUERY, field_separator="|")
        if code != 0:
            return self._make_result(
                CheckStatus.ERROR, "Cannot query schedule tick aggregates", details=(stderr[:200],)
            )
        try:
            active, due, age = map(int, stdout.strip().split("|"))
        except ValueError:
            return self._make_result(CheckStatus.ERROR, "Invalid schedule tick aggregate response")
        evidence = (f"active_schedules={active}", f"due_schedules={due}", f"latest_dispatch_age_seconds={age}")
        if active == 0:
            return self._make_result(
                CheckStatus.SKIPPED, "No active schedules; tick publication not required", details=evidence
            )
        if due > 0 and (age < 0 or age > _MAX_STALE_SECONDS):
            return self._make_result(
                CheckStatus.FAILED,
                "Schedule tick publication is stalled",
                details=evidence,
                remediation_hint="Inspect schedule service tick loop, Kafka publication, and consumer membership",
            )
        return self._make_result(CheckStatus.PASSED, "Schedule tick publication is continuous", details=evidence)
