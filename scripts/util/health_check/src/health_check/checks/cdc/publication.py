"""Health check: PostgreSQL outbox publication exists with expected tables."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

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
    description="Verify the Nohiki PostgreSQL publication exists with outbox tables.",
)

_PUB_QUERY: Final[str] = "SELECT pubname FROM pg_publication WHERE pubname LIKE 'nohiki%'"
_PUB_TABLES_QUERY: Final[str] = (
    "SELECT schemaname || '.' || tablename FROM pg_publication_tables WHERE pubname = '{name}'"
)


async def _publication_table_failures(
    platform: Platform,
    pub_name: str,
) -> list[str]:
    """Return failures if the publication has no outbox tables."""
    code, stdout, _ = await asyncio.to_thread(
        platform.exec_psql,
        _PUB_TABLES_QUERY.format(name=pub_name),
    )
    if code != 0:
        return [f"{pub_name}: cannot query publication tables"]

    tables = [t.strip() for t in stdout.strip().split("\n") if t.strip()]
    if not tables:
        return [f"{pub_name}: publication exists but has no tables"]

    outbox_tables = [t for t in tables if "outbox" in t.lower()]
    if not outbox_tables:
        return [f"{pub_name}: no outbox tables in publication (found: {tables})"]

    return []


class PublicationCheck(HealthCheck):
    """Verify the Nohiki PostgreSQL logical replication publication is configured."""

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

        pub_names = [n.strip() for n in stdout.strip().split("\n") if n.strip()]
        if not pub_names:
            return self._make_result(
                CheckStatus.FAILED,
                "No Nohiki publication found",
                remediation_hint="Run: just kafka-connect-register - Debezium creates the publication on startup",
            )

        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_publication_table_failures(platform, name)) for name in pub_names]

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
            f"{len(pub_names)} publication(s) configured with outbox tables",
        )
