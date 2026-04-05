"""Data models for the Kafka admin module."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

TOPIC_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z0-9._-]+$")
MAX_TOPIC_NAME_LENGTH: Final[int] = 249


def _validate_topic_name(name: str) -> None:
    """Validate a Kafka topic name against protocol rules.

    Args:
        name: Topic name to validate.

    Raises:
        ValueError: If the name is empty, too long, or contains invalid characters.

    """
    if not name or not name.strip():
        msg = "Topic name cannot be empty"
        raise ValueError(msg)
    if len(name) > MAX_TOPIC_NAME_LENGTH:
        msg = f"Topic name exceeds {MAX_TOPIC_NAME_LENGTH} characters: {name!r}"
        raise ValueError(msg)
    if not TOPIC_NAME_PATTERN.match(name):
        msg = f"Topic name contains invalid characters: {name!r} (allowed: [a-zA-Z0-9._-])"
        raise ValueError(msg)


def _validate_positive(value: int, field_name: str) -> None:
    """Validate that an integer field is at least 1.

    Args:
        value: Value to check.
        field_name: Name of the field for error messages.

    Raises:
        ValueError: If value is less than 1.

    """
    if value < 1:
        msg = f"{field_name} must be >= 1, got {value}"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TopicSpec:
    """Specification for a Kafka topic to create.

    Attributes:
        name: Topic name (must match Kafka naming rules).
        num_partitions: Number of partitions for the topic.
        replication_factor: Replication factor for the topic.
        topic_configs: Optional Kafka topic-level configuration overrides
            (e.g. ``{"retention.ms": "86400000"}``).

    """

    name: str
    num_partitions: int = 3
    replication_factor: int = 1
    topic_configs: dict[str, str] | None = None

    def __post_init__(self) -> None:
        """Validate topic specification fields."""
        _validate_topic_name(self.name)
        _validate_positive(self.num_partitions, "num_partitions")
        _validate_positive(self.replication_factor, "replication_factor")


@dataclass(frozen=True, slots=True)
class TopicDescription:
    """Metadata about an existing Kafka topic.

    Attributes:
        name: Topic name.
        num_partitions: Current number of partitions.

    """

    name: str
    num_partitions: int


@dataclass(frozen=True, slots=True)
class EnsureTopicsResult:
    """Result of an ensure_topics_exist operation.

    All sequence fields are immutable tuples to match the frozen semantics
    of this result object.

    Attributes:
        created: Topic names that were newly created.
        existing: Topic names that already existed.
        warnings: Human-readable warnings (e.g. partition mismatches).

    """

    created: tuple[str, ...] = ()
    existing: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
