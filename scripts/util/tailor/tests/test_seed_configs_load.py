"""Tests for seed template lint configs.

Tests load and verify the real seed YAML configurations.
"""

from __future__ import annotations

from tailor.core.config import SEED_TEMPLATES_DIR
from tailor.lint import LintConfig, load_lint_config


class TestSeedConfigs:
    """Tests for seed template lint configs."""

    def test_resume_lint_config_loads(self) -> None:
        """Resume lint config must load successfully."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_resume_template.html")
        assert isinstance(result, LintConfig)
        assert len(result.rules) > 0

    def test_cover_letter_lint_config_loads(self) -> None:
        """Cover letter lint config must load successfully."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_cover_letter_template.html")
        assert isinstance(result, LintConfig)
        assert len(result.rules) > 0

    def test_resume_has_experience_bullets_rule(self) -> None:
        """Resume config must have experience_bullets related rules."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_resume_template.html")
        assert result is not None
        rule_ids = [r.rule_id for r in result.rules]
        assert any("experience" in rid for rid in rule_ids)

    def test_resume_has_skill_categories_rule(self) -> None:
        """Resume config must have skill_categories related rules."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_resume_template.html")
        assert result is not None
        rule_ids = [r.rule_id for r in result.rules]
        assert any("skill" in rid.lower() for rid in rule_ids)

    def test_resume_has_min_items_rules(self) -> None:
        """Resume config must have min_items rules."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_resume_template.html")
        assert result is not None
        types = [r.type for r in result.rules]
        assert "min_items" in types

    def test_resume_has_max_items_rules(self) -> None:
        """Resume config must have max_items rules."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_resume_template.html")
        assert result is not None
        types = [r.type for r in result.rules]
        assert "max_items" in types

    def test_resume_has_unique_opening_words_rules(self) -> None:
        """Resume config must have unique_opening_words rules."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_resume_template.html")
        assert result is not None
        types = [r.type for r in result.rules]
        assert "unique_opening_words" in types

    def test_resume_has_verb_tense_rules(self) -> None:
        """Resume config must have verb_tense rules."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_resume_template.html")
        assert result is not None
        types = [r.type for r in result.rules]
        assert "verb_tense" in types

    def test_resume_has_banned_child_names_rules(self) -> None:
        """Resume config must have banned_child_names rules."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_resume_template.html")
        assert result is not None
        types = [r.type for r in result.rules]
        assert "banned_child_names" in types

    def test_resume_has_first_item_capitalization_rules(self) -> None:
        """Resume config must have first_item_capitalization rules."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_resume_template.html")
        assert result is not None
        types = [r.type for r in result.rules]
        assert "first_item_capitalization" in types

    def test_cover_letter_has_body_paragraphs_rules(self) -> None:
        """Cover letter config must have body_paragraphs related rules."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_cover_letter_template.html")
        assert result is not None
        rule_ids = [r.rule_id for r in result.rules]
        assert any("body" in rid.lower() for rid in rule_ids)

    def test_cover_letter_has_min_total_words_rule(self) -> None:
        """Cover letter config must have min_total_words rule."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_cover_letter_template.html")
        assert result is not None
        types = [r.type for r in result.rules]
        assert "min_total_words" in types

    def test_cover_letter_has_max_total_words_rule(self) -> None:
        """Cover letter config must have max_total_words rule."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_cover_letter_template.html")
        assert result is not None
        types = [r.type for r in result.rules]
        assert "max_total_words" in types

    def test_cover_letter_has_banned_patterns_rules(self) -> None:
        """Cover letter config must have banned_patterns rules."""
        result = load_lint_config(SEED_TEMPLATES_DIR / "default_cover_letter_template.html")
        assert result is not None
        types = [r.type for r in result.rules]
        assert "banned_patterns" in types
