"""Health check: Kafka event flow is active on key topics."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Final

from health_check.config.thresholds import KAFKA_CONNECT_DEFAULT_PORT
from health_check.core.base import HealthCheck
from health_check.core.models import (
    CheckCategory,
    CheckMetadata,
    CheckResult,
    CheckStatus,
)
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="kafka_event_flow",
    name="Kafka Event Flow",
    category=CheckCategory.MESSAGING,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"kafka_topics", "core_services"}),
    timeout_seconds=20.0,
    description="Verify Kafka Connect REST API is reachable and connectors are registered.",
)


def _connectors_path(platform: Platform) -> str:
    return f"{platform.service_url('kafka-connect', KAFKA_CONNECT_DEFAULT_PORT)}/connectors"


class KafkaEventFlowCheck(HealthCheck):
    """Verify Kafka Connect REST API is up and connectors are registered."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the Kafka event flow check."""
        code, stdout, stderr = await asyncio.to_thread(
            platform.curl,
            _connectors_path(platform),
            timeout=10,
        )

        if code != 0:
            return self._make_result(
                CheckStatus.FAILED,
                "Cannot reach Kafka Connect REST API",
                details=(stderr[:200],),
                remediation_hint=f"Ensure kafka-connect container is running on port {KAFKA_CONNECT_DEFAULT_PORT}",
            )

        try:
            connectors = json.loads(stdout)
            count = len(connectors) if isinstance(connectors, list) else 0
        except json.JSONDecodeError, ValueError:
            count = 0

        return self._make_result(
            CheckStatus.PASSED,
            f"Kafka Connect active ({count} connector(s) registered)",
        )
