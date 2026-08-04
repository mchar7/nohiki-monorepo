"""PostgreSQL logical replication capacity and slot-inventory invariant."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.kafka import cdc_connectors_for
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final = CheckMetadata(
    check_id="replication_capacity",
    name="Replication Capacity",
    category=CheckCategory.CDC,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"replication_slot"}),
    description="Verify replication slot and WAL sender headroom against the configured inventory.",
)


def _capacity_query(target: PlatformTarget) -> str:
    """Build the exact target-specific canonical-slot capacity query."""
    canonical = ", ".join(f"'{connector.slot_name}'" for connector in cdc_connectors_for(target))
    return f"""
SELECT
 (SELECT count(*) FROM pg_replication_slots),
 current_setting('max_replication_slots')::int,
 (SELECT count(*) FROM pg_stat_replication),
 current_setting('max_wal_senders')::int,
 (SELECT count(*) FROM pg_replication_slots WHERE slot_name NOT IN ({canonical}))
"""


class ReplicationCapacityCheck(HealthCheck):
    """Detect exhausted PostgreSQL CDC capacity and surplus slots."""

    metadata = _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the replication capacity check."""
        code, stdout, stderr = await asyncio.to_thread(
            platform.exec_psql, _capacity_query(platform.target), field_separator="|"
        )
        if code != 0:
            return self._make_result(CheckStatus.ERROR, "Cannot query replication capacity", details=(stderr[:200],))
        try:
            used_slots, max_slots, used_senders, max_senders, unexpected_slots = map(int, stdout.strip().split("|"))
        except ValueError:
            return self._make_result(CheckStatus.ERROR, "Invalid replication capacity response")

        slot_headroom = max_slots - used_slots
        sender_headroom = max_senders - used_senders
        expected = len(cdc_connectors_for(platform.target))
        evidence = (
            f"slots={used_slots}/{max_slots} headroom={slot_headroom}",
            f"wal_senders={used_senders}/{max_senders} headroom={sender_headroom}",
            f"canonical_slots={used_slots - unexpected_slots}/{expected} unexpected={unexpected_slots}",
        )
        failures = []
        if slot_headroom <= 0:
            failures.append("max_replication_slots exhausted")
        if sender_headroom <= 0:
            failures.append("max_wal_senders exhausted")
        if unexpected_slots:
            failures.append(f"{unexpected_slots} unexpected replication slot(s)")
        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                "; ".join(failures),
                details=evidence,
                remediation_hint="Drop verified unexpected slots or increase PostgreSQL replication capacity",
            )
        return self._make_result(CheckStatus.PASSED, "Replication capacity has headroom", details=evidence)
