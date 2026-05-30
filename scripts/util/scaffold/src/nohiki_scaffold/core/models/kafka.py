"""Kafka feature configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from nohiki_scaffold.core.exceptions import ValidationError
from nohiki_scaffold.core.features import HandlerKind, KafkaRole

from ._validation import validate_max_concurrent_handlers


@dataclass(frozen=True, slots=True)
class KafkaOptions:
    """Kafka-related feature flags."""

    role: KafkaRole = KafkaRole.NONE
    handlers: frozenset[HandlerKind] = field(default_factory=frozenset)
    embedding_callback: bool = False
    max_concurrent_handlers: int | None = None

    def __post_init__(self) -> None:
        """Enforce role/handler consistency and max_concurrent_handlers range."""
        has_consumer = self.role in {KafkaRole.CONSUMER_ONLY, KafkaRole.BOTH}
        if self.handlers and not has_consumer:
            msg = f"kafka.handlers requires a consumer role, got role={self.role.value!r}"
            raise ValidationError(msg)
        if self.embedding_callback and not has_consumer:
            msg = "kafka.embedding_callback requires a consumer role"
            raise ValidationError(msg)
        if self.max_concurrent_handlers is not None:
            validate_max_concurrent_handlers(self.max_concurrent_handlers)


__all__ = ["KafkaOptions"]
