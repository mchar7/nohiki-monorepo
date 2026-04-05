"""Tests for derive_seniority_level function."""

import pytest
from nohiki.common.v1 import SeniorityLevel
from nohiki_ml_core.seniority import derive_seniority_level


class TestDeriveSeniorityLevel:
    """Test suite for derive_seniority_level function."""

    def test_none_returns_unspecified(self) -> None:
        """Test None min_years returns UNSPECIFIED."""
        result = derive_seniority_level(None)
        assert result == SeniorityLevel.UNSPECIFIED

    def test_negative_returns_unspecified(self) -> None:
        """Test negative min_years returns UNSPECIFIED."""
        result = derive_seniority_level(-1)
        assert result == SeniorityLevel.UNSPECIFIED

    def test_zero_returns_entry(self) -> None:
        """Test 0 years returns ENTRY level."""
        result = derive_seniority_level(0)
        assert result == SeniorityLevel.ENTRY

    def test_one_year_returns_entry(self) -> None:
        """Test 1 year returns ENTRY level."""
        result = derive_seniority_level(1)
        assert result == SeniorityLevel.ENTRY

    def test_two_years_returns_mid(self) -> None:
        """Test 2 years (boundary) returns MID level."""
        result = derive_seniority_level(2)
        assert result == SeniorityLevel.MID

    def test_three_years_returns_mid(self) -> None:
        """Test 3 years returns MID level."""
        result = derive_seniority_level(3)
        assert result == SeniorityLevel.MID

    def test_four_years_returns_mid(self) -> None:
        """Test 4 years returns MID level."""
        result = derive_seniority_level(4)
        assert result == SeniorityLevel.MID

    def test_five_years_returns_senior(self) -> None:
        """Test 5 years (boundary) returns SENIOR level."""
        result = derive_seniority_level(5)
        assert result == SeniorityLevel.SENIOR

    def test_seven_years_returns_senior(self) -> None:
        """Test 7 years returns SENIOR level."""
        result = derive_seniority_level(7)
        assert result == SeniorityLevel.SENIOR

    def test_nine_years_returns_senior(self) -> None:
        """Test 9 years returns SENIOR level."""
        result = derive_seniority_level(9)
        assert result == SeniorityLevel.SENIOR

    def test_ten_years_returns_staff(self) -> None:
        """Test 10 years (boundary) returns STAFF level."""
        result = derive_seniority_level(10)
        assert result == SeniorityLevel.STAFF

    def test_fifteen_years_returns_staff(self) -> None:
        """Test 15 years returns STAFF level."""
        result = derive_seniority_level(15)
        assert result == SeniorityLevel.STAFF

    def test_twenty_years_returns_staff(self) -> None:
        """Test 20 years returns STAFF level."""
        result = derive_seniority_level(20)
        assert result == SeniorityLevel.STAFF


class TestDeriveSeniorityLevelCustomThresholds:
    """Test custom threshold parameters."""

    def test_custom_entry_max(self) -> None:
        """Test custom entry_max threshold."""
        # With entry_max=3, 2 years should still be ENTRY
        result = derive_seniority_level(2, entry_max=3)
        assert result == SeniorityLevel.ENTRY

        # 3 years should be MID
        result = derive_seniority_level(3, entry_max=3)
        assert result == SeniorityLevel.MID

    def test_custom_mid_max(self) -> None:
        """Test custom mid_max threshold."""
        # With mid_max=8, 7 years should still be MID
        result = derive_seniority_level(7, mid_max=8)
        assert result == SeniorityLevel.MID

        # 8 years should be SENIOR
        result = derive_seniority_level(8, mid_max=8)
        assert result == SeniorityLevel.SENIOR

    def test_custom_senior_max(self) -> None:
        """Test custom senior_max threshold."""
        # With senior_max=15, 14 years should still be SENIOR
        result = derive_seniority_level(14, senior_max=15)
        assert result == SeniorityLevel.SENIOR

        # 15 years should be STAFF
        result = derive_seniority_level(15, senior_max=15)
        assert result == SeniorityLevel.STAFF

    def test_all_custom_thresholds(self) -> None:
        """Test all custom thresholds together.

        Thresholds: entry_max=1, mid_max=3, senior_max=5
        """
        assert derive_seniority_level(0, entry_max=1, mid_max=3, senior_max=5) == SeniorityLevel.ENTRY
        assert derive_seniority_level(1, entry_max=1, mid_max=3, senior_max=5) == SeniorityLevel.MID
        assert derive_seniority_level(2, entry_max=1, mid_max=3, senior_max=5) == SeniorityLevel.MID
        assert derive_seniority_level(3, entry_max=1, mid_max=3, senior_max=5) == SeniorityLevel.SENIOR
        assert derive_seniority_level(4, entry_max=1, mid_max=3, senior_max=5) == SeniorityLevel.SENIOR
        assert derive_seniority_level(5, entry_max=1, mid_max=3, senior_max=5) == SeniorityLevel.STAFF


class TestDeriveSeniorityLevelBoundaries:
    """Test boundary conditions."""

    def test_boundary_entry_to_mid(self) -> None:
        """Test exact boundary between ENTRY and MID."""
        # Default entry_max=2
        assert derive_seniority_level(1) == SeniorityLevel.ENTRY
        assert derive_seniority_level(2) == SeniorityLevel.MID

    def test_boundary_mid_to_senior(self) -> None:
        """Test exact boundary between MID and SENIOR."""
        # Default mid_max=5
        assert derive_seniority_level(4) == SeniorityLevel.MID
        assert derive_seniority_level(5) == SeniorityLevel.SENIOR

    def test_boundary_senior_to_staff(self) -> None:
        """Test exact boundary between SENIOR and STAFF."""
        # Default senior_max=10
        assert derive_seniority_level(9) == SeniorityLevel.SENIOR
        assert derive_seniority_level(10) == SeniorityLevel.STAFF

    def test_large_values(self) -> None:
        """Test very large year values."""
        assert derive_seniority_level(50) == SeniorityLevel.STAFF
        assert derive_seniority_level(100) == SeniorityLevel.STAFF


class TestDeriveSeniorityLevelReturnType:
    """Test return type is correct SeniorityLevel enum."""

    @pytest.mark.parametrize(
        ("years", "expected"),
        [
            (None, SeniorityLevel.UNSPECIFIED),
            (-5, SeniorityLevel.UNSPECIFIED),
            (0, SeniorityLevel.ENTRY),
            (1, SeniorityLevel.ENTRY),
            (2, SeniorityLevel.MID),
            (4, SeniorityLevel.MID),
            (5, SeniorityLevel.SENIOR),
            (9, SeniorityLevel.SENIOR),
            (10, SeniorityLevel.STAFF),
            (20, SeniorityLevel.STAFF),
        ],
    )
    def test_parametrized_levels(
        self,
        years: int | None,
        expected: SeniorityLevel,
    ) -> None:
        """Test various year values return correct levels."""
        result = derive_seniority_level(years)
        assert result == expected
        assert isinstance(result, SeniorityLevel)
