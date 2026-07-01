"""Shared helper functions for projection handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from nohiki.common.v1 import CorrelationStatus, Location, LocationType
from nohiki_domain_utils.threshold_constants import DEFAULT_NOTIFICATION_THRESHOLD
from nohiki_observability import get_logger
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from bff_service.db.models import CommandRequest

logger = get_logger(__name__)

_DEFAULT_CORRELATION_STATUS = "pending"
_CORRELATION_STATUS_PREFIX = "correlation_status_"


def percent_to_ratio(value: int) -> float:
    """Convert percentage integer (0-100) to ratio (0.0-1.0)."""
    return float(value) / 100.0


def get_notification_threshold(snapshot: object) -> float:
    """Extract notification threshold from SearchPrefSnapshot safely."""
    notification_config = getattr(snapshot, "notification_config", None)
    if notification_config is not None:
        threshold = getattr(notification_config, "threshold", DEFAULT_NOTIFICATION_THRESHOLD)
        return percent_to_ratio(threshold)
    return percent_to_ratio(DEFAULT_NOTIFICATION_THRESHOLD)


async def mark_command_completed(session: AsyncSession, correlation_id: str | None) -> None:
    """Mark a command request as completed based on correlation_id."""
    if not correlation_id:
        return
    try:
        request_id = UUID(correlation_id)
    except ValueError:
        logger.warning("Skipping non-UUID correlation_id on command completion", correlation_id=correlation_id)
        return
    stmt = (
        update(CommandRequest)
        .where(CommandRequest.request_id == request_id)
        .where(CommandRequest.status == "pending")
        .values(status="completed", completed_at=datetime.now(UTC))
    )
    await session.execute(stmt)


def normalize_correlation_status(status: CorrelationStatus | None) -> str:
    """Convert a CorrelationStatus enum to the lowercase string form stored in projections.

    UNSPECIFIED (proto default, falsy) and ``None`` both map to ``"pending"``
    so the projection column never stores an empty/sentinel value. The
    ``CORRELATION_STATUS_`` prefix is stripped defensively in case the
    upstream serializer ever emits the fully-qualified proto name: the
    projection column stores short forms like ``"pending"`` / ``"evaluated"``.
    """
    if not status:
        return _DEFAULT_CORRELATION_STATUS
    name = status.name.lower()
    name = name.removeprefix(_CORRELATION_STATUS_PREFIX)
    return name or _DEFAULT_CORRELATION_STATUS


def extract_enum_name(enum_val: object) -> str | None:
    """Extract enum name safely, returning None for unset/zero values."""
    if not enum_val:
        return None
    return str(enum_val.name) if hasattr(enum_val, "name") else None


def format_location_display(location: Location | None) -> str:
    """Render a Location as the display string stored in projection tables.

    Listings carry only structured Location post-enrichment; the legacy
    `location_raw` column on projection tables is populated from this
    canonical form so frontend rendering does not need the raw scrape.

    Intentionally duplicated with ``nohiki_test_utils.sample_data.format_location_raw``:
    test fixtures must not depend on bff-service runtime code, and bff-service
    must not depend on the test-utils library at runtime. The two helpers are
    kept in sync by hand because the rendering rule (``city, state`` or
    ``"Remote"``) is a stable display contract.
    """
    if location is None:
        return ""
    parts = [p for p in (location.city, location.state_province) if p]
    if parts:
        return ", ".join(parts)
    if location.location_type == LocationType.REMOTE:
        return "Remote"
    if location.country:
        return location.country.name
    return ""
