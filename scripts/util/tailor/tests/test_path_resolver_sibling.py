"""Tests for sibling document path resolution in path_resolver.

Tests cover the sibling.<name>.<path> prefix support in resolve_glob_path.
"""

from __future__ import annotations

from typing import cast

import pytest
from tailor.lint.content.rules.path_resolver import resolve_glob_path
from tailor.lint.runtime import LintRuntimeContext


class TestSiblingPathResolution:
    """Tests for sibling.<name>.<path> path resolution."""

    def test_resolve_sibling_with_subpath(self) -> None:
        """resolve_glob_path resolves sibling.<name>.<subpath> correctly."""
        sibling_data = cast("dict[str, object]", {"experience": [{"title": "Engineer", "years": 5}]})
        runtime = LintRuntimeContext(sibling_documents={"reference": sibling_data})

        result = resolve_glob_path({}, "sibling.reference.experience", runtime)

        assert len(result) == 1
        concrete_path, items = result[0]
        assert concrete_path == "sibling.reference.experience"
        assert items == [{"title": "Engineer", "years": 5}]

    def test_resolve_sibling_bare_name_without_subpath(self) -> None:
        """resolve_glob_path resolves bare sibling.<name> to sibling root."""
        sibling_data = cast("dict[str, object]", {"name": "Alice", "skills": ["Python", "Go"]})
        runtime = LintRuntimeContext(sibling_documents={"reference": sibling_data})

        result = resolve_glob_path({}, "sibling.reference", runtime)

        assert len(result) == 1
        concrete_path, items = result[0]
        assert concrete_path == "sibling.reference"
        assert items == [sibling_data]

    def test_resolve_sibling_with_wildcard_expansion(self) -> None:
        """resolve_glob_path resolves sibling.<name>.<path[*]> with wildcard."""
        sibling_data = cast(
            "dict[str, object]",
            {
                "experience": {
                    "entries": [
                        {"title": "Engineer", "items": ["Built X", "Led Y"]},
                        {"title": "Manager", "items": ["Managed team"]},
                    ]
                }
            },
        )
        runtime = LintRuntimeContext(sibling_documents={"reference": sibling_data})

        result = resolve_glob_path({}, "sibling.reference.experience.entries[*].items", runtime)

        assert len(result) == 2
        assert result[0][0] == "sibling.reference.experience.entries[0].items"
        assert result[0][1] == ["Built X", "Led Y"]
        assert result[1][0] == "sibling.reference.experience.entries[1].items"
        assert result[1][1] == ["Managed team"]

    def test_resolve_sibling_missing_name_raises_key_error(self) -> None:
        """resolve_glob_path raises KeyError when sibling name not loaded."""
        runtime = LintRuntimeContext(sibling_documents={"reference": {"name": "Alice"}})

        with pytest.raises(KeyError, match=r"Sibling.*not loaded"):
            resolve_glob_path({}, "sibling.missing.path", runtime)

    def test_resolve_sibling_requires_runtime_context(self) -> None:
        """resolve_glob_path raises KeyError when runtime is None for sibling path."""
        with pytest.raises(KeyError, match="requires a runtime context"):
            resolve_glob_path({}, "sibling.reference.path", runtime=None)

    def test_resolve_sibling_path_with_index_notation(self) -> None:
        """resolve_glob_path exposes an indexed sibling element as a singleton scope."""
        sibling_data = cast("dict[str, object]", {"items": [{"name": "A"}, {"name": "B"}, {"name": "C"}]})
        runtime = LintRuntimeContext(sibling_documents={"data": sibling_data})

        # An indexed access (items[1]) surfaces the second element as a one-item scope,
        # mirroring the primary-document primitive/dict wrapping semantics.
        result = resolve_glob_path({}, "sibling.data.items[1]", runtime)
        assert result == [("sibling.data.items[1]", [{"name": "B"}])]

        # The full list path still emits list-as-items:
        result_list = resolve_glob_path({}, "sibling.data.items", runtime)
        assert len(result_list) == 1
        assert result_list[0][1] == [{"name": "A"}, {"name": "B"}, {"name": "C"}]

    def test_primary_document_paths_still_work(self) -> None:
        """resolve_glob_path still works for primary document paths without sibling prefix."""
        data = cast("dict[str, object]", {"items": [1, 2, 3]})
        runtime = LintRuntimeContext(sibling_documents={"reference": cast("dict[str, object]", {"other": "data"})})

        result = resolve_glob_path(data, "items", runtime)

        assert len(result) == 1
        concrete_path, items = result[0]
        assert concrete_path == "$.items"
        assert items == [1, 2, 3]

    def test_multiple_siblings_loaded(self) -> None:
        """resolve_glob_path works when multiple siblings are loaded."""
        primary_data = cast("dict[str, object]", {})
        runtime = LintRuntimeContext(
            sibling_documents={
                "reference": cast("dict[str, object]", {"experience": [{"role": "Engineer"}]}),
                "primary": cast("dict[str, object]", {"body": "Dear hiring manager..."}),
                "references": cast("dict[str, object]", {"contacts": [{"name": "John"}]}),
            }
        )

        # Resolve from reference
        result_reference = resolve_glob_path(primary_data, "sibling.reference.experience", runtime)
        assert result_reference[0][0] == "sibling.reference.experience"
        assert result_reference[0][1] == [{"role": "Engineer"}]

        # Resolve from references
        result_refs = resolve_glob_path(primary_data, "sibling.references.contacts", runtime)
        assert result_refs[0][0] == "sibling.references.contacts"
        assert result_refs[0][1] == [{"name": "John"}]

    def test_sibling_path_with_nested_objects(self) -> None:
        """resolve_glob_path resolves deeply nested sibling paths."""
        sibling_data = cast(
            "dict[str, object]",
            {
                "profile": {
                    "contact": {
                        "emails": [
                            {"type": "work", "address": "test@company.com"},
                            {"type": "personal", "address": "test@gmail.com"},
                        ]
                    }
                }
            },
        )
        runtime = LintRuntimeContext(sibling_documents={"reference": sibling_data})

        result = resolve_glob_path({}, "sibling.reference.profile.contact.emails", runtime)

        assert len(result) == 1
        concrete_path, items = result[0]
        assert concrete_path == "sibling.reference.profile.contact.emails"
        assert len(items) == 2
        item_obj = cast("dict[str, object]", items[0])
        assert item_obj["type"] == "work"

    def test_sibling_missing_subpath_returns_empty(self) -> None:
        """resolve_glob_path returns empty when sibling subpath doesn't exist."""
        sibling_data = cast("dict[str, object]", {"name": "Alice"})
        runtime = LintRuntimeContext(sibling_documents={"reference": sibling_data})

        result = resolve_glob_path({}, "sibling.reference.nonexistent", runtime)

        assert result == []

    def test_sibling_nonlist_value_wraps_in_singleton(self) -> None:
        """resolve_glob_path exposes a sibling primitive as a one-item scope."""
        sibling_data = cast("dict[str, object]", {"name": "Alice"})  # scalar, not a list
        runtime = LintRuntimeContext(sibling_documents={"reference": sibling_data})

        result = resolve_glob_path({}, "sibling.reference.name", runtime)

        assert result == [("sibling.reference.name", ["Alice"])]

    def test_sibling_root_resolves_to_one_item_list(self) -> None:
        """resolve_glob_path resolves bare sibling.<name> to one-item list containing sibling root."""
        sibling_data = cast("dict[str, object]", {"key1": "value1", "key2": "value2"})
        runtime = LintRuntimeContext(sibling_documents={"data": sibling_data})

        result = resolve_glob_path({}, "sibling.data", runtime)

        assert len(result) == 1
        concrete_path, items = result[0]
        assert concrete_path == "sibling.data"
        assert len(items) == 1
        assert items[0] is sibling_data

    def test_sibling_with_wildcard_then_missing_child(self) -> None:
        """resolve_glob_path handles missing child keys in wildcard expansion over siblings."""
        sibling_data = cast(
            "dict[str, object]",
            {
                "entries": [
                    {"id": "1", "tags": ["a", "b"]},
                    {"id": "2"},  # Missing 'tags' key
                    {"id": "3", "tags": ["c"]},
                ]
            },
        )
        runtime = LintRuntimeContext(sibling_documents={"reference": sibling_data})

        result = resolve_glob_path({}, "sibling.reference.entries[*].tags", runtime)

        # Should emit (path, []) for entry with missing tags
        assert len(result) == 3
        assert result[0][1] == ["a", "b"]
        assert result[1][1] == []  # Missing key → empty list
        assert result[2][1] == ["c"]

    def test_error_message_includes_available_siblings(self) -> None:
        """resolve_glob_path error message lists available sibling names."""
        runtime = LintRuntimeContext(sibling_documents={"reference": {}, "letter": {}})

        with pytest.raises(KeyError) as exc_info:
            resolve_glob_path({}, "sibling.missing.path", runtime)

        error_msg = str(exc_info.value)
        assert "reference" in error_msg
        assert "letter" in error_msg
