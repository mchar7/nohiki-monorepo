"""Durable Redis Stream bridge for document SSE delivery."""

import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

import redis.asyncio as aioredis

from bff_service.sse.events import DocumentStatusPayload, build_stream_name

logger = logging.getLogger(__name__)

_STREAM_MAX_LENGTH = 256
_STREAM_RETENTION_SECONDS = 86_400
_RELEASE_STREAM_SLOT_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


@dataclass(frozen=True, slots=True)
class StreamLease:
    """Ownership token for one distributed per-user stream slot."""

    key: str
    token: str


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """One durable document event read from Redis."""

    event_id: str
    data: str
    terminal: bool


class SSEBridge:
    """Thin adapter around request-scoped Redis Streams."""

    def __init__(self, redis_url: str) -> None:
        """Configure the bridge for a Redis connection URL."""
        self._redis_url = redis_url
        self._client: aioredis.Redis[bytes] | None = None

    async def connect(self) -> None:
        """Create and store the Redis client."""
        self._client = aioredis.from_url(self._redis_url)
        logger.debug("SSEBridge connected to Redis at %s", self._redis_url)

    async def close(self) -> None:
        """Close the Redis client, if connected."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("SSEBridge Redis client closed")

    def _connected_client(self) -> aioredis.Redis[bytes]:
        if self._client is None:
            msg = "SSEBridge is not connected. Call connect() first"
            raise RuntimeError(msg)
        return self._client

    async def publish(self, user_id: UUID, payload: DocumentStatusPayload) -> str:
        """Append a status event to its bounded request-scoped stream."""
        client = self._connected_client()
        stream = build_stream_name(user_id, payload.request_id)
        raw_event_id = await client.xadd(
            stream,
            {"data": payload.to_sse_data(), "status": payload.status},
            maxlen=_STREAM_MAX_LENGTH,
            approximate=True,
        )
        await client.expire(stream, _STREAM_RETENTION_SECONDS)
        event_id = raw_event_id.decode("ascii") if isinstance(raw_event_id, bytes) else str(raw_event_id)
        logger.debug("Appended document SSE event %s to %s", event_id, stream)
        return event_id

    async def latest_id(self, user_id: UUID, request_id: UUID) -> str:
        """Return the current stream tail, or the Redis origin cursor."""
        entries = await self._connected_client().xrevrange(
            build_stream_name(user_id, str(request_id)),
            count=1,
        )
        if not entries:
            return "0-0"
        raw_event_id = entries[0][0]
        return raw_event_id.decode("ascii") if isinstance(raw_event_id, bytes) else str(raw_event_id)

    async def cursor_is_retained(
        self,
        user_id: UUID,
        request_id: UUID,
        cursor: str,
    ) -> bool:
        """Return whether Redis can replay continuously after ``cursor``."""
        stream = build_stream_name(user_id, str(request_id))
        client = self._connected_client()
        if cursor == "0-0":
            return bool(await client.xrevrange(stream, count=1))
        return bool(await client.xrange(stream, min=cursor, max=cursor, count=1))

    async def read_after(
        self,
        user_id: UUID,
        request_id: UUID,
        cursor: str,
        *,
        block_ms: int,
    ) -> list[StreamEvent]:
        """Read retained events strictly after ``cursor``."""
        stream = build_stream_name(user_id, str(request_id))
        batches = await self._connected_client().xread(
            {stream: cursor},
            count=_STREAM_MAX_LENGTH,
            block=block_ms,
        )
        events: list[StreamEvent] = []
        for _, entries in batches:
            for raw_event_id, fields in entries:
                raw_data = fields.get(b"data")
                raw_status = fields.get(b"status")
                if raw_data is None or raw_status is None:
                    continue
                event_id = raw_event_id.decode("ascii") if isinstance(raw_event_id, bytes) else str(raw_event_id)
                data = raw_data.decode("utf-8") if isinstance(raw_data, bytes) else str(raw_data)
                status = raw_status.decode("utf-8") if isinstance(raw_status, bytes) else str(raw_status)
                events.append(
                    StreamEvent(
                        event_id=event_id,
                        data=data,
                        terminal=status in {"completed", "failed"},
                    )
                )
        return events

    async def acquire_stream_slot(
        self,
        user_id: UUID,
        *,
        limit: int,
        ttl_seconds: int,
    ) -> StreamLease | None:
        """Atomically acquire one bounded per-user stream slot."""
        client = self._connected_client()
        token = str(uuid4())
        for slot in range(limit):
            key = f"sse:stream-slot:{user_id}:{slot}"
            if await client.set(key, token, ex=ttl_seconds, nx=True):
                return StreamLease(key=key, token=token)
        return None

    async def release_stream_slot(self, lease: StreamLease) -> None:
        """Release a slot only when its ownership token still matches."""
        if self._client is None:
            return
        await self._client.eval(
            _RELEASE_STREAM_SLOT_SCRIPT,
            1,
            lease.key,
            lease.token,
        )
