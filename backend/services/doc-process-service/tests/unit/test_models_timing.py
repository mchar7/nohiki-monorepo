"""Tests for doc_process_service.models.timing module."""

from __future__ import annotations

from doc_process_service.models.domain import ProcessingLevel
from doc_process_service.models.timing import TimingEstimate, get_timing_estimate


class TestGetTimingEstimate:
    """Tests for get_timing_estimate function."""

    def test_returns_estimate_for_known_level(self) -> None:
        """Known processing levels return their specific estimates."""
        result = get_timing_estimate(ProcessingLevel.FULL)

        assert isinstance(result, TimingEstimate)
        assert result.min_seconds == 60
        assert result.typical_seconds == 180
        assert result.max_seconds == 600

    def test_returns_estimate_for_basic_level(self) -> None:
        """BASIC level returns shortest estimates."""
        result = get_timing_estimate(ProcessingLevel.BASIC)

        assert result.min_seconds == 5
        assert result.typical_seconds == 15

    def test_all_levels_have_estimates(self) -> None:
        """Every ProcessingLevel has a defined timing estimate."""
        for level in ProcessingLevel:
            result = get_timing_estimate(level)
            assert isinstance(result, TimingEstimate)
            assert result.min_seconds > 0
