"""Decorator-based message handler framework for nohiki-kafka-client."""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Awaitable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

import betterproto2
from nohiki_common_exceptions import (
    DataNotAvailableError,
    DataNotFoundError,
    ExternalServiceError,
    NohikiError,
    RateLimitedError,
    SchemaVersionMismatchError,
    StaleDataError,
    ValidationError,
)

from nohiki_kafka_client.exceptions import SerializationError
from nohiki_kafka_client.middleware.protocol import Middleware

if TYPE_CHECKING:
    # nohiki-db-utils and its SQLAlchemy dependency require the optional `db` extra; eager imports
    # would break base installs.
    from nohiki_db_utils import OutboxWriter  # noqa: TC004
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: TC004

    from nohiki_kafka_client.producer import MessageMetadata


class KafkaPublisher(Protocol):
    """Protocol for objects that can publish Kafka messages."""

    async def publish(
        self,
        topic: str,
        message: betterproto2.Message,
        key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> MessageMetadata:
        """Publish a message to a Kafka topic."""


MIN_TOPIC_PARTS = 3
DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 10
DEFAULT_CIRCUIT_BREAKER_TIMEOUT = 60
DEFAULT_CIRCUIT_BREAKER_HALF_OPEN_CALLS = 5


class ErrorAction(StrEnum):
    """Actions to take when message processing fails."""

    SEND_TO_DLQ = "send_to_dlq"
    RETRY = "retry"


def classify_error_action(error: Exception) -> ErrorAction:
    """Classify an error into the appropriate action.

    Uses structural pattern matching to route errors to either retry
    (transient/recoverable) or DLQ (permanent/non-retryable).

    Args:
        error: The exception to classify.

    Returns:
        The appropriate error action for the given exception type.

    """
    match error:
        case SerializationError() | ValueError() | TypeError():
            return ErrorAction.SEND_TO_DLQ
        case KeyError() | AttributeError():
            return ErrorAction.SEND_TO_DLQ
        case asyncio.TimeoutError() | OSError():
            return ErrorAction.RETRY
        case _:
            return _classify_domain_error(error)


_DOMAIN_RETRY_TYPES: tuple[type[Exception], ...] = (
    DataNotAvailableError,
    ExternalServiceError,
    RateLimitedError,
    StaleDataError,
)
_DOMAIN_DLQ_TYPES: tuple[type[Exception], ...] = (
    DataNotFoundError,
    ValidationError,
    SchemaVersionMismatchError,
)


def _classify_domain_error(error: Exception) -> ErrorAction:
    """Classify domain-specific errors from nohiki-common-exceptions.

    Args:
        error: The exception to classify.

    Returns:
        The appropriate error action for the given exception type.

    """
    if _DOMAIN_RETRY_TYPES and isinstance(error, _DOMAIN_RETRY_TYPES):
        return ErrorAction.RETRY
    if _DOMAIN_DLQ_TYPES and isinstance(error, _DOMAIN_DLQ_TYPES):
        return ErrorAction.SEND_TO_DLQ
    if isinstance(error, NohikiError):
        return ErrorAction.RETRY if error.is_retryable else ErrorAction.SEND_TO_DLQ
    return ErrorAction.RETRY


class DLQStrategy(StrEnum):
    """Dead Letter Queue strategies."""

    REPUBLISH = "republish"
    LOG_ONLY = "log_only"


def _validate_positive(value: int, field_name: str) -> int:
    """Validate that a value is positive."""
    if value < 1:
        msg = f"{field_name} must be at least 1, got {value}"
        raise ValueError(msg)
    return value


def _validate_non_negative(value: int, field_name: str) -> int:
    """Validate that a value is non-negative."""
    if value < 0:
        msg = f"{field_name} must be non-negative, got {value}"
        raise ValueError(msg)
    return value


def _validate_non_empty_string(value: str, field_name: str) -> str:
    """Validate that a string is not empty or whitespace."""
    if not value.strip():
        msg = f"{field_name} cannot be empty or whitespace"
        raise ValueError(msg)
    return value


@dataclass(slots=True)
class MessageContext:
    """Context information for message processing."""

    topic: str
    partition: int
    offset: int
    timestamp: int
    headers: dict[str, str]
    key: str | None
    retry_count: int = 0
    correlation_id: str | None = None
    processing_metadata: dict[str, object] | None = None
    kafka_client: KafkaPublisher | None = None
    db_session: AsyncSession | None = None
    outbox: OutboxWriter | None = None
    session_factory: async_sessionmaker[AsyncSession] | None = None

    def __post_init__(self) -> None:
        """Initialize processing metadata and validate fields."""
        if self.processing_metadata is None:
            self.processing_metadata = {}

        self.partition = _validate_non_negative(self.partition, "partition")
        self.offset = _validate_non_negative(self.offset, "offset")
        self.retry_count = _validate_non_negative(self.retry_count, "retry_count")

    def require_db_session(self) -> AsyncSession:
        """Return the database session injected by ``@with_db_session``.

        Raises:
            RuntimeError: If no session was injected (handler not decorated
                with ``@with_db_session``).

        """
        if self.db_session is None:
            msg = "db_session not available in context - decorate the handler with @kafka_client.with_db_session()"
            raise RuntimeError(msg)
        return self.db_session

    def require_session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Return the session factory injected by ``@with_db_session``.

        Raises:
            RuntimeError: If no session factory was injected (handler not decorated
                with ``@with_db_session``).

        """
        if self.session_factory is None:
            msg = "session_factory not available in context - decorate the handler with @kafka_client.with_db_session()"
            raise RuntimeError(msg)
        return self.session_factory

    def require_outbox(self) -> OutboxWriter:
        """Return the outbox writer injected by ``@with_db_session(schema=...)``.

        Raises:
            RuntimeError: If no outbox was injected (handler not decorated
                with ``@with_db_session(schema=...)``).

        """
        if self.outbox is None:
            msg = (
                "outbox not available in context -- decorate the handler with @kafka_client.with_db_session(schema=...)"
            )
            raise RuntimeError(msg)
        return self.outbox

    async def publish(
        self,
        topic: str,
        message: betterproto2.Message,
        key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> MessageMetadata:
        """Publish message via the Kafka client."""
        if self.kafka_client is None:
            msg = "Kafka client not available in context"
            raise RuntimeError(msg)
        return await self.kafka_client.publish(topic, message, key, headers)


# Protocol definitions for handler functions with function metadata
class MessageHandlerFunc[T: betterproto2.Message](Protocol):
    """Protocol for message handler functions with function metadata.

    Handler functions must accept two positional arguments:
    - message: The deserialized protobuf message
    - context: The message context (can be named _context if unused)
    """

    __name__: str
    __module__: str

    def __call__(self, message: T, context: MessageContext, /) -> Coroutine[Any, Any, None]:
        """Process a single message."""
        ...


class BatchHandlerFunc[T: betterproto2.Message](Protocol):
    """Protocol for batch message handler functions with function metadata."""

    __name__: str
    __module__: str

    def __call__(self, messages: list[T], context: MessageContext) -> Awaitable[None]:
        """Process a batch of messages."""
        ...


@dataclass(slots=True)
class CircuitBreakerConfig:
    """Circuit breaker configuration for message handlers."""

    failure_threshold: int = field(default=DEFAULT_CIRCUIT_BREAKER_THRESHOLD)
    timeout_seconds: int = field(default=DEFAULT_CIRCUIT_BREAKER_TIMEOUT)
    half_open_max_calls: int = field(default=DEFAULT_CIRCUIT_BREAKER_HALF_OPEN_CALLS)

    def __post_init__(self) -> None:
        """Validate circuit breaker configuration."""
        self.failure_threshold = _validate_positive(self.failure_threshold, "failure_threshold")
        self.timeout_seconds = _validate_positive(self.timeout_seconds, "timeout_seconds")
        self.half_open_max_calls = _validate_positive(self.half_open_max_calls, "half_open_max_calls")


@dataclass(frozen=True, slots=True)
class ResilienceConfig:
    """Per-handler resilience overrides.

    Fields left as ``None`` inherit the service-level default from
    ``GlobalDLQConfig``.  Only set fields you want to override.
    """

    max_retries: int | None = None
    retry_backoff_ms: int | None = None
    max_backoff_ms: int | None = None
    strategy: DLQStrategy | None = None


@dataclass(frozen=True, slots=True)
class DbSessionConfig:
    """Database session configuration for handlers using ``@with_db_session``."""

    schema: str | None = None
    auto_commit: bool = True


@dataclass(slots=True)
class HandlerRegistration:
    """Information about a registered message handler."""

    topic: str
    message_type: type[betterproto2.Message]
    handler_func: MessageHandlerFunc[Any]
    group_id: str
    middleware: list[Middleware] = field(default_factory=list)
    is_transactional: bool = field(default=False)
    resilience_config: ResilienceConfig | None = None
    db_session_config: DbSessionConfig | None = None
    preserve_partition_order: bool = field(default=True)

    def _validate_topic_naming(self) -> None:
        """Validate topic naming convention (warning only)."""
        topic_parts = self.topic.split(".")
        if len(topic_parts) < MIN_TOPIC_PARTS:
            warnings.warn(
                f"Topic '{self.topic}' doesn't follow recommended naming pattern: "
                "service.entity.action.version (e.g., 'user.profile.updated.v1')",
                UserWarning,
                stacklevel=2,
            )

    def __post_init__(self) -> None:
        """Validate handler registration."""
        self.topic = _validate_non_empty_string(self.topic, "topic")
        self.group_id = _validate_non_empty_string(self.group_id, "group_id")

        if not callable(self.handler_func):
            msg = "handler_func must be callable"
            raise TypeError(msg)

        self._validate_topic_naming()
