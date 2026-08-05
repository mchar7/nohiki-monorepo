"""Health check: PostgreSQL replication slot exists and is active."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.kafka import cdc_connectors_for
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
    description="Verify every current CDC replication slot exists and is active.",
)

_SLOT_QUERY: Final[str] = "SELECT slot_name, active FROM pg_replication_slots ORDER BY slot_name"


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
    """Verify the exact current Nohiki replication slot inventory is active."""

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

        rows = dict(_parse_slot_rows(stdout))
        expected = frozenset(connector.slot_name for connector in cdc_connectors_for(platform.target))
        observed = frozenset(rows)
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        inactive = sorted(name for name in expected & observed if not rows[name])
        if missing or unexpected or inactive:
            details = (
                *(f"{name}: required slot missing" for name in missing),
                *(f"{name}: unexpected slot" for name in unexpected),
                *(f"{name}: inactive" for name in inactive),
            )
            return self._make_result(
                CheckStatus.FAILED,
                (
                    "replication slot inventory mismatch: "
                    f"{len(missing)} missing, {len(unexpected)} unexpected, {len(inactive)} inactive"
                ),
                details=details,
                remediation_hint=(
                    "For recognized superseded Compose CDC resources, run: just connect-reconcile-compose-cdc"
                    if platform.target == PlatformTarget.COMPOSE and unexpected
                    else "Reconcile the configured Debezium connector replication slot inventory"
                ),
            )

        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(expected)} current replication slots active",
        )
