"""Health check: PostgreSQL replication slot exists and is active."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="replication_slot",
    name="Replication Slot",
    category=CheckCategory.CDC,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"postgres_connectivity"}),
    timeout_seconds=15.0,
    description="Verify at least one active nohiki replication slot exists.",
)

_SLOT_QUERY: Final[str] = "SELECT slot_name, active FROM pg_replication_slots WHERE slot_name LIKE 'nohiki%'"


def _parse_slot_rows(stdout: str) -> list[tuple[str, bool]]:
    """Parse psql output into (slot_name, is_active) pairs."""
    rows: list[tuple[str, bool]] = []
    for line in stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2:
            rows.append((parts[0], parts[1] == "t"))
    return rows


class ReplicationSlotCheck(HealthCheck):
    """Verify a Nohiki replication slot exists and is active in PostgreSQL."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the replication slot check."""
        code, stdout, stderr = await asyncio.to_thread(
            platform.exec_psql,
            _SLOT_QUERY,
            field_separator="|",
        )
        if code != 0:
            return self._make_result(
                CheckStatus.ERROR,
                "Cannot query replication slots",
                details=(stderr[:200],),
            )

        rows = _parse_slot_rows(stdout)
        if not rows:
            return self._make_result(
                CheckStatus.FAILED,
                "No Nohiki replication slots found",
                remediation_hint="Run: just kafka-connect-register - Debezium creates slots on startup",
            )

        inactive = [name for name, active in rows if not active]
        if inactive:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(inactive)} replication slot(s) inactive",
                details=tuple(f"{n}: inactive" for n in inactive),
                remediation_hint="Restart Debezium: just restart kafka-connect",
            )

        return self._make_result(
            CheckStatus.PASSED,
            f"{len(rows)} active replication slot(s) found",
        )
