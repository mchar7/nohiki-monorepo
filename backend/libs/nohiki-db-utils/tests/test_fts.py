"""Tests for full-text search utilities."""

from __future__ import annotations

import pytest
from nohiki_db_utils.fts import build_prefix_tsquery


class TestBuildPrefixTsquery:
    """Tests for build_prefix_tsquery."""

    def test_single_word(self) -> None:
        assert build_prefix_tsquery("python") == "python:*"

    def test_multiple_words(self) -> None:
        assert build_prefix_tsquery("python kube") == "python:* & kube:*"

    def test_prefix_partial_word(self) -> None:
        """Verify partial words get :* appended for prefix matching."""
        assert build_prefix_tsquery("kube") == "kube:*"

    def test_empty_string(self) -> None:
        assert build_prefix_tsquery("") == ""

    def test_whitespace_only(self) -> None:
        assert build_prefix_tsquery("   ") == ""

    def test_special_characters_only(self) -> None:
        assert build_prefix_tsquery("!@#$%^&*()") == ""

    def test_mixed_special_and_alphanumeric(self) -> None:
        assert build_prefix_tsquery("python! @kube") == "python:* & kube:*"

    def test_numbers(self) -> None:
        assert build_prefix_tsquery("python3 k8s") == "python3:* & k8s:*"

    def test_sql_injection_attempt(self) -> None:
        """Ensure SQL injection is neutralized by stripping non-alphanumeric chars."""
        result = build_prefix_tsquery("'; DROP TABLE users; --")
        assert result == "DROP:* & TABLE:* & users:*"

    def test_tsquery_operator_injection(self) -> None:
        """Ensure tsquery operators in input are stripped."""
        result = build_prefix_tsquery("python & !kube | react")
        assert result == "python:* & kube:* & react:*"

    def test_single_character(self) -> None:
        assert build_prefix_tsquery("k") == "k:*"

    def test_tabs_and_newlines(self) -> None:
        assert build_prefix_tsquery("python\tkube\nreact") == "python:* & kube:* & react:*"

    def test_hyphenated_words(self) -> None:
        """Hyphens are stripped; each part becomes a separate term."""
        assert build_prefix_tsquery("full-stack") == "full:* & stack:*"

    @pytest.mark.parametrize(
        ("input_query", "expected"),
        [
            ("Python", "Python:*"),
            ("KUBERNETES", "KUBERNETES:*"),
            ("PyThOn KuBe", "PyThOn:* & KuBe:*"),
        ],
    )
    def test_preserves_case(self, input_query: str, expected: str) -> None:
        """Case is preserved; PostgreSQL to_tsquery handles normalization."""
        assert build_prefix_tsquery(input_query) == expected
