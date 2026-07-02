import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bff_service.sse.bridge import SSEBridge
from bff_service.sse.events import (
    SSE_EVENT_DOCUMENT_STATUS,
    DocumentStatusPayload,
    build_stream_name,
)

USER_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
REQUEST_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
REDIS_URL = "redis://localhost:6379/0"


def _payload(*, status: str = "completed") -> DocumentStatusPayload:
    return DocumentStatusPayload(
        type=SSE_EVENT_DOCUMENT_STATUS,
        request_id=str(REQUEST_ID),
        status=status,
        storage_key="rendered/output.pdf" if status == "completed" else None,
    )


@pytest.mark.asyncio
async def test_connect_and_close_own_the_redis_client() -> None:
    bridge = SSEBridge(REDIS_URL)
    client = AsyncMock()

    with patch("bff_service.sse.bridge.aioredis.from_url", return_value=client) as from_url:
        await bridge.connect()
        await bridge.close()

    from_url.assert_called_once_with(REDIS_URL)
    client.aclose.assert_awaited_once()
    assert bridge._client is None


@pytest.mark.asyncio
async def test_publish_appends_to_exact_user_request_stream_and_returns_event_id() -> None:
    bridge = SSEBridge(REDIS_URL)
    client = AsyncMock()
    client.xadd.return_value = b"1710000000000-0"
    bridge._client = client
    payload = _payload()

    event_id = await bridge.publish(USER_ID, payload)

    assert event_id == "1710000000000-0"
    stream = build_stream_name(USER_ID, str(REQUEST_ID))
    client.xadd.assert_awaited_once_with(
        stream,
        {"data": payload.to_sse_data(), "status": "completed"},
        maxlen=256,
        approximate=True,
    )
    client.expire.assert_awaited_once_with(stream, 86_400)


@pytest.mark.asyncio
async def test_latest_id_returns_tail_or_origin_cursor() -> None:
    bridge = SSEBridge(REDIS_URL)
    client = AsyncMock()
    client.xrevrange.side_effect = [[(b"1710000000004-2", {})], []]
    bridge._client = client

    assert await bridge.latest_id(USER_ID, REQUEST_ID) == "1710000000004-2"
    assert await bridge.latest_id(USER_ID, REQUEST_ID) == "0-0"
    expected_stream = build_stream_name(USER_ID, str(REQUEST_ID))
    assert all(call.args == (expected_stream,) for call in client.xrevrange.await_args_list)
    assert all(call.kwargs == {"count": 1} for call in client.xrevrange.await_args_list)


@pytest.mark.asyncio
async def test_origin_cursor_is_retained_only_while_stream_has_entries() -> None:
    bridge = SSEBridge(REDIS_URL)
    client = AsyncMock()
    client.xrevrange.side_effect = [[(b"1710000000004-2", {})], []]
    bridge._client = client

    assert await bridge.cursor_is_retained(USER_ID, REQUEST_ID, "0-0") is True
    assert await bridge.cursor_is_retained(USER_ID, REQUEST_ID, "0-0") is False
    stream = build_stream_name(USER_ID, str(REQUEST_ID))
    assert all(call.args == (stream,) for call in client.xrevrange.await_args_list)
    assert all(call.kwargs == {"count": 1} for call in client.xrevrange.await_args_list)
    client.xrange.assert_not_awaited()


@pytest.mark.asyncio
async def test_nonzero_cursor_is_retained_only_when_exact_entry_exists() -> None:
    bridge = SSEBridge(REDIS_URL)
    client = AsyncMock()
    client.xrange.side_effect = [[(b"1710000000004-2", {})], []]
    bridge._client = client
    cursor = "1710000000004-2"

    assert await bridge.cursor_is_retained(USER_ID, REQUEST_ID, cursor) is True
    assert await bridge.cursor_is_retained(USER_ID, REQUEST_ID, cursor) is False
    stream = build_stream_name(USER_ID, str(REQUEST_ID))
    assert all(call.args == (stream,) for call in client.xrange.await_args_list)
    assert all(call.kwargs == {"min": cursor, "max": cursor, "count": 1} for call in client.xrange.await_args_list)
    client.xrevrange.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_after_uses_cursor_verbatim_and_emits_ordered_ids() -> None:
    bridge = SSEBridge(REDIS_URL)
    client = AsyncMock()
    stream = build_stream_name(USER_ID, str(REQUEST_ID))
    client.xread.return_value = [
        (
            stream.encode(),
            [
                (
                    b"1710000000005-0",
                    {b"data": b'{"status":"in_progress"}', b"status": b"in_progress"},
                ),
                (
                    b"1710000000006-0",
                    {b"data": b'{"status":"completed"}', b"status": b"completed"},
                ),
            ],
        )
    ]
    bridge._client = client

    events = await bridge.read_after(
        USER_ID,
        REQUEST_ID,
        "1710000000004-2",
        block_ms=1500,
    )

    client.xread.assert_awaited_once_with(
        {stream: "1710000000004-2"},
        count=256,
        block=1500,
    )
    assert [event.event_id for event in events] == [
        "1710000000005-0",
        "1710000000006-0",
    ]
    assert [event.terminal for event in events] == [False, True]
    assert events[0].data == '{"status":"in_progress"}'


@pytest.mark.asyncio
async def test_read_after_drops_incomplete_stream_entries() -> None:
    bridge = SSEBridge(REDIS_URL)
    client = AsyncMock()
    client.xread.return_value = [
        (
            b"stream",
            [
                (b"1-0", {b"status": b"pending"}),
                (b"2-0", {b"data": b"{}"}),
            ],
        )
    ]
    bridge._client = client

    assert await bridge.read_after(USER_ID, REQUEST_ID, "0-0", block_ms=1) == []


@pytest.mark.asyncio
async def test_unconnected_bridge_fails_closed_for_publish_and_reads() -> None:
    bridge = SSEBridge(REDIS_URL)

    with pytest.raises(RuntimeError, match="not connected"):
        await bridge.publish(USER_ID, _payload())
    with pytest.raises(RuntimeError, match="not connected"):
        await bridge.latest_id(USER_ID, REQUEST_ID)
    with pytest.raises(RuntimeError, match="not connected"):
        await bridge.read_after(USER_ID, REQUEST_ID, "0-0", block_ms=1)


@pytest.mark.asyncio
async def test_stream_slot_release_is_token_checked_and_reconnectable() -> None:
    slots: dict[str, str] = {}

    async def _set(key: str, token: str, *, ex: int, nx: bool) -> bool:
        assert ex == 615
        assert nx is True
        if key in slots:
            return False
        slots[key] = token
        return True

    async def _eval(script: str, key_count: int, key: str, token: str) -> int:
        assert "GET" in script
        assert "DEL" in script
        assert key_count == 1
        if slots.get(key) != token:
            return 0
        del slots[key]
        return 1

    bridge = SSEBridge(REDIS_URL)
    client = MagicMock()
    client.set = AsyncMock(side_effect=_set)
    client.eval = AsyncMock(side_effect=_eval)
    bridge._client = client

    first = await bridge.acquire_stream_slot(USER_ID, limit=1, ttl_seconds=615)
    assert first is not None
    assert await bridge.acquire_stream_slot(USER_ID, limit=1, ttl_seconds=615) is None

    await bridge.release_stream_slot(first)
    second = await bridge.acquire_stream_slot(USER_ID, limit=1, ttl_seconds=615)

    assert second is not None
    assert second.key == first.key
    assert second.token != first.token
