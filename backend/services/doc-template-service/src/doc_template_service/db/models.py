"""Database models for doc-template-service.

Single-table design: Each row is a complete, immutable template version.
Multiple versions of the same template share (namespace, name, owner_id) but differ by version.
To get all versions: WHERE namespace=? AND name=? AND owner_id=?
To get latest: ORDER BY created_at DESC LIMIT 1
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from nohiki.common.v1 import AccessScope
from nohiki.doc.template.v1 import TemplateAudience
from nohiki_db_utils import SQL_NOW, BaseEntity, FreshnessTrackingMixin
from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_NAME = "doc_template_schema"

AccessScopeColumn = SQLEnum(
    AccessScope,
    name="access_scope_enum",
    schema=SCHEMA_NAME,
    create_constraint=False,
    native_enum=True,
)
TemplateAudienceColumn = SQLEnum(
    TemplateAudience,
    name="template_audience_enum",
    schema=SCHEMA_NAME,
    create_constraint=False,
    native_enum=True,
)


class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""


class DocumentTemplate(BaseEntity, FreshnessTrackingMixin, Base):
    """Single-table model for document templates.

    Each row is an immutable template version. Versions of the same template
    share (namespace, name, owner_id) but have different version strings.

    Freshness tracking: ``last_used_at`` and ``usage_count`` track render
    activity. Templates unused for ``__staleness_days__`` are flagged stale.
    """

    __repr_fields__ = ("id", "namespace", "name", "version")
    __staleness_days__ = 90

    __tablename__ = "document_templates"
    __table_args__ = (
        CheckConstraint(
            "version ~ '^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(-[0-9A-Za-z\\-\\.]+)?(\\+[0-9A-Za-z\\-\\.]+)?$'",
            name="chk_version_semver",
        ),
        CheckConstraint("content_schema IS JSON OBJECT", name="chk_content_schema_json"),
        UniqueConstraint(
            "namespace",
            "name",
            "version",
            "owner_id",
            name="uq_template_name_version_owner",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_template_namespace_name_owner", "namespace", "name", "owner_id"),
        Index("ix_template_access_scope_owner", "access_scope", "owner_id"),
        Index(
            "ix_template_created",
            "created_at",
            postgresql_using="brin",
            postgresql_with={"pages_per_range": "32"},
        ),
        {"schema": SCHEMA_NAME},
    )

    namespace: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)

    template_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb")
    )

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_scope: Mapped[AccessScope] = mapped_column(
        AccessScopeColumn,
        nullable=False,
        default=AccessScope.PUBLIC,
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(), nullable=True)
    audience: Mapped[TemplateAudience] = mapped_column(
        TemplateAudienceColumn,
        nullable=False,
        default=TemplateAudience.DOCUMENT,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=SQL_NOW,
    )
