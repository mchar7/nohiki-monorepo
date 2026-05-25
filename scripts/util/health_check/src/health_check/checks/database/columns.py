"""Health check: critical tables have all required columns."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.database import CRITICAL_COLUMNS
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="schema_columns",
    name="Schema Columns",
    category=CheckCategory.DATABASE,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"database_schemas"}),
    timeout_seconds=30.0,
    description="Verify critical tables have all required columns.",
)


def _column_query(schema: str, table: str) -> str:
    """Build the information_schema query for a table's columns.

    Args:
        schema: PostgreSQL schema name.
        table: Table name within the schema.

    Returns:
        SQL query string returning column names.
    """
    return (
        f"SELECT column_name FROM information_schema.columns WHERE table_schema = '{schema}' AND table_name = '{table}'"
    )


async def _check_table(
    platform: Platform,
    table_path: str,
    required: frozenset[str],
) -> str | None:
    """Check a single table for missing columns.

    Args:
        platform: Active platform for psql execution.
        table_path: ``"schema.table"`` string.
        required: Set of required column names.

    Returns:
        Failure message string, or ``None`` if all columns present.
    """
    schema, table = table_path.split(".", 1)
    code, stdout, _ = await asyncio.to_thread(platform.exec_psql, _column_query(schema, table))
    if code != 0:
        return f"{table_path}: cannot query columns"

    existing = frozenset(c.strip() for c in stdout.strip().split("\n") if c.strip())
    missing = required - existing
    if missing:
        return f"{table_path}: missing columns {sorted(missing)}"
    return None


class SchemaColumnsCheck(HealthCheck):
    """Verify critical tables contain all expected columns."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run all column checks in parallel."""
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(_check_table(platform, table_path, required))
                for table_path, required in CRITICAL_COLUMNS.items()
            ]

        failures = [msg for t in tasks if (msg := t.result()) is not None]

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} table(s) missing required columns",
                details=tuple(failures),
                remediation_hint="Run migrations for the affected service schemas",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(CRITICAL_COLUMNS)} critical tables have required columns",
        )
