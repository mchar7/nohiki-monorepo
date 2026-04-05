"""Shared handler registration logic for Kafka clients.

Provides the ``HandlerRegistryMixin`` that encapsulates all decorator-based
handler registration (``message_handler``, ``with_resilience``,
``transactional``, ``with_db_session``) so that ``AutoKafkaClient`` can
reuse validated logic without duplication.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import betterproto2

from .types import (
    DbSessionConfig,
    DLQStrategy,
    HandlerRegistration,
    MessageHandlerFunc,
    ResilienceConfig,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(slots=True)
class _HandlerMetadata:
    """Typed metadata accumulated by decorators before handler registration."""

    resilience_config: ResilienceConfig | None = None
    is_transactional: bool = False
    db_session_config: DbSessionConfig | None = None


def _propagate_to_existing[T: betterproto2.Message](
    handlers: dict[str, HandlerRegistration],
    func: MessageHandlerFunc[T],
    attr: str,
    value: object,
) -> None:
    """Push metadata onto an already-registered HandlerRegistration, if any."""
    for registration in handlers.values():
        if registration.handler_func is func:
            setattr(registration, attr, value)
            return


def _apply_metadata(registration: HandlerRegistration, meta: _HandlerMetadata) -> None:
    """Apply accumulated decorator metadata to a handler registration."""
    if meta.resilience_config is not None:
        registration.resilience_config = meta.resilience_config
    if meta.is_transactional:
        registration.is_transactional = True
    if meta.db_session_config is not None:
        registration.db_session_config = meta.db_session_config


class HandlerRegistryMixin:
    """Mixin providing decorator-based handler registration.

    Subclasses must define:
    - ``_handlers: dict[str, HandlerRegistration]``
    - ``_handler_metadata: dict[int, _HandlerMetadata]``

    Subclasses *may* override ``_on_handler_registered`` to hook post-registration
    behaviour (e.g. auto-starting consumers).
    """

    _handlers: dict[str, HandlerRegistration]
    _handler_metadata: dict[int, _HandlerMetadata]

    #: Registration hook (override in subclasses) --

    def _on_handler_registered(self, _registration: HandlerRegistration) -> None:
        """Called after a handler is registered.  Override for side-effects."""

    #: Decorators --

    def message_handler[T: betterproto2.Message](
        self,
        topic: str,
        message_type: type[T],
        *,
        group_id: str,
        middleware: list[object] | None = None,
        preserve_partition_order: bool = True,
    ) -> Callable[[MessageHandlerFunc[T]], MessageHandlerFunc[T]]:
        """Register a message handler for a topic.

        Args:
            topic: Kafka topic to subscribe to.
            message_type: Protobuf message type expected.
            group_id: Consumer group ID (REQUIRED).
            middleware: Optional list of middleware to apply to this handler.
                Middleware is executed in order, wrapping the handler in an
                "onion" pattern. Each middleware can perform pre/post processing
                or short-circuit execution (e.g., rate limiting).
            preserve_partition_order: If True, messages within the same
                partition are processed sequentially while different
                partitions run concurrently.  Set to False for handlers
                that are fully idempotent and order-independent.

        """
        if not issubclass(message_type, betterproto2.Message):
            msg = f"{message_type!r} must inherit from betterproto2.Message"
            raise TypeError(msg)

        from nohiki_kafka_client.middleware.protocol import Middleware  # noqa: PLC0415

        def decorator(func: MessageHandlerFunc[T]) -> MessageHandlerFunc[T]:
            handler_key = f"{topic}:{group_id}:{func.__name__}"

            # Validate middleware implements the Middleware protocol
            typed_middleware: list[Middleware] = []
            if middleware:
                for mw in middleware:
                    if not isinstance(mw, Middleware):
                        msg = f"Middleware {mw!r} does not implement the Middleware protocol"
                        raise TypeError(msg)
                    typed_middleware.append(mw)

            registration = HandlerRegistration(
                topic=topic,
                message_type=message_type,
                handler_func=func,
                group_id=group_id,
                middleware=typed_middleware,
                preserve_partition_order=preserve_partition_order,
            )

            if (meta := self._handler_metadata.get(id(func))) is not None:
                _apply_metadata(registration, meta)

            self._handlers[handler_key] = registration
            self._on_handler_registered(registration)
            return func

        return decorator

    def with_resilience[T: betterproto2.Message](
        self,
        *,
        max_retries: int | None = None,
        retry_backoff_ms: int | None = None,
        max_backoff_ms: int | None = None,
        strategy: str | None = None,
    ) -> Callable[[MessageHandlerFunc[T]], MessageHandlerFunc[T]]:
        """Override service-level resilience defaults for a specific handler.

        Only needed when a handler requires different retry/DLQ behaviour
        than the service default (e.g. more retries for external API calls).
        Fields left as ``None`` inherit the service-level ``GlobalDLQConfig``.

        Args:
            max_retries: Override maximum retry attempts before DLQ.
            retry_backoff_ms: Override base backoff delay (ms).
            max_backoff_ms: Override maximum backoff cap (ms).
            strategy: Override DLQ strategy (``"republish"`` or ``"log_only"``).

        """
        config = ResilienceConfig(
            max_retries=max_retries,
            retry_backoff_ms=retry_backoff_ms,
            max_backoff_ms=max_backoff_ms,
            strategy=DLQStrategy(strategy) if strategy is not None else None,
        )

        def decorator(func: MessageHandlerFunc[T]) -> MessageHandlerFunc[T]:
            self._handler_metadata.setdefault(id(func), _HandlerMetadata()).resilience_config = config
            _propagate_to_existing(self._handlers, func, "resilience_config", config)
            return func

        return decorator

    def transactional[T: betterproto2.Message](self, func: MessageHandlerFunc[T]) -> MessageHandlerFunc[T]:
        """Mark a handler as transactional (order-independent)."""
        self._handler_metadata.setdefault(id(func), _HandlerMetadata()).is_transactional = True
        _propagate_to_existing(self._handlers, func, "is_transactional", value=True)
        return func

    def with_db_session[T: betterproto2.Message](
        self,
        schema: str | None = None,
        *,
        auto_commit: bool = True,
    ) -> Callable[[MessageHandlerFunc[T]], MessageHandlerFunc[T]]:
        """Inject a database session into the handler's MessageContext.

        The session is created before handler execution and committed on
        success (if ``auto_commit=True``).  On exception the session is
        rolled back automatically by the context-manager exit.

        Args:
            schema: Database schema name.  If provided, an ``OutboxWriter``
                is also injected into ``context.outbox``.
            auto_commit: Whether to auto-commit on handler success.

        """
        config = DbSessionConfig(schema=schema, auto_commit=auto_commit)

        def decorator(func: MessageHandlerFunc[T]) -> MessageHandlerFunc[T]:
            self._handler_metadata.setdefault(id(func), _HandlerMetadata()).db_session_config = config
            _propagate_to_existing(self._handlers, func, "db_session_config", config)
            return func

        return decorator
