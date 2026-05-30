"""Integration tests for layout rules in seed templates.

Tests load the actual seed resume and cover letter template lint configs
and verify that layout rules are present and properly configured.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tailor.lint.config import load_lint_config
from tailor.lint.layout.rules import LAYOUT_RULE_REGISTRY
from tailor.lint.models import Severity

# Paths to seed templates
SEED_TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent.parent.parent / "backend/services/doc-template-service/seed_templates"
)
RESUME_TEMPLATE_PATH = SEED_TEMPLATES_DIR / "default_resume_template.html"
COVER_LETTER_TEMPLATE_PATH = SEED_TEMPLATES_DIR / "default_cover_letter_template.html"


class TestResumeTemplateLayoutRules:
    """Tests for layout rules in resume seed template."""

    def test_resume_template_config_exists(self) -> None:
        """Resume template lint config file exists."""
        lint_path = RESUME_TEMPLATE_PATH.with_suffix(".lint.yaml")
        assert lint_path.exists(), f"Resume lint config not found: {lint_path}"

    def test_resume_template_config_loads(self) -> None:
        """Resume template lint config loads without error."""
        config = load_lint_config(RESUME_TEMPLATE_PATH)
        assert config is not None

    def test_resume_template_has_layout_block(self) -> None:
        """Resume template config has a layout block."""
        config = load_lint_config(RESUME_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None

    def test_resume_template_layout_rules_present(self) -> None:
        """Resume template layout block has rules."""
        config = load_lint_config(RESUME_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        assert len(config.layout.rules) > 0

    def test_resume_template_max_pages_exceeded_rule(self) -> None:
        """Resume template has max_pages_exceeded rule."""
        config = load_lint_config(RESUME_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        rule_ids = [r.rule_id for r in config.layout.rules]
        assert "layout.max_pages_exceeded.resume" in rule_ids

    def test_resume_template_page_overflow_rule(self) -> None:
        """Resume template has page_overflow rule."""
        config = load_lint_config(RESUME_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        rule_ids = [r.rule_id for r in config.layout.rules]
        assert "layout.page_overflow.resume" in rule_ids

    def test_resume_max_pages_params(self) -> None:
        """Resume max_pages_exceeded rule has max_pages=2."""
        config = load_lint_config(RESUME_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        for rule in config.layout.rules:
            if rule.rule_id == "layout.max_pages_exceeded.resume":
                assert rule.params.get("max_pages") == 2
                assert rule.type == "max_pages_exceeded"
                break
        else:
            pytest.fail("max_pages_exceeded rule not found")

    def test_resume_page_overflow_params(self) -> None:
        """Resume page_overflow rule has max_pages and tolerance."""
        config = load_lint_config(RESUME_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        for rule in config.layout.rules:
            if rule.rule_id == "layout.page_overflow.resume":
                assert rule.params.get("max_pages") == 2
                assert isinstance(rule.params.get("tolerance_pt"), (int, float))
                assert rule.type == "page_overflow"
                break
        else:
            pytest.fail("page_overflow rule not found")

    def test_resume_layout_rules_are_registered(self) -> None:
        """All rule types in resume layout block are registered."""
        config = load_lint_config(RESUME_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        for rule in config.layout.rules:
            assert LAYOUT_RULE_REGISTRY.contains(rule.type), f"Rule type {rule.type} not registered"

    def test_resume_layout_rules_have_valid_scope_paths(self) -> None:
        """Resume layout rules have valid scope_paths."""
        config = load_lint_config(RESUME_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        for rule in config.layout.rules:
            assert len(rule.scope_paths) > 0
            # Layout rules are typically document-level (scope "$")
            assert "$" in rule.scope_paths

    def test_resume_layout_rules_have_severity(self) -> None:
        """Resume layout rules have severity set."""
        config = load_lint_config(RESUME_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        for rule in config.layout.rules:
            assert rule.severity in [Severity.ERROR, Severity.WARNING, Severity.INFO]


class TestCoverLetterTemplateLayoutRules:
    """Tests for layout rules in cover letter seed template."""

    def test_cover_letter_template_config_exists(self) -> None:
        """Cover letter template lint config file exists."""
        lint_path = COVER_LETTER_TEMPLATE_PATH.with_suffix(".lint.yaml")
        assert lint_path.exists(), f"Cover letter lint config not found: {lint_path}"

    def test_cover_letter_template_config_loads(self) -> None:
        """Cover letter template lint config loads without error."""
        config = load_lint_config(COVER_LETTER_TEMPLATE_PATH)
        assert config is not None

    def test_cover_letter_template_has_layout_block(self) -> None:
        """Cover letter template config has a layout block."""
        config = load_lint_config(COVER_LETTER_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None

    def test_cover_letter_template_layout_rules_present(self) -> None:
        """Cover letter template layout block has rules."""
        config = load_lint_config(COVER_LETTER_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        assert len(config.layout.rules) > 0

    def test_cover_letter_template_orphan_detected_rule(self) -> None:
        """Cover letter template has orphan_detected rule."""
        config = load_lint_config(COVER_LETTER_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        rule_ids = [r.rule_id for r in config.layout.rules]
        assert "layout.orphan.body_paragraphs" in rule_ids

    def test_cover_letter_template_max_pages_rule(self) -> None:
        """Cover letter template has max_pages_exceeded rule."""
        config = load_lint_config(COVER_LETTER_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        rule_ids = [r.rule_id for r in config.layout.rules]
        assert "layout.max_pages_exceeded.cover_letter" in rule_ids

    def test_cover_letter_orphan_params(self) -> None:
        """Cover letter orphan_detected rule has proper params."""
        config = load_lint_config(COVER_LETTER_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        for rule in config.layout.rules:
            if rule.rule_id == "layout.orphan.body_paragraphs":
                assert rule.type == "orphan_detected"
                assert "width_fill_ratio" in rule.params
                assert "min_substantive_words" in rule.params
                assert "exclude_single_line" in rule.params
                break
        else:
            pytest.fail("orphan rule not found")

    def test_cover_letter_max_pages_is_one(self) -> None:
        """Cover letter max_pages_exceeded rule has max_pages=1."""
        config = load_lint_config(COVER_LETTER_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        for rule in config.layout.rules:
            if rule.rule_id == "layout.max_pages_exceeded.cover_letter":
                assert rule.params.get("max_pages") == 1
                assert rule.type == "max_pages_exceeded"
                break
        else:
            pytest.fail("max_pages rule not found")

    def test_cover_letter_layout_rules_are_registered(self) -> None:
        """All rule types in cover letter layout block are registered."""
        config = load_lint_config(COVER_LETTER_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        for rule in config.layout.rules:
            assert LAYOUT_RULE_REGISTRY.contains(rule.type), f"Rule type {rule.type} not registered"

    def test_cover_letter_layout_rules_have_valid_scope_paths(self) -> None:
        """Cover letter layout rules have valid scope_paths."""
        config = load_lint_config(COVER_LETTER_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        for rule in config.layout.rules:
            assert len(rule.scope_paths) > 0

    def test_cover_letter_layout_rules_have_severity(self) -> None:
        """Cover letter layout rules have severity set."""
        config = load_lint_config(COVER_LETTER_TEMPLATE_PATH)
        assert config is not None
        assert config.layout is not None
        for rule in config.layout.rules:
            assert rule.severity in [Severity.ERROR, Severity.WARNING, Severity.INFO]


class TestLayoutRulesAcrossTemplates:
    """Cross-template tests for layout rule consistency."""

    def test_both_templates_have_layout_blocks(self) -> None:
        """Both seed templates have layout rule blocks."""
        resume_config = load_lint_config(RESUME_TEMPLATE_PATH)
        cover_letter_config = load_lint_config(COVER_LETTER_TEMPLATE_PATH)
        assert resume_config is not None
        assert cover_letter_config is not None
        assert resume_config.layout is not None
        assert cover_letter_config.layout is not None

    def test_no_duplicate_rule_ids_within_template(self) -> None:
        """No duplicate rule_id within same template's layout block."""
        resume_config = load_lint_config(RESUME_TEMPLATE_PATH)
        assert resume_config is not None
        assert resume_config.layout is not None
        rule_ids = [r.rule_id for r in resume_config.layout.rules]
        assert len(rule_ids) == len(set(rule_ids)), "Duplicate rule_ids in resume layout block"

        cover_letter_config = load_lint_config(COVER_LETTER_TEMPLATE_PATH)
        assert cover_letter_config is not None
        assert cover_letter_config.layout is not None
        rule_ids = [r.rule_id for r in cover_letter_config.layout.rules]
        assert len(rule_ids) == len(set(rule_ids)), "Duplicate rule_ids in cover letter layout block"

    def test_all_layout_rule_types_are_built_in(self) -> None:
        """All rule types used are registered built-in types."""
        resume_config = load_lint_config(RESUME_TEMPLATE_PATH)
        cover_letter_config = load_lint_config(COVER_LETTER_TEMPLATE_PATH)
        assert resume_config is not None
        assert cover_letter_config is not None

        all_configs = []
        if resume_config.layout:
            all_configs.extend(resume_config.layout.rules)
        if cover_letter_config.layout:
            all_configs.extend(cover_letter_config.layout.rules)

        known_types = LAYOUT_RULE_REGISTRY.known_types()
        for rule in all_configs:
            assert rule.type in known_types, f"Unknown rule type: {rule.type}"
