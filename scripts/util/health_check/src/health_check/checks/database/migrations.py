"""Health check: all service schemas have current Alembic migrations."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.database import CRITICAL_SCHEMAS
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="alembic_migrations",
    name="Alembic Migrations",
    category=CheckCategory.DATABASE,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"database_schemas"}),
    timeout_seconds=30.0,
    description="Verify all service schemas have the expected Alembic migration revision.",
)


def _version_query(schema: str) -> str:
    """Build alembic_version query for a schema."""
    return f"SELECT version_num FROM {schema}.alembic_version LIMIT 1"


async def _check_migration(
    platform: Platform,
    schema: str,
    service: str,
    expected_rev: str,
) -> str | None:
    """Check one schema's migration revision.

    Args:
        platform: Active platform for psql execution.
        schema: PostgreSQL schema name.
        service: Service that owns the schema (for error messages).
        expected_rev: Expected Alembic revision string.

    Returns:
        Failure message, or ``None`` when revision matches.
    """
    code, stdout, _ = await asyncio.to_thread(platform.exec_psql, _version_query(schema))
    if code != 0:
        return f"{service}: no alembic_version table in {schema}"

    actual = stdout.strip()
    if not actual:
        return f"{service}: alembic_version is empty in {schema}"
    if actual != expected_rev:
        return f"{service}: migration mismatch (expected {expected_rev!r}, got {actual!r})"
    return None


class AlembicMigrationsCheck(HealthCheck):
    """Verify every service schema has its expected Alembic revision applied."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run all migration checks in parallel."""
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(_check_migration(platform, schema, exp.service, exp.migration))
                for schema, exp in CRITICAL_SCHEMAS.items()
            ]

        failures = [msg for t in tasks if (msg := t.result()) is not None]

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} migration(s) not current",
                details=tuple(failures),
                remediation_hint="Run migrations: just migrate <service>",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(CRITICAL_SCHEMAS)} schemas have current migrations",
        )
