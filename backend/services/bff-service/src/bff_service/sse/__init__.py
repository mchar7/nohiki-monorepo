"""SSE bridge singleton lifecycle management."""

import asyncio
import logging
from dataclasses import dataclass

from bff_service.sse.bridge import SSEBridge

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _SSELifecycle:
    bridge: SSEBridge | None = None
    shutdown_event: asyncio.Event | None = None


_state = _SSELifecycle()


async def init_sse_bridge(redis_url: str) -> None:
    """Initialize the SSE bridge singleton and shutdown event.

    Args:
        redis_url: Redis connection string for durable streams.
    """
    _state.bridge = SSEBridge(redis_url)
    _state.shutdown_event = asyncio.Event()
    await _state.bridge.connect()
    logger.info("SSE bridge ready")


def get_sse_bridge() -> SSEBridge:
    """Get the initialized SSE bridge."""
    if _state.bridge is None:
        msg = "SSE bridge not initialized. Call init_sse_bridge() first"
        raise RuntimeError(msg)
    return _state.bridge


def get_shutdown_event() -> asyncio.Event:
    """Get the initialized SSE shutdown event."""
    if _state.shutdown_event is None:
        msg = "SSE bridge not initialized. Call init_sse_bridge() first"
        raise RuntimeError(msg)
    return _state.shutdown_event


async def close_sse_bridge() -> None:
    """Signal active streams, allow graceful drain, and close Redis."""
    if _state.shutdown_event is not None:
        _state.shutdown_event.set()
    await asyncio.sleep(1)
    if _state.bridge is not None:
        await _state.bridge.close()
    _state.bridge = None
    _state.shutdown_event = None
    logger.info("SSE bridge closed")
