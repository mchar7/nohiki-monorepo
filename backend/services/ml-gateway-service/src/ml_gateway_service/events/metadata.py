"""Shared event metadata creation for ML gateway handlers."""

from __future__ import annotations

from nohiki.common.v1 import EventMetadata
from nohiki_kafka_client import create_event_metadata as _create_event_metadata

from ml_gateway_service.core.config import get_settings

settings = get_settings()


def create_event_metadata(correlation_id: str | None = None) -> EventMetadata:
    """Create EventMetadata for outgoing events.

    Args:
        correlation_id: Optional correlation ID to propagate.

    Returns:
        EventMetadata with a fresh event_id (uuid7) and current timestamp.

    """
    return _create_event_metadata(settings.service_name, correlation_id)
