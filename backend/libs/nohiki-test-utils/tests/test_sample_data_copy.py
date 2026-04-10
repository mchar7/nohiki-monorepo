"""Tests for sample_data._copy module."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from nohiki_test_utils.sample_data._copy import copy_with


@dataclass(frozen=True, slots=True)
class SampleDataclass:
    """Test dataclass for copy_with testing."""

    field_a: str
    field_b: int
    field_c: bool = True


class TestCopyWith:
    """Tests for copy_with function."""

    def test_copy_with_single_override(self) -> None:
        """Copy with single field override."""
        original = SampleDataclass(field_a="original", field_b=42)
        copied = copy_with(original, field_a="modified")
        assert copied.field_a == "modified"
        assert copied.field_b == 42
        assert copied.field_c is True

    def test_copy_with_multiple_overrides(self) -> None:
        """Copy with multiple field overrides."""
        original = SampleDataclass(field_a="original", field_b=42, field_c=True)
        copied = copy_with(original, field_a="modified", field_b=100, field_c=False)
        assert copied.field_a == "modified"
        assert copied.field_b == 100
        assert copied.field_c is False

    def test_copy_with_no_overrides(self) -> None:
        """Copy with no overrides creates identical instance."""
        original = SampleDataclass(field_a="original", field_b=42)
        copied = copy_with(original)
        assert copied.field_a == original.field_a
        assert copied.field_b == original.field_b
        assert copied.field_c == original.field_c

    def test_copy_with_creates_new_instance(self) -> None:
        """Copy creates a new instance, not a reference."""
        original = SampleDataclass(field_a="original", field_b=42)
        copied = copy_with(original, field_a="modified")
        assert copied is not original
        assert original.field_a == "original"
        assert copied.field_a == "modified"

    def test_copy_with_rejects_non_dataclass_instance(self) -> None:
        """Reject non-dataclass values early with a clear error."""
        with pytest.raises(TypeError, match="Expected dataclass instance, got int"):
            copy_with(123)
