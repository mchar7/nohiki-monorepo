"""Health check: Kafka broker port is accessible."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.thresholds import KAFKA_PORT
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
    check_id="kafka_broker",
    name="Kafka Broker",
    category=CheckCategory.INFRASTRUCTURE,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"infra_services"}),
    timeout_seconds=15.0,
    description="Verify the Kafka broker port is accessible.",
)

_FAIL_MSG: Final[str] = f"Kafka broker port {KAFKA_PORT} not accessible"
_OK_MSG: Final[str] = "Kafka broker accepting connections"
_HINT: Final[str] = "Run: just logs kafka -- check for broker startup errors"


class KafkaBrokerCheck(HealthCheck):
    """Verify the Kafka broker TCP port is reachable."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the Kafka broker accessibility check."""
        host = (
            platform.kafka_bootstrap_server.rsplit(":", 1)[0]
            if platform.target is PlatformTarget.KUBERNETES
            else "localhost"
        )
        ok = await asyncio.to_thread(platform.check_port, host, KAFKA_PORT)
        if not ok:
            return self._make_result(CheckStatus.FAILED, _FAIL_MSG, remediation_hint=_HINT)
        return self._make_result(CheckStatus.PASSED, _OK_MSG)
