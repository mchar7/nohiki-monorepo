"""Tests for JSON schema preprocessing for LLM consumption."""

from __future__ import annotations

import copy

import pytest
from doc_content_service.services.schema_preprocessing import preprocess_schema_for_llm


class TestPreprocessSchemaForLlm:
    """Top-level preprocessing function tests."""

    def test_returns_deep_copy(self) -> None:
        """Original schema must not be mutated."""
        original = {"type": "object", "properties": {"a": {"type": "string"}}}
        frozen = copy.deepcopy(original)
        preprocess_schema_for_llm(original)
        assert original == frozen

    def test_empty_schema(self) -> None:
        """Empty dict should pass through without error."""
        assert preprocess_schema_for_llm({}) == {}


class TestAdditionalProperties:
    """additionalProperties: false is added to all object nodes."""

    def test_root_object(self) -> None:
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        result = preprocess_schema_for_llm(schema)
        assert result["additionalProperties"] is False

    def test_nested_object(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "contact": {
                    "type": "object",
                    "properties": {"email": {"type": "string"}},
                }
            },
        }
        result = preprocess_schema_for_llm(schema)
        assert result["properties"]["contact"]["additionalProperties"] is False

    def test_preserves_existing_additional_properties(self) -> None:
        """If already set to false, should remain false (idempotent)."""
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"a": {"type": "string"}},
        }
        result = preprocess_schema_for_llm(schema)
        assert result["additionalProperties"] is False

    def test_object_without_properties_untouched(self) -> None:
        """Objects with no properties key should not get additionalProperties."""
        schema = {"type": "object", "description": "bare object"}
        result = preprocess_schema_for_llm(schema)
        assert "additionalProperties" not in result


class TestXExtensionStripping:
    """All x-* vendor extensions are removed."""

    def test_strips_x_widget(self) -> None:
        schema = {"type": "string", "x-widget": "textarea"}
        result = preprocess_schema_for_llm(schema)
        assert "x-widget" not in result

    def test_strips_x_show_item_labels(self) -> None:
        schema = {"type": "array", "items": {"type": "string"}, "x-show-item-labels": False}
        result = preprocess_schema_for_llm(schema)
        assert "x-show-item-labels" not in result

    def test_strips_x_render_as_fields(self) -> None:
        schema = {
            "type": "array",
            "prefixItems": [{"type": "string"}, {"type": "string"}],
            "x-render-as-fields": True,
            "x-field-names": ["Start", "End"],
        }
        result = preprocess_schema_for_llm(schema)
        assert "x-render-as-fields" not in result
        assert "x-field-names" not in result

    def test_strips_x_placeholder(self) -> None:
        schema = {"type": "array", "items": {"type": "string"}, "x-placeholder": "Enter..."}
        result = preprocess_schema_for_llm(schema)
        assert "x-placeholder" not in result

    def test_strips_multiple_x_extensions_at_once(self) -> None:
        schema = {
            "type": "string",
            "x-widget": "input",
            "x-llm-hint": "hint text",
            "x-custom": 42,
        }
        result = preprocess_schema_for_llm(schema)
        x_keys = [k for k in result if k.startswith("x-")]
        assert x_keys == []


class TestLlmHintMerging:
    """x-llm-hint content is merged into description."""

    def test_hint_merged_when_no_description(self) -> None:
        schema = {"type": "string", "x-llm-hint": "Use short names"}
        result = preprocess_schema_for_llm(schema)
        assert result["description"] == "Use short names"
        assert "x-llm-hint" not in result

    def test_hint_appended_to_existing_description(self) -> None:
        schema = {
            "type": "string",
            "description": "Certification name",
            "x-llm-hint": "Use acronyms like CKA",
        }
        result = preprocess_schema_for_llm(schema)
        assert result["description"] == "Certification name. Use acronyms like CKA"
        assert "x-llm-hint" not in result

    def test_empty_hint_ignored(self) -> None:
        schema = {"type": "string", "description": "Original", "x-llm-hint": ""}
        result = preprocess_schema_for_llm(schema)
        assert result["description"] == "Original"

    def test_non_string_hint_ignored(self) -> None:
        schema = {"type": "string", "description": "Original", "x-llm-hint": 42}
        result = preprocess_schema_for_llm(schema)
        assert result["description"] == "Original"


class TestUnsupportedFormatRemoval:
    """format values unsupported by GBNF grammars are stripped."""

    @pytest.mark.parametrize(
        "fmt",
        ["email", "uri", "uri-reference", "hostname", "ipv4", "ipv6", "iri", "iri-reference"],
    )
    def test_unsupported_format_removed(self, fmt: str) -> None:
        schema = {"type": "string", "format": fmt}
        result = preprocess_schema_for_llm(schema)
        assert "format" not in result

    @pytest.mark.parametrize("fmt", ["date", "date-time", "time", "duration", "uuid"])
    def test_supported_format_preserved(self, fmt: str) -> None:
        schema = {"type": "string", "format": fmt}
        result = preprocess_schema_for_llm(schema)
        assert result["format"] == fmt


class TestRecursion:
    """Preprocessing recurses into all schema structures."""

    def test_recurses_into_properties(self) -> None:
        schema = {
            "type": "object",
            "properties": {"field": {"type": "string", "x-widget": "input"}},
        }
        result = preprocess_schema_for_llm(schema)
        assert "x-widget" not in result["properties"]["field"]

    def test_recurses_into_items(self) -> None:
        schema = {
            "type": "array",
            "items": {"type": "string", "x-widget": "textarea"},
        }
        result = preprocess_schema_for_llm(schema)
        assert "x-widget" not in result["items"]

    def test_recurses_into_prefix_items(self) -> None:
        schema = {
            "type": "array",
            "prefixItems": [
                {"type": "string", "x-widget": "date"},
                {"type": "string", "x-widget": "date"},
            ],
        }
        result = preprocess_schema_for_llm(schema)
        assert "x-widget" not in result["prefixItems"][0]
        assert "x-widget" not in result["prefixItems"][1]

    def test_recurses_into_any_of(self) -> None:
        schema = {
            "anyOf": [
                {"type": "string", "x-widget": "input"},
                {"type": "integer"},
            ]
        }
        result = preprocess_schema_for_llm(schema)
        assert "x-widget" not in result["anyOf"][0]

    def test_recurses_into_one_of(self) -> None:
        schema = {
            "oneOf": [
                {"type": "object", "properties": {"a": {"type": "string"}}, "x-custom": True},
            ]
        }
        result = preprocess_schema_for_llm(schema)
        assert "x-custom" not in result["oneOf"][0]
        assert result["oneOf"][0]["additionalProperties"] is False

    def test_recurses_into_conditional_keywords(self) -> None:
        schema = {
            "if": {"type": "object", "properties": {"a": {"type": "string"}}, "x-custom": True},
            "then": {"type": "string", "x-widget": "input"},
        }
        result = preprocess_schema_for_llm(schema)
        assert "x-custom" not in result["if"]
        assert "x-widget" not in result["then"]

    def test_deeply_nested_structure(self) -> None:
        """Simulates the resume schema structure: object → array → object → array."""
        schema = {
            "type": "object",
            "properties": {
                "experience": {
                    "type": "object",
                    "properties": {
                        "entries": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "bullets": {
                                        "type": "array",
                                        "items": {"type": "string", "x-widget": "textarea"},
                                        "x-show-item-labels": False,
                                    }
                                },
                            },
                        }
                    },
                }
            },
        }
        result = preprocess_schema_for_llm(schema)

        entries_items = result["properties"]["experience"]["properties"]["entries"]["items"]
        assert entries_items["additionalProperties"] is False

        bullets = entries_items["properties"]["bullets"]
        assert "x-show-item-labels" not in bullets
        assert "x-widget" not in bullets["items"]


class TestResumeSchemaIntegration:
    """Integration test with the actual resume schema structure."""

    @pytest.fixture
    def resume_schema_fragment(self) -> dict:
        """Minimal representative fragment of the resume schema."""
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "certifications": {
                    "type": "object",
                    "properties": {
                        "entries": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "Certification name",
                                        "x-llm-hint": "Use acronyms like CKA",
                                    }
                                },
                            },
                        }
                    },
                },
                "hobbies": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "x-llm-hint": "1-3 words max",
                                "x-widget": "input",
                            },
                            "x-show-item-labels": False,
                        }
                    },
                },
                "contact": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string", "format": "email"},
                    },
                },
            },
        }

    def test_all_transformations_applied(self, resume_schema_fragment: dict) -> None:
        result = preprocess_schema_for_llm(resume_schema_fragment)

        cert_entry = result["properties"]["certifications"]["properties"]["entries"]["items"]
        assert cert_entry["additionalProperties"] is False
        assert cert_entry["properties"]["name"]["description"] == "Certification name. Use acronyms like CKA"
        assert "x-llm-hint" not in cert_entry["properties"]["name"]

        hobby_items = result["properties"]["hobbies"]["properties"]["items"]
        assert "x-show-item-labels" not in hobby_items
        assert "x-widget" not in hobby_items["items"]
        assert hobby_items["items"]["description"] == "1-3 words max"

        email = result["properties"]["contact"]["properties"]["email"]
        assert "format" not in email

        assert result["properties"]["certifications"]["additionalProperties"] is False
        assert result["properties"]["hobbies"]["additionalProperties"] is False
        assert result["properties"]["contact"]["additionalProperties"] is False
