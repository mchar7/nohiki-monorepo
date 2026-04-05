"""Utilities for the command/callback pattern over Kafka."""

from __future__ import annotations

from dataclasses import dataclass, field

from nohiki.common.v1 import CallbackHeader, CommandHeader


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Transport-level context for command/callback messages.

    Bundles ``caller_context`` (opaque domain state) and ``attributes``
    (key-value metadata) that are echoed unchanged in callbacks.
    Keeps publisher method signatures under the PLR0913 argument limit.

    """

    caller_context: bytes = b""
    attributes: dict[str, str] = field(default_factory=dict)


def callback_from_command(command: CommandHeader) -> CallbackHeader:
    """Build a CallbackHeader by echoing fields from a CommandHeader.

    Used by every responder when building callback messages.

    Args:
        command: The CommandHeader from the incoming request.

    Returns:
        CallbackHeader with operation_id, caller_context, and attributes echoed.

    """
    return CallbackHeader(
        operation_id=command.operation_id,
        caller_context=command.caller_context,
        attributes=dict(command.attributes) if command.attributes else {},
    )
