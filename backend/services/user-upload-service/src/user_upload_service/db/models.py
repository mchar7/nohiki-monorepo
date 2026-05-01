"""Database models for user-upload-service (user-upload domain).

Schema: user_upload_schema
Tables: uploads
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from nohiki.common.v1 import ContentType, DocumentCategory
from nohiki_db_utils import BaseEntity
from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_NAME = "user_upload_schema"

# Mapping between ContentType enum and MIME types
_CONTENT_TYPE_TO_MIME: dict[ContentType, str] = {
    ContentType.PDF: "application/pdf",
    ContentType.DOC: "application/msword",
    ContentType.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ContentType.TXT: "text/plain",
    ContentType.RTF: "application/rtf",
    ContentType.HTML: "text/html",
    ContentType.MARKDOWN: "text/markdown",
    ContentType.JSON: "application/json",
    ContentType.PNG: "image/png",
    ContentType.JPEG: "image/jpeg",
    ContentType.WEBP: "image/webp",
}

_MIME_TO_CONTENT_TYPE: dict[str, ContentType] = {v: k for k, v in _CONTENT_TYPE_TO_MIME.items()}


def mime_to_content_type(mime: str) -> ContentType:
    """Convert MIME type string to ContentType enum."""
    return _MIME_TO_CONTENT_TYPE.get(mime, ContentType.UNSPECIFIED)


class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""


class Upload(BaseEntity, Base):
    """Account-uploaded document.

    Stores metadata about files uploaded by users (resumes, cover letters, etc.).
    Actual file content is stored in S3 (referenced by storage_key).
    """

    __repr_fields__ = ("id", "name", "user_id", "category")

    __tablename__ = "uploads"
    __table_args__ = (
        sa.Index(
            "ix_uploads_user_name_active",
            "user_id",
            "name",
            unique=True,
            postgresql_where=sa.text("is_deleted = false"),
        ),
        {"schema": SCHEMA_NAME},
    )

    # Owner reference (logical FK to user-auth-service)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Document classification
    category: Mapped[DocumentCategory] = mapped_column(
        SQLEnum(
            DocumentCategory,
            name="document_category_enum",
            schema=SCHEMA_NAME,
            native_enum=True,
            create_type=False,
            values_callable=lambda enum_cls: [e.name for e in enum_cls],
        ),
        nullable=False,
        server_default="UNSPECIFIED",
    )

    # File metadata - using ContentType proto enum
    content_type: Mapped[ContentType] = mapped_column(
        SQLEnum(
            ContentType,
            name="content_type_enum",
            schema=SCHEMA_NAME,
            native_enum=True,
            create_type=False,
            values_callable=lambda enum_cls: [e.name for e in enum_cls],
        ),
        nullable=False,
        server_default="UNSPECIFIED",
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)

    # Storage reference
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)

    # Soft delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("false"), nullable=False)

    # BaseEntity provides: id, created_at, updated_at
