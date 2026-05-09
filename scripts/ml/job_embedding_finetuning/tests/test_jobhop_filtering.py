"""Tests for JobHop adapter ISCO-3 prefix filtering."""

from __future__ import annotations

from job_embedding_finetuning.dataset_adapters.adapters.jobhop import _isco3_prefix


class TestIsco3Prefix:
    """Verify ISCO-3 prefix extraction from ESCO codes."""

    def test_standard_esco_code(self) -> None:
        """Standard ESCO code like '2512.17' extracts to '251'."""
        assert _isco3_prefix("2512.17") == "251"

    def test_longer_esco_code(self) -> None:
        """Longer codes like '1324.8.3' still extract 3-digit prefix."""
        assert _isco3_prefix("1324.8.3") == "132"

    def test_four_digit_only(self) -> None:
        """Four-digit ISCO without dot still works."""
        assert _isco3_prefix("2512") == "251"

    def test_three_digit_only(self) -> None:
        """Exactly 3 digits should return itself."""
        assert _isco3_prefix("251") == "251"

    def test_too_short(self) -> None:
        """Single digit codes return None (too short for ISCO-3)."""
        assert _isco3_prefix("9") is None

    def test_two_digit(self) -> None:
        """Two digit codes return None."""
        assert _isco3_prefix("25") is None

    def test_empty_string(self) -> None:
        """Empty string returns None."""
        assert _isco3_prefix("") is None

    def test_nan_string(self) -> None:
        """'nan' has 3 chars, so prefix extraction returns 'nan' (NaN filtering is upstream)."""
        assert _isco3_prefix("nan") == "nan"

    def test_same_isco3_match(self) -> None:
        """Same 3-digit prefix means skills are in same minor group."""
        code_a = "2512.17"
        code_b = "2512.1"
        assert _isco3_prefix(code_a) == _isco3_prefix(code_b)

    def test_different_isco3_no_match(self) -> None:
        """Different 3-digit prefixes should not match."""
        code_teacher = "2340.1"
        code_dev = "2512.17"
        assert _isco3_prefix(code_teacher) != _isco3_prefix(code_dev)
