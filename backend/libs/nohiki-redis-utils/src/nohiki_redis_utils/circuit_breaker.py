"""Circuit breaker pattern for Redis operations."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from nohiki_observability import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = get_logger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior.

    Attributes:
        failure_threshold: Number of consecutive failures before opening circuit.
        success_threshold: Number of successful probes in half-open to close circuit.
        timeout_seconds: Time in open state before transitioning to half-open.
        half_open_max_calls: Maximum concurrent probe calls allowed in half-open state.

    """

    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_seconds: float = 30.0
    half_open_max_calls: int = 1


@dataclass(slots=True)
class _CircuitBreakerState:
    """Internal mutable state for circuit breaker."""

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    half_open_calls: int = 0
    _lock: asyncio.Lock | None = field(default=None, repr=False)
    _lock_loop_id: int | None = field(default=None, repr=False)

    def get_lock(self) -> asyncio.Lock:
        """Get or create lock for current event loop."""
        # Get current event loop ID to detect loop changes (sync decorator creates new loops)
        try:
            current_loop = asyncio.get_running_loop()
            current_loop_id = id(current_loop)
        except RuntimeError:
            # No running loop - create lock anyway, will be used when loop starts
            current_loop_id = None

        # Recreate lock if event loop changed (handles sync decorator case)
        if self._lock is None or (current_loop_id is not None and self._lock_loop_id != current_loop_id):
            self._lock = asyncio.Lock()
            self._lock_loop_id = current_loop_id

        return self._lock


class CircuitBreaker:
    """Circuit breaker for protecting against cascading failures.

    Implements the circuit breaker pattern with three states:
    - CLOSED: Normal operation, tracking failures
    - OPEN: Failing fast, returning fallback values
    - HALF_OPEN: Testing if service has recovered

    Example:
        cb = CircuitBreaker("redis")
        result = await cb.call(lambda: redis.get("key"), fallback=None)

    """

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None) -> None:
        """Initialize circuit breaker.

        Args:
            name: Identifier for this circuit breaker (used in logging).
            config: Configuration options. Uses defaults if not provided.

        """
        self._name = name
        self._config = config or CircuitBreakerConfig()
        self._state = _CircuitBreakerState()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state.state

    @property
    def is_closed(self) -> bool:
        """Check if circuit is in closed (healthy) state."""
        return self._state.state == CircuitState.CLOSED

    def reset(self) -> None:
        """Manually reset circuit breaker to closed state."""
        self._state.state = CircuitState.CLOSED
        self._state.failure_count = 0
        self._state.success_count = 0
        self._state.half_open_calls = 0
        logger.info("Circuit breaker manually reset", circuit=self._name)

    async def call[T](
        self,
        func: Callable[[], Awaitable[T]],
        fallback: T | None = None,
    ) -> T | None:
        """Execute function through circuit breaker.

        Args:
            func: Async callable to execute.
            fallback: Value to return if circuit is open or call fails.

        Returns:
            Result of func() if successful, fallback otherwise.

        """
        async with self._state.get_lock():
            # Check for state transitions before executing
            self._check_state_transition()

            match self._state.state:
                case CircuitState.OPEN:
                    logger.debug(
                        "Circuit open, returning fallback",
                        circuit=self._name,
                        fallback_type=type(fallback).__name__,
                    )
                    return fallback

                case CircuitState.HALF_OPEN:
                    if self._state.half_open_calls >= self._config.half_open_max_calls:
                        logger.debug(
                            "Half-open call limit reached, returning fallback",
                            circuit=self._name,
                            current_calls=self._state.half_open_calls,
                            max_calls=self._config.half_open_max_calls,
                        )
                        return fallback
                    self._state.half_open_calls += 1

                case CircuitState.CLOSED:
                    pass  # Proceed to execute function below

        # Execute outside lock to allow concurrent operations in CLOSED state
        try:
            result = await func()
        except asyncio.CancelledError:
            await self._release_half_open_slot()
            raise
        except Exception as e:
            await self._record_failure(e)
            return fallback
        else:
            await self._record_success()
            return result

    def _check_state_transition(self) -> None:
        """Check and apply state transitions based on timeout.

        Must be called while holding the lock.
        """
        if self._state.state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._state.last_failure_time
            if elapsed >= self._config.timeout_seconds:
                self._state.state = CircuitState.HALF_OPEN
                self._state.half_open_calls = 0
                self._state.success_count = 0
                logger.info(
                    "Circuit transitioned to half-open",
                    circuit=self._name,
                    elapsed_seconds=elapsed,
                )

    async def _record_success(self) -> None:
        """Record successful call and potentially close circuit."""
        async with self._state.get_lock():
            match self._state.state:
                case CircuitState.CLOSED:
                    self._state.failure_count = 0
                case CircuitState.HALF_OPEN:
                    self._state.success_count += 1
                    self._state.half_open_calls = max(0, self._state.half_open_calls - 1)

                    if self._state.success_count >= self._config.success_threshold:
                        self._state.state = CircuitState.CLOSED
                        self._state.failure_count = 0
                        self._state.success_count = 0
                        logger.info(
                            "Circuit closed after successful probes",
                            circuit=self._name,
                            success_count=self._config.success_threshold,
                        )

    async def _record_failure(self, error: Exception) -> None:
        """Record failed call and potentially open circuit."""
        async with self._state.get_lock():
            logger.warning(
                "Circuit breaker recorded failure",
                circuit=self._name,
                error_type=type(error).__name__,
                error_msg=str(error),
                state=self._state.state.value,
            )

            match self._state.state:
                case CircuitState.CLOSED:
                    self._state.failure_count += 1

                    if self._state.failure_count >= self._config.failure_threshold:
                        self._state.state = CircuitState.OPEN
                        self._state.last_failure_time = time.monotonic()
                        logger.warning(
                            "Circuit opened due to failures",
                            circuit=self._name,
                            failure_count=self._state.failure_count,
                            threshold=self._config.failure_threshold,
                        )
                case CircuitState.HALF_OPEN:
                    self._state.state = CircuitState.OPEN
                    self._state.last_failure_time = time.monotonic()
                    self._state.half_open_calls = 0
                    self._state.success_count = 0
                    logger.warning(
                        "Circuit reopened after half-open probe failure",
                        circuit=self._name,
                    )

    # --- Granular control methods for external retry loops ---

    async def can_execute(self) -> bool:
        """Check if a call can be executed based on circuit breaker state.

        Use this for granular control when not using the call() wrapper.

        Returns:
            True if call is allowed:
            - Circuit is CLOSED
            - Circuit is HALF_OPEN and under the max probe limit
            - Circuit is OPEN but timeout has elapsed (transitions to HALF_OPEN)

            False if call is blocked:
            - Circuit is OPEN and timeout hasn't elapsed
            - Circuit is HALF_OPEN and at max probe limit

        """
        async with self._state.get_lock():
            self._check_state_transition()

            if self._state.state == CircuitState.CLOSED:
                return True
            if self._state.state == CircuitState.OPEN:
                return False
            # HALF_OPEN
            if self._state.half_open_calls < self._config.half_open_max_calls:
                self._state.half_open_calls += 1
                return True
            return False

    async def record_success(self) -> None:
        """Record a successful call.

        Use this for granular control when not using the call() wrapper.
        Delegates to internal _record_success.
        """
        await self._record_success()

    async def record_failure(self, error: Exception | None = None) -> None:
        """Record a failed call.

        Use this for granular control when not using the call() wrapper.
        Delegates to internal _record_failure.

        Args:
            error: Optional exception that caused the failure (for logging).

        """
        if error is None:
            error = Exception("Unknown error")
        await self._record_failure(error)

    def get_retry_after(self) -> float | None:
        """Get seconds until circuit may transition to half-open.

        Returns:
            Seconds remaining if circuit is OPEN, None otherwise.

        """
        if self._state.state != CircuitState.OPEN:
            return None
        elapsed = time.monotonic() - self._state.last_failure_time
        remaining = self._config.timeout_seconds - elapsed
        if remaining > 0:
            return remaining
        return None

    async def _release_half_open_slot(self) -> None:
        """Release an in-flight half-open slot after cancellation."""
        async with self._state.get_lock():
            if self._state.state == CircuitState.HALF_OPEN:
                self._state.half_open_calls = max(0, self._state.half_open_calls - 1)

    def release_half_open_slot(self) -> None:
        """Release a half-open probe slot without recording success or failure.

        Use this when an excluded exception occurs during a half-open probe.
        """
        if self._state.state == CircuitState.HALF_OPEN:
            self._state.half_open_calls = max(0, self._state.half_open_calls - 1)
