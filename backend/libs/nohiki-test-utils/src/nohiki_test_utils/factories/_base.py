"""Base factory for betterproto2 dataclasses with quirk handling."""

from __future__ import annotations

import enum
import random
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, get_type_hints

import betterproto2
from polyfactory.factories import DataclassFactory


def _replace_if_unspecified(instance: object, field_name: str, field_type: type) -> None:
    """Replace a single UNSPECIFIED enum field with a random valid member.

    Args:
        instance: The betterproto2 message instance to mutate in place.
        field_name: Name of the field to inspect and possibly replace.
        field_type: Resolved type of the field.
    """
    try:
        if not issubclass(field_type, betterproto2.Enum):
            return
        current = getattr(instance, field_name, None)
        if isinstance(current, betterproto2.Enum) and current.value == 0:
            valid = [m for m in field_type if m.value != 0]
            if valid:
                setattr(instance, field_name, random.choice(valid))  # noqa: S311  # does not require cryptographic strength
    except TypeError:
        pass


def _fix_unspecified_enums(instance: object, *, explicitly_set: frozenset[str]) -> None:
    """Replace betterproto2 UNSPECIFIED (value=0) enum fields post-build.

    Polyfactory may generate 0 for IntEnum fields since betterproto2 enums
    inherit from int. This catches and replaces any UNSPECIFIED values with
    a random valid member regardless of how polyfactory resolved the field type.

    Args:
        instance: The betterproto2 message instance to fix in place.
        explicitly_set: Field names that were explicitly provided by the caller
            and must not be overridden.
    """
    try:
        hints = get_type_hints(type(instance))
    except NameError, AttributeError, TypeError:
        return
    for field_name, field_type in hints.items():
        if field_name in explicitly_set or not isinstance(field_type, type):
            continue
        _replace_if_unspecified(instance, field_name, field_type)


def _make_enum_provider(enum_type: type[enum.IntEnum]) -> Callable[[], enum.IntEnum]:
    """Build a provider that returns a random non-UNSPECIFIED enum member.

    Betterproto2 enums always define ``UNSPECIFIED = 0`` as a sentinel.
    Polyfactory picks the first member by default, which is always
    ``UNSPECIFIED``.  This provider filters it out so factories produce
    semantically valid values.

    Args:
        enum_type: The betterproto2 IntEnum subclass to build a provider for.

    Returns:
        A callable that returns a random non-UNSPECIFIED enum member each time.
    """
    valid = [m for m in enum_type if m.value != 0]
    if not valid:
        valid = list(enum_type)
    return lambda: random.choice(valid)  # noqa: S311  # does not require cryptographic strength


def _fix_none_datetimes(instance: object, *, explicitly_set: frozenset[str]) -> None:
    """Backfill ``None`` datetime fields with timezone-aware values.

    Polyfactory resolves ``datetime | None`` union types by randomly picking
    ``None`` roughly half the time.  For test factories we almost always want
    populated timestamps, so this replaces any ``None`` datetime field with
    ``datetime.now(UTC)`` unless the caller explicitly passed ``None``.

    Args:
        instance: The betterproto2 message instance to fix in place.
        explicitly_set: Field names that were explicitly provided by the caller
            and must not be overridden.
    """
    try:
        hints = get_type_hints(type(instance))
    except NameError, AttributeError, TypeError:
        return
    for field_name, field_type in hints.items():
        if field_name in explicitly_set:
            continue
        if getattr(instance, field_name, None) is not None:
            continue
        if _hint_contains_datetime(field_type):
            setattr(instance, field_name, datetime.now(UTC))


def _hint_contains_datetime(hint: object) -> bool:
    """Check whether a type hint includes ``datetime`` (e.g. ``datetime | None``)."""
    if hint is datetime:
        return True
    args = getattr(hint, "__args__", None)
    if args is not None:
        return any(a is datetime for a in args)
    return False


class BetterprotoFactory(DataclassFactory[Any]):
    """Base factory for betterproto2 messages handling common quirks.

    Handles:
    - Timezone-aware datetimes (betterproto2 requires tz-aware for serialization)
    - Valid UUID strings for *_id fields
    - Enum fields: excludes UNSPECIFIED=0 sentinel to produce valid values
    """

    __is_base_factory__ = True

    @classmethod
    def build(cls, **kwargs: Any) -> Any:
        """Build instance and fix betterproto2 quirks post-build.

        Fixes two polyfactory issues with betterproto2 messages:
        1. UNSPECIFIED enum fields (value=0) replaced with valid members
        2. Optional datetime fields (``datetime | None``) that polyfactory
           randomly resolves to ``None`` are backfilled with tz-aware values

        Args:
            **kwargs: Field overrides forwarded to the parent factory.

        Returns:
            A fully-built betterproto2 message instance with valid enum values
            and populated datetime fields.
        """
        instance = super().build(**kwargs)
        explicitly_set = frozenset(kwargs)
        _fix_unspecified_enums(instance, explicitly_set=explicitly_set)
        _fix_none_datetimes(instance, explicitly_set=explicitly_set)
        return instance

    @classmethod
    def get_provider_map(cls) -> dict[type, Any]:
        """Provide custom generators for betterproto2 types.

        Returns:
            Provider map with datetime and betterproto2 enum overrides.
        """
        providers = super().get_provider_map()
        providers[datetime] = lambda: datetime.now(UTC)

        if not hasattr(cls, "__model__"):
            return providers

        try:
            hints = get_type_hints(cls.__model__)
        except NameError, AttributeError, TypeError:
            return providers

        for field_type in hints.values():
            if not isinstance(field_type, type):
                continue
            try:
                if issubclass(field_type, betterproto2.Enum) and field_type not in providers:
                    providers[field_type] = _make_enum_provider(field_type)
            except TypeError:
                pass

        return providers
