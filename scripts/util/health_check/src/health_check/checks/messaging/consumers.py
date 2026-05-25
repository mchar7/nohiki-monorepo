"""Health check: critical Kafka consumer groups have active members."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.checks._utils import consumer_group_has_members
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="kafka_consumers",
    name="Kafka Consumers",
    category=CheckCategory.MESSAGING,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"kafka_topics", "core_services"}),
    timeout_seconds=45.0,
    description="Verify critical Kafka consumer groups have active members.",
)

_CRITICAL_GROUPS: Final[tuple[str, ...]] = (
    "doc-template-service-consumer-commands",
    "bff-service-consumer-projections",
    "job-storage-service-consumer",
    "job-correlation-evaluation-service-consumer",
    "job-correlation-evaluation-service-consumer-projection",
)


class KafkaConsumersCheck(HealthCheck):
    """Verify critical Kafka consumer groups are active with members."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run all consumer group checks in parallel."""
        async with asyncio.TaskGroup() as tg:
            tasks = {group: tg.create_task(consumer_group_has_members(platform, group)) for group in _CRITICAL_GROUPS}

        failures = [f"{group}: NO ACTIVE MEMBERS (consumer dead)" for group, task in tasks.items() if not task.result()]

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} consumer group(s) have no active members",
                details=tuple(failures),
                remediation_hint="Restart affected services: just restart <service>",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(_CRITICAL_GROUPS)} critical consumer groups active",
        )
