"""Tests for circuit_breaker decorator."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from nohiki_redis_utils import CircuitOpenError, circuit_breaker
from nohiki_redis_utils.circuit_breaker import CircuitBreakerConfig, CircuitState
from nohiki_redis_utils.circuit_breaker_decorator import (
    _CircuitBreakerProxy,
    _Components,
    _DecoratorConfig,
    _ExcludedExceptionHandler,
    _Executor,
    _FallbackResolver,
    _StateChangeNotifier,
)

ERR_FAIL = "fail"
ERR_INVALID_INPUT = "invalid input"


class SimulatedError(Exception):
    """Simulated exception for circuit breaker tests."""


class SimulatedValidationError(Exception):
    """Simulated validation error that should be excluded."""


# CircuitOpenError Tests


class TestCircuitOpenError:
    """Tests for CircuitOpenError exception."""

    def test_message_without_retry(self) -> None:
        """Error message is correct without retry_after."""
        err = CircuitOpenError("test-circuit")
        assert str(err) == "Circuit 'test-circuit' is open"
        assert err.name == "test-circuit"
        assert err.retry_after is None

    def test_message_with_retry(self) -> None:
        """Verify error message includes retry_after when provided."""
        err = CircuitOpenError("test-circuit", retry_after=15.5)
        assert str(err) == "Circuit 'test-circuit' is open. Retry after 15.5s"
        assert err.retry_after is not None
        assert abs(err.retry_after - 15.5) < 0.01


# _FallbackResolver Tests


class TestFallbackResolver:
    """Tests for _FallbackResolver helper class."""

    async def test_resolve_none(self) -> None:
        """Returns None when no fallback configured."""
        resolver: _FallbackResolver[str] = _FallbackResolver(None)
        assert not resolver.has_fallback
        result = await resolver.resolve()
        assert result is None

    async def test_resolve_static_value(self) -> None:
        """Returns static value directly."""
        resolver: _FallbackResolver[dict[str, str]] = _FallbackResolver({"key": "value"})
        assert resolver.has_fallback
        result = await resolver.resolve()
        assert result == {"key": "value"}

    async def test_resolve_sync_callable(self) -> None:
        """Calls sync callable and returns result."""
        resolver: _FallbackResolver[str] = _FallbackResolver(lambda: "sync-result")
        assert resolver.has_fallback
        result = await resolver.resolve()
        assert result == "sync-result"

    async def test_resolve_async_callable(self) -> None:
        """Awaits async callable and returns result."""

        async def async_fallback() -> str:
            await asyncio.sleep(0)
            return "async-result"

        resolver: _FallbackResolver[str] = _FallbackResolver(async_fallback)
        assert resolver.has_fallback
        result = await resolver.resolve()
        assert result == "async-result"


# _StateChangeNotifier Tests


class TestStateChangeNotifier:
    """Tests for _StateChangeNotifier helper class."""

    def test_no_callback_no_notification(self) -> None:
        """No notification when callback is None."""
        notifier = _StateChangeNotifier("test", None)
        notifier.initialize(CircuitState.CLOSED)
        # Should not raise
        notifier.check_and_notify(CircuitState.OPEN)

    def test_callback_invoked_on_change(self) -> None:
        """Callback is invoked when state changes."""
        callback = MagicMock()
        notifier = _StateChangeNotifier("test", callback)
        notifier.initialize(CircuitState.CLOSED)

        notifier.check_and_notify(CircuitState.OPEN)

        callback.assert_called_once_with(CircuitState.CLOSED, CircuitState.OPEN)

    def test_callback_not_invoked_when_same_state(self) -> None:
        """Callback is not invoked when state is the same."""
        callback = MagicMock()
        notifier = _StateChangeNotifier("test", callback)
        notifier.initialize(CircuitState.CLOSED)

        notifier.check_and_notify(CircuitState.CLOSED)

        callback.assert_not_called()

    def test_callback_not_invoked_before_initialize(self) -> None:
        """Callback is not invoked before initialize is called."""
        callback = MagicMock()
        notifier = _StateChangeNotifier("test", callback)

        notifier.check_and_notify(CircuitState.OPEN)

        callback.assert_not_called()

    def test_notify_early_return_when_no_callback(self) -> None:
        """_notify returns early when callback is None."""
        notifier = _StateChangeNotifier("test", None)
        notifier._last_state = CircuitState.CLOSED
        # Call _notify directly - should return early without error
        notifier._notify(CircuitState.OPEN)


# _ExcludedExceptionHandler Tests


class TestExcludedExceptionHandler:
    """Tests for _ExcludedExceptionHandler helper class."""

    def test_no_excluded_exceptions(self) -> None:
        """Returns False when no exceptions are excluded."""
        handler = _ExcludedExceptionHandler("test", ())
        assert not handler.is_excluded(SimulatedError("test"))

    def test_excluded_exception_detected(self) -> None:
        """Returns True for excluded exception types."""
        handler = _ExcludedExceptionHandler("test", (SimulatedValidationError,))
        assert handler.is_excluded(SimulatedValidationError("invalid"))
        assert not handler.is_excluded(SimulatedError("test"))

    def test_excluded_exception_subclass(self) -> None:
        """Returns True for subclasses of excluded exceptions."""

        class SpecificSimulatedValidationError(SimulatedValidationError):
            pass

        handler = _ExcludedExceptionHandler("test", (SimulatedValidationError,))
        assert handler.is_excluded(SpecificSimulatedValidationError("specific"))


# _CircuitBreakerProxy Tests


class TestCircuitBreakerProxy:
    """Tests for _CircuitBreakerProxy helper class."""

    def test_state_property(self) -> None:
        """State property delegates to breaker."""
        mock_breaker = MagicMock()
        mock_breaker.state = CircuitState.OPEN
        proxy = _CircuitBreakerProxy(lambda: mock_breaker)

        assert proxy.state == CircuitState.OPEN

    def test_is_closed_property(self) -> None:
        """is_closed property delegates to breaker."""
        mock_breaker = MagicMock()
        mock_breaker.is_closed = True
        proxy = _CircuitBreakerProxy(lambda: mock_breaker)

        assert proxy.is_closed is True

    def test_reset_method(self) -> None:
        """Reset method delegates to breaker."""
        mock_breaker = MagicMock()
        proxy = _CircuitBreakerProxy(lambda: mock_breaker)

        proxy.reset()

        mock_breaker.reset.assert_called_once()

    def test_repr(self) -> None:
        """Repr delegates to breaker."""
        mock_breaker = MagicMock()
        mock_breaker.__repr__ = MagicMock(return_value="<CircuitBreaker test>")
        proxy = _CircuitBreakerProxy(lambda: mock_breaker)

        result = repr(proxy)

        assert result == "<CircuitBreaker test>"


# _Components Tests


class TestComponents:
    """Tests for _Components helper class."""

    def test_get_or_create_breaker_creates_once(self) -> None:
        """Breaker is created only once."""
        config = _DecoratorConfig(name="test")
        components: _Components[str] = _Components(
            config=config,
            fallback_resolver=_FallbackResolver(None),
            state_notifier=_StateChangeNotifier("test", None),
            exception_handler=_ExcludedExceptionHandler("test", ()),
        )

        breaker1 = components.get_or_create_breaker("func")
        breaker2 = components.get_or_create_breaker("func")

        assert breaker1 is breaker2

    def test_create_executor(self) -> None:
        """Creates executor with correct components."""
        config = _DecoratorConfig(name="test")
        components: _Components[str] = _Components(
            config=config,
            fallback_resolver=_FallbackResolver(None),
            state_notifier=_StateChangeNotifier("test", None),
            exception_handler=_ExcludedExceptionHandler("test", ()),
        )
        breaker = components.get_or_create_breaker("func")

        executor = components.create_executor(breaker)

        assert executor.breaker is breaker
        assert executor.circuit_name == "test"


# Decorator Basic Functionality Tests


class TestCircuitBreakerDecoratorBasic:
    """Tests for basic decorator functionality."""

    async def test_successful_call_returns_result(self) -> None:
        """Successful call returns the function result."""

        @circuit_breaker("test-success")
        async def successful_func() -> str:
            await asyncio.sleep(0)
            return "success"

        result = await successful_func()
        assert result == "success"

    def test_preserves_function_metadata(self) -> None:
        """Decorator preserves function name and docstring."""

        @circuit_breaker("test-metadata")
        async def documented_func() -> str:
            """Return a result for testing."""
            await asyncio.sleep(0)
            return "result"

        assert documented_func.__name__ == "documented_func"
        assert documented_func.__doc__ == "Return a result for testing."

    async def test_passes_arguments_correctly(self) -> None:
        """Arguments are passed to the decorated function."""

        @circuit_breaker("test-args")
        async def func_with_args(a: int, b: str, *, flag: bool = False) -> tuple[int, str, bool]:
            await asyncio.sleep(0)
            return (a, b, flag)

        result = await func_with_args(1, "two", flag=True)
        assert result == (1, "two", True)


# Circuit Opens After Failures Tests


class TestCircuitBreakerOpensAfterFailures:
    """Tests for circuit opening after failure threshold."""

    async def test_circuit_opens_after_failure_threshold(self) -> None:
        """Circuit opens after reaching failure threshold."""

        @circuit_breaker(
            "test-open",
            config=CircuitBreakerConfig(failure_threshold=3),
            fallback="fallback",
        )
        async def failing_func() -> str:
            raise SimulatedError(ERR_FAIL)

        # First 3 calls fail but circuit stays closed
        for _ in range(3):
            result = await failing_func()
            assert result == "fallback"

        # Circuit should now be open
        proxy = failing_func.circuit_breaker
        assert proxy.state == CircuitState.OPEN

    async def test_raises_circuit_open_error_when_no_fallback(self) -> None:
        """Raises CircuitOpenError when circuit is open and no fallback."""

        @circuit_breaker(
            "test-no-fallback",
            config=CircuitBreakerConfig(failure_threshold=1, timeout_seconds=3600),
        )
        async def failing_func() -> str:
            raise SimulatedError(ERR_FAIL)

        # First call fails and opens circuit
        with pytest.raises(SimulatedError):
            await failing_func()

        # Second call should raise CircuitOpenError
        with pytest.raises(CircuitOpenError) as exc_info:
            await failing_func()

        assert exc_info.value.name == "test-no-fallback"


# Fallback Tests


class TestCircuitBreakerFallback:
    """Tests for fallback functionality."""

    async def test_static_fallback_returned_when_open(self) -> None:
        """Static fallback value is returned when circuit is open."""

        @circuit_breaker(
            "test-static-fallback",
            config=CircuitBreakerConfig(failure_threshold=1, timeout_seconds=3600),
            fallback={"status": "unavailable"},
        )
        async def failing_func() -> dict[str, str]:
            raise SimulatedError(ERR_FAIL)

        # First call fails
        result = await failing_func()
        assert result == {"status": "unavailable"}

        # Circuit is open, fallback returned
        result = await failing_func()
        assert result == {"status": "unavailable"}

    async def test_sync_callable_fallback(self) -> None:
        """Sync callable fallback is called when circuit is open."""
        call_count = 0

        def sync_fallback() -> str:
            nonlocal call_count
            call_count += 1
            return f"fallback-{call_count}"

        @circuit_breaker(
            "test-sync-fallback",
            config=CircuitBreakerConfig(failure_threshold=1, timeout_seconds=3600),
            fallback=sync_fallback,
        )
        async def failing_func() -> str:
            raise SimulatedError(ERR_FAIL)

        result1 = await failing_func()
        result2 = await failing_func()

        assert result1 == "fallback-1"
        assert result2 == "fallback-2"

    async def test_async_callable_fallback(self) -> None:
        """Async callable fallback is awaited when circuit is open."""

        async def async_fallback() -> str:
            await asyncio.sleep(0)
            return "async-fallback"

        @circuit_breaker(
            "test-async-fallback",
            config=CircuitBreakerConfig(failure_threshold=1),
            fallback=async_fallback,
        )
        async def failing_func() -> str:
            raise SimulatedError(ERR_FAIL)

        result = await failing_func()
        assert result == "async-fallback"

    async def test_fallback_on_failure_before_circuit_opens(self) -> None:
        """Fallback is returned on failure even before circuit opens."""

        @circuit_breaker(
            "test-fallback-before-open",
            config=CircuitBreakerConfig(failure_threshold=5),
            fallback="fallback",
        )
        async def failing_func() -> str:
            raise SimulatedError(ERR_FAIL)

        result = await failing_func()
        assert result == "fallback"
        # Circuit should still be closed (threshold not reached)
        proxy = failing_func.circuit_breaker
        assert proxy.state == CircuitState.CLOSED


# State Transition Tests


class TestCircuitBreakerStateTransitions:
    """Tests for circuit state transitions."""

    async def test_transitions_to_half_open_after_timeout(self) -> None:
        """Circuit transitions to half-open after timeout."""

        @circuit_breaker(
            "test-half-open",
            config=CircuitBreakerConfig(failure_threshold=1, timeout_seconds=0.1),
            fallback="fallback",
        )
        async def failing_func() -> str:
            raise SimulatedError(ERR_FAIL)

        # Open the circuit
        await failing_func()
        proxy = failing_func.circuit_breaker
        assert proxy.state == CircuitState.OPEN

        # Wait for timeout
        import asyncio

        await asyncio.sleep(0.15)

        # Next call should transition to half-open
        await failing_func()
        # After failure in half-open, goes back to open
        assert proxy.state == CircuitState.OPEN

    async def test_closes_after_successful_probes(self) -> None:
        """Circuit closes after successful probes in half-open."""
        call_count = 0

        @circuit_breaker(
            "test-close",
            config=CircuitBreakerConfig(failure_threshold=1, success_threshold=2, timeout_seconds=0.1),
            fallback="fallback",
        )
        async def sometimes_failing_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SimulatedError(ERR_FAIL)
            return "success"

        # First call fails, opens circuit
        await sometimes_failing_func()
        proxy = sometimes_failing_func.circuit_breaker
        assert proxy.state == CircuitState.OPEN

        # Wait for timeout
        import asyncio

        await asyncio.sleep(0.15)

        # Successful probes should close circuit
        await sometimes_failing_func()
        await sometimes_failing_func()

        assert proxy.state == CircuitState.CLOSED


# Excluded Exceptions Tests


class TestCircuitBreakerExcludedExceptions:
    """Tests for excluded exceptions functionality."""

    async def test_excluded_exceptions_dont_trip_circuit(self) -> None:
        """Excluded exceptions don't count as failures."""
        call_count = 0

        @circuit_breaker(
            "test-excluded",
            config=CircuitBreakerConfig(failure_threshold=2),
            excluded_exceptions=(SimulatedValidationError,),
        )
        async def func_with_validation() -> str:
            nonlocal call_count
            call_count += 1
            raise SimulatedValidationError(ERR_INVALID_INPUT)

        # Multiple validation errors should not open circuit
        for _ in range(5):
            with pytest.raises(SimulatedValidationError):
                await func_with_validation()

        # Circuit should still be closed
        proxy = func_with_validation.circuit_breaker
        assert proxy.state == CircuitState.CLOSED

    async def test_excluded_exceptions_are_reraised(self) -> None:
        """Excluded exceptions are re-raised to caller."""

        @circuit_breaker(
            "test-reraise",
            excluded_exceptions=(SimulatedValidationError,),
        )
        async def func_with_validation() -> str:
            raise SimulatedValidationError(ERR_INVALID_INPUT)

        with pytest.raises(SimulatedValidationError, match=ERR_INVALID_INPUT):
            await func_with_validation()


# State Change Callback Tests


class TestCircuitBreakerStateChangeCallback:
    """Tests for state change callback functionality."""

    async def test_callback_invoked_on_state_change(self) -> None:
        """Callback is invoked when circuit state changes."""
        state_changes: list[tuple[CircuitState, CircuitState]] = []

        def on_change(old: CircuitState, new: CircuitState) -> None:
            state_changes.append((old, new))

        @circuit_breaker(
            "test-callback",
            config=CircuitBreakerConfig(failure_threshold=1),
            fallback="fallback",
            on_state_change=on_change,
        )
        async def failing_func() -> str:
            raise SimulatedError(ERR_FAIL)

        await failing_func()

        assert len(state_changes) == 1
        assert state_changes[0] == (CircuitState.CLOSED, CircuitState.OPEN)


# Circuit Breaker Accessor Tests


class TestCircuitBreakerAccessor:
    """Tests for circuit breaker accessor on wrapper."""

    def test_circuit_breaker_accessible_on_wrapper(self) -> None:
        """Circuit breaker is accessible via wrapper.circuit_breaker."""

        @circuit_breaker("test-accessor")
        async def my_func() -> str:
            return "result"

        # Access before any calls (lazy init)
        proxy = my_func.circuit_breaker
        assert proxy.state == CircuitState.CLOSED

    async def test_manual_reset_works(self) -> None:
        """Manual reset returns circuit to closed state."""

        @circuit_breaker(
            "test-reset",
            config=CircuitBreakerConfig(failure_threshold=1),
            fallback="fallback",
        )
        async def failing_func() -> str:
            raise SimulatedError(ERR_FAIL)

        # Open the circuit
        await failing_func()
        proxy = failing_func.circuit_breaker
        assert proxy.state == CircuitState.OPEN

        # Reset
        proxy.reset()
        assert proxy.state == CircuitState.CLOSED


# Independence Tests


class TestCircuitBreakerIndependence:
    """Tests for circuit breaker independence between functions."""

    async def test_separate_circuits_are_independent(self) -> None:
        """Different decorated functions have independent circuits."""

        @circuit_breaker(
            "circuit-a",
            config=CircuitBreakerConfig(failure_threshold=1),
            fallback="fallback-a",
        )
        async def func_a() -> str:
            raise SimulatedError(ERR_FAIL)

        @circuit_breaker(
            "circuit-b",
            config=CircuitBreakerConfig(failure_threshold=1),
            fallback="fallback-b",
        )
        async def func_b() -> str:
            raise SimulatedError(ERR_FAIL)

        # Open circuit A
        await func_a()
        proxy_a = func_a.circuit_breaker
        assert proxy_a.state == CircuitState.OPEN

        # Circuit B should still be closed
        proxy_b = func_b.circuit_breaker
        assert proxy_b.state == CircuitState.CLOSED


# Configuration Tests


class TestCircuitBreakerConfiguration:
    """Tests for circuit breaker configuration options."""

    async def test_custom_failure_threshold(self) -> None:
        """Custom failure threshold is respected."""

        @circuit_breaker(
            "test-threshold",
            config=CircuitBreakerConfig(failure_threshold=5),
            fallback="fallback",
        )
        async def failing_func() -> str:
            raise SimulatedError(ERR_FAIL)

        # 4 failures should not open circuit
        for _ in range(4):
            await failing_func()

        proxy = failing_func.circuit_breaker
        assert proxy.state == CircuitState.CLOSED

        # 5th failure opens circuit
        await failing_func()
        assert proxy.state == CircuitState.OPEN

    async def test_custom_timeout_seconds(self) -> None:
        """Custom timeout is respected for half-open transition."""
        import asyncio

        @circuit_breaker(
            "test-timeout",
            config=CircuitBreakerConfig(failure_threshold=1, timeout_seconds=0.2),
            fallback="fallback",
        )
        async def failing_func() -> str:
            raise SimulatedError(ERR_FAIL)

        # Open circuit
        await failing_func()

        # Wait less than timeout
        await asyncio.sleep(0.05)

        # Should still be open (fallback returned, no state change)
        result = await failing_func()
        assert result == "fallback"
        proxy = failing_func.circuit_breaker
        assert proxy.state == CircuitState.OPEN


# _Executor Tests


class TestExecutor:
    """Tests for _Executor class."""

    async def test_execute_success(self) -> None:
        """Successful execution returns result."""
        from nohiki_redis_utils.circuit_breaker import CircuitBreaker

        breaker = CircuitBreaker("test")
        executor: _Executor[str] = _Executor(
            breaker=breaker,
            fallback_resolver=_FallbackResolver(None),
            state_notifier=_StateChangeNotifier("test", None),
            exception_handler=_ExcludedExceptionHandler("test", ()),
            circuit_name="test",
        )

        async def success_func() -> str:
            await asyncio.sleep(0)
            return "success"

        result = await executor.execute(success_func, (), {})
        assert result == "success"

    async def test_execute_with_fallback_on_failure(self) -> None:
        """Fallback is returned on failure."""
        from nohiki_redis_utils.circuit_breaker import CircuitBreaker

        breaker = CircuitBreaker("test")
        executor: _Executor[str] = _Executor(
            breaker=breaker,
            fallback_resolver=_FallbackResolver("fallback"),
            state_notifier=_StateChangeNotifier("test", None),
            exception_handler=_ExcludedExceptionHandler("test", ()),
            circuit_name="test",
        )

        async def failing_func() -> str:
            raise SimulatedError(ERR_FAIL)

        result = await executor.execute(failing_func, (), {})
        assert result == "fallback"


# _DecoratorConfig Tests


class TestDecoratorConfig:
    """Tests for _DecoratorConfig class."""

    def test_to_breaker_config(self) -> None:
        """Converts to CircuitBreakerConfig correctly."""
        config = _DecoratorConfig(
            name="test",
            failure_threshold=10,
            success_threshold=3,
            timeout_seconds=60.0,
            half_open_max_calls=2,
        )

        breaker_config = config.to_breaker_config()

        assert breaker_config.failure_threshold == 10
        assert breaker_config.success_threshold == 3
        assert abs(breaker_config.timeout_seconds - 60.0) < 0.001
        assert breaker_config.half_open_max_calls == 2

    def test_default_values(self) -> None:
        """Default values are set correctly."""
        config = _DecoratorConfig(name="test")

        assert config.failure_threshold == 5
        assert config.success_threshold == 2
        assert abs(config.timeout_seconds - 30.0) < 0.001
        assert config.half_open_max_calls == 1
        assert config.excluded_exceptions == ()
