import asyncio
import json
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta, tzinfo
from types import SimpleNamespace
from typing import TYPE_CHECKING, Protocol, Self, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from bff_service.core.config import SSESettings
from bff_service.sse.bridge import SSEBridge, StreamEvent
from bff_service.sse.events import SSE_EVENT_DOCUMENT_STATUS
from bff_service.sse.stream import SSEStreamContext, sse_event_generator
from nohiki_fastapi_utils import JWTClaims
from sqlalchemy.exc import OperationalError

if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql import ClauseElement

USER_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
REQUEST_ID = uuid.UUID("aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb")


def _principal(
    *,
    now: datetime | None = None,
    expires_at: datetime | None = None,
    jti: str = "87654321-4321-8765-4321-876543218765",
    session_family_id: str | None = None,
) -> JWTClaims:
    issued = now or datetime.now(UTC)
    return JWTClaims(
        sub=str(USER_ID),
        iss="https://api.nohiki.com",
        aud="https://app.nohiki.com",
        exp=int((expires_at or issued + timedelta(hours=1)).timestamp()),
        iat=int((issued - timedelta(minutes=1)).timestamp()),
        jti=jti,
        roles=["user"],
        permissions=[],
        tenant_id=None,
        session_family_id=session_family_id,
    )


def _settings(**updates: object) -> SSESettings:
    settings = SSESettings(
        heartbeat_interval_seconds=10,
        max_stream_duration_seconds=600,
        reconnect_interval_ms=5000,
        stale_cutoff_hours=24,
    )
    return settings.model_copy(update=updates)


def _row(**updates: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "request_id": REQUEST_ID,
        "user_id": USER_ID,
        "status": "pending",
        "storage_key": None,
        "error_message": None,
        "file_size": None,
        "content_hash": None,
    }
    values |= updates
    return SimpleNamespace(**values)


class _SessionFactoryState(Protocol):
    active: int
    capacity: int
    max_active: int
    entries: list[int]
    exits: list[int]
    order: list[str]


class _SessionContext:
    def __init__(self, factory: _SessionFactoryState, session: AsyncSession, session_id: int) -> None:
        self.factory = factory
        self.session = session
        self.session_id = session_id

    async def __aenter__(self) -> AsyncSession:
        if self.factory.active >= self.factory.capacity:
            message = "SSE stream exhausted the session pool"
            raise AssertionError(message)
        self.factory.active += 1
        self.factory.max_active = max(self.factory.max_active, self.factory.active)
        self.factory.entries.append(self.session_id)
        self.factory.order.append(f"enter:{self.session_id}")
        return self.session

    async def __aexit__(
        self,
        type_: type[BaseException] | None,
        value: BaseException | None,
        traceback: object,
    ) -> None:
        self.factory.order.append(f"exit:{self.session_id}")
        self.factory.exits.append(self.session_id)
        self.factory.active -= 1


class _SessionFactory:
    def __init__(
        self,
        rows: Sequence[SimpleNamespace] = (),
        *,
        capacity: int = 5,
        order: list[str] | None = None,
        on_execute: Callable[[ClauseElement], None] | None = None,
    ) -> None:
        self.rows = list(rows)
        self.capacity = capacity
        self.order = order if order is not None else []
        self.on_execute = on_execute
        self.active = 0
        self.max_active = 0
        self.entries: list[int] = []
        self.exits: list[int] = []
        self.sessions: list[AsyncMock] = []

    def __call__(self) -> _SessionContext:
        session_id = len(self.sessions) + 1
        scalar_result = MagicMock()
        scalar_result.all.return_value = self.rows
        result = MagicMock()
        result.scalars.return_value = scalar_result
        result.scalar_one_or_none.return_value = self.rows[0] if self.rows else None

        async def _execute(statement: ClauseElement, **_kwargs: object) -> MagicMock:
            self.order.append(f"execute:{session_id}")
            if self.on_execute is not None:
                self.on_execute(statement)
            return result

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute)
        self.sessions.append(session)
        return _SessionContext(self, cast("AsyncSession", session), session_id)


def _bridge(
    *,
    latest_id: str = "0-0",
    cursor_retained: bool = True,
    reads: Sequence[Sequence[StreamEvent]] = (),
) -> AsyncMock:
    bridge = AsyncMock(spec=SSEBridge)
    bridge.latest_id.return_value = latest_id
    bridge.cursor_is_retained.return_value = cursor_retained
    bridge.read_after.side_effect = [list(batch) for batch in reads]
    return bridge


@pytest.fixture(autouse=True)
def _authorized_stream(mocker: MockerFixture) -> None:
    mocker.patch(
        "bff_service.sse.stream.is_access_token_revoked",
        new=AsyncMock(return_value=False),
    )


@pytest.mark.parametrize(("expired", "revoked"), [(True, False), (False, True)])
@pytest.mark.asyncio
async def test_unauthorized_principal_cannot_query_or_receive_snapshot(
    mocker: MockerFixture,
    *,
    expired: bool,
    revoked: bool,
) -> None:
    revocation_check = mocker.patch(
        "bff_service.sse.stream.is_access_token_revoked",
        new=AsyncMock(return_value=revoked),
    )
    factory = _SessionFactory([_row()])

    events = [
        event
        async for event in sse_event_generator(
            USER_ID,
            _principal(expires_at=(datetime.now(UTC) - timedelta(seconds=1)) if expired else None),
            SSEStreamContext(
                session_factory=factory,
                bridge=_bridge(),
                settings=_settings(),
                shutdown_event=asyncio.Event(),
            ),
            request_id=REQUEST_ID,
        )
    ]

    assert events == []
    assert sum(session.execute.await_count for session in factory.sessions) == 0
    if expired:
        revocation_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_snapshot_is_scoped_and_uses_captured_tail_for_lossless_live_replay() -> None:
    order: list[str] = []
    statements: list[ClauseElement] = []
    factory = _SessionFactory(
        [_row(storage_key="s3://bucket/request.pdf", file_size=2048)],
        order=order,
        on_execute=statements.append,
    )
    live_event = StreamEvent(
        event_id="11-0",
        data='{"type":"document_status","request_id":"aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb","status":"completed"}',
        terminal=True,
    )
    bridge = _bridge(latest_id="10-0")

    async def _latest_id(*_args: object) -> str:
        order.append("latest")
        return "10-0"

    async def _read_after(*_args: object, **_kwargs: object) -> list[StreamEvent]:
        order.append("read")
        return [live_event]

    bridge.latest_id.side_effect = _latest_id
    bridge.read_after.side_effect = _read_after

    events = [
        event
        async for event in sse_event_generator(
            USER_ID,
            _principal(),
            SSEStreamContext(
                session_factory=factory,
                bridge=bridge,
                settings=_settings(),
                shutdown_event=asyncio.Event(),
            ),
            request_id=REQUEST_ID,
        )
    ]

    assert order.index("latest") < order.index("execute:1") < order.index("read")
    assert len(statements) == 1
    query_parameters = list(statements[0].compile().params.values())
    assert USER_ID in query_parameters
    assert REQUEST_ID in query_parameters
    assert [event.id for event in events] == [None, "11-0"]
    assert json.loads(str(events[0].data)) == {
        "type": SSE_EVENT_DOCUMENT_STATUS,
        "request_id": str(REQUEST_ID),
        "status": "pending",
        "storage_key": "s3://bucket/request.pdf",
        "error_message": None,
        "file_size": 2048,
        "content_hash": None,
    }
    bridge.latest_id.assert_awaited_once_with(USER_ID, REQUEST_ID)
    bridge.cursor_is_retained.assert_not_awaited()
    assert bridge.read_after.await_args.args == (USER_ID, REQUEST_ID, "10-0")


@pytest.mark.asyncio
async def test_retained_cursor_skips_snapshot_and_replays_strictly_after_it() -> None:
    factory = _SessionFactory([_row(status="failed")])
    replay = StreamEvent(
        event_id="42-1",
        data='{"type":"document_status","status":"completed"}',
        terminal=True,
    )
    bridge = _bridge(reads=[[replay]])

    events = [
        event
        async for event in sse_event_generator(
            USER_ID,
            _principal(),
            SSEStreamContext(
                session_factory=factory,
                bridge=bridge,
                settings=_settings(),
                shutdown_event=asyncio.Event(),
            ),
            request_id=REQUEST_ID,
            last_event_id="42-0",
        )
    ]

    bridge.cursor_is_retained.assert_awaited_once_with(USER_ID, REQUEST_ID, "42-0")
    bridge.latest_id.assert_not_awaited()
    assert sum(session.execute.await_count for session in factory.sessions) == 0
    assert [(event.id, event.data) for event in events] == [("42-1", replay.data)]
    assert bridge.read_after.await_args.args == (USER_ID, REQUEST_ID, "42-0")


@pytest.mark.asyncio
async def test_unretained_cursor_falls_back_to_fresh_scoped_snapshot() -> None:
    factory = _SessionFactory([_row(status="completed", content_hash="sha256:done")])
    bridge = _bridge(latest_id="91-0", cursor_retained=False)

    events = [
        event
        async for event in sse_event_generator(
            USER_ID,
            _principal(),
            SSEStreamContext(
                session_factory=factory,
                bridge=bridge,
                settings=_settings(),
                shutdown_event=asyncio.Event(),
            ),
            request_id=REQUEST_ID,
            last_event_id="12-0",
        )
    ]

    bridge.cursor_is_retained.assert_awaited_once_with(USER_ID, REQUEST_ID, "12-0")
    bridge.latest_id.assert_awaited_once_with(USER_ID, REQUEST_ID)
    bridge.read_after.assert_not_awaited()
    assert len(events) == 1
    assert events[0].id is None
    assert json.loads(str(events[0].data))["content_hash"] == "sha256:done"


@pytest.mark.asyncio
async def test_terminal_snapshot_is_yielded_once_without_opening_live_read() -> None:
    bridge = _bridge(latest_id="30-0")

    events = [
        event
        async for event in sse_event_generator(
            USER_ID,
            _principal(),
            SSEStreamContext(
                session_factory=_SessionFactory([_row(status="failed", error_message="render failed")]),
                bridge=bridge,
                settings=_settings(),
                shutdown_event=asyncio.Event(),
            ),
            request_id=REQUEST_ID,
        )
    ]

    assert len(events) == 1
    assert json.loads(str(events[0].data))["error_message"] == "render failed"
    bridge.read_after.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_live_event_stops_before_later_batch_entries() -> None:
    terminal = StreamEvent("7-1", '{"status":"completed"}', terminal=True)
    unreachable = StreamEvent("7-2", '{"status":"pending"}', terminal=False)
    bridge = _bridge(reads=[[terminal, unreachable]])

    events = [
        event
        async for event in sse_event_generator(
            USER_ID,
            _principal(),
            SSEStreamContext(
                session_factory=_SessionFactory(),
                bridge=bridge,
                settings=_settings(),
                shutdown_event=asyncio.Event(),
            ),
            request_id=REQUEST_ID,
            last_event_id="7-0",
        )
    ]

    assert [(event.id, event.data) for event in events] == [("7-1", terminal.data)]
    bridge.read_after.assert_awaited_once()


@pytest.mark.asyncio
async def test_idle_reads_use_independent_short_lived_sessions_and_observe_revocation(
    mocker: MockerFixture,
) -> None:
    factory = _SessionFactory(capacity=1)
    revocation_check = mocker.patch(
        "bff_service.sse.stream.is_access_token_revoked",
        new=AsyncMock(side_effect=[False, False, True]),
    )
    bridge = _bridge(reads=[[], []])

    events = [
        event
        async for event in sse_event_generator(
            USER_ID,
            _principal(),
            SSEStreamContext(
                session_factory=factory,
                bridge=bridge,
                settings=_settings(),
                shutdown_event=asyncio.Event(),
            ),
            request_id=REQUEST_ID,
            last_event_id="1-0",
        )
    ]

    assert events == []
    assert factory.entries == [1, 2, 3]
    assert factory.exits == [1, 2, 3]
    assert factory.max_active == 1
    assert [call.args[0] for call in revocation_check.await_args_list] == factory.sessions
    assert bridge.read_after.await_count == 2


@pytest.mark.asyncio
async def test_family_revocation_and_revocation_store_failure_fail_closed(
    mocker: MockerFixture,
) -> None:
    family_id = str(uuid.uuid4())
    revocation_check = mocker.patch(
        "bff_service.sse.stream.is_access_token_revoked",
        new=AsyncMock(
            side_effect=[
                True,
                OperationalError("SELECT", {}, RuntimeError("database down")),
            ]
        ),
    )

    for principal in (_principal(session_family_id=family_id), _principal()):
        factory = _SessionFactory([_row()])
        events = [
            event
            async for event in sse_event_generator(
                USER_ID,
                principal,
                SSEStreamContext(
                    session_factory=factory,
                    bridge=_bridge(),
                    settings=_settings(),
                    shutdown_event=asyncio.Event(),
                ),
                request_id=REQUEST_ID,
            )
        ]
        assert events == []
        assert sum(session.execute.await_count for session in factory.sessions) == 0

    assert revocation_check.await_args_list[0].kwargs["session_family_id"] == family_id


@pytest.mark.asyncio
async def test_shutdown_interrupts_idle_read_and_emits_terminal_event() -> None:
    shutdown = asyncio.Event()
    read_started = asyncio.Event()
    never = asyncio.Event()
    bridge = _bridge()

    async def _blocked_read(*_args: object, **_kwargs: object) -> list[StreamEvent]:
        read_started.set()
        await never.wait()
        return []

    bridge.read_after.side_effect = _blocked_read
    generator = sse_event_generator(
        USER_ID,
        _principal(),
        SSEStreamContext(
            session_factory=_SessionFactory(),
            bridge=bridge,
            settings=_settings(),
            shutdown_event=shutdown,
        ),
        request_id=REQUEST_ID,
        last_event_id="1-0",
    )
    next_event = asyncio.create_task(anext(generator))

    await asyncio.wait_for(read_started.wait(), timeout=1)
    shutdown.set()
    event = await asyncio.wait_for(next_event, timeout=1)
    with pytest.raises(StopAsyncIteration):
        await anext(generator)

    assert event.event == "shutdown"
    assert event.data == "{}"


@pytest.mark.asyncio
async def test_token_expiry_during_idle_read_closes_stream(
    mocker: MockerFixture,
) -> None:
    start = datetime(2030, 1, 1, tzinfo=UTC)

    class _Clock(datetime):
        current = start

        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            del tz
            return cast("Self", cls.current)

    mocker.patch("bff_service.sse.stream.datetime", _Clock)
    bridge = _bridge()

    async def _expire_token(*_args: object, **_kwargs: object) -> list[StreamEvent]:
        _Clock.current = start + timedelta(seconds=6)
        return []

    bridge.read_after.side_effect = _expire_token
    events = [
        event
        async for event in sse_event_generator(
            USER_ID,
            _principal(now=start, expires_at=start + timedelta(seconds=5)),
            SSEStreamContext(
                session_factory=_SessionFactory(),
                bridge=bridge,
                settings=_settings(),
                shutdown_event=asyncio.Event(),
            ),
            request_id=REQUEST_ID,
            last_event_id="1-0",
        )
    ]

    assert events == []
    bridge.read_after.assert_awaited_once()
    assert 0 < bridge.read_after.await_args.kwargs["block_ms"] <= 5_000


@pytest.mark.asyncio
async def test_snapshot_time_counts_against_max_stream_duration(
    mocker: MockerFixture,
) -> None:
    fake_loop = SimpleNamespace(time=MagicMock(return_value=100.0))
    mocker.patch("bff_service.sse.stream.asyncio.get_running_loop", return_value=fake_loop)

    def _finish_slow_snapshot(_statement: ClauseElement) -> None:
        fake_loop.time.return_value = 101.0

    bridge = _bridge()
    events = [
        event
        async for event in sse_event_generator(
            USER_ID,
            _principal(),
            SSEStreamContext(
                session_factory=_SessionFactory([_row()], on_execute=_finish_slow_snapshot),
                bridge=bridge,
                settings=_settings(max_stream_duration_seconds=1),
                shutdown_event=asyncio.Event(),
            ),
            request_id=REQUEST_ID,
        )
    ]

    assert events == []
    bridge.read_after.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_propagates_without_generator_side_cleanup() -> None:
    bridge = _bridge()
    bridge.read_after.side_effect = asyncio.CancelledError
    generator = sse_event_generator(
        USER_ID,
        _principal(),
        SSEStreamContext(
            session_factory=_SessionFactory(),
            bridge=bridge,
            settings=_settings(),
            shutdown_event=asyncio.Event(),
        ),
        request_id=REQUEST_ID,
        last_event_id="1-0",
    )

    with pytest.raises(asyncio.CancelledError):
        async for _ in generator:
            pass

    bridge.release_stream_slot.assert_not_awaited()
