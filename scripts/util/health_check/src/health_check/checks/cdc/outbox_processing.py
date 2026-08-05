"""Health check: outbox CDC pipeline is fully operational."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.checks._utils import ConnectorStatus, fetch_connector_status
from health_check.config.kafka import cdc_connectors_for
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

_SLOT_QUERY: Final[str] = "SELECT slot_name, active FROM pg_replication_slots ORDER BY slot_name"


def _connect_base(platform: Platform) -> str:
    return platform.service_url("kafka-connect", KAFKA_CONNECT_DEFAULT_PORT)


def _slot_states(stdout: str) -> dict[str, bool]:
    """Parse psql output into replication slot states."""
    states: dict[str, bool] = {}
    for line in stdout.splitlines():
        name, separator, active = line.partition("|")
        if separator:
            states[name.strip()] = active.strip() == "t"
    return states


async def _slot_failures(platform: Platform) -> list[str]:
    """Return current CDC replication slot inventory failures."""
    code, stdout, _ = await asyncio.to_thread(platform.exec_psql, _SLOT_QUERY, field_separator="|")
    if code != 0:
        return ["Failed to query replication slots"]

    states = _slot_states(stdout)
    expected = frozenset(connector.slot_name for connector in cdc_connectors_for(platform.target))
    observed = frozenset(states)
    return [
        *(f"Replication slot {name} missing" for name in sorted(expected - observed)),
        *(f"Replication slot {name} unexpected" for name in sorted(observed - expected)),
        *(f"Replication slot {name} inactive (CDC broken)" for name in sorted(expected & observed) if not states[name]),
    ]


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
        connectors = cdc_connectors_for(platform.target)
        async with asyncio.TaskGroup() as tg:
            connector_tasks = [
                tg.create_task(fetch_connector_status(platform, connect_base, connector.name))
                for connector in connectors
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
            f"All {len(connectors)} CDC connectors running with active slots",
        )
