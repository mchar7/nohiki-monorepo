"""Saga base mixin and status enum for multi-callback convergence."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from nohiki_db_utils.db_mixins import SQL_NOW, UUIDPrimaryKeyMixin
from nohiki_db_utils.state_machine import StateMachineMixin


class SagaStatus(StrEnum):
    """Lifecycle states for saga rows."""

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class SagaBaseMixin(UUIDPrimaryKeyMixin, StateMachineMixin):
    """SQLAlchemy mixin providing common saga columns and state transitions.

    Subclasses add domain-specific columns (e.g., listing_id, embedding JSON).
    The mixin provides lifecycle management: status tracking, callback counting,
    optimistic locking via version column, and expiry tracking.

    State transitions:
        PENDING → COMPLETED (all callbacks received)
        PENDING → FAILED (unrecoverable error)
        PENDING → EXPIRED (stale saga cleanup)

    Attributes:
        status: Current saga lifecycle state.
        expected_callbacks: Number of callbacks required for completion.
        received_callbacks: Number of callbacks received so far.
        created_at: When the saga was created.
        expires_at: When the saga should be considered stale.
        version: Optimistic lock version for concurrent callback handling.

    """

    __abstract__ = True
    __status_field__: ClassVar[str] = "status"
    __transitions__: ClassVar[dict[str, frozenset[str]]] = {
        "PENDING": frozenset({"COMPLETED", "FAILED", "EXPIRED"}),
        "COMPLETED": frozenset(),
        "FAILED": frozenset(),
        "EXPIRED": frozenset(),
    }

    status: Mapped[SagaStatus] = mapped_column(
        String(20),
        default=SagaStatus.PENDING,
        nullable=False,
        comment="Saga lifecycle state",
    )
    expected_callbacks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Number of callbacks required for completion",
    )
    received_callbacks: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of callbacks received so far",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=SQL_NOW,
        nullable=False,
        comment="When the saga was created",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When the saga should be considered stale",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        comment="Optimistic lock version for concurrent callback handling",
    )

    @property
    def is_complete(self) -> bool:
        """Check whether all expected callbacks have been received."""
        return self.received_callbacks >= self.expected_callbacks
