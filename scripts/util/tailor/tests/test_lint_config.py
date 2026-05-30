"""Tests for the lint config loader (tailor.lint.config) -- flat schema API."""

from __future__ import annotations

from pathlib import Path

import pytest
from tailor.exceptions import LintConfigError
from tailor.lint import LintConfig, load_lint_config


class TestLoadLintConfig:
    """Tests for load_lint_config function."""

    def test_returns_none_when_no_lint_yaml(self, tmp_path: Path) -> None:
        """load_lint_config must return None when no .lint.yaml file exists."""
        assert load_lint_config(tmp_path / "nonexistent.html") is None

    def test_returns_none_for_empty_yaml(self, tmp_path: Path) -> None:
        """load_lint_config must return None for empty YAML file."""
        (tmp_path / "empty.html").touch()
        (tmp_path / "empty.lint.yaml").write_text("", encoding="utf-8")
        assert load_lint_config(tmp_path / "empty.html") is None

    def test_valid_yaml_returns_lint_config(self, tmp_path: Path) -> None:
        """load_lint_config must return LintConfig for valid YAML."""
        (tmp_path / "valid.html").touch()
        (tmp_path / "valid.lint.yaml").write_text(
            "rules:\n"
            "  - rule_id: test.min_items\n"
            "    type: min_items\n"
            "    severity: error\n"
            "    scope_paths:\n"
            "      - items\n"
            "    params:\n"
            "      value: 1\n",
            encoding="utf-8",
        )
        result = load_lint_config(tmp_path / "valid.html")
        assert isinstance(result, LintConfig)
        assert len(result.rules) == 1
        assert result.rules[0].rule_id == "test.min_items"
        assert result.rules[0].type == "min_items"

    def test_invalid_yaml_raises_lint_config_error(self, tmp_path: Path) -> None:
        """load_lint_config must raise LintConfigError for invalid YAML."""
        (tmp_path / "bad.html").touch()
        (tmp_path / "bad.lint.yaml").write_text("{{{invalid", encoding="utf-8")
        with pytest.raises(LintConfigError) as exc_info:
            load_lint_config(tmp_path / "bad.html")
        assert exc_info.value.path is not None
        assert "bad.lint.yaml" in exc_info.value.path

    def test_non_mapping_yaml_raises_lint_config_error(self, tmp_path: Path) -> None:
        """load_lint_config must raise LintConfigError for non-mapping YAML."""
        (tmp_path / "list.html").touch()
        (tmp_path / "list.lint.yaml").write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(LintConfigError) as exc_info:
            load_lint_config(tmp_path / "list.html")
        assert "must be a YAML mapping" in str(exc_info.value)

    def test_validation_error_includes_error_count_and_field(self, tmp_path: Path) -> None:
        """load_lint_config must include error details in LintConfigError."""
        (tmp_path / "invalid.html").touch()
        (tmp_path / "invalid.lint.yaml").write_text(
            "rules:\n  - rule_id: test\n    unknown_field: true\n",
            encoding="utf-8",
        )
        with pytest.raises(LintConfigError) as exc_info:
            load_lint_config(tmp_path / "invalid.html")
        assert "error(s)" in str(exc_info.value)

    def test_derives_lint_yaml_from_html_path(self, tmp_path: Path) -> None:
        """load_lint_config must derive .lint.yaml path from .html path."""
        (tmp_path / "my_template.html").touch()
        (tmp_path / "my_template.lint.yaml").write_text(
            "rules:\n"
            "  - rule_id: test.rule\n"
            "    type: min_items\n"
            "    severity: error\n"
            "    scope_paths:\n"
            "      - items\n"
            "    params:\n"
            "      value: 1\n",
            encoding="utf-8",
        )
        assert load_lint_config(tmp_path / "my_template.html") is not None

    def test_lint_config_error_has_path_attribute(self, tmp_path: Path) -> None:
        """LintConfigError must have path attribute."""
        (tmp_path / "err.html").touch()
        (tmp_path / "err.lint.yaml").write_text("{{bad", encoding="utf-8")
        with pytest.raises(LintConfigError) as exc_info:
            load_lint_config(tmp_path / "err.html")
        assert exc_info.value.path is not None
        assert "err.lint.yaml" in exc_info.value.path

    def test_empty_rules_rejected(self, tmp_path: Path) -> None:
        """An empty rules list fails config validation at load time."""
        (tmp_path / "empty.html").touch()
        (tmp_path / "empty.lint.yaml").write_text("rules: []\n", encoding="utf-8")
        with pytest.raises(LintConfigError, match="rules must be non-empty"):
            load_lint_config(tmp_path / "empty.html")

    def test_layout_rules_loads(self, tmp_path: Path) -> None:
        """load_lint_config must handle layout rules block with registered layout types."""
        (tmp_path / "layout.html").touch()
        (tmp_path / "layout.lint.yaml").write_text(
            "rules:\n"
            "  - rule_id: content.placeholder\n"
            "    type: min_items\n"
            "    severity: info\n"
            "    scope_paths:\n"
            "      - items\n"
            "    params:\n"
            "      value: 0\n"
            "layout:\n"
            "  rules:\n"
            "    - rule_id: layout.test.max_pages\n"
            "      type: max_pages_exceeded\n"
            "      severity: error\n"
            "      scope_paths:\n"
            "        - $\n"
            "      params:\n"
            "        max_pages: 2\n",
            encoding="utf-8",
        )
        result = load_lint_config(tmp_path / "layout.html")
        assert result is not None
        assert result.layout is not None
        assert len(result.layout.rules) == 1
        assert result.layout.rules[0].type == "max_pages_exceeded"

    def test_layout_rules_rejects_content_rule_types(self, tmp_path: Path) -> None:
        """A ``min_items`` (content rule) under the layout block is a config error."""
        (tmp_path / "layout.html").touch()
        (tmp_path / "layout.lint.yaml").write_text(
            "rules:\n"
            "  - rule_id: content.placeholder\n"
            "    type: min_items\n"
            "    severity: info\n"
            "    scope_paths:\n"
            "      - items\n"
            "    params:\n"
            "      value: 0\n"
            "layout:\n"
            "  rules:\n"
            "    - rule_id: layout.wrong\n"
            "      type: min_items\n"
            "      severity: error\n"
            "      scope_paths:\n"
            "        - $\n"
            "      params:\n"
            "        value: 1\n",
            encoding="utf-8",
        )
        with pytest.raises(LintConfigError) as exc_info:
            load_lint_config(tmp_path / "layout.html")
        assert "layout" in str(exc_info.value).lower()

    def test_extra_forbid_rejects_unknown_yaml_keys(self, tmp_path: Path) -> None:
        """load_lint_config must reject unknown keys via extra='forbid'."""
        (tmp_path / "extra.html").touch()
        (tmp_path / "extra.lint.yaml").write_text(
            "rules:\n"
            "  - rule_id: test\n"
            "    type: min_items\n"
            "    scope_paths:\n"
            "      - items\n"
            "    unknown_field: true\n",
            encoding="utf-8",
        )
        with pytest.raises(LintConfigError):
            load_lint_config(tmp_path / "extra.html")
