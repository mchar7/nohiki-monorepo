"""Consumer supervisor for Kafka consumer management.

Provides automatic reconnection with exponential backoff for transient failures
like coordinator errors, heartbeat timeouts, and network issues.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from aiokafka.errors import (
    CommitFailedError,
    ConsumerStoppedError,
    GroupAuthorizationFailedError,
    IllegalStateError,
    KafkaConnectionError,
    KafkaError,
    NodeNotReadyError,
    RequestTimedOutError,
    UnknownMemberIdError,
)
from nohiki_observability import get_logger

from nohiki_kafka_client.exceptions import DLQPublishError

if TYPE_CHECKING:
    from nohiki_kafka_client.handlers import HandlerRegistration

logger = get_logger(__name__)

type ConsumerFactory = Callable[[HandlerRegistration], Awaitable[None]]
type HealthSummaryValue = str | int | float | bool | None
type HealthSummary = dict[str, dict[str, HealthSummaryValue]]

DEFAULT_INITIAL_BACKOFF_SECONDS = 1.0
DEFAULT_MAX_BACKOFF_SECONDS = 60.0
DEFAULT_BACKOFF_MULTIPLIER = 2.0
DEFAULT_JITTER_FACTOR = 0.2
DEFAULT_MAX_CONSECUTIVE_FAILURES = 10

COORDINATOR_ERROR_TYPES: tuple[type[KafkaError], ...] = (
    NodeNotReadyError,
    UnknownMemberIdError,
    CommitFailedError,
    IllegalStateError,
)
TRANSIENT_ERROR_TYPES: tuple[type[BaseException], ...] = (
    KafkaConnectionError,
    RequestTimedOutError,
    DLQPublishError,
    OSError,
    TimeoutError,
)
COORDINATOR_MESSAGE_TERMS: frozenset[str] = frozenset({"coordinator", "heartbeat", "rebalance", "timeout", "not ready"})
TRANSIENT_MESSAGE_TERMS: frozenset[str] = frozenset({"connection", "network", "disconnect"})
RECOVERABLE_CATEGORIES: frozenset[ErrorCategory] = frozenset()  # Defined after ErrorCategory


class ConsumerState(StrEnum):
    """Consumer lifecycle state."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    BACKOFF = "backoff"
    FAILED = "failed"


class ErrorCategory(StrEnum):
    """Classification of Kafka errors for recovery strategy."""

    TRANSIENT = "transient"
    COORDINATOR = "coordinator"
    AUTH = "auth"
    FATAL = "fatal"


RECOVERABLE_CATEGORIES = frozenset({ErrorCategory.TRANSIENT, ErrorCategory.COORDINATOR})


@dataclass(slots=True)
class SupervisorConfig:
    """Configuration for consumer supervisor."""

    initial_backoff_seconds: float = DEFAULT_INITIAL_BACKOFF_SECONDS
    max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS
    backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER
    jitter_factor: float = DEFAULT_JITTER_FACTOR
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES


@dataclass(slots=True)
class ConsumerMetrics:
    """Metrics for supervised consumer."""

    state: ConsumerState = ConsumerState.STOPPED
    consecutive_failures: int = 0
    total_restarts: int = 0
    last_successful_consume: float | None = None
    last_error: str | None = None
    last_error_time: float | None = None
    last_error_category: ErrorCategory | None = None
    current_backoff_seconds: float = 0.0
    started_at: float | None = None


@dataclass(slots=True)
class SupervisedConsumer:
    """State for a supervised consumer."""

    registration: HandlerRegistration
    config: SupervisorConfig
    metrics: ConsumerMetrics = field(default_factory=ConsumerMetrics)
    task: asyncio.Task[None] | None = None
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def consumer_key(self) -> str:
        """Unique key for this consumer."""
        return f"{self.registration.topic}:{self.registration.group_id}"


def classify_error(error: BaseException) -> ErrorCategory:
    """Classify a Kafka error to determine recovery strategy.

    Args:
        error: The exception raised by the Kafka consumer or broker.

    Returns:
        The ``ErrorCategory`` that drives restart vs. backoff vs. abort decisions.

    """
    match error:
        case _ if isinstance(error, COORDINATOR_ERROR_TYPES):
            return ErrorCategory.COORDINATOR
        case _ if isinstance(error, TRANSIENT_ERROR_TYPES):
            return ErrorCategory.TRANSIENT
        case GroupAuthorizationFailedError():
            return ErrorCategory.AUTH
        case ConsumerStoppedError():
            return ErrorCategory.FATAL
        case KafkaError():
            return _classify_by_message(str(error).lower())
        case _:
            return ErrorCategory.FATAL


def _classify_by_message(error_msg: str) -> ErrorCategory:
    """Classify KafkaError by inspecting error message using set membership."""
    if _contains_any_term(error_msg, COORDINATOR_MESSAGE_TERMS):
        return ErrorCategory.COORDINATOR
    if _contains_any_term(error_msg, TRANSIENT_MESSAGE_TERMS):
        return ErrorCategory.TRANSIENT
    return ErrorCategory.FATAL


def _contains_any_term(text: str, terms: frozenset[str]) -> bool:
    """Check if text contains any of the terms. O(k) where k = len(terms)."""
    return any(term in text for term in terms)


def is_recoverable(category: ErrorCategory) -> bool:
    """Check if error category is recoverable. O(1) frozenset lookup.

    Args:
        category: The error category returned by ``classify_error``.

    Returns:
        ``True`` if the consumer should be restarted; ``False`` if it should abort.

    """
    return category in RECOVERABLE_CATEGORIES


def calculate_backoff(attempt: int, config: SupervisorConfig) -> float:
    """Calculate backoff duration with exponential increase and jitter.

    Args:
        attempt: Zero-based retry attempt count.
        config: Supervisor configuration containing backoff parameters.

    Returns:
        Sleep duration in seconds, bounded between ``config.initial_backoff_seconds``
        and ``config.max_backoff_seconds`` with random jitter applied.

    """
    base = config.initial_backoff_seconds * (config.backoff_multiplier**attempt)
    capped = min(base, config.max_backoff_seconds)
    jitter = capped * config.jitter_factor * random.uniform(-1, 1)  # noqa: S311  # jitter does not require cryptographic strength
    return max(config.initial_backoff_seconds, capped + jitter)


class ConsumerSupervisor:
    """Supervises Kafka consumers with automatic restart on failures.

    Features:
    - Automatic reconnection with exponential backoff
    - Error classification for smart recovery
    - Health tracking per consumer
    - Graceful shutdown handling
    """

    __slots__ = ("_config", "_consumers", "_shutdown_event", "_supervisor_task")

    def __init__(self, config: SupervisorConfig | None = None) -> None:
        """Initialize supervisor with optional configuration."""
        self._config = config or SupervisorConfig()
        self._consumers: dict[str, SupervisedConsumer] = {}
        self._shutdown_event = asyncio.Event()
        self._supervisor_task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        """Check if supervisor is running."""
        return self._supervisor_task is not None and not self._supervisor_task.done()

    def register(self, registration: HandlerRegistration) -> SupervisedConsumer:
        """Register a consumer for supervision."""
        supervised = SupervisedConsumer(registration=registration, config=self._config)
        self._consumers[supervised.consumer_key] = supervised
        return supervised

    def get_consumer(self, key: str) -> SupervisedConsumer | None:
        """Get supervised consumer by key. O(1) dict lookup."""
        return self._consumers.get(key)

    def get_all_consumers(self) -> dict[str, SupervisedConsumer]:
        """Get shallow copy of all supervised consumers."""
        return self._consumers.copy()

    def get_health_summary(self) -> HealthSummary:
        """Get health summary for all consumers using dict comprehension."""
        return {key: _build_health_entry(c.metrics) for key, c in self._consumers.items()}

    async def start_consumer(
        self,
        supervised: SupervisedConsumer,
        consumer_factory: ConsumerFactory,
    ) -> None:
        """Start a supervised consumer with automatic restart on failure."""
        consumer_key = supervised.consumer_key
        metrics = supervised.metrics

        logger.info(
            "Starting supervised consumer",
            consumer_key=consumer_key,
            topic=supervised.registration.topic,
            group_id=supervised.registration.group_id,
        )

        while self._should_continue(supervised):
            _reset_for_start(metrics)
            try:
                await self._run_consumer(supervised, consumer_factory)
                _reset_on_success(metrics)
            except asyncio.CancelledError:
                logger.info("Consumer cancelled", consumer_key=consumer_key)
                metrics.state = ConsumerState.STOPPED
                raise
            except (KafkaError, ConsumerStoppedError, DLQPublishError, OSError) as e:
                if self._handle_and_should_stop(supervised, e):
                    break
                if await self._wait_backoff(supervised):
                    break
            except Exception as e:
                self._handle_and_should_stop(supervised, e)
                raise

        if metrics.state != ConsumerState.FAILED:
            metrics.state = ConsumerState.STOPPED
        logger.info("Supervised consumer stopped", consumer_key=consumer_key)

    def _should_continue(self, supervised: SupervisedConsumer) -> bool:
        """Check if consumer loop should continue."""
        return not supervised.shutdown_event.is_set() and not self._shutdown_event.is_set()

    def _handle_and_should_stop(self, supervised: SupervisedConsumer, error: BaseException) -> bool:
        """Handle failure and return True if consumer should stop."""
        _record_failure(supervised.metrics, error)
        self._log_failure(supervised, error)

        category = supervised.metrics.last_error_category or ErrorCategory.FATAL

        if not is_recoverable(category):
            self._log_fatal(supervised, error, "non-recoverable error")
            supervised.metrics.state = ConsumerState.FAILED
            return True

        if supervised.metrics.consecutive_failures >= self._config.max_consecutive_failures:
            self._log_fatal(supervised, error, "max consecutive failures exceeded")
            supervised.metrics.state = ConsumerState.FAILED
            return True

        return False

    def _log_failure(self, supervised: SupervisedConsumer, error: BaseException) -> None:
        """Log consumer failure warning."""
        logger.warning(
            "Consumer failed",
            consumer_key=supervised.consumer_key,
            error=str(error),
            category=supervised.metrics.last_error_category,
            consecutive_failures=supervised.metrics.consecutive_failures,
        )

    def _log_fatal(self, supervised: SupervisedConsumer, error: BaseException, reason: str) -> None:
        """Log fatal consumer failure."""
        logger.exception(
            "Consumer stopped",
            reason=reason,
            consumer_key=supervised.consumer_key,
            error=str(error),
            category=supervised.metrics.last_error_category,
        )

    async def _wait_backoff(self, supervised: SupervisedConsumer) -> bool:
        """Wait for backoff period. Returns True if shutdown requested."""
        metrics = supervised.metrics
        backoff = calculate_backoff(metrics.consecutive_failures, self._config)
        metrics.current_backoff_seconds = backoff
        metrics.state = ConsumerState.BACKOFF

        logger.warning(
            "Consumer will restart after backoff",
            consumer_key=supervised.consumer_key,
            backoff_seconds=round(backoff, 2),
            attempt=metrics.consecutive_failures,
        )

        try:
            await asyncio.wait_for(supervised.shutdown_event.wait(), timeout=backoff)
        except TimeoutError:
            metrics.state = ConsumerState.RECONNECTING
            metrics.total_restarts += 1
            return False
        return True

    async def _run_consumer(
        self,
        supervised: SupervisedConsumer,
        consumer_factory: ConsumerFactory,
    ) -> None:
        """Run the actual consumer using the factory."""
        supervised.metrics.state = ConsumerState.RUNNING
        await consumer_factory(supervised.registration)
        supervised.metrics.last_successful_consume = time.time()

    async def stop_consumer(self, key: str) -> None:
        """Stop a specific consumer by key."""
        if supervised := self._consumers.get(key):
            await _cancel_consumer(supervised)

    async def stop_all(self) -> None:
        """Stop all supervised consumers concurrently."""
        self._shutdown_event.set()
        for supervised in self._consumers.values():
            supervised.shutdown_event.set()

        pending_tasks = [s.task for s in self._consumers.values() if s.task and not s.task.done()]
        if pending_tasks:
            await _cancel_tasks(pending_tasks)

        logger.info("All supervised consumers stopped", count=len(self._consumers))


def _build_health_entry(metrics: ConsumerMetrics) -> dict[str, HealthSummaryValue]:
    """Build health summary entry for a single consumer."""
    return {
        "state": metrics.state.value,
        "healthy": metrics.state == ConsumerState.RUNNING,
        "consecutive_failures": metrics.consecutive_failures,
        "total_restarts": metrics.total_restarts,
        "last_error": metrics.last_error,
        "last_error_category": metrics.last_error_category.value if metrics.last_error_category else None,
        "current_backoff_seconds": metrics.current_backoff_seconds,
    }


def _reset_for_start(metrics: ConsumerMetrics) -> None:
    """Reset metrics at start of consume attempt."""
    metrics.state = ConsumerState.STARTING
    metrics.started_at = time.time()


def _reset_on_success(metrics: ConsumerMetrics) -> None:
    """Reset failure counters on successful consume."""
    metrics.consecutive_failures = 0
    metrics.current_backoff_seconds = 0.0


def _record_failure(metrics: ConsumerMetrics, error: BaseException) -> None:
    """Record failure in metrics."""
    metrics.consecutive_failures += 1
    metrics.last_error = str(error)
    metrics.last_error_time = time.time()
    metrics.last_error_category = classify_error(error)


async def _cancel_consumer(supervised: SupervisedConsumer) -> None:
    """Cancel a single consumer's task."""
    supervised.shutdown_event.set()
    if supervised.task and not supervised.task.done():
        supervised.task.cancel()
        with suppress(asyncio.CancelledError):
            await supervised.task


async def _cancel_tasks(tasks: list[asyncio.Task[None]]) -> None:
    """Cancel multiple tasks concurrently."""
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
