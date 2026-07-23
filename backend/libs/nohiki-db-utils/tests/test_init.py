"""Tests for nohiki_db_utils __init__.py module imports and stubs."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


class TestLazyImports:
    """Tests for lazy import functionality in __init__.py."""

    def test_heavy_modules_load_only_on_first_use(self) -> None:
        """Test that a plain root import does not load database or migration modules."""
        prefixes = ("alembic", "nohiki_db_utils")
        saved = {
            name: module
            for name, module in sys.modules.items()
            if name == "alembic" or name.startswith(("alembic.", "nohiki_db_utils"))
        }
        try:
            for name in tuple(sys.modules):
                if name in prefixes or name.startswith(("alembic.", "nohiki_db_utils.")):
                    del sys.modules[name]

            import nohiki_db_utils

            lazy_modules = [
                "nohiki_db_utils.async_db",
                "nohiki_db_utils.health",
                "nohiki_db_utils.migrations",
                "nohiki_db_utils.outbox",
                "nohiki_db_utils.seeding",
                "nohiki_db_utils.testing",
            ]
            for module_name in lazy_modules:
                assert module_name not in sys.modules
            assert "alembic" not in sys.modules

            assert nohiki_db_utils.OutboxWriter.__name__ == "OutboxWriter"
            assert "nohiki_db_utils.outbox" in sys.modules
            assert "alembic" not in sys.modules

            if nohiki_db_utils._HAS_ALEMBIC:
                assert callable(nohiki_db_utils.configure_offline_context)
                assert "nohiki_db_utils.alembic_env" in sys.modules
                assert "alembic" in sys.modules
        finally:
            for name in tuple(sys.modules):
                if name in prefixes or name.startswith(("alembic.", "nohiki_db_utils.")):
                    del sys.modules[name]
            sys.modules.update(saved)

    def test_unknown_attribute_raises_attribute_error(self) -> None:
        """Test that an unknown root attribute preserves normal module behavior."""
        import nohiki_db_utils

        with pytest.raises(AttributeError, match="has no attribute 'missing_export'"):
            _ = nohiki_db_utils.missing_export

    def test_all_exports_resolve(self) -> None:
        """Test that every advertised export resolves on first use."""
        import nohiki_db_utils

        for name in nohiki_db_utils.__all__:
            assert getattr(nohiki_db_utils, name) is not None

    def test_alembic_exports_are_absent_without_extra(self) -> None:
        """Test that migration exports retain the missing-extra pathway."""
        saved = {
            name: module
            for name, module in sys.modules.items()
            if name == "nohiki_db_utils" or name.startswith("nohiki_db_utils.")
        }
        try:
            for name in tuple(saved):
                del sys.modules[name]

            with patch("importlib.util.find_spec", return_value=None):
                import nohiki_db_utils

            assert not nohiki_db_utils._HAS_ALEMBIC
            assert "MigrationState" not in nohiki_db_utils.__all__
            with pytest.raises(AttributeError, match="has no attribute 'MigrationState'"):
                _ = nohiki_db_utils.MigrationState
        finally:
            for name in tuple(sys.modules):
                if name == "nohiki_db_utils" or name.startswith("nohiki_db_utils."):
                    del sys.modules[name]
            sys.modules.update(saved)


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
