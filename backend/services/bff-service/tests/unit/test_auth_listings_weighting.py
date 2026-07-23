"""Unit tests for auth-listings weight computation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from bff_service.services.auth_listings.constants import (
    GEOGRAPHIC_TIER_BACKFILL,
    GEOGRAPHIC_TIER_SAME_COUNTRY,
    LANGUAGE_MISMATCH_FACTOR,
    RECENCY_BRACKETS,
    RECENCY_FLOOR,
)
from bff_service.services.auth_listings.weighting import compute_weight

# Helpers


def _posted_days_ago(days: int) -> datetime:
    """Return a UTC datetime exactly *days* days in the past."""
    return datetime.now(UTC) - timedelta(days=days)


# Full-formula integration: known combinations


class TestComputeWeightKnownCombinations:
    """High-level sanity checks combining all three factors."""

    def test_same_country_today_same_language(self) -> None:
        """Best-case candidate: same country, posted today, same language → 1.0."""
        weight = compute_weight(
            _posted_days_ago(0),
            is_same_country=True,
            listing_language="en",
            user_language="en",
        )
        assert weight == pytest.approx(1.0)

    def test_backfill_10_days_different_language(self) -> None:
        """Worst-ish candidate: backfill, 10-day-old, language mismatch → low."""
        weight = compute_weight(
            _posted_days_ago(10),
            is_same_country=False,
            listing_language="de",
            user_language="en",
        )
        # geo=0.15, recency bracket (7,0.75) < 10 <= (14,0.5) → 0.5, lang=0.7
        expected = GEOGRAPHIC_TIER_BACKFILL * 0.5 * LANGUAGE_MISMATCH_FACTOR
        assert weight == pytest.approx(expected)

    def test_same_country_today_none_language(self) -> None:
        """Unknown listing language should not penalise: treated as match → 1.0."""
        weight = compute_weight(
            _posted_days_ago(0),
            is_same_country=True,
            listing_language=None,
            user_language="en",
        )
        assert weight == pytest.approx(1.0)


# Recency bracket boundaries


class TestRecencyBrackets:
    """Verify each bracket boundary maps to the correct multiplier."""

    @pytest.mark.parametrize(
        ("days_old", "expected_multiplier"),
        [
            (0, 1.0),  # exact boundary: (0, 1.0)
            (2, 0.9),  # exact boundary: (2, 0.9)
            (7, 0.75),  # exact boundary: (7, 0.75)
            (14, 0.5),  # exact boundary: (14, 0.5)
            (30, 0.3),  # exact boundary: (30, 0.3)
        ],
        ids=["0d", "2d", "7d", "14d", "30d"],
    )
    def test_exact_bracket_boundaries(self, days_old: int, expected_multiplier: float) -> None:
        """Listing posted exactly at a bracket boundary gets that bracket's multiplier."""
        weight = compute_weight(
            _posted_days_ago(days_old),
            is_same_country=True,
            listing_language="en",
            user_language="en",
        )
        # geo=1.0, lang=1.0 → weight == recency multiplier
        assert weight == pytest.approx(expected_multiplier)

    @pytest.mark.parametrize(
        ("days_old", "expected_multiplier"),
        [
            (1, 0.9),  # 0 < 1 <= 2 → bracket (2, 0.9)
            (5, 0.75),  # 2 < 5 <= 7 → bracket (7, 0.75)
            (10, 0.5),  # 7 < 10 <= 14 → bracket (14, 0.5)
            (20, 0.3),  # 14 < 20 <= 30 → bracket (30, 0.3)
        ],
        ids=["1d", "5d", "10d", "20d"],
    )
    def test_mid_bracket_values(self, days_old: int, expected_multiplier: float) -> None:
        """Listings between bracket boundaries get the next bracket's multiplier."""
        weight = compute_weight(
            _posted_days_ago(days_old),
            is_same_country=True,
            listing_language="en",
            user_language="en",
        )
        assert weight == pytest.approx(expected_multiplier)

    def test_beyond_all_brackets_uses_recency_floor(self) -> None:
        """Listing older than the last bracket falls to RECENCY_FLOOR."""
        weight = compute_weight(
            _posted_days_ago(60),
            is_same_country=True,
            listing_language="en",
            user_language="en",
        )
        assert weight == pytest.approx(RECENCY_FLOOR)

    def test_recency_brackets_are_ascending(self) -> None:
        """Sanity: RECENCY_BRACKETS days thresholds are strictly ascending."""
        days = [b[0] for b in RECENCY_BRACKETS]
        assert days == sorted(days)
        assert len(days) == len(set(days)), "Duplicate bracket thresholds"


# Language bonus


class TestLanguageBonus:
    """Verify language matching logic."""

    def test_both_none_gives_full_bonus(self) -> None:
        """Both listing and user language None → no penalty."""
        weight = compute_weight(
            _posted_days_ago(0),
            is_same_country=True,
            listing_language=None,
            user_language=None,
        )
        assert weight == pytest.approx(1.0)

    def test_listing_none_gives_full_bonus(self) -> None:
        """Listing language None → no penalty even if user has a preference."""
        weight = compute_weight(
            _posted_days_ago(0),
            is_same_country=True,
            listing_language=None,
            user_language="en",
        )
        assert weight == pytest.approx(1.0)

    def test_user_none_gives_full_bonus(self) -> None:
        """User language None → no penalty even if listing has a language."""
        weight = compute_weight(
            _posted_days_ago(0),
            is_same_country=True,
            listing_language="de",
            user_language=None,
        )
        assert weight == pytest.approx(1.0)

    def test_same_language_gives_full_bonus(self) -> None:
        """Exact language match → no penalty."""
        weight = compute_weight(
            _posted_days_ago(0),
            is_same_country=True,
            listing_language="en",
            user_language="en",
        )
        assert weight == pytest.approx(1.0)

    def test_different_languages_apply_mismatch_factor(self) -> None:
        """Language mismatch → LANGUAGE_MISMATCH_FACTOR applied."""
        weight = compute_weight(
            _posted_days_ago(0),
            is_same_country=True,
            listing_language="de",
            user_language="en",
        )
        assert weight == pytest.approx(LANGUAGE_MISMATCH_FACTOR)


# Geographic tier


class TestGeographicTier:
    """Verify geographic tier selection."""

    def test_same_country_tier(self) -> None:
        """Same country → GEOGRAPHIC_TIER_SAME_COUNTRY (1.0)."""
        weight = compute_weight(
            _posted_days_ago(0),
            is_same_country=True,
            listing_language="en",
            user_language="en",
        )
        assert weight == pytest.approx(GEOGRAPHIC_TIER_SAME_COUNTRY)

    def test_backfill_tier(self) -> None:
        """Different country → GEOGRAPHIC_TIER_BACKFILL (0.15)."""
        weight = compute_weight(
            _posted_days_ago(0),
            is_same_country=False,
            listing_language="en",
            user_language="en",
        )
        assert weight == pytest.approx(GEOGRAPHIC_TIER_BACKFILL)


# Weight range guarantees


class TestWeightRange:
    """Ensure the weight always stays within [0, 1]."""

    @pytest.mark.parametrize(
        ("days_old", "is_same_country", "listing_lang", "user_lang"),
        [
            (0, True, "en", "en"),
            (1, False, "de", "en"),
            (2, True, None, None),
            (7, False, None, "en"),
            (14, True, "en", None),
            (30, False, "en", "en"),
            (60, True, "de", "en"),
            (365, False, None, None),
        ],
        ids=[
            "today-best",
            "mid-mismatch",
            "2d-unknown",
            "7d-listing-unknown",
            "14d-user-unknown",
            "30d",
            "60d",
            "365d",
        ],
    )
    def test_weight_in_unit_interval(
        self,
        days_old: int,
        is_same_country: bool,  # noqa: FBT001 - pytest parametrize injects positionally
        listing_lang: str | None,
        user_lang: str | None,
    ) -> None:
        """Weight stays in [0, 1] across recency boundaries and representative factors."""
        weight = compute_weight(
            _posted_days_ago(days_old),
            is_same_country=is_same_country,
            listing_language=listing_lang,
            user_language=user_lang,
        )
        assert 0.0 <= weight <= 1.0
