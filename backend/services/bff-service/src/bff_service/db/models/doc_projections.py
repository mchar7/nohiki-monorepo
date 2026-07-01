"""Document-domain projection models (schemas, templates, generation status)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

import sqlalchemy as sa
from nohiki.common.v1 import AccessScope
from nohiki.doc.template.v1 import TemplateAudience
from nohiki_db_utils import RepresentableMixin, StateMachineMixin
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from bff_service.db.models.base import (
    SCHEMA_NAME,
    SQL_NOW,
    AccessScopeEnum,
    Base,
    TemplateAudienceEnum,
)


class SchemaFamilyProjection(Base, RepresentableMixin):
    """Projection of schema families from doc-schema-service events."""

    __repr_fields__ = ("id", "namespace", "name")

    __tablename__ = "schema_family_projections"
    __table_args__ = (
        sa.Index("ix_schema_family_projections_namespace", "namespace"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)


class SchemaVersionProjection(Base, RepresentableMixin):
    """Projection of schema versions from doc-schema-service events."""

    __repr_fields__ = ("id", "family_id", "version")

    __tablename__ = "schema_version_projections"
    __table_args__ = (
        sa.Index("ix_schema_version_projections_family_id", "family_id"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)


class TemplateProjection(Base, RepresentableMixin):
    """Projection of templates from doc-template-service events.

    Single-table design: Each row is a complete template version.
    Multiple versions share (namespace, name) but differ by version string.
    """

    __repr_fields__ = ("id", "namespace", "name", "version")

    __tablename__ = "template_projections"
    __table_args__ = (
        sa.Index("ix_template_projections_namespace_name", "namespace", "name"),
        sa.Index("ix_template_projections_created_at", "created_at"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(), nullable=True)
    namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    template_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_scope: Mapped[AccessScope] = mapped_column(
        AccessScopeEnum, server_default=sa.text("'PUBLIC'"), nullable=False
    )
    audience: Mapped[TemplateAudience] = mapped_column(
        TemplateAudienceEnum, server_default=sa.text("'DOCUMENT'"), nullable=False
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentGenerationStatus(Base, StateMachineMixin, RepresentableMixin):
    """Tracks async document generation requests."""

    __repr_fields__ = ("request_id", "status", "output_format")
    __status_field__ = "status"
    __transitions__: ClassVar[dict[str, frozenset[str]]] = {
        "pending": frozenset({"in_progress"}),
        "in_progress": frozenset({"completed", "failed"}),
        "failed": frozenset({"pending"}),
        "completed": frozenset(),
    }

    __tablename__ = "document_generation_status"
    __table_args__ = (
        sa.Index("ix_document_generation_status_user_id", "user_id"),
        {"schema": SCHEMA_NAME},
    )

    request_id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    job_correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(), nullable=True)
    pref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(), nullable=True)
    listing_id: Mapped[uuid.UUID | None] = mapped_column(UUID(), nullable=True)
    template_version_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    output_format: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default="pending", nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
