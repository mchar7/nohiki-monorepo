"""Unit tests for listing_factory module."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from job_ingest_discovery_service.core.listing_factory import (
    _normalize_timestamp,
    to_discovered_listing,
)
from job_ingest_discovery_service.core.models import RawListing
from nohiki.common.v1 import JobBoardSource


class TestToDiscoveredListing:
    """Tests for to_discovered_listing conversion."""

    def _make_raw(self, **overrides: Any) -> RawListing:  # noqa: ANN401
        defaults: dict[str, Any] = {
            "listing_url": "https://example.com/job/1",
            "source": JobBoardSource.INDEED,
            "title": "Software Engineer",
            "company": "Acme Corp",
            "description": "Build things.",
        }
        return RawListing(**(defaults | overrides))

    def test_basic_conversion(self) -> None:
        """Converts RawListing to DiscoveredListing with correct fields."""
        raw = self._make_raw()
        result = to_discovered_listing(raw)

        assert result.listing_url == "https://example.com/job/1"
        assert result.source == JobBoardSource.INDEED
        assert result.title == "Software Engineer"
        assert result.company_name == "Acme Corp"
        assert result.description == "Build things."
        assert result.content_hash != ""

    def test_uses_provided_discovered_at(self) -> None:
        """Uses explicit discovered_at timestamp when provided."""
        ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        raw = self._make_raw()
        result = to_discovered_listing(raw, discovered_at=ts)

        assert result.discovered_timestamp == ts

    def test_defaults_discovered_at_to_now(self) -> None:
        """Falls back to now when discovered_at not provided."""
        before = datetime.now(UTC)
        raw = self._make_raw()
        result = to_discovered_listing(raw)
        after = datetime.now(UTC)

        assert result.discovered_timestamp is not None
        assert before <= result.discovered_timestamp <= after

    def test_posted_at_preserved(self) -> None:
        """Uses raw posted_at when available."""
        ts = datetime(2025, 1, 1, tzinfo=UTC)
        raw = self._make_raw(posted_at=ts)
        result = to_discovered_listing(raw)

        assert result.posted_timestamp == ts

    def test_posted_at_falls_back_to_now(self) -> None:
        """Falls back to discovered_at when posted_at is None."""
        ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        raw = self._make_raw(posted_at=None)
        result = to_discovered_listing(raw, discovered_at=ts)

        assert result.posted_timestamp == ts

    def test_optional_fields_mapped(self) -> None:
        """Optional fields are passed through correctly."""
        raw = self._make_raw(
            external_id="ext-123",
            apply_url="https://apply.example.com",
            company_url="https://company.example.com",
            location_raw="San Francisco, CA",
            raw_skills=["Python", "Go"],
        )
        result = to_discovered_listing(raw)

        assert result.external_id == "ext-123"
        assert result.apply_url == "https://apply.example.com"
        assert result.company_url == "https://company.example.com"
        assert result.location_raw == "San Francisco, CA"
        assert list(result.raw_skills) == ["Python", "Go"]

    def test_content_hash_deterministic(self) -> None:
        """Same input produces same content hash."""
        raw = self._make_raw()
        r1 = to_discovered_listing(raw)
        r2 = to_discovered_listing(raw)

        assert r1.content_hash == r2.content_hash

    def test_content_hash_differs_for_different_input(self) -> None:
        """Different title produces different content hash."""
        r1 = to_discovered_listing(self._make_raw(title="Engineer"))
        r2 = to_discovered_listing(self._make_raw(title="Manager"))

        assert r1.content_hash != r2.content_hash


class TestNormalizeTimestamp:
    """Tests for _normalize_timestamp helper."""

    def test_none_returns_none(self) -> None:
        """None input returns None."""
        assert _normalize_timestamp(None) is None

    def test_utc_aware_passthrough(self) -> None:
        """UTC-aware timestamp passes through unchanged."""
        ts = datetime(2025, 1, 1, tzinfo=UTC)
        assert _normalize_timestamp(ts) is ts

    def test_naive_gets_utc(self) -> None:
        """Naive timestamp gets UTC timezone attached."""
        ts = datetime(2025, 1, 1, tzinfo=None)  # noqa: DTZ001
        result = _normalize_timestamp(ts)

        assert result is not None
        assert result.tzinfo == UTC
        assert result.year == 2025

    def test_non_utc_aware_passthrough(self) -> None:
        """Non-UTC aware timestamp passes through (has tzinfo)."""
        est = timezone(offset=timedelta(hours=-5))
        ts = datetime(2025, 1, 1, tzinfo=est)
        result = _normalize_timestamp(ts)

        assert result is ts
