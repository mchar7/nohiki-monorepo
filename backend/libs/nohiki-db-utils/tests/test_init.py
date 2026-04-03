"""Tests for nohiki_db_utils __init__.py module imports and stubs."""

from __future__ import annotations


class TestInitModuleImports:
    """Tests for __init__.py module import handling."""

    def test_import_core_functionality(self) -> None:
        """Test that core exports are available."""
        import nohiki_db_utils

        assert hasattr(nohiki_db_utils, "DatabaseDependencies")
        assert hasattr(nohiki_db_utils, "DatabaseHealthProbe")
        assert hasattr(nohiki_db_utils, "DatabaseMetrics")
        assert hasattr(nohiki_db_utils, "OutboxEntry")
        assert hasattr(nohiki_db_utils, "OutboxEventParams")
        assert hasattr(nohiki_db_utils, "OutboxWriter")

    def test_migrations_import_from_submodule(self) -> None:
        """Test migrations imports work from submodule."""
        from nohiki_db_utils.migrations import (
            MigrationState,
            get_migration_state,
            skip_migrations,
        )

        state = MigrationState()
        assert state.status == "not_started"
        assert callable(get_migration_state)
        assert callable(skip_migrations)

    def test_seeding_import_from_submodule(self) -> None:
        """Test seeding imports work from submodule."""
        from nohiki_db_utils.seeding import SeedingError, SeedingState

        SeedingState()  # Verify class is importable and instantiable
        error = SeedingError("test")
        assert str(error) == "test"


class TestInitExports:
    """Tests that __all__ exports are correct."""

    def test_all_exports_present(self) -> None:
        """Test all expected exports are available."""
        import nohiki_db_utils

        expected_exports = [
            "EVENT_VERSION",
            "SQL_NOW",
            "UUID_DEFAULT",
            "AuditMixin",
            "BaseEntity",
            "CreatedAtMixin",
            "DatabaseDependencies",
            "DatabaseHealthProbe",
            "DatabaseMetrics",
            "IdMixin",
            "OutboxEntry",
            "OutboxEventParams",
            "OutboxWriter",
            "SchemaMixin",
            "UUIDPrimaryKeyMixin",
            "UpdatedAtMixin",
            "UserAuditMixin",
            "UserBaseEntity",
            "close_all_engines",
            "configure_offline_context",
            "create_event_metadata",
            "create_schema_if_not_exists",
            "db_session",
            "ensure_database_ready",
            "get_async_engine",
            "get_async_sessionmaker",
            "get_database_metrics",
            "get_sync_database_url",
            "reset_db",
            "run_online_migrations",
        ]

        for export in expected_exports:
            assert hasattr(nohiki_db_utils, export), f"Missing export: {export}"

    def test_version_export(self) -> None:
        """Test __version__ is exported."""
        import nohiki_db_utils

        assert nohiki_db_utils.__version__ == "0.1.0"
