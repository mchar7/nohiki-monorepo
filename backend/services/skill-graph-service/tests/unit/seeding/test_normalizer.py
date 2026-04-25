"""Tests for skill text normalizer."""

from __future__ import annotations

from skill_graph_service.seeding.normalizer import normalize_skill_text


class TestNormalizeSkillText:
    """Tests for normalize_skill_text function."""

    def test_lowercase(self) -> None:
        """normalize_skill_text converts to lowercase."""
        result = normalize_skill_text("Python Programming")
        assert result == "python programming"

    def test_strip_whitespace(self) -> None:
        """normalize_skill_text strips leading/trailing whitespace."""
        result = normalize_skill_text("  python  ")
        assert result == "python"

    def test_collapse_internal_whitespace(self) -> None:
        """normalize_skill_text collapses multiple internal spaces."""
        result = normalize_skill_text("python   programming   skills")
        assert result == "python programming skills"

    def test_empty_string_returns_empty(self) -> None:
        """normalize_skill_text returns empty string for empty input."""
        result = normalize_skill_text("")
        assert result == ""

    def test_whitespace_only_returns_empty(self) -> None:
        """normalize_skill_text returns empty string for whitespace-only input."""
        result = normalize_skill_text("   ")
        assert result == ""

    def test_mixed_case_and_whitespace(self) -> None:
        """normalize_skill_text handles mixed case and whitespace."""
        result = normalize_skill_text("  Python   Programming  SKILLS  ")
        assert result == "python programming skills"

    def test_single_word(self) -> None:
        """normalize_skill_text handles single word."""
        result = normalize_skill_text("Python")
        assert result == "python"

    def test_hyphens_converted_to_spaces(self) -> None:
        """normalize_skill_text converts word-internal hyphens to spaces."""
        result = normalize_skill_text("Cross-Sector Skills")
        assert result == "cross sector skills"

    def test_preserves_numbers(self) -> None:
        """normalize_skill_text preserves numbers."""
        result = normalize_skill_text("Python 3.12")
        assert result == "python 3.12"

    def test_strips_diacritics(self) -> None:
        """normalize_skill_text strips diacritics from unicode."""
        result = normalize_skill_text("Développement Web")
        assert result == "developpement web"

    def test_nfkc_normalizes_compatibility_characters(self) -> None:
        """Compatibility-equivalent spellings collapse to one canonical skill."""
        assert (
            normalize_skill_text("\uff26\uff55\uff4c\uff4c\uff0d\uff33\uff54\uff41\uff43\uff4b \ufb01")
            == "full stack fi"
        )

    def test_strips_quotes(self) -> None:
        """normalize_skill_text removes quote characters."""
        result = normalize_skill_text('"Python" Programming')
        assert result == "python programming"

    def test_max_length_truncation(self) -> None:
        """normalize_skill_text truncates to max_length."""
        long_text = "a" * 200
        result = normalize_skill_text(long_text)
        assert len(result) == 100

    def test_custom_max_length(self) -> None:
        """normalize_skill_text respects custom max_length."""
        long_text = "a" * 50
        result = normalize_skill_text(long_text, max_length=10)
        assert len(result) == 10
