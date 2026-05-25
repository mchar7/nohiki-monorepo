"""Health check: all critical database schemas exist."""

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
    check_id="database_schemas",
    name="Database Schemas",
    category=CheckCategory.DATABASE,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"postgres_connectivity"}),
    timeout_seconds=20.0,
    description="Verify all critical PostgreSQL schemas exist.",
)

_SCHEMA_QUERY: Final[str] = "SELECT nspname FROM pg_namespace WHERE nspname LIKE '%_schema'"


def _parse_existing_schemas(stdout: str) -> frozenset[str]:
    """Extract schema names from psql output."""
    return frozenset(s.strip() for s in stdout.strip().split("\n") if s.strip())


def _missing_schema_failures(existing: frozenset[str]) -> list[str]:
    """Return failure messages for schemas that do not exist."""
    return [
        f"{schema}: not created (owned by {exp.service})"
        for schema, exp in CRITICAL_SCHEMAS.items()
        if schema not in existing
    ]


class DatabaseSchemasCheck(HealthCheck):
    """Verify all critical service schemas are present in PostgreSQL."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the database schemas check."""
        code, stdout, stderr = await asyncio.to_thread(platform.exec_psql, _SCHEMA_QUERY)
        if code != 0:
            return self._make_result(
                CheckStatus.ERROR,
                "Cannot query database schemas",
                details=(stderr[:200],),
                remediation_hint="Ensure PostgreSQL is running and accessible",
            )

        existing = _parse_existing_schemas(stdout)
        failures = _missing_schema_failures(existing)

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} schema(s) missing",
                details=tuple(failures),
                remediation_hint="Run migrations: just migrate <service>",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(CRITICAL_SCHEMAS)} critical schemas exist",
        )
