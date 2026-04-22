"""Messaging service package for notification operations.

Components:
- MessageRepository: Database CRUD for Message entities
- NotificationService: Orchestration for sending notifications
- Channel validation and recipient resolution utilities
"""

from notification_service.services.messaging.channel_service import (
    ValidatedChannels,
    resolve_recipient_for_channel,
    validate_channels,
)
from notification_service.services.messaging.models import (
    BatchJobNotificationParams,
    NotificationMessageContext,
    NotificationParams,
)
from notification_service.services.messaging.notification_service import NotificationService
from notification_service.services.messaging.repository import MessageRepository

__all__ = [
    "BatchJobNotificationParams",
    "MessageRepository",
    "NotificationMessageContext",
    "NotificationParams",
    "NotificationService",
    "ValidatedChannels",
    "resolve_recipient_for_channel",
    "validate_channels",
]
