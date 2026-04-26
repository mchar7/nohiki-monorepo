"""Event handling for user-auth-service.

This service is producer-only and does not consume Kafka events.
"""

from user_auth_service.events.publishers import (
    publish_user_created_event,
    publish_user_deleted_event,
    publish_user_updated_event,
)

__all__ = [
    "publish_user_created_event",
    "publish_user_deleted_event",
    "publish_user_updated_event",
]
