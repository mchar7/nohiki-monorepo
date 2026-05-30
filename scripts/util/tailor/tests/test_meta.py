"""Tests for tailor.lint.meta module.

Tests cover TailorMetaConfig, extract_tailor_meta, and build_runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tailor.exceptions import LintConfigError
from tailor.lint.meta import TailorMetaConfig, build_runtime, extract_tailor_meta
from tailor.lint.runtime import LintRuntimeContext


class TestTailorMetaConfig:
    """Tests for TailorMetaConfig dataclass."""

    def test_accepts_all_fields(self) -> None:
        """TailorMetaConfig accepts all documented meta fields."""
        config = TailorMetaConfig(
            lint_tags=frozenset({"tag1", "tag2"}),
            lint_vars={"var1": "value1"},
            sibling_documents={"reference": "reference.json"},
            lint_disable_rule_ids=frozenset({"rule1", "rule2"}),
        )
        assert config.lint_tags == frozenset({"tag1", "tag2"})
        assert config.lint_vars == {"var1": "value1"}
        assert config.sibling_documents == {"reference": "reference.json"}
        assert config.lint_disable_rule_ids == frozenset({"rule1", "rule2"})

    def test_fields_have_empty_defaults(self) -> None:
        """TailorMetaConfig fields default to empty collections."""
        config = TailorMetaConfig()
        assert config.lint_tags == frozenset()
        assert config.lint_vars == {}
        assert config.sibling_documents == {}
        assert config.lint_disable_rule_ids == frozenset()

    def test_rejects_invalid_tag_names(self) -> None:
        """lint_tags values must be snake-case lowercase identifiers."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="Invalid lint_tag"):
            TailorMetaConfig(lint_tags=frozenset({"Bad-Tag"}))

    def test_rejects_invalid_var_names(self) -> None:
        """lint_vars keys must be valid Python identifier strings."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="Invalid lint_vars key"):
            TailorMetaConfig(lint_vars={"bad-name": "v"})

    def test_frozen_immutable(self) -> None:
        """TailorMetaConfig is frozen (immutable) - verify by model config."""
        config = TailorMetaConfig(lint_tags=frozenset({"a"}))
        # Check that the model is configured as frozen
        assert config.model_config.get("frozen", False) is True

    def test_extra_forbid_rejects_unknown_keys(self) -> None:
        """TailorMetaConfig rejects unknown keys via extra='forbid'."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TailorMetaConfig.model_validate({"unknown_key": "value"})


class TestExtractTailorMeta:
    """Tests for extract_tailor_meta()."""

    def test_no_meta_key_returns_none(self) -> None:
        """extract_tailor_meta returns (data, None) when _tailor_meta is absent."""
        data = {"name": "Alice", "age": 30}
        stripped, meta = extract_tailor_meta(data)
        assert stripped == data
        assert meta is None

    def test_strips_meta_key_from_returned_data(self) -> None:
        """extract_tailor_meta removes _tailor_meta from stripped data."""
        data = {"name": "Alice", "_tailor_meta": {"lint_tags": ["tag1"]}}
        stripped, meta = extract_tailor_meta(data)
        assert "_tailor_meta" not in stripped
        assert "name" in stripped
        assert meta is not None

    def test_returns_parsed_config_when_present(self) -> None:
        """extract_tailor_meta parses _tailor_meta to TailorMetaConfig."""
        data = {
            "content": "data",
            "_tailor_meta": {
                "lint_tags": ["tag1", "tag2"],
                "lint_vars": {"var": "value"},
            },
        }
        _, meta = extract_tailor_meta(data)
        assert meta is not None
        assert meta.lint_tags == frozenset({"tag1", "tag2"})
        assert meta.lint_vars == {"var": "value"}

    def test_raises_when_meta_is_not_mapping(self) -> None:
        """extract_tailor_meta raises LintConfigError when _tailor_meta is not a dict."""
        with pytest.raises(LintConfigError, match="_tailor_meta must be a mapping"):
            extract_tailor_meta({"_tailor_meta": ["list", "not", "dict"]})
        with pytest.raises(LintConfigError, match="_tailor_meta must be a mapping"):
            extract_tailor_meta({"_tailor_meta": 42})
        with pytest.raises(LintConfigError, match="_tailor_meta must be a mapping"):
            extract_tailor_meta({"_tailor_meta": "string"})

    def test_raises_when_meta_has_invalid_schema(self) -> None:
        """extract_tailor_meta raises LintConfigError when _tailor_meta has invalid fields."""
        # Unknown field
        with pytest.raises(LintConfigError, match="Invalid _tailor_meta"):
            extract_tailor_meta({"_tailor_meta": {"unknown_field": "value"}})
        # Wrong type
        with pytest.raises(LintConfigError, match="Invalid _tailor_meta"):
            extract_tailor_meta({"_tailor_meta": {"lint_tags": "not-a-list"}})

    def test_does_not_mutate_input(self) -> None:
        """extract_tailor_meta does not mutate the input data."""
        data = {"name": "Alice", "_tailor_meta": {"lint_tags": ["tag1"]}}
        original_keys = set(data.keys())
        extract_tailor_meta(data)
        assert set(data.keys()) == original_keys
        assert "_tailor_meta" in data


class TestBuildRuntime:
    """Tests for build_runtime()."""

    def test_none_meta_returns_empty_context(self) -> None:
        """build_runtime(None) returns empty LintRuntimeContext."""
        ctx = build_runtime(None)
        assert isinstance(ctx, LintRuntimeContext)
        assert ctx.active_tags == frozenset()
        assert ctx.variables == {}
        assert ctx.sibling_documents == {}
        assert ctx.disabled_rule_ids == frozenset()

    def test_populates_active_tags_as_frozenset(self) -> None:
        """build_runtime populates active_tags as frozenset from lint_tags."""
        meta = TailorMetaConfig(lint_tags=frozenset({"tag1", "tag2"}))
        ctx = build_runtime(meta)
        assert ctx.active_tags == frozenset(("tag1", "tag2"))

    def test_populates_variables_dict(self) -> None:
        """build_runtime populates variables from lint_vars."""
        meta = TailorMetaConfig(lint_vars={"var1": "value1", "var2": "value2"})
        ctx = build_runtime(meta)
        assert ctx.variables == {"var1": "value1", "var2": "value2"}

    def test_populates_disabled_rule_ids_as_frozenset(self) -> None:
        """build_runtime populates disabled_rule_ids as frozenset."""
        meta = TailorMetaConfig(lint_disable_rule_ids=frozenset({"rule.1", "rule.2"}))
        ctx = build_runtime(meta)
        assert ctx.disabled_rule_ids == frozenset(("rule.1", "rule.2"))

    def test_loads_sibling_json_files(self, tmp_path: Path) -> None:
        """build_runtime loads sibling JSON files from disk."""
        # Create two sibling files
        reference_file = tmp_path / "reference.json"
        reference_file.write_text(json.dumps({"name": "Alice", "skills": ["Python"]}))

        letter_file = tmp_path / "letter.json"
        letter_file.write_text(json.dumps({"body": "Dear hiring manager..."}))

        meta = TailorMetaConfig(
            sibling_documents={
                "reference": "reference.json",
                "letter": "letter.json",
            }
        )
        ctx = build_runtime(meta, base_dir=tmp_path)

        assert "reference" in ctx.sibling_documents
        assert ctx.sibling_documents["reference"] == {"name": "Alice", "skills": ["Python"]}
        assert "letter" in ctx.sibling_documents
        assert ctx.sibling_documents["letter"] == {"body": "Dear hiring manager..."}

    def test_raises_when_sibling_file_missing(self, tmp_path: Path) -> None:
        """build_runtime raises LintConfigError when sibling file missing."""
        meta = TailorMetaConfig(sibling_documents={"reference": "nonexistent.json"})
        with pytest.raises(LintConfigError, match="not found"):
            build_runtime(meta, base_dir=tmp_path)

    def test_raises_when_sibling_invalid_json(self, tmp_path: Path) -> None:
        """build_runtime raises LintConfigError when sibling is not valid JSON."""
        bad_json_file = tmp_path / "bad.json"
        bad_json_file.write_text("{ invalid json }")

        meta = TailorMetaConfig(sibling_documents={"bad": "bad.json"})
        with pytest.raises(LintConfigError, match="not valid JSON"):
            build_runtime(meta, base_dir=tmp_path)

    def test_raises_when_sibling_is_not_json_object(self, tmp_path: Path) -> None:
        """build_runtime raises LintConfigError when sibling is not a JSON object."""
        # Array instead of object
        array_file = tmp_path / "array.json"
        array_file.write_text(json.dumps([1, 2, 3]))

        meta = TailorMetaConfig(sibling_documents={"arr": "array.json"})
        with pytest.raises(LintConfigError, match="must be a JSON object"):
            build_runtime(meta, base_dir=tmp_path)

        # Scalar instead of object
        scalar_file = tmp_path / "scalar.json"
        scalar_file.write_text(json.dumps(42))

        meta = TailorMetaConfig(sibling_documents={"num": "scalar.json"})
        with pytest.raises(LintConfigError, match="must be a JSON object"):
            build_runtime(meta, base_dir=tmp_path)

    def test_uses_cwd_when_base_dir_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """build_runtime uses cwd when base_dir is None."""
        # Create sibling file in tmp directory and change cwd
        sibling_file = tmp_path / "sibling.json"
        sibling_file.write_text(json.dumps({"key": "value"}))

        monkeypatch.chdir(tmp_path)
        meta = TailorMetaConfig(sibling_documents={"sibling": "sibling.json"})
        ctx = build_runtime(meta, base_dir=None)

        assert ctx.sibling_documents["sibling"] == {"key": "value"}

    def test_handles_absolute_sibling_paths(self, tmp_path: Path) -> None:
        """build_runtime handles absolute sibling paths."""
        sibling_file = tmp_path / "absolute.json"
        sibling_file.write_text(json.dumps({"key": "absolute"}))

        meta = TailorMetaConfig(sibling_documents={"abs": str(sibling_file.absolute())})
        ctx = build_runtime(meta, base_dir=tmp_path)

        assert ctx.sibling_documents["abs"] == {"key": "absolute"}

    def test_sibling_error_includes_path_in_exception(self, tmp_path: Path) -> None:
        """build_runtime includes file path in LintConfigError for sibling issues."""
        meta = TailorMetaConfig(sibling_documents={"missing": "missing.json"})
        with pytest.raises(LintConfigError) as exc_info:
            build_runtime(meta, base_dir=tmp_path)
        assert "missing.json" in str(exc_info.value)
