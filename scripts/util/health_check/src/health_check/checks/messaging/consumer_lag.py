"""Health check: critical Kafka consumer groups are not lagging excessively."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.services import CRITICAL_CONSUMER_GROUPS_LAG
from health_check.config.thresholds import CONSUMER_LAG_THRESHOLD
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="consumer_lag",
    name="Consumer Lag",
    category=CheckCategory.MESSAGING,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"kafka_consumers"}),
    timeout_seconds=45.0,
    description=f"Verify consumer lag is below {CONSUMER_LAG_THRESHOLD} for critical groups.",
)

_LAG_COLUMN_INDEX: Final[int] = 5


def _parse_total_lag(stdout: str) -> int:
    """Sum the LAG column from kafka-consumer-groups --describe output."""
    total = 0
    for line in stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) > _LAG_COLUMN_INDEX:
            lag_str = parts[_LAG_COLUMN_INDEX]
            if lag_str.isdigit():
                total += int(lag_str)
    return total


async def _group_lag_failure(platform: Platform, group: str) -> str | None:
    """Return a failure message if the group lag exceeds the threshold.

    Args:
        platform: Active platform for Kafka CLI execution.
        group: Consumer group ID to inspect.

    Returns:
        Failure message, or ``None`` if lag is acceptable.
    """
    code, stdout, _ = await asyncio.to_thread(
        platform.exec_kafka_cmd,
        [
            "kafka-consumer-groups",
            "--bootstrap-server",
            platform.kafka_bootstrap_server,
            "--describe",
            "--group",
            group,
        ],
        timeout=15,
    )
    if code != 0:
        return f"{group}: cannot query"
    lag = _parse_total_lag(stdout)
    if lag > CONSUMER_LAG_THRESHOLD:
        return f"{group}: LAG={lag} (threshold={CONSUMER_LAG_THRESHOLD})"
    return None


class ConsumerLagCheck(HealthCheck):
    """Verify critical consumer groups are not accumulating excessive lag."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run all consumer lag checks in parallel."""
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_group_lag_failure(platform, group)) for group in CRITICAL_CONSUMER_GROUPS_LAG]

        failures = [msg for t in tasks if (msg := t.result()) is not None]

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} group(s) have high consumer lag",
                details=tuple(failures),
                remediation_hint="Check consumer service health; restart if stuck",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(CRITICAL_CONSUMER_GROUPS_LAG)} groups have acceptable lag",
        )
