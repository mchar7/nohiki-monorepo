"""Health check: all Debezium connectors are running."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.checks._utils import ConnectorStatus, fetch_connector_names, fetch_connector_status
from health_check.config.kafka import OUTBOX_CONNECTOR_NAMES
from health_check.config.thresholds import KAFKA_CONNECT_DEFAULT_PORT
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus, FixResult, FixStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="debezium_connectors",
    name="Debezium Connectors",
    category=CheckCategory.CDC,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"kafka_broker", "postgres_connectivity"}),
    timeout_seconds=30.0,
    description="Verify all Kafka Connect connectors are RUNNING with active tasks.",
)


def _collect_failures(statuses: list[ConnectorStatus]) -> list[str]:
    """Extract failure messages from connector statuses."""
    return [issue for s in statuses if (issue := s.issue) is not None]


class DebeziumConnectorsCheck(HealthCheck):
    """Verify all Kafka Connect connectors are registered and in a healthy state."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    @property
    def supports_fix(self) -> bool:
        """Return whether the connector check supports repair."""
        return True

    @property
    def fix_timeout(self) -> float:
        """Return the maximum repair duration in seconds."""
        return 10.0

    async def fix(self, _platform: Platform, _check_result: CheckResult) -> FixResult:
        """Restart at most one canonical connector with an exact FAILED state."""
        platform = _platform
        start = self._start_timer()
        connect_base = platform.service_url("kafka-connect", KAFKA_CONNECT_DEFAULT_PORT)
        names = await fetch_connector_names(platform, connect_base)
        expected = tuple(OUTBOX_CONNECTOR_NAMES)
        if names is None or frozenset(names) != frozenset(expected):
            return FixResult(
                self.metadata.check_id,
                FixStatus.NOT_SUPPORTED,
                "Connector inventory is not safely repairable",
                duration_ms=self._elapsed_ms(start),
            )
        statuses = [await fetch_connector_status(platform, connect_base, name) for name in expected]
        eligible = next(
            (status.name for status in statuses if status.state == "FAILED" or "FAILED" in status.task_states),
            None,
        )
        if eligible is None:
            return FixResult(
                self.metadata.check_id,
                FixStatus.NO_ACTION,
                "Connector recovered before remediation",
                duration_ms=self._elapsed_ms(start),
            )
        code, stdout, stderr = await asyncio.to_thread(
            platform.restart_kafka_connector,
            eligible,
            timeout=int(self.fix_timeout),
        )
        detail = tuple(part for part in (stdout.strip(), stderr.strip()) if part)
        return FixResult(
            self.metadata.check_id,
            FixStatus.SUCCESS if code == 0 else FixStatus.FAILED,
            f"Restarted failed connector {eligible}" if code == 0 else f"Failed to restart connector {eligible}",
            action_id="kafka_connect.restart_failed",
            details=detail,
            duration_ms=self._elapsed_ms(start),
        )

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the Debezium connectors check."""
        connect_base = platform.service_url("kafka-connect", KAFKA_CONNECT_DEFAULT_PORT)
        names = await fetch_connector_names(platform, connect_base)
        if names is None:
            return self._make_result(
                CheckStatus.ERROR,
                "Cannot reach Kafka Connect REST API",
                remediation_hint=f"Ensure kafka-connect is running on port {KAFKA_CONNECT_DEFAULT_PORT}",
            )
        if not names:
            return self._make_result(
                CheckStatus.FAILED,
                "No connectors registered in Kafka Connect",
                remediation_hint="Register connectors: just kafka-connect-register",
            )
        expected = frozenset(OUTBOX_CONNECTOR_NAMES)
        observed = frozenset(names)
        missing = sorted(expected - observed)
        unexpected = sorted(name for name in observed - expected if name.startswith("nohiki"))
        if missing or unexpected:
            details = (
                *(f"{name}: required connector missing" for name in missing),
                *(f"{name}: unexpected legacy connector" for name in unexpected),
            )
            return self._make_result(
                CheckStatus.FAILED,
                f"connector inventory mismatch: {len(missing)} missing, {len(unexpected)} legacy",
                details=details,
                remediation_hint="Reconcile connector inventory: just kafka-connect-register",
            )

        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(fetch_connector_status(platform, connect_base, n)) for n in names]

        failures = _collect_failures([t.result() for t in tasks])
        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)}/{len(names)} connector(s) unhealthy",
                details=tuple(failures),
                remediation_hint="Restart failed connectors via Kafka Connect API",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(names)} connector(s) running",
        )
