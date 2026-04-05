"""Event metadata utilities for Kafka event publishing.

Helpers for creating EventMetadata instances that follow
the standard Nohiki event envelope pattern. Services should use these helpers
instead of duplicating metadata creation logic.

Usage:
    from nohiki_kafka_client import create_event_metadata

    event = MyEvent(
        metadata=create_event_metadata(
            source_service="my-service",
            correlation_id="abc-123",
        ),
        # ... event-specific fields
    )

"""

from __future__ import annotations

from datetime import UTC, datetime

from nohiki.common.v1 import EventMetadata
from uuid_utils.compat import uuid7

# Standard version for all events
EVENT_VERSION = "v1"


def create_event_metadata(
    source_service: str,
    correlation_id: str | None = None,
    *,
    causation_id: str | None = None,
    version: str = EVENT_VERSION,
) -> EventMetadata:
    """Create standard event metadata for Kafka event publishing.

    Args:
        source_service: Name of the service publishing the event.
        correlation_id: Optional correlation ID for distributed tracing.
        causation_id: Optional ID of the event that caused this event.
        version: Event schema version (defaults to "v1").
    """
    return EventMetadata(
        event_id=str(uuid7()),
        timestamp=datetime.now(UTC),
        source_service=source_service,
        correlation_id=correlation_id,
        causation_id=causation_id,
        version=version,
    )
