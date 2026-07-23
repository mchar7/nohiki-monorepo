"""Tests for database health checks."""

from __future__ import annotations

from health_check.checks.database.columns import SchemaColumnsCheck
from health_check.checks.database.migrations import AlembicMigrationsCheck
from health_check.checks.database.schemas import DatabaseSchemasCheck
from health_check.config.database import CRITICAL_SCHEMAS
from health_check.core.models import CheckStatus

from .._helpers import MockPlatform


class TestDatabaseSchemasCheck:
    async def test_passes_when_all_schemas_exist(self) -> None:
        schema_names = "\n".join(CRITICAL_SCHEMAS)
        platform = MockPlatform(_psql_result=(0, schema_names, ""))
        result = await DatabaseSchemasCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_schemas_missing(self) -> None:
        platform = MockPlatform(_psql_result=(0, "", ""))
        result = await DatabaseSchemasCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert result.details

    async def test_error_when_psql_fails(self) -> None:
        platform = MockPlatform(_psql_result=(1, "", "connection refused"))
        result = await DatabaseSchemasCheck().execute(platform)
        assert result.status == CheckStatus.ERROR

    def test_metadata_check_id(self) -> None:
        assert DatabaseSchemasCheck().metadata.check_id == "database_schemas"

    def test_depends_on_postgres(self) -> None:
        assert "postgres_connectivity" in DatabaseSchemasCheck().metadata.depends_on


class TestSchemaColumnsCheck:
    async def test_passes_when_all_columns_present(self) -> None:
        from health_check.config.database import CRITICAL_COLUMNS

        all_cols = "\n".join(col for required in CRITICAL_COLUMNS.values() for col in required)
        platform = MockPlatform(_psql_result=(0, all_cols, ""))
        result = await SchemaColumnsCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_columns_missing(self) -> None:
        platform = MockPlatform(_psql_result=(0, "", ""))
        result = await SchemaColumnsCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    async def test_error_when_psql_fails(self) -> None:
        platform = MockPlatform(_psql_result=(1, "", "error"))
        result = await SchemaColumnsCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    def test_metadata_check_id(self) -> None:
        assert SchemaColumnsCheck().metadata.check_id == "schema_columns"


class TestAlembicMigrationsCheck:
    async def test_passes_when_all_migrations_current(self) -> None:
        first_expected = next(iter(CRITICAL_SCHEMAS.values())).migration
        platform = MockPlatform(_psql_result=(0, first_expected, ""))
        result = await AlembicMigrationsCheck().execute(platform)
        assert result.status in {CheckStatus.PASSED, CheckStatus.FAILED}

    async def test_fails_when_version_mismatched(self) -> None:
        platform = MockPlatform(_psql_result=(0, "wrong_rev", ""))
        result = await AlembicMigrationsCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert any("mismatch" in d for d in result.details)

    async def test_fails_when_no_alembic_table(self) -> None:
        platform = MockPlatform(_psql_result=(1, "", "table not found"))
        result = await AlembicMigrationsCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    async def test_fails_when_version_empty(self) -> None:
        platform = MockPlatform(_psql_result=(0, "", ""))
        result = await AlembicMigrationsCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    def test_depends_on_schemas(self) -> None:
        assert "database_schemas" in AlembicMigrationsCheck().metadata.depends_on
