"""Base mixin class for infrastructure settings composition."""

from __future__ import annotations


class SettingsMixin:
    """Base class for infrastructure settings mixins.

    All domain-specific mixins (KafkaMixin, DatabaseMixin, RedisMixin, S3Mixin,
    LLMMixin) inherit from this. Provides a clean extension point for future
    mixin introspection and a semantic marker for settings composition.

    The ``environment`` annotation declares the attribute that NohikiBaseSettings
    provides via MRO, allowing static type checkers to resolve it in mixin
    validators without requiring a Protocol or ABC.
    """

    environment: str
