"""Tests for nohiki_kafka_client.utils.callback_state module."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from nohiki_kafka_client.utils.callback_state import CallbackStateMixin, _get_valid_field_names


@dataclass(frozen=True, slots=True)
class SampleState(CallbackStateMixin):
    """Test state for CallbackStateMixin tests."""

    entity_id: str
    action: str


@dataclass(frozen=True, slots=True)
class NestedState(CallbackStateMixin):
    """State with nested structures for roundtrip tests."""

    items: list[str]
    metadata: dict[str, str]
    optional_value: str | None = None


@dataclass(frozen=True, slots=True)
class EmptyState(CallbackStateMixin):
    """Degenerate state with no fields: edge case for caching."""


class TestCallbackStateMixin:
    """Tests for CallbackStateMixin serialization/deserialization."""

    def test_roundtrip(self) -> None:
        """to_bytes/from_bytes roundtrip preserves all fields."""
        state = SampleState(entity_id="abc-123", action="create")
        recovered = SampleState.from_bytes(state.to_bytes())

        assert recovered.entity_id == "abc-123"
        assert recovered.action == "create"

    def test_unknown_field_filtering(self) -> None:
        """Extra fields in JSON are silently ignored (defensive deserialization)."""
        data = json.dumps(
            {
                "entity_id": "abc-123",
                "action": "create",
                "future_field": "should_be_ignored",
            }
        ).encode("utf-8")

        state = SampleState.from_bytes(data)

        assert state.entity_id == "abc-123"
        assert state.action == "create"

    def test_missing_field_raises_type_error(self) -> None:
        """Missing required fields raise TypeError."""
        data = json.dumps({"entity_id": "abc-123"}).encode("utf-8")

        with pytest.raises(TypeError):
            SampleState.from_bytes(data)

    def test_empty_bytes_raises_json_decode_error(self) -> None:
        """Empty bytes raise JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            SampleState.from_bytes(b"")

    def test_invalid_json_raises_json_decode_error(self) -> None:
        """Non-JSON bytes raise JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            SampleState.from_bytes(b"not json")

    def test_unicode_handling(self) -> None:
        """Non-ASCII text survives roundtrip."""
        state = SampleState(entity_id="日本語テスト", action="作成")
        recovered = SampleState.from_bytes(state.to_bytes())

        assert recovered.entity_id == "日本語テスト"
        assert recovered.action == "作成"

    def test_nested_structures(self) -> None:
        """Lists, dicts, and None values survive roundtrip."""
        state = NestedState(
            items=["a", "b", "c"],
            metadata={"key": "value"},
            optional_value=None,
        )
        recovered = NestedState.from_bytes(state.to_bytes())

        assert recovered.items == ["a", "b", "c"]
        assert recovered.metadata == {"key": "value"}
        assert recovered.optional_value is None

    def test_nested_with_optional_value(self) -> None:
        """Optional fields with values survive roundtrip."""
        state = NestedState(
            items=[],
            metadata={},
            optional_value="present",
        )
        recovered = NestedState.from_bytes(state.to_bytes())

        assert recovered.optional_value == "present"

    def test_to_bytes_returns_bytes(self) -> None:
        """to_bytes returns bytes, not str."""
        state = SampleState(entity_id="test", action="update")
        result = state.to_bytes()

        assert isinstance(result, bytes)

    def test_serialized_json_is_valid(self) -> None:
        """Serialized bytes are valid UTF-8 JSON."""
        state = SampleState(entity_id="test", action="delete")
        raw = state.to_bytes()
        parsed = json.loads(raw.decode("utf-8"))

        assert parsed["entity_id"] == "test"
        assert parsed["action"] == "delete"

    def test_empty_dataclass_roundtrip(self) -> None:
        """Dataclass with no fields serializes to {} and deserializes correctly."""
        state = EmptyState()
        recovered = EmptyState.from_bytes(state.to_bytes())

        assert isinstance(recovered, EmptyState)

    def test_empty_dataclass_bytes_are_empty_json_object(self) -> None:
        """Dataclass with no fields serializes to b'{}'."""
        state = EmptyState()
        assert state.to_bytes() == b"{}"


class TestGetValidFieldNamesCache:
    """Tests for the _get_valid_field_names lru_cache helper."""

    def test_returns_correct_field_names(self) -> None:
        """Returns frozenset of field names for a dataclass."""
        result = _get_valid_field_names(SampleState)

        assert result == frozenset({"entity_id", "action"})

    def test_cache_hit_returns_same_object(self) -> None:
        """Second call returns the identical frozenset object (cache hit)."""
        first = _get_valid_field_names(SampleState)
        second = _get_valid_field_names(SampleState)

        assert first is second

    def test_empty_dataclass_returns_empty_frozenset(self) -> None:
        """Dataclass with no fields returns an empty frozenset."""
        result = _get_valid_field_names(EmptyState)

        assert result == frozenset()

    def test_different_classes_cached_independently(self) -> None:
        """Different dataclasses get independently cached results."""
        sample = _get_valid_field_names(SampleState)
        nested = _get_valid_field_names(NestedState)

        assert sample != nested
        assert "items" in nested
        assert "items" not in sample
