"""Data transfer objects for messaging service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(slots=True)
class NotificationParams:
    """Parameters for creating notification messages."""

    user_id: UUID
    channels: list[str]
    recipient_email: str | None
    template_vars: dict[str, Any]
    auth_header: str | None = None


@dataclass(frozen=True, slots=True)
class BatchJobNotificationParams:
    """Parameters for batch job notification processing."""

    user_id: UUID
    role_id: UUID
    listing_id: UUID
    subject: str
    stored_listing_ids: list[UUID]
    channels: list[str]
    listings: list[dict[str, Any]] | None = None
    auth_header: str | None = None
    template_name: str | None = None
    rendered_body: str | None = None
    correlation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class NotificationMessageContext:
    """Common context for creating a batch of notification messages."""

    user_id: UUID
    user_email: str | None
    subject: str
    template_vars: dict[str, Any]
    auth_header: str | None
    template_name: str | None = None
    rendered_body: str | None = None
    correlation_id: UUID | None = None
    stored_listing_id: UUID | None = None
