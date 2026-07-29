"""Database models for messaging service."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, ClassVar, Final

import sqlalchemy as sa
from nohiki.common.v1 import NotificationChannel
from nohiki_db_utils.db_mixins import RepresentableMixin
from nohiki_db_utils.state_machine import StateMachineMixin
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_NAME: Final[str] = "notification_schema"
SQL_NOW = sa.text("now()")


class NotificationChannelDB(enum.StrEnum):
    """Database-compatible enum for notification channels (maps to proto enum)."""

    EMAIL = "EMAIL"
    PUSH_API = "PUSH_API"

    @classmethod
    def from_proto(cls, proto_channel: NotificationChannel) -> NotificationChannelDB:
        """Convert proto enum to database enum."""
        return cls[proto_channel.name]

    def to_proto(self) -> NotificationChannel:
        """Convert database enum to proto enum."""
        return NotificationChannel[self.name]


class MessageStatus(enum.Enum):
    """Enum representing message status."""

    PENDING = "pending"
    WAITING_FOR_RENDER = "waiting_for_render"
    SENT = "sent"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""


class Message(RepresentableMixin, StateMachineMixin, Base):
    """Model representing a message to be sent."""

    __repr_fields__ = ("id", "channel", "status", "recipient")
    __status_field__ = "status"
    __transitions__: ClassVar[dict[str, frozenset[str]]] = {
        "PENDING": frozenset({"WAITING_FOR_RENDER", "SENT", "FAILED", "CANCELLED"}),
        "WAITING_FOR_RENDER": frozenset({"PENDING", "SENT", "FAILED", "CANCELLED"}),
        "FAILED": frozenset({"RETRYING", "CANCELLED"}),
        "RETRYING": frozenset({"PENDING", "SENT", "FAILED", "CANCELLED"}),
        "SENT": frozenset(),
        "CANCELLED": frozenset(),
    }

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "retry_count >= 0 AND retry_count <= 10",
            name="chk_retry_count_range",
            comment="Retry attempts limited to 0-10 to prevent infinite retry loops and resource exhaustion",
        ),
        CheckConstraint(
            "(status = 'sent' AND sent_at IS NOT NULL) OR (status != 'sent')",
            name="chk_sent_at_consistency",
            comment="Messages marked as 'sent' must have a sent_at timestamp for audit and tracking purposes",
        ),
        CheckConstraint(
            "priority >= 0",
            name="chk_priority_range",
            comment="Message priority must be non-negative (higher numbers = higher priority)",
        ),
        CheckConstraint(
            "template_vars IS NULL OR template_vars IS JSON OBJECT",
            name="chk_template_vars_json",
        ),
        CheckConstraint(
            "provider_payload IS NULL OR provider_payload IS JSON OBJECT",
            name="chk_provider_payload_json",
        ),
        UniqueConstraint("user_id", "stored_listing_id", name="uq_messages_user_stored_job"),
        {"schema": "notification_schema"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True, server_default=sa.text("uuidv7()"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(), nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(), nullable=True, comment="Correlation ID for tracking related events"
    )
    stored_listing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(), nullable=True, comment="Reference to stored job for deduplication"
    )
    channel: Mapped[NotificationChannelDB] = mapped_column(
        SQLAlchemyEnum(
            NotificationChannelDB,
            name="notification_channel_enum",
            schema="notification_schema",
            native_enum=True,
            create_type=False,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    provider_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Name of the specific provider to use for this message"
    )
    status: Mapped[MessageStatus] = mapped_column(
        SQLAlchemyEnum(
            MessageStatus,
            name="msg_status_enum",
            schema="notification_schema",
            native_enum=True,
            create_type=False,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        server_default=sa.text("'pending'"),
    )
    external_layout_id: Mapped[uuid.UUID | None] = mapped_column(UUID(), nullable=True)
    # Immutable ECST snapshot captured with an external layout request.
    external_layout_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_layout_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_vars: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Variables used for template rendering",
    )
    provider_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Provider-specific payload data",
    )
    # Ensure we don't send NULL (violates NOT NULL constraint) when attribute not explicitly set during object creation
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sa.text("0"), nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, server_default=sa.text("0"), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Past this instant the message is cancelled instead of sent",
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_msg_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=SQL_NOW,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=SQL_NOW,
        nullable=False,
        onupdate=SQL_NOW,
    )
