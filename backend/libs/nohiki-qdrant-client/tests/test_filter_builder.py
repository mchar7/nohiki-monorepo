"""Tests for Qdrant filter builder."""

from __future__ import annotations

from datetime import UTC, datetime

from nohiki_qdrant_client import build_filter, build_filter_with_should


class TestBuildFilter:
    """Tests for build_filter function."""

    def test_boolean_filter(self) -> None:
        """Test boolean value filter."""
        result = build_filter({"is_active": True})
        assert isinstance(result.must, list)
        assert len(result.must) == 1

    def test_string_filter(self) -> None:
        """Test string value filter."""
        result = build_filter({"job_type": "full_time"})
        assert isinstance(result.must, list)
        assert len(result.must) == 1

    def test_integer_filter(self) -> None:
        """Test integer value filter."""
        result = build_filter({"priority": 5})
        assert isinstance(result.must, list)
        assert len(result.must) == 1

    def test_list_filter(self) -> None:
        """Test list value filter (MatchAny)."""
        result = build_filter({"company": ["Google", "Meta", "Apple"]})
        assert isinstance(result.must, list)
        assert len(result.must) == 1

    def test_empty_list_filter(self) -> None:
        """Test empty list is ignored."""
        result = build_filter({"company": []})
        assert result.must == []

    def test_none_value_ignored(self) -> None:
        """Test None values are ignored."""
        result = build_filter({"field": None})
        assert result.must == []

    def test_range_filter_gt(self) -> None:
        """Test greater than range filter."""
        result = build_filter({"salary": {"$gt": 50000}})
        assert isinstance(result.must, list)
        assert len(result.must) == 1

    def test_range_filter_gte_lte(self) -> None:
        """Test range filter with both bounds."""
        result = build_filter({"salary": {"$gte": 50000, "$lte": 100000}})
        assert isinstance(result.must, list)
        assert len(result.must) == 1

    def test_range_filter_datetime(self) -> None:
        """Test datetime range filter."""
        result = build_filter({"posted_at": {"$gte": datetime(2024, 1, 1, tzinfo=UTC)}})
        assert isinstance(result.must, list)
        assert len(result.must) == 1

    def test_multiple_filters(self) -> None:
        """Test multiple filters combined."""
        result = build_filter({"is_active": True, "job_type": "full_time"})
        assert isinstance(result.must, list)
        assert len(result.must) == 2

    def test_invalid_range_operator(self) -> None:
        """Test invalid range operator is ignored."""
        result = build_filter({"field": {"$invalid": 100}})
        assert result.must == []

    def test_float_value_cast_to_int(self) -> None:
        """Test float values are cast to int for MatchValue."""
        result = build_filter({"score": 0.5})
        assert isinstance(result.must, list)
        assert len(result.must) == 1

    def test_empty_range_dict_returns_no_condition(self) -> None:
        """Test empty operator dict produces no filter condition."""
        result = build_filter({"field": {}})
        assert result.must == []

    def test_unconvertible_range_value_is_skipped(self) -> None:
        """Test a range value that cannot be cast to float is silently skipped."""
        result = build_filter({"field": {"$gt": "not-a-number"}})
        assert result.must == []


class TestBuildFilterWithShould:
    """Tests for build_filter_with_should function."""

    def test_must_only(self) -> None:
        """Test with only must filters."""
        result = build_filter_with_should(must_filters={"is_active": True})
        assert isinstance(result.must, list)
        assert len(result.must) == 1
        assert result.should is None
        assert result.must_not is None

    def test_should_only(self) -> None:
        """Test with only should filters."""
        result = build_filter_with_should(should_filters=[{"company": "Google"}, {"company": "Meta"}])
        assert result.must is None
        assert isinstance(result.should, list)
        assert len(result.should) == 2
        assert result.must_not is None

    def test_must_not_only(self) -> None:
        """Test with only must_not filters."""
        result = build_filter_with_should(must_not_filters={"is_active": False})
        assert result.must is None
        assert result.should is None
        assert isinstance(result.must_not, list)
        assert len(result.must_not) == 1

    def test_all_filter_types(self) -> None:
        """Test with all filter types."""
        result = build_filter_with_should(
            must_filters={"is_active": True},
            should_filters=[{"company": "Google"}],
            must_not_filters={"job_type": "contract"},
        )
        assert result.must is not None
        assert result.should is not None
        assert result.must_not is not None

    def test_empty_filters(self) -> None:
        """Test with no filters."""
        result = build_filter_with_should()
        assert result.must is None
        assert result.should is None
        assert result.must_not is None
