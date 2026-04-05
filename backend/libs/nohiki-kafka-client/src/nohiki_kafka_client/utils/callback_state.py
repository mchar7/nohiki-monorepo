"""Mixin for frozen dataclasses that serialize to/from bytes for ECST caller_context."""

from __future__ import annotations

import dataclasses
import functools
import json
from typing import Self


@functools.cache
def _get_valid_field_names(cls: type) -> frozenset[str]:
    """Return the frozenset of field names for a dataclass, cached per class.

    Frozen dataclasses never change shape, so caching permanently is safe and correct.
    """
    return frozenset(f.name for f in dataclasses.fields(cls))


class CallbackStateMixin:
    """JSON serialization mixin for ECST callback state dataclasses.

    Defensive deserialization: ignores unknown fields in the serialized data,
    allowing safe evolution of state schemas across deployments.

    Usage:
        @dataclass(frozen=True, slots=True)
        class MyCallbackState(CallbackStateMixin):
            entity_id: str
            action: str

        state = MyCallbackState(entity_id="...", action="create")
        caller_context_bytes = state.to_bytes()
        recovered = MyCallbackState.from_bytes(message.callback.caller_context)

    """

    def to_bytes(self) -> bytes:
        """Serialize this state to JSON bytes for ``caller_context``."""
        if not dataclasses.is_dataclass(self):
            msg = f"{type(self).__name__} must be decorated with @dataclass"
            raise TypeError(msg)
        fields = dataclasses.fields(self)
        payload = {field.name: getattr(self, field.name) for field in fields}
        return json.dumps(payload).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        """Deserialize JSON bytes from ``caller_context`` to a typed state instance.

        Args:
            data: JSON bytes from the callback message's ``caller_context`` field.

        Returns:
            Typed state instance with all fields populated.

        Raises:
            json.JSONDecodeError: If data is not valid JSON.
            TypeError: If required fields are missing after filtering.

        """
        parsed = json.loads(data.decode("utf-8"))
        valid_field_names = _get_valid_field_names(cls)
        filtered = {k: v for k, v in parsed.items() if k in valid_field_names}
        return cls(**filtered)
