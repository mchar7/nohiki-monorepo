"""Feature enums driving template selection.

These are the orthogonal axes of the scaffold matrix. Every other decision
(which template files fire, which lifespan blocks are emitted, which deps
appear in pyproject) flows from these values.
"""

from __future__ import annotations

from enum import StrEnum


class ServiceShape(StrEnum):
    """Transport-layer shape of a service."""

    KAFKA_ONLY = "kafka-only"
    HTTP_ONLY = "http-only"
    HTTP_AND_KAFKA = "http-and-kafka"


class KafkaRole(StrEnum):
    """Service's participation in Kafka."""

    NONE = "none"
    PRODUCER_ONLY = "producer-only"
    CONSUMER_ONLY = "consumer-only"
    BOTH = "both"


class HandlerKind(StrEnum):
    """Conventional groupings of Kafka message handlers.

    Each kind maps to a file under ``events/`` in the generated service.
    """

    COMMANDS = "commands"
    CALLBACKS = "callbacks"
    UPSTREAM_CDC = "upstream-cdc"
    FEEDBACK = "feedback"
    BACKFILL = "backfill"


class VerifyMode(StrEnum):
    """Verification depth after scaffolding."""

    DEFAULT = "default"
    FULL = "full"
    NONE = "none"


__all__ = ["HandlerKind", "KafkaRole", "ServiceShape", "VerifyMode"]
