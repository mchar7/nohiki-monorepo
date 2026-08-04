"""Tests for tailor.lint.content.rules.path_resolver."""

from __future__ import annotations

from tailor.lint.content.rules.path_resolver import navigate, resolve_glob_path, resolve_glob_paths


class TestNavigate:
    """Tests for navigate()."""

    def test_simple_key(self) -> None:
        assert navigate({"a": 1}, "a") == 1

    def test_nested_keys(self) -> None:
        assert navigate({"a": {"b": 2}}, "a.b") == 2

    def test_missing_key_returns_none(self) -> None:
        assert navigate({"a": 1}, "b") is None

    def test_index_notation(self) -> None:
        assert navigate({"items": [10, 20]}, "items[0]") == 10
        assert navigate({"items": [10, 20]}, "items[1]") == 20

    def test_index_out_of_range_returns_none(self) -> None:
        assert navigate({"items": [10]}, "items[5]") is None

    def test_deep_path(self) -> None:
        data = {"a": {"b": [{"c": 3}]}}
        assert navigate(data, "a.b[0].c") == 3

    def test_non_dict_intermediate_returns_none(self) -> None:
        assert navigate({"a": "string"}, "a.b") is None

    def test_empty_path_returns_data(self) -> None:
        data = {"a": 1}
        assert navigate(data, "") is data

    def test_none_intermediate_returns_none(self) -> None:
        assert navigate({"a": None}, "a.b") is None

    def test_list_at_root(self) -> None:
        assert navigate([1, 2, 3], "") == [1, 2, 3]


class TestResolveGlobPath:
    """Tests for resolve_glob_path()."""

    def test_no_wildcard_value_is_list(self) -> None:
        data = {"items": [1, 2, 3]}
        result = resolve_glob_path(data, "items")
        assert result == [("$.items", [1, 2, 3])]

    def test_no_wildcard_primitive_value_wraps_in_singleton(self) -> None:
        """A concrete path to a primitive (e.g. items[1]) exposes the value as a singleton scope."""
        data = {"name": "Alice"}
        assert resolve_glob_path(data, "name") == [("$.name", ["Alice"])]

    def test_no_wildcard_dict_value_wraps_in_singleton(self) -> None:
        """A concrete path to a dict exposes the mapping as a singleton scope."""
        data = {"meta": {"owner": "Alice"}}
        assert resolve_glob_path(data, "meta") == [("$.meta", [{"owner": "Alice"}])]

    def test_no_wildcard_indexed_access_to_list_element(self) -> None:
        """``items[1]`` exposes the indexed element as a singleton scope."""
        data = {"items": ["p0", "p1", "p2"]}
        assert resolve_glob_path(data, "items[1]") == [("$.items[1]", ["p1"])]

    def test_no_wildcard_missing_path(self) -> None:
        assert resolve_glob_path({"a": 1}, "b") == []

    def test_wildcard_expands_entries(self) -> None:
        data = {
            "records": {
                "entries": [
                    {"items": ["Did X", "Did Y"]},
                    {"items": ["Led A"]},
                ]
            }
        }
        result = resolve_glob_path(data, "records.entries[*].items")
        assert result == [
            ("$.records.entries[0].items", ["Did X", "Did Y"]),
            ("$.records.entries[1].items", ["Led A"]),
        ]

    def test_wildcard_no_suffix_item_is_list(self) -> None:
        data = {"matrix": [[1, 2], [3, 4]]}
        result = resolve_glob_path(data, "matrix[*]")
        assert result == [
            ("$.matrix[0]", [1, 2]),
            ("$.matrix[1]", [3, 4]),
        ]

    def test_wildcard_no_suffix_items_are_primitives(self) -> None:
        """list-of-primitives (e.g. items) expands one item per index."""
        data = {"items": ["First item.", "Second item."]}
        result = resolve_glob_path(data, "items[*]")
        assert result == [
            ("$.items[0]", ["First item."]),
            ("$.items[1]", ["Second item."]),
        ]

    def test_wildcard_no_suffix_items_are_dicts(self) -> None:
        """Dict items are exposed so downstream rules (e.g. section structure) can inspect them."""
        data = {"entries": [{"name": "A"}, {"name": "B"}]}
        result = resolve_glob_path(data, "entries[*]")
        assert result == [
            ("$.entries[0]", [{"name": "A"}]),
            ("$.entries[1]", [{"name": "B"}]),
        ]

    def test_missing_child_key_emits_empty_list(self) -> None:
        """Missing child key on a dict item emits (path, []) -- critical for min_items."""
        data = {"items": [{"name": "A"}, {"name": "B"}]}
        result = resolve_glob_path(data, "items[*].missing_key")
        assert result == [
            ("$.items[0].missing_key", []),
            ("$.items[1].missing_key", []),
        ]

    def test_prefix_not_list_returns_empty(self) -> None:
        data = {"experience": "not a list"}
        assert resolve_glob_path(data, "experience[*].bullets") == []

    def test_non_dict_items_skipped(self) -> None:
        data = {"items": ["string", 42, None]}
        result = resolve_glob_path(data, "items[*].child")
        assert result == []

    def test_simple_path_to_nested_list(self) -> None:
        data = {"skills": {"categories": [{"name": "A"}, {"name": "B"}]}}
        result = resolve_glob_path(data, "skills.categories")
        assert result == [("$.skills.categories", [{"name": "A"}, {"name": "B"}])]

    def test_mixed_present_and_missing_children(self) -> None:
        """Items where child exists as list vs missing produce different results."""
        data = {
            "entries": [
                {"bullets": ["a", "b"]},
                {"other": "x"},  # missing 'bullets'
            ]
        }
        result = resolve_glob_path(data, "entries[*].bullets")
        assert result == [
            ("$.entries[0].bullets", ["a", "b"]),
            ("$.entries[1].bullets", []),  # dict item, missing key → empty list
        ]


class TestResolveGlobPaths:
    """Tests for resolve_glob_paths()."""

    def test_empty_paths_returns_empty(self) -> None:
        assert resolve_glob_paths({"a": 1}, []) == []

    def test_single_path_delegates(self) -> None:
        data = {"items": [1, 2]}
        result = resolve_glob_paths(data, ["items"])
        assert result == [("$.items", [1, 2])]

    def test_multiple_paths_concatenated(self) -> None:
        data = {"a": [1, 2], "b": [3, 4]}
        result = resolve_glob_paths(data, ["a", "b"])
        assert result == [("$.a", [1, 2]), ("$.b", [3, 4])]

    def test_order_preserved(self) -> None:
        data = {"x": [1], "y": [2], "z": [3]}
        result = resolve_glob_paths(data, ["z", "x", "y"])
        assert [r[0] for r in result] == ["$.z", "$.x", "$.y"]
