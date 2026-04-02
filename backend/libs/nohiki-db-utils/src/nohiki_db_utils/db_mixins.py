"""Database mixins for common patterns across services."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

_REPR_AUTO_DETECT_FIELDS: tuple[str, ...] = (
    "name",
    "title",
    "status",
    "email",
    "version",
    "slug",
)

UUID_DEFAULT = sa.text("uuidv7()")
SQL_NOW = sa.text("now()")


class CreatedAtMixin:
    """Mixin for created_at timestamp column.

    Provides just the created_at timestamp for entities that don't need updated_at.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=SQL_NOW,
        nullable=False,
        comment="Timestamp when the record was created",
    )


class UpdatedAtMixin:
    """Mixin for updated_at timestamp column.

    Provides just the updated_at timestamp for entities that don't need created_at.
    """

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=SQL_NOW,
        nullable=False,
        onupdate=SQL_NOW,
        comment="Timestamp when the record was last updated",
    )


class IdMixin:
    """Mixin for UUID primary key with uuidv7().

    Provides time-sortable UUID primary keys across all services.
    UUIDv7 encodes timestamp for natural ordering and index locality.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        primary_key=True,
        server_default=UUID_DEFAULT,
        comment="Time-sortable UUID v7 primary key",
    )


class AuditMixin:
    """Mixin for audit columns (created_at, updated_at).

    Provides standard timestamp tracking for all entities.
    Uses PostgreSQL server-side defaults for consistency.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=SQL_NOW,
        nullable=False,
        comment="Timestamp when the record was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=SQL_NOW,
        nullable=False,
        onupdate=SQL_NOW,
        comment="Timestamp when the record was last updated",
    )


class UserAuditMixin(AuditMixin):
    """Extended audit mixin that includes user tracking (created_by, updated_by).

    Useful for entities where user attribution is important.
    Note: These are logical references to Account.id from user-service.
    """

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(),
        nullable=True,
        comment="Account ID who created this record (logical reference to user-service)",
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(),
        nullable=True,
        comment="Account ID who last updated this record (logical reference to user-service)",
    )


class UUIDPrimaryKeyMixin:
    """Mixin for UUID primary key with uuidv7().

    Provides time-sortable UUID primary keys across all services.
    UUIDv7 encodes timestamp for natural ordering and index locality.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        primary_key=True,
        server_default=UUID_DEFAULT,
        comment="Time-sortable UUID v7 primary key",
    )


class SchemaMixin:
    """Base mixin for schema specification.

    Subclasses should override __table_args__ to specify their schema.
    """

    __table_args__: ClassVar = None


class RepresentableMixin:
    """Auto-generates ``__repr__`` from primary key and configurable display columns.

    Override ``__repr_fields__`` to control which columns appear in repr output.
    When not set, auto-detects ``id`` plus any column matching common names
    (name, title, status, email, version, slug).

    Attributes:
        __repr_fields__: Explicit tuple of column names to include in repr.
            Empty tuple triggers auto-detection.

    """

    __repr_fields__: ClassVar[tuple[str, ...]] = ()

    def __repr__(self) -> str:
        """Generate a descriptive repr from configured or auto-detected fields."""
        cls_name = type(self).__name__
        fields = self.__repr_fields__

        if not fields:
            detected: list[str] = []
            if hasattr(self, "id"):
                detected.append("id")
            detected.extend(c for c in _REPR_AUTO_DETECT_FIELDS if hasattr(self, c))
            fields = tuple(detected)

        parts = [f"{field}={getattr(self, field, None)!r}" for field in fields]
        return f"<{cls_name}({', '.join(parts)})>"


class BaseEntity(UUIDPrimaryKeyMixin, AuditMixin, RepresentableMixin):
    """Base entity combining UUID primary key, audit columns, and auto-repr.

    Most entities should inherit from this for consistency.
    """


class UserBaseEntity(UUIDPrimaryKeyMixin, UserAuditMixin, RepresentableMixin):
    """Base entity with user tracking for user-attributed actions.

    Includes auto-repr. Use when you need to track which user
    created/modified records.
    """
