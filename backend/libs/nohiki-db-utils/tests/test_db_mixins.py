"""Tests for database mixins."""

from __future__ import annotations

from typing import ClassVar

from nohiki_db_utils import (
    SQL_NOW,
    UUID_DEFAULT,
    AuditMixin,
    BaseEntity,
    CreatedAtMixin,
    IdMixin,
    SchemaMixin,
    UpdatedAtMixin,
    UserAuditMixin,
    UserBaseEntity,
    UUIDPrimaryKeyMixin,
)


class TestConstants:
    """Tests for SQL constants."""

    def test_sql_now(self) -> None:
        """Test SQL_NOW constant."""
        assert SQL_NOW is not None

    def test_uuid_default(self) -> None:
        """Test UUID_DEFAULT constant."""
        assert UUID_DEFAULT is not None


class TestIdMixin:
    """Tests for IdMixin."""

    def test_has_id_field(self) -> None:
        """Test IdMixin has id field."""
        assert hasattr(IdMixin, "id")


class TestUUIDPrimaryKeyMixin:
    """Tests for UUIDPrimaryKeyMixin."""

    def test_has_id_field(self) -> None:
        """Test UUIDPrimaryKeyMixin has id field."""
        assert hasattr(UUIDPrimaryKeyMixin, "id")


class TestCreatedAtMixin:
    """Tests for CreatedAtMixin."""

    def test_has_created_at_field(self) -> None:
        """Test CreatedAtMixin has created_at field."""
        assert hasattr(CreatedAtMixin, "created_at")


class TestUpdatedAtMixin:
    """Tests for UpdatedAtMixin."""

    def test_has_updated_at_field(self) -> None:
        """Test UpdatedAtMixin has updated_at field."""
        assert hasattr(UpdatedAtMixin, "updated_at")


class TestAuditMixin:
    """Tests for AuditMixin."""

    def test_has_audit_fields(self) -> None:
        """Test AuditMixin has audit fields."""
        assert hasattr(AuditMixin, "created_at")
        assert hasattr(AuditMixin, "updated_at")


class TestUserAuditMixin:
    """Tests for UserAuditMixin."""

    def test_has_user_audit_fields(self) -> None:
        """Test UserAuditMixin has user audit fields."""
        assert hasattr(UserAuditMixin, "created_by")
        assert hasattr(UserAuditMixin, "updated_by")


class TestSchemaMixin:
    """Tests for SchemaMixin."""

    def test_exists(self) -> None:
        """Test SchemaMixin exists."""
        assert SchemaMixin is not None


class TestRepresentableMixin:
    """Tests for RepresentableMixin auto-repr generation."""

    def test_repr_auto_detects_id(self) -> None:
        """Auto-detects id field when __repr_fields__ is empty."""
        from nohiki_db_utils.db_mixins import RepresentableMixin

        class Dummy(RepresentableMixin):
            __repr_fields__: ClassVar[tuple[str, ...]] = ()
            id: str = "abc-123"

        result = repr(Dummy())
        assert "Dummy" in result
        assert "id='abc-123'" in result

    def test_repr_auto_detects_common_fields(self) -> None:
        """Auto-detects common fields like name, status."""
        from nohiki_db_utils.db_mixins import RepresentableMixin

        class Dummy(RepresentableMixin):
            __repr_fields__: ClassVar[tuple[str, ...]] = ()
            id: str = "abc"
            name: str = "test-name"
            status: str = "active"

        result = repr(Dummy())
        assert "name='test-name'" in result
        assert "status='active'" in result

    def test_repr_uses_explicit_fields(self) -> None:
        """Uses explicit __repr_fields__ when set."""
        from nohiki_db_utils.db_mixins import RepresentableMixin

        class Dummy(RepresentableMixin):
            __repr_fields__: ClassVar[tuple[str, ...]] = ("custom_field",)
            custom_field: str = "val"

        result = repr(Dummy())
        assert "custom_field='val'" in result
        assert "id" not in result

    def test_repr_handles_missing_attr(self) -> None:
        """Handles missing attributes gracefully via getattr default."""
        from nohiki_db_utils.db_mixins import RepresentableMixin

        class Dummy(RepresentableMixin):
            __repr_fields__: ClassVar[tuple[str, ...]] = ("missing_field",)

        result = repr(Dummy())
        assert "missing_field=None" in result


class TestBaseEntity:
    """Tests for BaseEntity."""

    def test_has_base_fields(self) -> None:
        """Test BaseEntity has base fields."""
        assert hasattr(BaseEntity, "id")
        assert hasattr(BaseEntity, "created_at")
        assert hasattr(BaseEntity, "updated_at")


class TestUserBaseEntity:
    """Tests for UserBaseEntity."""

    def test_has_user_base_fields(self) -> None:
        """Test UserBaseEntity has user base fields."""
        assert hasattr(UserBaseEntity, "id")
        assert hasattr(UserBaseEntity, "created_at")
        assert hasattr(UserBaseEntity, "updated_at")
        assert hasattr(UserBaseEntity, "created_by")
        assert hasattr(UserBaseEntity, "updated_by")


class TestPackageExports:
    """Tests for package exports."""

    def test_all_exports_available(self) -> None:
        """Test all exports are available."""
        from nohiki_db_utils import (
            DatabaseDependencies,
            OutboxEntry,
            OutboxWriter,
            close_all_engines,
            db_session,
            get_async_engine,
            get_async_sessionmaker,
            initialize_database,
            reset_db,
        )

        assert DatabaseDependencies is not None
        assert OutboxEntry is not None
        assert OutboxWriter is not None
        assert close_all_engines is not None
        assert db_session is not None
        assert get_async_engine is not None
        assert get_async_sessionmaker is not None
        assert initialize_database is not None
        assert reset_db is not None
