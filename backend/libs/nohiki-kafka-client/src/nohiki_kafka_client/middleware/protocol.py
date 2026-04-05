"""Middleware protocol and chain execution for Kafka message handlers.

Provides a composable middleware pattern similar to Express.js/ASP.NET Core.
Middleware can wrap handler execution, modify context, perform pre/post
processing, or short-circuit the chain (e.g., rate limiting).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import betterproto2

    from nohiki_kafka_client.handlers import MessageContext

type NextHandler = Callable[["betterproto2.Message", "MessageContext"], Awaitable[None]]


@runtime_checkable
class Middleware(Protocol):
    """Protocol for message handler middleware.

    Middleware wraps handler execution using the "onion" pattern:
    - Receive message, context, and the next handler in chain
    - Perform pre-processing
    - Call next handler (or short-circuit by not calling)
    - Perform post-processing

    Example:
        class LoggingMiddleware:
            async def __call__(self, message, context, call_next):
                logger.info("Before handler", topic=context.topic)
                await call_next(message, context)
                logger.info("After handler", topic=context.topic)

    """

    async def __call__(
        self,
        message: betterproto2.Message,
        context: MessageContext,
        call_next: NextHandler,
    ) -> None:
        """Execute middleware logic.

        Args:
            message: The deserialized protobuf message.
            context: Message context (can be mutated to inject dependencies).
            call_next: Invoke the next middleware or handler in the chain.
                       Not calling this short-circuits execution.

        """
        ...


async def execute_middleware_chain(
    middleware_stack: list[Middleware],
    handler: NextHandler,
    message: betterproto2.Message,
    context: MessageContext,
) -> None:
    """Execute a middleware chain with the handler at the end.

    Builds an "onion" where each middleware wraps the next, with the
    actual handler at the center. Execution flows inward (pre-processing),
    then outward (post-processing).

    Args:
        middleware_stack: List of middleware to execute in order.
        handler: The actual message handler at the end of the chain.
        message: The deserialized protobuf message.
        context: Message context passed through the chain.

    Example:
        # Stack: [RateLimitMiddleware, LoggingMiddleware]
        # Execution order:
        # 1. RateLimitMiddleware pre-processing
        # 2. LoggingMiddleware pre-processing
        # 3. Handler execution
        # 4. LoggingMiddleware post-processing
        # 5. RateLimitMiddleware post-processing

    """
    if not middleware_stack:
        await handler(message, context)
        return

    def build_chain(index: int) -> NextHandler:
        """Recursively build the middleware chain."""
        if index >= len(middleware_stack):
            return handler

        current_middleware = middleware_stack[index]
        next_in_chain = build_chain(index + 1)

        async def wrapped(msg: betterproto2.Message, ctx: MessageContext) -> None:
            await current_middleware(msg, ctx, next_in_chain)

        return wrapped

    chain = build_chain(0)
    await chain(message, context)
