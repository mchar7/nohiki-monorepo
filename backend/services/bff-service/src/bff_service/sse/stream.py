"""Request-scoped, durable SSE stream generation for status changes."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Protocol, cast
from uuid import UUID

from nohiki_fastapi_utils import JWTClaims
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import ServerSentEvent

from bff_service.core.config import SSESettings
from bff_service.db.models import CommandRequest, DocumentGenerationStatus
from bff_service.services.auth_revocation import is_access_token_revoked
from bff_service.sse.bridge import SSEBridge, StreamEvent
from bff_service.sse.events import (
    SSE_EVENT_COMMAND_STATUS,
    SSE_EVENT_DOCUMENT_STATUS,
    CommandStatusPayload,
    DocumentStatusPayload,
)

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({"completed", "failed"})


class AsyncSessionContext(Protocol):
    """Async context manager yielding a database session."""

    async def __aenter__(self) -> AsyncSession:
        """Enter the context and return its session."""
        ...

    async def __aexit__(
        self,
        type_: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Exit the session context."""
        ...


class AsyncSessionFactory(Protocol):
    """Callable producing an independently scoped async session."""

    def __call__(self) -> AsyncSessionContext:
        """Create an independently scoped session context."""
        ...


@dataclass(frozen=True, slots=True)
class SSEStreamContext:
    """Infrastructure dependencies shared by one SSE stream."""

    session_factory: AsyncSessionFactory
    bridge: SSEBridge
    settings: SSESettings
    shutdown_event: asyncio.Event
    event_type: str = SSE_EVENT_DOCUMENT_STATUS


@dataclass(frozen=True, slots=True)
class _AuthorizationContext:
    user_id: UUID
    principal: JWTClaims
    issued_at: datetime
    expires_at: datetime


async def _authorization_valid(
    *,
    db_session: AsyncSession,
    user_id: UUID,
    principal: JWTClaims,
    issued_at: datetime,
    expires_at: datetime,
) -> bool:
    """Check token expiry and durable revocation, failing closed."""
    if not principal.jti or datetime.now(UTC) >= expires_at:
        return False
    try:
        return not await is_access_token_revoked(
            db_session,
            user_id=user_id,
            jti=principal.jti,
            issued_at=issued_at,
            session_family_id=principal.session_family_id,
        )
    except SQLAlchemyError, OverflowError, OSError, ValueError:
        logger.warning("Closing SSE stream because authentication state is unavailable")
        return False


async def _stream_authorized(context: SSEStreamContext, authorization: _AuthorizationContext) -> bool:
    """Check authorization in an independent short-lived session."""
    try:
        async with context.session_factory() as db_session:
            return await _authorization_valid(
                db_session=db_session,
                user_id=authorization.user_id,
                principal=authorization.principal,
                issued_at=authorization.issued_at,
                expires_at=authorization.expires_at,
            )
    except SQLAlchemyError:
        logger.warning("Closing SSE stream because authentication state is unavailable")
        return False


def _snapshot_event(
    row: DocumentGenerationStatus | CommandRequest,
    event_type: str,
) -> ServerSentEvent:
    if event_type == SSE_EVENT_COMMAND_STATUS:
        command = cast("CommandRequest", row)
        payload = CommandStatusPayload(
            type=event_type,
            request_id=str(command.request_id),
            command_type=command.command_type,
            status=command.status,
            error_message=command.error_message,
        )
    else:
        document = cast("DocumentGenerationStatus", row)
        payload = DocumentStatusPayload(
            type=event_type,
            request_id=str(document.request_id),
            status=document.status,
            storage_key=document.storage_key,
            error_message=document.error_message,
            file_size=document.file_size,
            content_hash=document.content_hash,
        )
    return ServerSentEvent(data=payload.to_sse_data(), event=event_type)


def _stream_event_name(event: StreamEvent) -> str | None:
    """Read the SSE event name from the durable payload discriminator."""
    try:
        event_type = json.loads(event.data).get("type")
    except AttributeError, json.JSONDecodeError, TypeError:
        return None
    if event_type in (SSE_EVENT_COMMAND_STATUS, SSE_EVENT_DOCUMENT_STATUS):
        return event_type
    return None


async def _read_or_shutdown(
    context: SSEStreamContext,
    *,
    user_id: UUID,
    request_id: UUID,
    cursor: str,
    block_ms: int,
) -> tuple[list[StreamEvent], bool]:
    """Read durable events while allowing shutdown to interrupt a blocked Redis read."""
    read_task = asyncio.create_task(context.bridge.read_after(user_id, request_id, cursor, block_ms=block_ms))
    shutdown_task = asyncio.create_task(context.shutdown_event.wait())
    try:
        done, _ = await asyncio.wait((read_task, shutdown_task), return_when=asyncio.FIRST_COMPLETED)
        if shutdown_task in done and shutdown_task.result():
            return [], True
        return read_task.result(), False
    finally:
        for task in (read_task, shutdown_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(read_task, shutdown_task, return_exceptions=True)


async def _initial_stream_state(
    context: SSEStreamContext,
    authorization: _AuthorizationContext,
    request_id: UUID,
    last_event_id: str | None,
    event_type: str,
) -> tuple[str, DocumentGenerationStatus | CommandRequest | None] | None:
    async with context.session_factory() as db_session:
        if not await _authorization_valid(
            db_session=db_session,
            user_id=authorization.user_id,
            principal=authorization.principal,
            issued_at=authorization.issued_at,
            expires_at=authorization.expires_at,
        ):
            return None

        retained_cursor = last_event_id is not None and await context.bridge.cursor_is_retained(
            authorization.user_id, request_id, last_event_id
        )
        if retained_cursor:
            return last_event_id, None

        cursor = await context.bridge.latest_id(authorization.user_id, request_id)
        model = CommandRequest if event_type == SSE_EVENT_COMMAND_STATUS else DocumentGenerationStatus
        result = await db_session.execute(
            select(model).where(
                model.user_id == authorization.user_id,
                model.request_id == request_id,
            )
        )
        return cursor, result.scalar_one_or_none()


def _wait_seconds(
    context: SSEStreamContext,
    authorization: _AuthorizationContext,
    deadline: float,
    loop: asyncio.AbstractEventLoop,
) -> float:
    return min(
        deadline - loop.time(),
        (authorization.expires_at - datetime.now(UTC)).total_seconds(),
        context.settings.heartbeat_interval_seconds,
    )


async def _live_events(
    context: SSEStreamContext,
    authorization: _AuthorizationContext,
    request_id: UUID,
    cursor: str,
    deadline: float,
) -> AsyncIterator[ServerSentEvent]:
    loop = asyncio.get_running_loop()
    while True:
        wait_seconds = _wait_seconds(context, authorization, deadline, loop)
        if wait_seconds <= 0:
            return
        if context.shutdown_event.is_set():
            yield ServerSentEvent(event="shutdown", data="{}")
            return

        events, shutting_down = await _read_or_shutdown(
            context,
            user_id=authorization.user_id,
            request_id=request_id,
            cursor=cursor,
            block_ms=max(1, int(wait_seconds * 1000)),
        )
        if shutting_down:
            yield ServerSentEvent(event="shutdown", data="{}")
            return
        if not await _stream_authorized(context, authorization):
            return

        for event in events:
            cursor = event.event_id
            event_name = _stream_event_name(event)
            if event_name is None:
                logger.warning("Ignoring SSE event without a recognized type for request %s", request_id)
                continue
            yield ServerSentEvent(
                data=event.data,
                event=event_name,
                id=event.event_id,
            )
            if event.terminal:
                return


async def sse_event_generator(
    user_id: UUID,
    principal: JWTClaims,
    context: SSEStreamContext,
    *,
    request_id: UUID,
    last_event_id: str | None = None,
) -> AsyncGenerator[ServerSentEvent]:
    """Yield one request's durable events while authorization remains valid."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + context.settings.max_stream_duration_seconds
    authorization = _AuthorizationContext(
        user_id=user_id,
        principal=principal,
        issued_at=datetime.fromtimestamp(principal.iat, tz=UTC),
        expires_at=datetime.fromtimestamp(principal.exp, tz=UTC),
    )

    try:
        state = await _initial_stream_state(
            context,
            authorization,
            request_id,
            last_event_id,
            context.event_type,
        )
        if state is None or loop.time() >= deadline:
            return
        cursor, snapshot = state
        if snapshot is not None:
            yield _snapshot_event(snapshot, context.event_type)
            if snapshot.status in _TERMINAL_STATUSES:
                return

        async for event in _live_events(context, authorization, request_id, cursor, deadline):
            yield event
    except asyncio.CancelledError:
        logger.debug("SSE stream cancelled for user %s request %s", user_id, request_id)
        raise
