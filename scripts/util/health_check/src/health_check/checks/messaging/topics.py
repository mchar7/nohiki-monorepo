"""Health check: all expected Kafka topics exist in the cluster."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.kafka import get_all_topic_names
from health_check.config.thresholds import KAFKA_TOPICS_CMD_TIMEOUT_SECONDS
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="kafka_topics",
    name="Kafka Topics",
    category=CheckCategory.MESSAGING,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"kafka_broker"}),
    timeout_seconds=30.0,
    description="Verify all canonical Kafka topics exist in the cluster.",
)


def _parse_topic_list(stdout: str) -> frozenset[str]:
    """Parse kafka-topics --list output into a set of topic names."""
    return frozenset(line.strip() for line in stdout.splitlines() if line.strip())


class KafkaTopicsCheck(HealthCheck):
    """Verify all topics declared in nohiki_kafka_client.Topics are present."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the Kafka topics existence check."""
        code, stdout, stderr = await asyncio.to_thread(
            platform.exec_kafka_cmd,
            [
                "kafka-topics",
                "--bootstrap-server",
                platform.kafka_bootstrap_server,
                "--list",
            ],
            timeout=KAFKA_TOPICS_CMD_TIMEOUT_SECONDS,
        )
        if code != 0:
            return self._make_result(
                CheckStatus.ERROR,
                "Cannot list Kafka topics",
                details=(stderr[:200],),
                remediation_hint="Ensure Kafka broker is reachable",
            )

        expected = get_all_topic_names()
        existing = _parse_topic_list(stdout)
        missing = expected - existing

        if missing:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(missing)} topic(s) missing",
                details=tuple(sorted(missing)),
                remediation_hint="Topics are auto-created on first producer publish; ensure services started",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(expected)} expected topics exist",
        )
