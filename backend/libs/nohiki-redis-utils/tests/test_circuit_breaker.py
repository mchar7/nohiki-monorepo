"""Tests for circuit breaker implementation."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from nohiki_redis_utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)

# Constants for test exceptions
_TEST_ERROR_MSG = "test error"
_REDIS_UNAVAILABLE_MSG = "Redis unavailable"


class TestCircuitBreakerState:
    """Tests for circuit breaker state management."""

    def test_starts_in_closed_state(self) -> None:
        """Circuit breaker should start in CLOSED state."""
        cb = CircuitBreaker("test")
        assert cb.state is CircuitState.CLOSED
        assert cb.is_closed is True

    def test_is_closed_property(self) -> None:
        """Verify is_closed property reflects state correctly."""
        cb = CircuitBreaker("test")
        assert cb.is_closed is True

        # Manually set state to verify property
        cb._state.state = CircuitState.OPEN
        assert cb.is_closed is False

        cb._state.state = CircuitState.HALF_OPEN
        assert cb.is_closed is False


class TestCircuitBreakerClosedState:
    """Tests for CLOSED state behavior."""

    @pytest.mark.asyncio
    async def test_successful_call_returns_result(self) -> None:
        """Successful call should return the function result."""
        cb = CircuitBreaker("test")

        async def success_fn() -> str:
            await asyncio.sleep(0)
            return "success"

        result = await cb.call(success_fn)
        assert result == "success"
        assert cb.state is CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failures_increment_counter(self) -> None:
        """Failed calls should increment failure counter."""
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=5))

        async def failing_fn() -> None:
            await asyncio.sleep(0)
            raise RuntimeError(_TEST_ERROR_MSG)

        # Call twice and check failures are tracked
        await cb.call(failing_fn, fallback=None)
        assert cb._state.failure_count == 1

        await cb.call(failing_fn, fallback=None)
        assert cb._state.failure_count == 2
        assert cb.state is CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_success_resets_failure_counter(self) -> None:
        """Successful call should reset failure counter in CLOSED state."""
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=5))

        async def failing_fn() -> None:
            await asyncio.sleep(0)
            raise RuntimeError(_TEST_ERROR_MSG)

        async def success_fn() -> str:
            await asyncio.sleep(0)
            return "ok"

        # Accumulate some failures
        await cb.call(failing_fn, fallback=None)
        await cb.call(failing_fn, fallback=None)
        assert cb._state.failure_count == 2

        # Success should reset counter
        await cb.call(success_fn)
        assert cb._state.failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold_failures(self) -> None:
        """Circuit should open after reaching failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker("test", config)

        async def failing_fn() -> None:
            await asyncio.sleep(0)
            raise RuntimeError(_TEST_ERROR_MSG)

        # Fail until threshold
        for _ in range(3):
            await cb.call(failing_fn, fallback=None)

        assert cb.state is CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_failure_returns_fallback(self) -> None:
        """Failed call should return fallback value."""
        cb = CircuitBreaker("test")

        async def failing_fn() -> str:
            raise RuntimeError(_TEST_ERROR_MSG)

        result = await cb.call(failing_fn, fallback="fallback_value")
        assert result == "fallback_value"


class TestCircuitBreakerOpenState:
    """Tests for OPEN state behavior."""

    @pytest.mark.asyncio
    async def test_open_circuit_returns_fallback_without_calling_function(self) -> None:
        """Open circuit should return fallback immediately without calling function."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout_seconds=60)
        cb = CircuitBreaker("test", config)

        # Open the circuit
        async def failing_fn() -> None:
            await asyncio.sleep(0)
            raise RuntimeError(_TEST_ERROR_MSG)

        await cb.call(failing_fn, fallback=None)
        assert cb.state is CircuitState.OPEN

        # Now verify function is not called when circuit is open
        call_count = 0

        async def tracked_fn() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0)
            return "should not be called"

        result = await cb.call(tracked_fn, fallback="open_fallback")
        assert result == "open_fallback"
        assert call_count == 0  # Function was not called

    @pytest.mark.asyncio
    async def test_circuit_transitions_to_half_open_after_timeout(self) -> None:
        """Circuit should transition from OPEN to HALF_OPEN after timeout."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout_seconds=0.1)
        cb = CircuitBreaker("test", config)

        # Open the circuit
        async def failing_fn() -> None:
            await asyncio.sleep(0)
            raise RuntimeError(_TEST_ERROR_MSG)

        await cb.call(failing_fn, fallback=None)
        assert cb.state is CircuitState.OPEN

        # Wait for timeout
        await asyncio.sleep(0.15)

        # Next call should trigger transition to HALF_OPEN
        async def success_fn() -> str:
            await asyncio.sleep(0)
            return "success"

        await cb.call(success_fn)
        # After successful call in HALF_OPEN, should be back to CLOSED
        # (because success_threshold default is 2, but we need to verify transition happened)
        assert cb.state in (CircuitState.HALF_OPEN, CircuitState.CLOSED)


class TestCircuitBreakerHalfOpenState:
    """Tests for HALF_OPEN state behavior."""

    @pytest.mark.asyncio
    async def test_successful_probe_closes_circuit(self) -> None:
        """Successful probes in HALF_OPEN should close circuit."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            success_threshold=2,
            timeout_seconds=0.05,
            half_open_max_calls=3,
        )
        cb = CircuitBreaker("test", config)

        # Open the circuit
        async def failing_fn() -> None:
            await asyncio.sleep(0)
            raise RuntimeError(_TEST_ERROR_MSG)

        await cb.call(failing_fn, fallback=None)
        assert cb.state is CircuitState.OPEN

        # Wait for transition to HALF_OPEN
        await asyncio.sleep(0.1)

        # Make successful calls to close circuit
        async def success_fn() -> str:
            await asyncio.sleep(0)
            return "success"

        await cb.call(success_fn)
        assert cb.state is CircuitState.HALF_OPEN  # Need 2 successes

        await cb.call(success_fn)
        assert cb.state is CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failed_probe_reopens_circuit(self) -> None:
        """Failed probe in HALF_OPEN should reopen circuit."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            success_threshold=2,
            timeout_seconds=0.05,
        )
        cb = CircuitBreaker("test", config)

        # Open the circuit
        async def failing_fn() -> None:
            await asyncio.sleep(0)
            raise RuntimeError(_TEST_ERROR_MSG)

        await cb.call(failing_fn, fallback=None)
        assert cb.state is CircuitState.OPEN

        # Wait for transition to HALF_OPEN
        await asyncio.sleep(0.1)

        # Trigger half-open check with a call
        async def success_fn() -> str:
            await asyncio.sleep(0)
            return "success"

        await cb.call(success_fn)
        # Force state for test (in real scenario would happen via timeout)
        cb._state.state = CircuitState.HALF_OPEN
        cb._state.half_open_calls = 0

        # Now fail in HALF_OPEN
        await cb.call(failing_fn, fallback=None)
        assert cb.state is CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_half_open_limits_concurrent_calls(self) -> None:
        """HALF_OPEN state should limit concurrent probe calls."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            timeout_seconds=0.05,
            half_open_max_calls=1,
        )
        cb = CircuitBreaker("test", config)

        # Open the circuit
        async def failing_fn() -> None:
            await asyncio.sleep(0)
            raise RuntimeError(_TEST_ERROR_MSG)

        await cb.call(failing_fn, fallback=None)
        await asyncio.sleep(0.1)

        # Force HALF_OPEN state with max calls reached
        cb._state.state = CircuitState.HALF_OPEN
        cb._state.half_open_calls = 1

        # Should return fallback due to call limit
        call_count = 0

        async def tracked_fn() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0)
            return "result"

        result = await cb.call(tracked_fn, fallback="limited")
        assert result == "limited"
        assert call_count == 0


class TestCircuitBreakerReset:
    """Tests for manual reset functionality."""

    @pytest.mark.asyncio
    async def test_manual_reset_closes_circuit(self) -> None:
        """Manual reset should close circuit and clear counters."""
        config = CircuitBreakerConfig(failure_threshold=1)
        cb = CircuitBreaker("test", config)

        # Open the circuit
        async def failing_fn() -> None:
            await asyncio.sleep(0)
            raise RuntimeError(_TEST_ERROR_MSG)

        await cb.call(failing_fn, fallback=None)
        assert cb.state is CircuitState.OPEN

        # Reset
        cb.reset()

        assert cb.state is CircuitState.CLOSED
        assert cb._state.failure_count == 0
        assert cb._state.success_count == 0
        assert cb._state.half_open_calls == 0

    @pytest.mark.asyncio
    async def test_reset_allows_new_calls(self) -> None:
        """After reset, calls should work normally."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout_seconds=60)
        cb = CircuitBreaker("test", config)

        # Open the circuit
        async def failing_fn() -> None:
            await asyncio.sleep(0)
            raise RuntimeError(_TEST_ERROR_MSG)

        await cb.call(failing_fn, fallback=None)
        assert cb.state is CircuitState.OPEN

        # Reset
        cb.reset()

        # Now calls should work
        async def success_fn() -> str:
            await asyncio.sleep(0)
            return "working"

        result = await cb.call(success_fn)
        assert result == "working"


class TestCircuitBreakerThreadSafety:
    """Tests for thread safety (async lock behavior)."""

    @pytest.mark.asyncio
    async def test_concurrent_calls_are_safe(self) -> None:
        """Concurrent calls should not corrupt state."""
        config = CircuitBreakerConfig(failure_threshold=100)
        cb = CircuitBreaker("test", config)

        call_count = 0

        async def slow_fn() -> str:
            await asyncio.sleep(0)
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            return "result"

        # Run many concurrent calls
        tasks = [cb.call(slow_fn) for _ in range(50)]
        results = await asyncio.gather(*tasks)

        assert all(r == "result" for r in results)
        assert call_count == 50
        assert cb.state is CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_concurrent_failures_track_correctly(self) -> None:
        """Concurrent failures should be tracked correctly."""
        config = CircuitBreakerConfig(failure_threshold=20)
        cb = CircuitBreaker("test", config)

        async def failing_fn() -> None:
            await asyncio.sleep(0.001)
            raise RuntimeError(_TEST_ERROR_MSG)

        # Run concurrent failures
        tasks = [cb.call(failing_fn, fallback=None) for _ in range(25)]
        await asyncio.gather(*tasks)

        # Circuit should be open (we exceeded threshold)
        assert cb.state is CircuitState.OPEN


class TestCircuitBreakerLogging:
    """Tests for logging behavior."""

    @pytest.mark.asyncio
    async def test_logs_on_circuit_open(self) -> None:
        """Should log when circuit opens."""
        config = CircuitBreakerConfig(failure_threshold=1)
        cb = CircuitBreaker("test-circuit", config)

        async def failing_fn() -> None:
            await asyncio.sleep(0)
            raise RuntimeError(_TEST_ERROR_MSG)

        with patch("nohiki_redis_utils.circuit_breaker.logger") as mock_logger:
            await cb.call(failing_fn, fallback=None)
            # Verify warning was logged about circuit opening
            mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_logs_on_manual_reset(self) -> None:
        """Should log when circuit is manually reset."""
        cb = CircuitBreaker("test-circuit")

        with patch("nohiki_redis_utils.circuit_breaker.logger") as mock_logger:
            cb.reset()
            mock_logger.info.assert_called()


class TestCircuitBreakerIntegration:
    """Integration tests simulating real usage patterns."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self) -> None:
        """Test complete circuit breaker lifecycle."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=2,
            timeout_seconds=0.1,
        )
        cb = CircuitBreaker("lifecycle-test", config)

        # 1. Start CLOSED
        assert cb.state is CircuitState.CLOSED

        # 2. Accumulate failures
        async def failing_fn() -> None:
            await asyncio.sleep(0)
            raise RuntimeError(_TEST_ERROR_MSG)

        for _ in range(3):
            await cb.call(failing_fn, fallback=None)

        # 3. Circuit OPEN
        assert cb.state is CircuitState.OPEN

        # 4. Wait for timeout
        await asyncio.sleep(0.15)

        # 5. Transition to HALF_OPEN on next call
        async def success_fn() -> str:
            await asyncio.sleep(0)
            return "ok"

        await cb.call(success_fn)
        # First success in half-open
        assert cb.state is CircuitState.HALF_OPEN

        # 6. Second success closes circuit
        await cb.call(success_fn)
        assert cb.state is CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_redis_cache_simulation(self) -> None:
        """Simulate Redis cache usage with circuit breaker."""
        config = CircuitBreakerConfig(failure_threshold=2)
        cb = CircuitBreaker("redis-sim", config)

        # Simulate Redis operations
        redis_available = True

        async def redis_get(key: str) -> str | None:
            await asyncio.sleep(0)
            if not redis_available:
                raise ConnectionError(_REDIS_UNAVAILABLE_MSG)
            return f"value-{key}"

        # Normal operation
        result = await cb.call(lambda: redis_get("key1"), fallback=None)
        assert result == "value-key1"

        # Redis goes down
        redis_available = False
        await cb.call(lambda: redis_get("key2"), fallback=None)
        await cb.call(lambda: redis_get("key3"), fallback=None)

        # Circuit should be open
        assert cb.state is CircuitState.OPEN

        # Calls should return fallback without trying Redis
        result = await cb.call(lambda: redis_get("key4"), fallback="cached")
        assert result == "cached"


class TestCircuitBreakerStateGetLockNoLoop:
    """Tests for _CircuitBreakerState.get_lock when no event loop is running."""

    def test_get_lock_without_running_loop(self) -> None:
        """get_lock() creates lock even without a running event loop."""
        from nohiki_redis_utils.circuit_breaker import _CircuitBreakerState

        state = _CircuitBreakerState()
        lock = state.get_lock()
        assert isinstance(lock, asyncio.Lock)
        assert state._lock_loop_id is None


class TestCircuitBreakerHalfOpenMaxCalls:
    """Tests for half-open state at max probe limit."""

    @pytest.mark.asyncio
    async def test_can_execute_returns_false_at_max_half_open_calls(self) -> None:
        """can_execute() returns False when half_open_calls >= max."""
        cb = CircuitBreaker(
            "test",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                half_open_max_calls=1,
                timeout_seconds=0.01,
            ),
        )

        async def fail() -> None:
            raise RuntimeError(_TEST_ERROR_MSG)

        await cb.call(fail, fallback=None)
        assert cb.state is CircuitState.OPEN

        await asyncio.sleep(0.02)

        assert await cb.can_execute() is True
        assert cb.state is CircuitState.HALF_OPEN
        assert await cb.can_execute() is False


class TestCircuitBreakerRecordFailureNone:
    """Tests for record_failure with no error argument."""

    @pytest.mark.asyncio
    async def test_record_failure_without_error_creates_default(self) -> None:
        """record_failure(None) creates a default Exception."""
        cb = CircuitBreaker("test", config=CircuitBreakerConfig(failure_threshold=2))
        await cb.record_failure()
        assert cb._state.failure_count == 1


class TestCircuitBreakerGetRetryAfter:
    """Tests for get_retry_after method."""

    def test_returns_none_when_not_open(self) -> None:
        """get_retry_after() returns None when circuit is CLOSED."""
        cb = CircuitBreaker("test")
        assert cb.get_retry_after() is None

    @pytest.mark.asyncio
    async def test_returns_none_when_timeout_elapsed(self) -> None:
        """get_retry_after() returns None when timeout has elapsed."""
        cb = CircuitBreaker(
            "test",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                timeout_seconds=0.01,
            ),
        )

        async def fail() -> None:
            raise RuntimeError(_TEST_ERROR_MSG)

        await cb.call(fail, fallback=None)
        assert cb.state is CircuitState.OPEN

        await asyncio.sleep(0.02)
        assert cb.get_retry_after() is None

    @pytest.mark.asyncio
    async def test_returns_remaining_seconds_when_open(self) -> None:
        """get_retry_after() returns positive float when circuit is OPEN."""
        cb = CircuitBreaker(
            "test",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                timeout_seconds=60.0,
            ),
        )

        async def fail() -> None:
            raise RuntimeError(_TEST_ERROR_MSG)

        await cb.call(fail, fallback=None)
        assert cb.state is CircuitState.OPEN

        remaining = cb.get_retry_after()
        assert remaining is not None
        assert remaining > 0


class TestCircuitBreakerReleaseHalfOpenSlot:
    """Tests for release_half_open_slot method."""

    @pytest.mark.asyncio
    async def test_release_slot_decrements_half_open_calls(self) -> None:
        """release_half_open_slot() decrements counter in HALF_OPEN state."""
        cb = CircuitBreaker(
            "test",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                half_open_max_calls=2,
                timeout_seconds=0.01,
            ),
        )

        async def fail() -> None:
            raise RuntimeError(_TEST_ERROR_MSG)

        await cb.call(fail, fallback=None)
        assert cb.state is CircuitState.OPEN

        await asyncio.sleep(0.02)

        assert await cb.can_execute() is True
        assert cb.state is CircuitState.HALF_OPEN
        assert cb._state.half_open_calls == 1

        cb.release_half_open_slot()
        assert cb._state.half_open_calls == 0
