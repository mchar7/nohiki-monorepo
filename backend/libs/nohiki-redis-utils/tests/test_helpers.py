"""Tests for cache helper utilities."""

from __future__ import annotations

from uuid import UUID

from nohiki_redis_utils.helpers import hash_dict, make_cache_key, sanitize_cache_value


class TestMakeCacheKey:
    """Tests for make_cache_key function."""

    def test_simple_parts(self) -> None:
        """Test with simple string parts."""
        result = make_cache_key("user", "profile", "123")
        assert result == "user:profile:123"

    def test_with_uuid(self) -> None:
        """Test with UUID part."""
        test_uuid = UUID("550e8400-e29b-41d4-a716-446655440000")
        result = make_cache_key("user", test_uuid)
        assert result == "user:550e8400-e29b-41d4-a716-446655440000"

    def test_with_int(self) -> None:
        """Test with integer part."""
        result = make_cache_key("page", 42)
        assert result == "page:42"

    def test_with_kwargs(self) -> None:
        """Test with keyword arguments."""
        result = make_cache_key("search", query="test", limit=10)
        assert "query=test" in result
        assert "limit=10" in result

    def test_kwargs_sorted(self) -> None:
        """Test kwargs are sorted for deterministic keys."""
        result1 = make_cache_key("search", z_param="z", a_param="a")
        result2 = make_cache_key("search", a_param="a", z_param="z")
        assert result1 == result2

    def test_none_kwargs_excluded(self) -> None:
        """Test None kwargs are excluded."""
        result = make_cache_key("search", query="test", filter=None)
        assert "filter" not in result
        assert "query=test" in result


class TestHashDict:
    """Tests for hash_dict function."""

    def test_simple_dict(self) -> None:
        """Test hashing a simple dict."""
        result = hash_dict({"key": "value"})
        assert len(result) == 64  # SHA256 hex length

    def test_deterministic(self) -> None:
        """Test hash is deterministic."""
        data = {"a": 1, "b": 2}
        result1 = hash_dict(data)
        result2 = hash_dict(data)
        assert result1 == result2

    def test_key_order_independent(self) -> None:
        """Test hash is independent of key order."""
        result1 = hash_dict({"a": 1, "b": 2})
        result2 = hash_dict({"b": 2, "a": 1})
        assert result1 == result2

    def test_different_dicts_different_hash(self) -> None:
        """Test different dicts produce different hashes."""
        result1 = hash_dict({"key": "value1"})
        result2 = hash_dict({"key": "value2"})
        assert result1 != result2


class TestSanitizeCacheValue:
    """Tests for sanitize_cache_value function."""

    def test_none(self) -> None:
        """Test None value."""
        assert sanitize_cache_value(None) is None

    def test_string(self) -> None:
        """Test string value."""
        assert sanitize_cache_value("test") == "test"

    def test_int(self) -> None:
        """Test int value."""
        assert sanitize_cache_value(42) == 42

    def test_float(self) -> None:
        """Test float value."""
        result = sanitize_cache_value(3.14)
        assert isinstance(result, float)
        assert abs(result - 3.14) < 0.01

    def test_bool(self) -> None:
        """Test bool value."""
        true_value = True
        false_value = False
        assert sanitize_cache_value(true_value) is True
        assert sanitize_cache_value(false_value) is False

    def test_uuid(self) -> None:
        """Test UUID value."""
        test_uuid = UUID("550e8400-e29b-41d4-a716-446655440000")
        result = sanitize_cache_value(test_uuid)
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_dict(self) -> None:
        """Test dict value."""
        result = sanitize_cache_value({"key": "value", "num": 42})
        assert result == {"key": "value", "num": 42}

    def test_nested_dict(self) -> None:
        """Test nested dict value."""
        result = sanitize_cache_value({"outer": {"inner": "value"}})
        assert result == {"outer": {"inner": "value"}}

    def test_list(self) -> None:
        """Test list value."""
        result = sanitize_cache_value([1, 2, 3])
        assert result == [1, 2, 3]

    def test_tuple(self) -> None:
        """Test tuple value (converted to list)."""
        result = sanitize_cache_value((1, 2, 3))
        assert result == [1, 2, 3]

    def test_custom_object(self) -> None:
        """Test custom object is converted to string."""

        class CustomObj:
            def __str__(self) -> str:
                return "custom_string"

        result = sanitize_cache_value(CustomObj())
        assert result == "custom_string"

    def test_dict_with_uuid_values(self) -> None:
        """Test dict with UUID values."""
        test_uuid = UUID("550e8400-e29b-41d4-a716-446655440000")
        result = sanitize_cache_value({"id": test_uuid})
        assert result == {"id": "550e8400-e29b-41d4-a716-446655440000"}
