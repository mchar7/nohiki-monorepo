"""Circuit breaker for Kafka producer fault tolerance."""

from __future__ import annotations

import time
from enum import StrEnum
from typing import TYPE_CHECKING

from nohiki_observability import get_logger

from nohiki_kafka_client.exceptions import CircuitBreakerOpenError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nohiki_kafka_client.handlers import CircuitBreakerConfig

logger = get_logger(__name__)

ERR_CIRCUIT_BREAKER_OPEN = "Circuit breaker is open"


class CircuitState(StrEnum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit breaker with closed → open → half-open state machine."""

    __slots__ = (
        "_failure_count",
        "_failure_threshold",
        "_last_failure_time",
        "_recovery_timeout",
        "_state",
    )

    def __init__(self, config: CircuitBreakerConfig) -> None:
        """Initialize circuit breaker with configuration."""
        self._failure_threshold = config.failure_threshold
        self._recovery_timeout = config.timeout_seconds
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._state = CircuitState.CLOSED

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state

    def _check_state(self) -> None:
        """Transition from OPEN → HALF_OPEN if recovery timeout elapsed, else raise."""
        if self._state != CircuitState.OPEN:
            return
        if time.perf_counter() - self._last_failure_time > self._recovery_timeout:
            self._transition(CircuitState.HALF_OPEN)
        else:
            raise CircuitBreakerOpenError(ERR_CIRCUIT_BREAKER_OPEN)

    def _record_failure(self) -> None:
        """Record a failure and open the circuit if threshold reached."""
        self._failure_count += 1
        self._last_failure_time = time.perf_counter()
        if self._failure_count >= self._failure_threshold:
            self._transition(CircuitState.OPEN)
            logger.warning(
                "Circuit breaker opened",
                failure_count=self._failure_count,
                threshold=self._failure_threshold,
            )

    def _record_success(self) -> None:
        """Reset failure count on every success; close circuit if HALF_OPEN."""
        self._failure_count = 0
        if self._state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.CLOSED)
            logger.info("Circuit breaker recovered", to_state=CircuitState.CLOSED.value)

    def _transition(self, new_state: CircuitState) -> None:
        """Transition to a new state with logging."""
        old_state = self._state
        self._state = new_state
        if old_state != new_state:
            logger.info(
                "Circuit breaker transition",
                from_state=old_state.value,
                to_state=new_state.value,
            )

    async def execute[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        """Execute operation with circuit breaker protection."""
        self._check_state()
        try:
            result = await operation()
        except Exception:
            self._record_failure()
            raise
        self._record_success()
        return result
