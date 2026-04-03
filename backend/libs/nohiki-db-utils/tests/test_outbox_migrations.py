"""Tests for outbox_migrations module (SQL generation for Debezium CDC)."""

from __future__ import annotations

from nohiki_db_utils.outbox_migrations import (
    get_create_outbox_indexes_sql,
    get_create_outbox_table_sql,
)


class TestGetCreateOutboxTableSql:
    """Tests for get_create_outbox_table_sql function."""

    def test_returns_create_table_statement(self) -> None:
        """Test that function returns CREATE TABLE statement."""
        sql = get_create_outbox_table_sql("test_schema")

        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "test_schema.outbox" in sql

    def test_contains_required_columns(self) -> None:
        """Test that table has all required Debezium columns."""
        sql = get_create_outbox_table_sql("my_schema")

        assert "id UUID PRIMARY KEY" in sql
        assert "aggregatetype VARCHAR(255) NOT NULL" in sql
        assert "aggregateid VARCHAR(255) NOT NULL" in sql
        assert "type VARCHAR(255) NOT NULL" in sql
        assert "payload BYTEA NOT NULL" in sql
        assert "timestamp TIMESTAMPTZ" in sql
        assert "tracingspancontext VARCHAR(256)" in sql

    def test_no_polling_columns(self) -> None:
        """Test that polling columns are NOT present (Debezium CDC only)."""
        sql = get_create_outbox_table_sql("test_schema")

        assert "published" not in sql.lower()
        assert "published_at" not in sql.lower()

    def test_uses_schema_parameter(self) -> None:
        """Test that schema parameter is used correctly."""
        sql1 = get_create_outbox_table_sql("schema_one")
        sql2 = get_create_outbox_table_sql("schema_two")

        assert "schema_one.outbox" in sql1
        assert "schema_two.outbox" in sql2
        assert "schema_one" not in sql2
        assert "schema_two" not in sql1

    def test_id_has_default(self) -> None:
        """Test that id column has gen_random_uuid() default."""
        sql = get_create_outbox_table_sql("test_schema")

        assert "gen_random_uuid()" in sql

    def test_timestamp_has_default(self) -> None:
        """Test that timestamp column has NOW() default."""
        sql = get_create_outbox_table_sql("test_schema")

        assert "DEFAULT NOW()" in sql


class TestGetCreateOutboxIndexesSql:
    """Tests for get_create_outbox_indexes_sql function."""

    def test_returns_create_index_statement(self) -> None:
        """Test that function returns CREATE INDEX statement."""
        sql = get_create_outbox_indexes_sql("test_schema")

        assert "CREATE INDEX IF NOT EXISTS" in sql

    def test_creates_timestamp_index(self) -> None:
        """Test that timestamp index is created."""
        sql = get_create_outbox_indexes_sql("my_schema")

        assert "ix_my_schema_outbox_timestamp" in sql
        assert "my_schema.outbox" in sql
        assert "(timestamp)" in sql

    def test_no_polling_indexes(self) -> None:
        """Test that polling-related indexes are NOT present."""
        sql = get_create_outbox_indexes_sql("test_schema")

        assert "unpublished" not in sql.lower()
        assert "cleanup" not in sql.lower()
        assert "published = false" not in sql.lower()
        assert "published = true" not in sql.lower()

    def test_uses_schema_parameter(self) -> None:
        """Test that schema parameter is used in index name and table."""
        sql = get_create_outbox_indexes_sql("custom_schema")

        assert "ix_custom_schema_outbox_timestamp" in sql
        assert "custom_schema.outbox" in sql


class TestRemovedFunctions:
    """Tests verifying removed polling functions no longer exist."""

    def test_no_notify_trigger_function(self) -> None:
        """Test that get_create_notify_trigger_sql is removed."""
        from nohiki_db_utils import outbox_migrations

        assert not hasattr(outbox_migrations, "get_create_notify_trigger_sql")

    def test_no_notify_channel_function(self) -> None:
        """Test that get_notify_channel is removed."""
        from nohiki_db_utils import outbox_migrations

        assert not hasattr(outbox_migrations, "get_notify_channel")


class TestModuleExports:
    """Tests for module-level exports."""

    def test_exports_table_sql_function(self) -> None:
        """Test that get_create_outbox_table_sql is exported."""
        from nohiki_db_utils.outbox_migrations import get_create_outbox_table_sql

        assert callable(get_create_outbox_table_sql)

    def test_exports_indexes_sql_function(self) -> None:
        """Test that get_create_outbox_indexes_sql is exported."""
        from nohiki_db_utils.outbox_migrations import get_create_outbox_indexes_sql

        assert callable(get_create_outbox_indexes_sql)
