"""Tests for nohiki_kafka_client.utils.callback_utils module."""

from __future__ import annotations

from nohiki.common.v1 import CallbackHeader, CommandHeader
from nohiki_kafka_client import CommandContext, callback_from_command


class TestCallbackFromCommand:
    """Tests for callback_from_command utility."""

    def test_echoes_operation_id(self) -> None:
        """Operation ID is echoed unchanged from command to callback."""
        cmd = CommandHeader(
            operation_id="550e8400-e29b-41d4-a716-446655440000",
            callback_topic="test.sys.callback.v1",
        )
        cb = callback_from_command(cmd)

        assert cb.operation_id == "550e8400-e29b-41d4-a716-446655440000"

    def test_echoes_caller_context(self) -> None:
        """Caller context bytes are echoed unchanged."""
        context_bytes = b'{"pref_id": "abc", "action": "create"}'
        cmd = CommandHeader(
            operation_id="550e8400-e29b-41d4-a716-446655440000",
            callback_topic="test.sys.callback.v1",
            caller_context=context_bytes,
        )
        cb = callback_from_command(cmd)

        assert cb.caller_context == context_bytes

    def test_echoes_attributes(self) -> None:
        """Attributes map is echoed unchanged."""
        attrs = {"embedding_role": "retrieval", "version": "v1"}
        cmd = CommandHeader(
            operation_id="550e8400-e29b-41d4-a716-446655440000",
            callback_topic="test.sys.callback.v1",
            attributes=attrs,
        )
        cb = callback_from_command(cmd)

        assert cb.attributes == attrs

    def test_empty_caller_context(self) -> None:
        """Empty caller_context echoes as empty bytes."""
        cmd = CommandHeader(
            operation_id="550e8400-e29b-41d4-a716-446655440000",
            callback_topic="test.sys.callback.v1",
            caller_context=b"",
        )
        cb = callback_from_command(cmd)

        assert cb.caller_context == b""

    def test_empty_attributes(self) -> None:
        """Empty attributes echoes as empty dict."""
        cmd = CommandHeader(
            operation_id="550e8400-e29b-41d4-a716-446655440000",
            callback_topic="test.sys.callback.v1",
        )
        cb = callback_from_command(cmd)

        assert cb.attributes == {}

    def test_callback_does_not_include_callback_topic(self) -> None:
        """CallbackHeader structurally cannot contain callback_topic."""
        cmd = CommandHeader(
            operation_id="550e8400-e29b-41d4-a716-446655440000",
            callback_topic="test.sys.callback.v1",
        )
        cb = callback_from_command(cmd)

        assert not hasattr(cb, "callback_topic")

    def test_returns_callback_header_type(self) -> None:
        """Return type is CallbackHeader, not CommandHeader."""
        cmd = CommandHeader(
            operation_id="550e8400-e29b-41d4-a716-446655440000",
            callback_topic="test.sys.callback.v1",
        )
        cb = callback_from_command(cmd)

        assert isinstance(cb, CallbackHeader)


class TestCommandContext:
    """Tests for CommandContext dataclass."""

    def test_defaults(self) -> None:
        """Default CommandContext has empty caller_context and attributes."""
        ctx = CommandContext()

        assert ctx.caller_context == b""
        assert ctx.attributes == {}

    def test_custom_values(self) -> None:
        """CommandContext preserves custom caller_context and attributes."""
        ctx = CommandContext(
            caller_context=b"test-bytes",
            attributes={"key": "value"},
        )

        assert ctx.caller_context == b"test-bytes"
        assert ctx.attributes == {"key": "value"}

    def test_frozen(self) -> None:
        """CommandContext is immutable."""
        import dataclasses

        assert dataclasses.is_dataclass(CommandContext)
        params = getattr(CommandContext, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True
