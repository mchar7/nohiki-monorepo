"""Database session middleware for Kafka message handlers.

Provides the session lifecycle wrapper used by the ``with_db_session``
decorator.  All database types are behind ``TYPE_CHECKING``: the concrete
``async_sessionmaker`` instance is passed in at runtime by the caller.
"""

import asyncio
from typing import TYPE_CHECKING, Any

from nohiki_observability import get_logger

if TYPE_CHECKING:
    import betterproto2
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nohiki_kafka_client.handlers import (
        DbSessionConfig,
        MessageContext,
        MessageHandlerFunc,
    )

logger = get_logger(__name__)


async def execute_with_db_session(
    handler_func: MessageHandlerFunc[Any],
    message: betterproto2.Message,
    context: MessageContext,
    config: DbSessionConfig,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Wrap handler execution in a database session lifecycle.

    Creates an ``AsyncSession`` before calling the handler, injects it into
    ``context.db_session``, and auto-commits on success.  When ``config.schema``
    is provided, an ``OutboxWriter`` is also injected into ``context.outbox``.
    On exception the session is rolled back explicitly before re-raising.

    Args:
        handler_func: The message handler to execute.
        message: The deserialized protobuf message.
        context: Message context: mutated in-place (``db_session`` and
            optionally ``outbox`` fields set).
        config: Typed database session configuration.
        session_factory: SQLAlchemy async session factory provided by the service.

    """
    async with session_factory() as session:
        context.db_session = session

        context.session_factory = session_factory

        if config.schema:
            from nohiki_db_utils import OutboxWriter  # noqa: PLC0415

            context.outbox = OutboxWriter(schema=config.schema)

        try:
            await handler_func(message, context)

            if config.auto_commit:
                await session.commit()
        except asyncio.CancelledError:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise
