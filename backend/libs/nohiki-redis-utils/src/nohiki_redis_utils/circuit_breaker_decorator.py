"""Circuit breaker decorator for async functions."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol, cast

from nohiki_observability import get_logger

from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState


class _AsyncFunc[**P, T](Protocol):
    """Protocol for async functions with __name__ attribute."""

    __name__: str

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[T]: ...


class CircuitBreakerWrapper[**P, T](Protocol):
    """Protocol for circuit breaker decorated functions."""

    __name__: str
    circuit_breaker: _CircuitBreakerProxy

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[T]:
        """Call the wrapped async function."""
        ...


logger = get_logger(__name__)


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open and no fallback is provided."""

    def __init__(self, name: str, retry_after: float | None = None) -> None:
        """Initialize exception with circuit name and optional retry hint."""
        self.name = name
        self.retry_after = retry_after
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        """Build the exception message."""
        msg = f"Circuit '{self.name}' is open"
        if self.retry_after is not None:
            msg += f". Retry after {self.retry_after:.1f}s"
        return msg


@dataclass(frozen=True, slots=True)
class _DecoratorConfig:
    """Internal configuration for the circuit breaker decorator."""

    name: str
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_seconds: float = 30.0
    half_open_max_calls: int = 1
    excluded_exceptions: tuple[type[Exception], ...] = ()

    def to_breaker_config(self) -> CircuitBreakerConfig:
        """Convert to CircuitBreakerConfig for the underlying breaker."""
        return CircuitBreakerConfig(
            failure_threshold=self.failure_threshold,
            success_threshold=self.success_threshold,
            timeout_seconds=self.timeout_seconds,
            half_open_max_calls=self.half_open_max_calls,
        )


@dataclass(slots=True)
class _RuntimeState:
    """Mutable runtime state for the circuit breaker decorator."""

    breaker: CircuitBreaker | None = None
    last_state: CircuitState | None = None


class _FallbackResolver:
    """Resolves fallback values, handling static values and callables."""

    def __init__(
        self,
        fallback: object | Callable[[], object] | Callable[[], Awaitable[object]] | None,
    ) -> None:
        """Initialize the resolver."""
        self._fallback = fallback
        self._is_async_callable = inspect.iscoroutinefunction(fallback)
        self._is_callable = callable(fallback)

    @property
    def has_fallback(self) -> bool:
        """Check if a fallback is configured."""
        return self._fallback is not None

    async def resolve(self) -> object:
        """Resolve the fallback value."""
        if self._fallback is None:
            return None
        return await self._resolve_non_none()

    async def _resolve_non_none(self) -> object:
        """Resolve when fallback is known to be non-None."""
        fallback = self._fallback
        if not self._is_callable:
            return fallback
        if self._is_async_callable:
            async_fn = cast("Callable[[], Awaitable[object]]", fallback)
            return await async_fn()
        sync_fn = cast("Callable[[], object]", fallback)
        return sync_fn()


class _StateChangeNotifier:
    """Notifies callbacks when circuit state changes."""

    def __init__(
        self,
        circuit_name: str,
        callback: Callable[[CircuitState, CircuitState], None] | None,
    ) -> None:
        """Initialize the notifier."""
        self._circuit_name = circuit_name
        self._callback = callback
        self._last_state: CircuitState | None = None

    def check_and_notify(self, current_state: CircuitState) -> None:
        """Check for state change and notify callback if changed."""
        if self._should_notify(current_state):
            self._notify(current_state)
        self._last_state = current_state

    def _should_notify(self, current_state: CircuitState) -> bool:
        """Determine if notification is needed."""
        if self._callback is None:
            return False
        if self._last_state is None:
            return False
        return self._last_state != current_state

    def _notify(self, current_state: CircuitState) -> None:
        """Send notification to callback."""
        if self._callback is None or self._last_state is None:
            return
        logger.info(
            "Circuit state changed",
            circuit=self._circuit_name,
            old_state=self._last_state.value,
            new_state=current_state.value,
        )
        self._callback(self._last_state, current_state)

    def initialize(self, initial_state: CircuitState) -> None:
        """Set the initial state without triggering notification."""
        self._last_state = initial_state


class _ExcludedExceptionHandler:
    """Handles exceptions that should not trip the circuit."""

    def __init__(
        self,
        circuit_name: str,
        excluded_exceptions: tuple[type[Exception], ...],
    ) -> None:
        """Initialize the handler."""
        self._circuit_name = circuit_name
        self._excluded_exceptions = excluded_exceptions

    def is_excluded(self, exc: Exception) -> bool:
        """Check if an exception should be excluded from failure tracking."""
        if not self._excluded_exceptions:
            return False
        return isinstance(exc, self._excluded_exceptions)

    def handle(self, exc: Exception, breaker: CircuitBreaker) -> None:
        """Handle an excluded exception by releasing the half-open slot."""
        logger.debug(
            "Excluded exception, not counting as failure",
            circuit=self._circuit_name,
            exception_type=type(exc).__name__,
        )
        breaker.release_half_open_slot()


class _CircuitBreakerProxy:
    """Proxy that provides access to the circuit breaker instance."""

    def __init__(self, breaker_getter: Callable[[], CircuitBreaker]) -> None:
        """Initialize the proxy."""
        self._get_breaker = breaker_getter

    @property
    def state(self) -> CircuitState:
        """Get the current circuit state."""
        return self._get_breaker().state

    @property
    def is_closed(self) -> bool:
        """Check if the circuit is closed."""
        return self._get_breaker().is_closed

    def reset(self) -> None:
        """Reset the circuit breaker."""
        self._get_breaker().reset()

    def __repr__(self) -> str:
        """Return string representation."""
        return repr(self._get_breaker())


@dataclass(slots=True)
class _Executor[T]:
    """Executes functions through the circuit breaker with proper handling."""

    breaker: CircuitBreaker
    fallback_resolver: _FallbackResolver
    state_notifier: _StateChangeNotifier
    exception_handler: _ExcludedExceptionHandler
    circuit_name: str

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> T:
        """Execute a function through the circuit breaker."""
        can_execute = await self.breaker.can_execute()
        self.state_notifier.check_and_notify(self.breaker.state)

        if not can_execute:
            return await self._handle_circuit_open()

        return await self._execute_function(func, args, kwargs)

    async def _handle_circuit_open(self) -> T:
        """Handle the case when the circuit is open."""
        logger.debug("Circuit open, using fallback", circuit=self.circuit_name)
        if not self.fallback_resolver.has_fallback:
            raise CircuitOpenError(self.circuit_name, self.breaker.get_retry_after())
        return cast("T", await self.fallback_resolver.resolve())

    async def _execute_function(
        self,
        func: Callable[..., Awaitable[T]],
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> T:
        """Execute the function and handle the result."""
        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            return await self._handle_exception(exc)
        return await self._handle_success(result)

    async def _handle_exception(self, exc: Exception) -> T:
        """Handle an exception during function execution."""
        if self.exception_handler.is_excluded(exc):
            self.exception_handler.handle(exc, self.breaker)
            raise exc from None  # NOSONAR - re-raising caught exception
        return await self._handle_failure(exc)

    async def _handle_failure(self, exc: Exception) -> T:
        """Handle a non-excluded failure."""
        await self.breaker.record_failure(exc)
        self.state_notifier.check_and_notify(self.breaker.state)

        if not self.fallback_resolver.has_fallback:
            raise exc from None  # NOSONAR - re-raising caught exception
        logger.debug(
            "Call failed, using fallback",
            circuit=self.circuit_name,
            exception_type=type(exc).__name__,
        )
        return cast("T", await self.fallback_resolver.resolve())

    async def _handle_success(self, result: T) -> T:
        """Handle a successful function execution."""
        await self.breaker.record_success()
        self.state_notifier.check_and_notify(self.breaker.state)
        return result


@dataclass(slots=True)
class _Components:
    """Components needed for the circuit breaker decorator."""

    config: _DecoratorConfig
    fallback_resolver: _FallbackResolver
    state_notifier: _StateChangeNotifier
    exception_handler: _ExcludedExceptionHandler
    runtime_state: _RuntimeState = field(default_factory=_RuntimeState)

    def get_or_create_breaker(self, func_name: str) -> CircuitBreaker:
        """Get or create the circuit breaker instance."""
        breaker = self.runtime_state.breaker
        if breaker is not None:
            return breaker
        return self._initialize_breaker(func_name)

    def _initialize_breaker(self, func_name: str) -> CircuitBreaker:
        """Initialize a new circuit breaker."""
        breaker = CircuitBreaker(
            self.config.name,
            self.config.to_breaker_config(),
        )
        self.runtime_state.breaker = breaker
        self.state_notifier.initialize(breaker.state)
        logger.debug(
            "Circuit breaker initialized",
            circuit=self.config.name,
            function=func_name,
        )
        return breaker

    def create_executor[T](self, breaker: CircuitBreaker) -> _Executor[T]:
        """Create an executor for the given breaker."""
        return _Executor(
            breaker=breaker,
            fallback_resolver=self.fallback_resolver,
            state_notifier=self.state_notifier,
            exception_handler=self.exception_handler,
            circuit_name=self.config.name,
        )


def _build_components(
    config: _DecoratorConfig,
    fallback: object | Callable[[], object] | Callable[[], Awaitable[object]] | None,
    on_state_change: Callable[[CircuitState, CircuitState], None] | None,
) -> _Components:
    """Build all components needed for the decorator."""
    return _Components(
        config=config,
        fallback_resolver=_FallbackResolver(fallback),
        state_notifier=_StateChangeNotifier(config.name, on_state_change),
        exception_handler=_ExcludedExceptionHandler(
            config.name,
            config.excluded_exceptions,
        ),
    )


def _create_wrapper[T, **P](
    func: _AsyncFunc[P, T],
    components: _Components,
) -> Callable[P, Awaitable[T]]:
    """Create the wrapper function for the decorator."""
    func_name = func.__name__

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        breaker = components.get_or_create_breaker(func_name)
        executor: _Executor[T] = components.create_executor(breaker)
        return await executor.execute(func, tuple(args), dict(kwargs))

    return wrapper


def _attach_proxy[T, **P](
    wrapper: Callable[P, Awaitable[T]],
    components: _Components,
    func_name: str,
) -> None:
    """Attach the circuit breaker proxy to the wrapper function."""
    proxy = _CircuitBreakerProxy(
        lambda: components.get_or_create_breaker(func_name),
    )
    object.__setattr__(wrapper, "circuit_breaker", proxy)


def circuit_breaker[T, **P](
    name: str,
    *,
    config: CircuitBreakerConfig | None = None,
    fallback: object | Callable[[], object] | Callable[[], Awaitable[object]] | None = None,
    excluded_exceptions: tuple[type[Exception], ...] = (),
    on_state_change: Callable[[CircuitState, CircuitState], None] | None = None,
) -> Callable[[_AsyncFunc[P, T]], CircuitBreakerWrapper[P, T]]:
    """Circuit breaker decorator for async functions.

    Protects against cascading failures by tracking consecutive failures
    and temporarily blocking calls when a threshold is reached.

    Args:
        name: Unique identifier for this circuit breaker (used in logging/metrics).
        config: Optional CircuitBreakerConfig object.
        fallback: Value or callable to return when circuit is open or call fails.
                  Can be sync or async callable. If None, exceptions are raised.
        excluded_exceptions: Exception types that should NOT trip the circuit.
                             These are re-raised without counting as failures.
        on_state_change: Optional callback when circuit state changes.

    Returns:
        Decorated async function with circuit breaker protection.

    Example:
        @circuit_breaker("llm-api", fallback={"error": "Service unavailable"})
        async def call_llm(prompt: str) -> dict:
            return await llm_client.process(prompt)

    """
    effective_config = config or CircuitBreakerConfig()

    decorator_config = _DecoratorConfig(
        name=name,
        failure_threshold=effective_config.failure_threshold,
        success_threshold=effective_config.success_threshold,
        timeout_seconds=effective_config.timeout_seconds,
        half_open_max_calls=effective_config.half_open_max_calls,
        excluded_exceptions=excluded_exceptions,
    )

    components = _build_components(decorator_config, fallback, on_state_change)

    def decorator(func: _AsyncFunc[P, T]) -> CircuitBreakerWrapper[P, T]:
        func_name = func.__name__
        wrapper = _create_wrapper(func, components)
        _attach_proxy(wrapper, components, func_name)
        return cast("CircuitBreakerWrapper[P, T]", wrapper)

    return decorator
