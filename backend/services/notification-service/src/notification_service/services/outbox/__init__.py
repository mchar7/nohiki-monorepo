"""Outbox worker package for background message processing.

Components:
- OutboxWorker: Background processing loop for pending messages
- MessageExpirySweep: Periodic cancellation of messages past their TTL
- NotificationEventPublisher: Kafka event publishing for sent/failed notifications
- RetryStrategy: Exponential backoff calculation for retries
- ProviderRouter: Resilient provider dispatch with per-provider circuit breakers
- SendOutcome / SendVerdict: ADT describing a router dispatch result
"""

from notification_service.services.outbox.event_publisher import NotificationEventPublisher
from notification_service.services.outbox.expiry_sweep import MessageExpirySweep
from notification_service.services.outbox.provider_router import (
    ProviderRouter,
    SendOutcome,
    SendVerdict,
)
from notification_service.services.outbox.retry_strategy import RetryStrategy
from notification_service.services.outbox.worker import OutboxWorker

__all__ = [
    "MessageExpirySweep",
    "NotificationEventPublisher",
    "OutboxWorker",
    "ProviderRouter",
    "RetryStrategy",
    "SendOutcome",
    "SendVerdict",
]
