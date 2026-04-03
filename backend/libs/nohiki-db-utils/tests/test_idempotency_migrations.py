"""Tests for idempotency migration SQL helpers."""

from __future__ import annotations

from nohiki_db_utils.idempotency_migrations import (
    get_cleanup_processed_events_sql,
    get_create_processed_events_index_sql,
    get_create_processed_events_sql,
)


class TestGetCreateProcessedEventsSql:
    """Tests for get_create_processed_events_sql."""

    def test_contains_schema(self) -> None:
        """SQL references the correct schema."""
        sql = get_create_processed_events_sql("my_schema")
        assert "my_schema.processed_events" in sql

    def test_contains_primary_key(self) -> None:
        """SQL defines composite primary key on (event_id, handler_name)."""
        sql = get_create_processed_events_sql("test_schema")
        assert "PRIMARY KEY (event_id, handler_name)" in sql

    def test_contains_required_columns(self) -> None:
        """SQL defines all required columns."""
        sql = get_create_processed_events_sql("test_schema")
        assert "event_id UUID NOT NULL" in sql
        assert "handler_name VARCHAR(255) NOT NULL" in sql
        assert "processed_at TIMESTAMPTZ" in sql

    def test_uses_create_if_not_exists(self) -> None:
        """SQL uses IF NOT EXISTS for idempotent migration."""
        sql = get_create_processed_events_sql("test_schema")
        assert "CREATE TABLE IF NOT EXISTS" in sql


class TestGetCreateProcessedEventsIndexSql:
    """Tests for get_create_processed_events_index_sql."""

    def test_contains_schema(self) -> None:
        """Index SQL references the correct schema."""
        sql = get_create_processed_events_index_sql("my_schema")
        assert "my_schema.processed_events" in sql

    def test_indexes_processed_at(self) -> None:
        """Index is on the processed_at column for TTL cleanup."""
        sql = get_create_processed_events_index_sql("test_schema")
        assert "(processed_at)" in sql

    def test_uses_create_if_not_exists(self) -> None:
        """Index SQL uses IF NOT EXISTS."""
        sql = get_create_processed_events_index_sql("test_schema")
        assert "CREATE INDEX IF NOT EXISTS" in sql

    def test_index_name_includes_schema(self) -> None:
        """Index name includes schema to avoid collisions."""
        sql = get_create_processed_events_index_sql("my_schema")
        assert "idx_my_schema_processed_events_processed_at" in sql


class TestGetCleanupProcessedEventsSql:
    """Tests for get_cleanup_processed_events_sql."""

    def test_contains_schema(self) -> None:
        """Cleanup SQL references the correct schema."""
        sql = get_cleanup_processed_events_sql("my_schema")
        assert "my_schema.processed_events" in sql

    def test_default_retention_is_168_hours(self) -> None:
        """Default retention is 168 hours (7 days)."""
        sql = get_cleanup_processed_events_sql("test_schema")
        assert "168 hours" in sql

    def test_custom_retention(self) -> None:
        """Custom retention hours are used."""
        sql = get_cleanup_processed_events_sql("test_schema", retention_hours=24)
        assert "24 hours" in sql

    def test_deletes_old_events(self) -> None:
        """SQL uses DELETE with time-based WHERE clause."""
        sql = get_cleanup_processed_events_sql("test_schema")
        assert "DELETE FROM" in sql
        assert "processed_at < NOW()" in sql
