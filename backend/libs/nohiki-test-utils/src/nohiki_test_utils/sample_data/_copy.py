"""Copy helpers for betterproto dataclass instances."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import cast


def copy_with[T](instance: T, /, **overrides: object) -> T:
    """Return a dataclass copy with selected field overrides.

    Args:
        instance: Dataclass-based instance to copy.
        **overrides: Field overrides applied to the cloned object.

    Returns:
        A new instance with override values applied.
    """
    if not is_dataclass(instance):
        msg = f"Expected dataclass instance, got {type(instance).__name__}"
        raise TypeError(msg)

    values = {field.name: getattr(instance, field.name) for field in fields(instance)}
    return cast("T", type(instance)(**(values | overrides)))
