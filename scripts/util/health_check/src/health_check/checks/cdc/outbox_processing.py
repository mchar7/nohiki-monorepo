"""Health check: outbox CDC pipeline is fully operational."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.checks._utils import ConnectorStatus, fetch_connector_status
from health_check.config.kafka import OUTBOX_CONNECTOR_NAMES
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
    check_id="outbox_processing",
    name="Outbox Processing",
    category=CheckCategory.CDC,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"debezium_connectors", "database_schemas"}),
    timeout_seconds=30.0,
    description="Verify all outbox connectors are running and replication slots are active.",
)

_CONNECT_BASE: Final[str] = f"http://localhost:{KAFKA_CONNECT_DEFAULT_PORT}"
_INACTIVE_SLOT_QUERY: Final[str] = (
    "SELECT slot_name FROM pg_replication_slots WHERE slot_name LIKE 'nohiki_outbox_%' AND active = false"
)


def _connect_base(platform: Platform) -> str:
    return "http://nohiki-connect-api:8083" if platform.target is PlatformTarget.KUBERNETES else _CONNECT_BASE


def _inactive_slot_names(stdout: str) -> list[str]:
    """Parse psql output into a list of inactive slot names."""
    return [s.strip() for s in stdout.strip().split("\n") if s.strip()]


async def _slot_failures(platform: Platform) -> list[str]:
    """Return failure messages for inactive Debezium replication slots."""
    code, stdout, _ = await asyncio.to_thread(platform.exec_psql, _INACTIVE_SLOT_QUERY)
    if code != 0:
        return ["Failed to query replication slots"]
    return [f"Replication slot {name} inactive (CDC broken)" for name in _inactive_slot_names(stdout)]


def _connector_failures(statuses: list[ConnectorStatus]) -> list[str]:
    """Extract failure messages from connector statuses."""
    return [issue for s in statuses if (issue := s.issue) is not None]


class OutboxProcessingCheck(HealthCheck):
    """Verify every outbox connector is running and all replication slots are active."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run connector and replication slot checks in parallel."""
        connect_base = _connect_base(platform)
        async with asyncio.TaskGroup() as tg:
            connector_tasks = [
                tg.create_task(fetch_connector_status(platform, connect_base, name)) for name in OUTBOX_CONNECTOR_NAMES
            ]
            slot_task = tg.create_task(_slot_failures(platform))

        failures = _connector_failures([t.result() for t in connector_tasks]) + slot_task.result()

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} outbox pipeline issue(s)",
                details=tuple(failures),
                remediation_hint="Run: just kafka-connect-register to re-register connectors",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(OUTBOX_CONNECTOR_NAMES)} outbox connectors running with active slots",
        )
