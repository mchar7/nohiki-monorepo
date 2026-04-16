"""Unit tests for experience extraction schemas.

Tests validation logic for ExperienceYearsBound and ExperienceExtraction,
including source/confidence consistency, range validation, and the silent
coercion pattern that prevents retry loops for explicit bounds.
"""

from __future__ import annotations

import pytest
from job_ingest_enrichment_service.schemas.experience import (
    ExperienceExtraction,
    ExperienceYearsBound,
)
from pydantic import ValidationError


def _explicit_bound(years: int, confidence: int | None = None) -> ExperienceYearsBound:
    return ExperienceYearsBound(years=years, source="explicit", confidence_percent=confidence)


def _inferred_bound(years: int, confidence: int = 70) -> ExperienceYearsBound:
    return ExperienceYearsBound(years=years, source="inferred", confidence_percent=confidence)


class TestExperienceYearsBound:
    """Tests for ExperienceYearsBound validation."""

    def test_explicit_no_confidence(self) -> None:
        bound = _explicit_bound(5)
        assert bound.confidence_percent is None

    def test_explicit_coerces_confidence_to_none(self) -> None:
        bound = ExperienceYearsBound(years=5, source="explicit", confidence_percent=80)
        assert bound.confidence_percent is None

    def test_inferred_requires_confidence(self) -> None:
        bound = _inferred_bound(5, confidence=75)
        assert bound.confidence_percent == 75

    def test_inferred_without_confidence_rejected(self) -> None:
        with pytest.raises(ValidationError, match="confidence_percent is required for source"):
            ExperienceYearsBound(years=5, source="inferred")

    def test_zero_years_accepted(self) -> None:
        bound = _explicit_bound(0)
        assert bound.years == 0

    def test_fifty_years_accepted(self) -> None:
        bound = _explicit_bound(50)
        assert bound.years == 50

    def test_negative_years_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExperienceYearsBound(years=-1, source="explicit")

    def test_years_above_fifty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExperienceYearsBound(years=51, source="explicit")

    def test_confidence_at_minimum_accepted(self) -> None:
        bound = _inferred_bound(5, confidence=1)
        assert bound.confidence_percent == 1

    def test_confidence_at_100_accepted(self) -> None:
        bound = _inferred_bound(5, confidence=100)
        assert bound.confidence_percent == 100

    def test_confidence_above_100_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExperienceYearsBound(years=5, source="inferred", confidence_percent=101)


class TestExperienceExtraction:
    """Tests for ExperienceExtraction validation."""

    def test_both_none_is_valid(self) -> None:
        ext = ExperienceExtraction()
        assert ext.min_years is None
        assert ext.max_years is None

    def test_min_only(self) -> None:
        ext = ExperienceExtraction(min_years=_explicit_bound(5))
        assert ext.min_years is not None
        assert ext.min_years.years == 5
        assert ext.max_years is None

    def test_max_only(self) -> None:
        ext = ExperienceExtraction(max_years=_explicit_bound(8))
        assert ext.min_years is None
        assert ext.max_years is not None

    def test_valid_range(self) -> None:
        ext = ExperienceExtraction(
            min_years=_explicit_bound(3),
            max_years=_explicit_bound(7),
        )
        assert ext.min_years is not None
        assert ext.max_years is not None
        assert ext.min_years.years == 3
        assert ext.max_years.years == 7

    def test_equal_min_max_accepted(self) -> None:
        ext = ExperienceExtraction(
            min_years=_explicit_bound(5),
            max_years=_explicit_bound(5),
        )
        assert ext.min_years is not None
        assert ext.min_years.years == 5

    def test_min_exceeds_max_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cannot exceed max_years"):
            ExperienceExtraction(
                min_years=_explicit_bound(8),
                max_years=_explicit_bound(5),
            )

    def test_mixed_sources_valid(self) -> None:
        ext = ExperienceExtraction(
            min_years=_explicit_bound(5),
            max_years=_inferred_bound(10, confidence=60),
        )
        assert ext.min_years is not None
        assert ext.min_years.source == "explicit"
        assert ext.max_years is not None
        assert ext.max_years.source == "inferred"

    def test_zero_min_with_inferred_max(self) -> None:
        ext = ExperienceExtraction(
            min_years=_explicit_bound(0),
            max_years=_inferred_bound(2, confidence=70),
        )
        assert ext.min_years is not None
        assert ext.min_years.years == 0
