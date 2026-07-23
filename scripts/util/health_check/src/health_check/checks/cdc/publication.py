"""Health check: PostgreSQL outbox publication exists with expected tables."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.kafka import CdcConnector, cdc_connectors_for
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="publication",
    name="Outbox Publication",
    category=CheckCategory.CDC,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"postgres_connectivity"}),
    timeout_seconds=15.0,
    description="Verify every current CDC publication exists with its configured table.",
)

_PUB_QUERY: Final[str] = "SELECT pubname FROM pg_publication ORDER BY pubname"
_PUB_TABLES_QUERY: Final[str] = (
    "SELECT schemaname || '.' || tablename FROM pg_publication_tables WHERE pubname = '{name}'"
)


async def _publication_table_failures(
    platform: Platform,
    connector: CdcConnector,
) -> list[str]:
    """Return failures when a publication lacks its configured source table."""
    code, stdout, _ = await asyncio.to_thread(
        platform.exec_psql,
        _PUB_TABLES_QUERY.format(name=connector.publication_name),
    )
    if code != 0:
        return [f"{connector.publication_name}: cannot query publication tables"]

    tables = [t.strip() for t in stdout.strip().split("\n") if t.strip()]
    if not tables:
        return [f"{connector.publication_name}: publication exists but has no tables"]

    if connector.table_name not in tables:
        return [f"{connector.publication_name}: missing configured table {connector.table_name} (found: {tables})"]

    return []


class PublicationCheck(HealthCheck):
    """Verify the exact current PostgreSQL publication inventory and tables."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the publication check."""
        code, stdout, stderr = await asyncio.to_thread(platform.exec_psql, _PUB_QUERY)
        if code != 0:
            return self._make_result(
                CheckStatus.ERROR,
                "Cannot query pg_publication",
                details=(stderr[:200],),
            )

        connectors = cdc_connectors_for(platform.target)
        pub_names = frozenset(n.strip() for n in stdout.splitlines() if n.strip())
        expected = frozenset(connector.publication_name for connector in connectors)
        missing = sorted(expected - pub_names)
        unexpected = sorted(pub_names - expected)
        if missing or unexpected:
            details = (
                *(f"{name}: required publication missing" for name in missing),
                *(f"{name}: unexpected publication" for name in unexpected),
            )
            return self._make_result(
                CheckStatus.FAILED,
                f"publication inventory mismatch: {len(missing)} missing, {len(unexpected)} unexpected",
                details=details,
                remediation_hint="Reconcile current Debezium connectors and remove verified legacy publications",
            )

        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_publication_table_failures(platform, connector)) for connector in connectors]

        failures = [msg for t in tasks for msg in t.result()]

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} publication issue(s)",
                details=tuple(failures),
                remediation_hint="Verify Debezium connector configuration includes correct table filters",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(expected)} current publications contain their configured tables",
        )
