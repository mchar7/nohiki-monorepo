"""Type definitions for messaging service."""

from datetime import datetime
from typing import Any
from uuid import UUID

from nohiki.common.v1 import NotificationChannel
from pydantic import BaseModel, ConfigDict, Field


class MessageCreate(BaseModel):
    """Data for creating a new message."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: UUID
    correlation_id: UUID | None = None
    stored_listing_id: UUID | None = None
    channel: NotificationChannel
    recipient: str
    subject: str | None = None
    body: str | None = None
    external_layout_id: UUID | None = None
    # External layouts must carry their immutable version/content snapshot at request time.
    external_layout_version: str | None = None
    external_layout_content: str | None = None
    template_vars: dict[str, Any] | None = None
    provider_payload: dict[str, Any] | None = None
    priority: int = 0
    scheduled_at: datetime | None = None


class MessageUpdate(BaseModel):
    """Data for updating an existing message."""

    status: str | None = None
    sent_at: datetime | None = None
    error_message: str | None = None
    retry_count: int | None = None
    subject: str | None = None
    body: str | None = None
    recipient: str | None = None
    channel: NotificationChannel | None = None


class MessageListResponse(BaseModel):
    """Response for listing messages."""

    messages: list[Any]
    total: int
    page: int = 1
    size: int = 20


class MessageStatsResponse(BaseModel):
    """Response for message statistics."""

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)


class MessageQueryParams(BaseModel):
    """Parameters for querying messages."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    db: Any
    user_id: UUID | None = None
    status: str | None = None
    channel: str | None = None
    page: int = 1
    size: int = 20


class NotificationParams(BaseModel):
    """Parameters for job notifications."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    db: Any
    user_id: UUID
    channels: list[str]
    recipient_email: str | None = None
    template_vars: dict[str, Any] = Field(default_factory=dict)
    auth_header: str | None = None
