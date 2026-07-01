"""CQRS command request tracking model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar

import sqlalchemy as sa
from nohiki_db_utils import RepresentableMixin, StateMachineMixin
from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from bff_service.db.models.base import SCHEMA_NAME, SQL_NOW, Base


class CommandRequest(Base, StateMachineMixin, RepresentableMixin):
    """Tracks command requests for status polling in CQRS pattern."""

    __repr_fields__ = ("request_id", "command_type", "status")
    __status_field__ = "status"
    __transitions__: ClassVar[dict[str, frozenset[str]]] = {
        "pending": frozenset({"in_progress", "completed", "failed"}),
        "in_progress": frozenset({"completed", "failed"}),
        "failed": frozenset(),
        "completed": frozenset(),
    }

    __tablename__ = "command_requests"
    __table_args__ = (
        sa.Index("ix_command_requests_user_id", "user_id"),
        {"schema": SCHEMA_NAME},
    )

    request_id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    command_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
