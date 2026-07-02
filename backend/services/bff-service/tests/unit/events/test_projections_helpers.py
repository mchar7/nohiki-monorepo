"""Tests for events/projections module - helper functions only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from bff_service.events.projections._helpers import (
    extract_enum_name,
    get_notification_threshold,
    mark_command_completed,
    normalize_correlation_status,
    percent_to_ratio,
)
from bff_service.events.projections.job_listing import (
    _build_listing_update_set,
    _build_listing_values,
)
from bff_service.events.projections.skill import _extract_skill_source_name
from nohiki.common.v1 import CorrelationStatus, Location
from nohiki_db_utils.testing import create_mock_session


def _make_location(*, city: str = "San Francisco", state_province: str = "CA") -> Location:
    """Build a structured Location for projection tests.

    The legacy `location_raw` text is now derived from the structured Location
    via `format_location_display`, so tests must supply a real Location rather
    than a free-form string.
    """
    return Location(city=city, state_province=state_province)


def test_percent_to_ratio() -> None:
    """Test percent_to_ratio conversion."""
    assert percent_to_ratio(75) == pytest.approx(0.75)
    assert percent_to_ratio(100) == pytest.approx(1.0)
    assert percent_to_ratio(0) == pytest.approx(0.0)


def test_get_notification_threshold_with_config() -> None:
    """Test get_notification_threshold with notification_config."""
    from types import SimpleNamespace

    mock_config = SimpleNamespace(threshold=80)
    mock_snapshot = SimpleNamespace(notification_config=mock_config)
    result = get_notification_threshold(mock_snapshot)
    assert result == pytest.approx(0.8)


def test_get_notification_threshold_default() -> None:
    """Test get_notification_threshold with default value."""
    from types import SimpleNamespace

    mock_snapshot = SimpleNamespace(notification_config=None)
    result = get_notification_threshold(mock_snapshot)
    assert result == pytest.approx(0.70)


def test_extract_enum_name_with_value() -> None:
    """Test extract_enum_name with enum value."""
    from types import SimpleNamespace

    mock_enum = SimpleNamespace(name="REMOTE")
    result = extract_enum_name(mock_enum)
    assert result == "REMOTE"


def test_extract_enum_name_none() -> None:
    """Test extract_enum_name with None."""
    result = extract_enum_name(None)
    assert result is None


def test_extract_enum_name_falsy() -> None:
    """Test extract_enum_name with falsy value."""
    result = extract_enum_name(0)
    assert result is None


def test_extract_skill_source_name_with_value() -> None:
    """Test _extract_skill_source_name with value."""
    from types import SimpleNamespace

    mock_source = SimpleNamespace(name="TABIYA")
    result = _extract_skill_source_name(mock_source)
    assert result == "TABIYA"


def test_extract_skill_source_name_none() -> None:
    """Test _extract_skill_source_name with None."""
    result = _extract_skill_source_name(None)
    assert result == "UNSPECIFIED"


def test_build_listing_values() -> None:
    """Test _build_listing_values includes all expected fields."""
    listing_id = uuid.uuid4()
    now = datetime.now(UTC)
    snapshot = MagicMock()
    snapshot.id = str(listing_id)
    snapshot.listing_url = "https://example.com/job"
    snapshot.source = SimpleNamespace(name="LINKEDIN")
    snapshot.title = "Software Engineer"
    snapshot.company_name = "TechCorp"
    snapshot.description = "A great job"
    snapshot.location = _make_location()
    snapshot.work_arrangement = SimpleNamespace(name="REMOTE")
    snapshot.seniority_level = SimpleNamespace(name="SENIOR")
    snapshot.language = "en"
    snapshot.version = 1
    snapshot.raw_content_hash = "abc123"
    snapshot.posted_at = now
    snapshot.discovered_at = now
    snapshot.required_skills = ["Python", "SQL"]
    result = _build_listing_values(snapshot, listing_id, now)
    assert result["id"] == listing_id
    assert result["title"] == "Software Engineer"
    assert result["source"] == "LINKEDIN"
    assert result["language"] == "en"
    assert result["location_raw"] == "San Francisco, CA"


def test_build_listing_values_empty_language_becomes_none() -> None:
    """Test _build_listing_values maps empty language string to None for nullable column."""
    listing_id = uuid.uuid4()
    now = datetime.now(UTC)
    snapshot = MagicMock()
    snapshot.id = str(listing_id)
    snapshot.listing_url = "https://example.com/job"
    snapshot.source = SimpleNamespace(name="LINKEDIN")
    snapshot.title = "Software Engineer"
    snapshot.company_name = "TechCorp"
    snapshot.description = "A great job"
    snapshot.location = _make_location()
    snapshot.work_arrangement = SimpleNamespace(name="REMOTE")
    snapshot.seniority_level = SimpleNamespace(name="SENIOR")
    # Proto3 string default is "": must map to None for backwards-compatible events
    snapshot.language = ""
    snapshot.version = 1
    snapshot.raw_content_hash = "abc123"
    snapshot.posted_at = now
    snapshot.discovered_at = now
    snapshot.required_skills = []
    result = _build_listing_values(snapshot, listing_id, now)
    assert result["language"] is None


def test_build_listing_update_set() -> None:
    """Test _build_listing_update_set includes all expected fields."""
    snapshot = MagicMock()
    snapshot.title = "Updated Title"
    snapshot.company_name = "NewCorp"
    snapshot.description = "Updated description"
    snapshot.location = _make_location(city="New York", state_province="NY")
    snapshot.work_arrangement = SimpleNamespace(name="HYBRID")
    snapshot.seniority_level = SimpleNamespace(name="STAFF")
    snapshot.language = "fr-CA"
    snapshot.version = 2
    snapshot.raw_content_hash = "def456"
    snapshot.required_skills = ["Go", "Rust"]
    result = _build_listing_update_set(snapshot)
    assert result["title"] == "Updated Title"
    assert result["company_name"] == "NewCorp"
    assert result["language"] == "fr-CA"
    assert result["location_raw"] == "New York, NY"


def test_build_listing_update_set_empty_language_becomes_none() -> None:
    """Test _build_listing_update_set maps empty language string to None for nullable column."""
    snapshot = MagicMock()
    snapshot.title = "Title"
    snapshot.company_name = "Corp"
    snapshot.description = "Desc"
    snapshot.location = _make_location()
    snapshot.work_arrangement = SimpleNamespace(name="REMOTE")
    snapshot.seniority_level = SimpleNamespace(name="MID")
    # Proto3 string default is "" when field is unset; normalize to NULL for nullable DB column
    snapshot.language = ""
    snapshot.version = 1
    snapshot.raw_content_hash = "abc"
    snapshot.required_skills = []
    result = _build_listing_update_set(snapshot)
    assert result["language"] is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("PENDING", "pending"),
        ("EVALUATED", "evaluated"),
        ("DISMISSED", "dismissed"),
        # Defensive: full proto-style name with prefix gets stripped
        ("CORRELATION_STATUS_PENDING", "pending"),
        ("CORRELATION_STATUS_EVALUATED", "evaluated"),
        ("CORRELATION_STATUS_REJECTED", "rejected"),
    ],
)
def test_normalize_correlation_status_strips_prefix(name: str, expected: str) -> None:
    """The helper returns the short lowercase form regardless of input shape."""
    fake_status = cast("CorrelationStatus", SimpleNamespace(name=name))
    assert normalize_correlation_status(fake_status) == expected


def test_normalize_correlation_status_none_returns_pending() -> None:
    """``None`` and falsy enums map to the default ``"pending"`` sentinel."""
    assert normalize_correlation_status(None) == "pending"


def test_normalize_correlation_status_unspecified_returns_pending() -> None:
    """An UNSPECIFIED enum (proto zero value) maps to the default."""

    class _ZeroEnum:
        name = "UNSPECIFIED"

        def __bool__(self) -> bool:
            return False

    assert normalize_correlation_status(cast("CorrelationStatus", _ZeroEnum())) == "pending"


def test_normalize_correlation_status_only_prefix_returns_pending() -> None:
    """Pathological case: ``CORRELATION_STATUS_`` alone collapses to default."""
    fake_status = cast("CorrelationStatus", SimpleNamespace(name="CORRELATION_STATUS_"))
    assert normalize_correlation_status(fake_status) == "pending"


@pytest.mark.asyncio
async def test_mark_command_completed_with_valid_uuid() -> None:
    """Test mark_command_completed with valid correlation_id."""
    mock_session = create_mock_session()
    mock_session.execute = AsyncMock()
    request_id = uuid.uuid4()

    await mark_command_completed(mock_session, str(request_id))

    mock_session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_command_completed_with_none() -> None:
    """Test mark_command_completed with None correlation_id."""
    mock_session = create_mock_session()
    mock_session.execute = AsyncMock()

    await mark_command_completed(mock_session, None)

    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_command_completed_with_empty_string() -> None:
    """Test mark_command_completed with empty string correlation_id."""
    mock_session = create_mock_session()
    mock_session.execute = AsyncMock()

    await mark_command_completed(mock_session, "")

    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_command_completed_with_invalid_uuid() -> None:
    """Test mark_command_completed with invalid UUID string."""
    mock_session = create_mock_session()
    mock_session.execute = AsyncMock()

    await mark_command_completed(mock_session, "not-a-valid-uuid")

    mock_session.execute.assert_not_awaited()
