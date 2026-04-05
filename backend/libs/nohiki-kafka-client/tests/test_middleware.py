"""Tests for middleware protocol and chain execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock

import betterproto2
import pytest
from nohiki_kafka_client.handlers import MessageContext
from nohiki_kafka_client.middleware.protocol import Middleware, NextHandler, execute_middleware_chain


class SimpleMiddleware:
    """Test middleware that tracks calls."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.pre_calls: list[str] = []
        self.post_calls: list[str] = []

    async def __call__(
        self,
        message: betterproto2.Message,
        context: MessageContext,
        call_next: Callable[[betterproto2.Message, MessageContext], Awaitable[None]],
    ) -> None:
        self.pre_calls.append(f"{self.name}:pre")
        await call_next(message, context)
        self.post_calls.append(f"{self.name}:post")


class ShortCircuitMiddleware:
    """Middleware that short-circuits without calling next."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(
        self,
        message: betterproto2.Message,
        context: MessageContext,
        call_next: Callable[[betterproto2.Message, MessageContext], Awaitable[None]],
    ) -> None:
        self.called = True


class ContextModifyingMiddleware:
    """Middleware that modifies context."""

    def __init__(self, key: str, value: object) -> None:
        self.key = key
        self.value = value

    async def __call__(
        self,
        message: betterproto2.Message,
        context: MessageContext,
        call_next: Callable[[betterproto2.Message, MessageContext], Awaitable[None]],
    ) -> None:
        if context.processing_metadata is None:
            context.processing_metadata = {}
        context.processing_metadata[self.key] = self.value
        await call_next(message, context)


@pytest.fixture
def mock_message() -> MagicMock:
    """Create a mock betterproto2 message."""
    return MagicMock(spec=betterproto2.Message)


@pytest.fixture
def mock_context() -> MessageContext:
    """Create a test MessageContext."""
    return MessageContext(
        topic="test.topic",
        partition=0,
        offset=0,
        timestamp=1234567890,
        headers={},
        key=None,
    )


class TestMiddlewareProtocol:
    """Tests for Middleware protocol compliance."""

    def test_simple_middleware_is_middleware(self) -> None:
        """SimpleMiddleware should be a valid Middleware."""
        mw = SimpleMiddleware("test")
        assert isinstance(mw, Middleware)

    def test_short_circuit_middleware_is_middleware(self) -> None:
        """ShortCircuitMiddleware should be a valid Middleware."""
        mw = ShortCircuitMiddleware()
        assert isinstance(mw, Middleware)

    def test_context_modifying_middleware_is_middleware(self) -> None:
        """ContextModifyingMiddleware should be a valid Middleware."""
        mw = ContextModifyingMiddleware("key", "value")
        assert isinstance(mw, Middleware)


class TestExecuteMiddlewareChain:
    """Tests for execute_middleware_chain function."""

    @pytest.mark.asyncio
    async def test_empty_middleware_calls_handler(
        self,
        mock_message: MagicMock,
        mock_context: MessageContext,
    ) -> None:
        """Empty middleware list should call handler directly."""
        handler = AsyncMock()

        await execute_middleware_chain([], handler, mock_message, mock_context)

        handler.assert_called_once_with(mock_message, mock_context)

    @pytest.mark.asyncio
    async def test_single_middleware_wraps_handler(
        self,
        mock_message: MagicMock,
        mock_context: MessageContext,
    ) -> None:
        """Single middleware should wrap handler."""
        mw = SimpleMiddleware("first")
        handler = AsyncMock()

        await execute_middleware_chain([mw], handler, mock_message, mock_context)

        handler.assert_called_once()
        assert mw.pre_calls == ["first:pre"]
        assert mw.post_calls == ["first:post"]

    @pytest.mark.asyncio
    async def test_multiple_middleware_onion_order(
        self,
        mock_message: MagicMock,
        mock_context: MessageContext,
    ) -> None:
        """Multiple middleware should execute in onion order."""
        mw1 = SimpleMiddleware("first")
        mw2 = SimpleMiddleware("second")
        mw3 = SimpleMiddleware("third")
        handler = AsyncMock()

        await execute_middleware_chain([mw1, mw2, mw3], handler, mock_message, mock_context)

        handler.assert_called_once()
        assert mw1.pre_calls == ["first:pre"]
        assert mw2.pre_calls == ["second:pre"]
        assert mw3.pre_calls == ["third:pre"]
        assert mw3.post_calls == ["third:post"]
        assert mw2.post_calls == ["second:post"]
        assert mw1.post_calls == ["first:post"]

    @pytest.mark.asyncio
    async def test_short_circuit_prevents_handler(
        self,
        mock_message: MagicMock,
        mock_context: MessageContext,
    ) -> None:
        """Short-circuit middleware should prevent handler execution."""
        mw1 = SimpleMiddleware("first")
        mw_short = ShortCircuitMiddleware()
        mw2 = SimpleMiddleware("second")
        handler = AsyncMock()

        await execute_middleware_chain([mw1, mw_short, mw2], handler, mock_message, mock_context)

        handler.assert_not_called()
        assert mw1.pre_calls == ["first:pre"]
        assert mw_short.called is True
        assert mw2.pre_calls == []
        assert mw1.post_calls == ["first:post"]

    @pytest.mark.asyncio
    async def test_context_modification_visible_to_handler(
        self,
        mock_message: MagicMock,
        mock_context: MessageContext,
    ) -> None:
        """Context modifications by middleware should be visible to handler."""
        mw = ContextModifyingMiddleware("test_key", "test_value")
        captured_metadata: dict[str, object] = {}

        async def handler(_msg: betterproto2.Message, ctx: MessageContext) -> None:
            if ctx.processing_metadata:
                captured_metadata.update(ctx.processing_metadata)

        await execute_middleware_chain([mw], handler, mock_message, mock_context)

        assert captured_metadata["test_key"] == "test_value"

    @pytest.mark.asyncio
    async def test_exception_propagates_through_chain(
        self,
        mock_message: MagicMock,
        mock_context: MessageContext,
    ) -> None:
        """Exceptions from handler should propagate through middleware."""
        mw = SimpleMiddleware("first")

        async def failing_handler(_msg: betterproto2.Message, _ctx: MessageContext) -> None:
            err_msg = "Handler failed"
            raise ValueError(err_msg)

        with pytest.raises(ValueError, match="Handler failed"):
            await execute_middleware_chain([mw], failing_handler, mock_message, mock_context)

        assert mw.pre_calls == ["first:pre"]
        assert mw.post_calls == []

    @pytest.mark.asyncio
    async def test_middleware_exception_stops_chain(
        self,
        mock_message: MagicMock,
        mock_context: MessageContext,
    ) -> None:
        """Exception in middleware should stop chain and propagate."""

        class FailingMiddleware:
            async def __call__(
                self,
                message: betterproto2.Message,
                context: MessageContext,
                call_next: NextHandler,
            ) -> None:
                err_msg = "Middleware failed"
                raise RuntimeError(err_msg)

        mw_fail: Middleware = FailingMiddleware()
        mw_after: Middleware = SimpleMiddleware("after")
        handler = AsyncMock()

        with pytest.raises(RuntimeError, match="Middleware failed"):
            await execute_middleware_chain([mw_fail, mw_after], handler, mock_message, mock_context)

        handler.assert_not_called()
        assert mw_after.pre_calls == []


class TestMiddlewareLazyImports:
    """Tests for middleware module __getattr__ lazy imports."""

    def test_getattr_returns_rate_limit_algorithm(self) -> None:
        """Test __getattr__ returns RateLimitAlgorithm when available."""
        from nohiki_kafka_client.middleware import RateLimitAlgorithm

        assert RateLimitAlgorithm is not None

    def test_getattr_returns_rate_limit_config(self) -> None:
        """Test __getattr__ returns RateLimitConfig when available."""
        from nohiki_kafka_client.middleware import RateLimitConfig

        assert RateLimitConfig is not None

    def test_getattr_returns_rate_limit_middleware(self) -> None:
        """Test __getattr__ returns RateLimitMiddleware when available."""
        from nohiki_kafka_client.middleware import RateLimitMiddleware

        assert RateLimitMiddleware is not None

    def test_getattr_raises_for_unknown_attribute(self) -> None:
        """Test __getattr__ raises AttributeError for unknown attributes."""
        from nohiki_kafka_client import middleware

        with pytest.raises(AttributeError, match=r"module .* has no attribute 'UnknownThing'"):
            _ = middleware.UnknownThing


class TestKafkaClientLazyImports:
    """Tests for top-level nohiki_kafka_client module __getattr__ lazy imports."""

    def test_getattr_returns_rate_limit_algorithm_from_toplevel(self) -> None:
        """Test __getattr__ returns RateLimitAlgorithm from top-level module."""
        from nohiki_kafka_client import RateLimitAlgorithm

        assert RateLimitAlgorithm is not None

    def test_getattr_returns_rate_limit_config_from_toplevel(self) -> None:
        """Test __getattr__ returns RateLimitConfig from top-level module."""
        from nohiki_kafka_client import RateLimitConfig

        assert RateLimitConfig is not None

    def test_getattr_returns_rate_limit_middleware_from_toplevel(self) -> None:
        """Test __getattr__ returns RateLimitMiddleware from top-level module."""
        from nohiki_kafka_client import RateLimitMiddleware

        assert RateLimitMiddleware is not None

    def test_getattr_raises_for_unknown_attribute_toplevel(self) -> None:
        """Test __getattr__ raises AttributeError for unknown attributes at top level."""
        import nohiki_kafka_client

        with pytest.raises(AttributeError, match=r"module .* has no attribute 'UnknownThing'"):
            _ = nohiki_kafka_client.UnknownThing
