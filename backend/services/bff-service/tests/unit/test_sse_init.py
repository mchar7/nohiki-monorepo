"""Unit tests for SSE lifecycle state management."""

import asyncio
from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import bff_service.sse as sse_module
import pytest


@pytest.fixture(autouse=True)
def reset_sse_lifecycle() -> Generator[None]:
    """Reset the lifecycle holder deterministically between tests."""
    sse_module._state.bridge = None
    sse_module._state.shutdown_event = None
    yield
    sse_module._state.bridge = None
    sse_module._state.shutdown_event = None


@pytest.fixture
def mock_bridge() -> AsyncMock:
    """Provide an async bridge test double."""
    bridge = AsyncMock()
    bridge.connect = AsyncMock()
    bridge.close = AsyncMock()
    return bridge


@pytest.mark.asyncio
async def test_init_sse_bridge_populates_lifecycle_state(
    mock_bridge: AsyncMock,
) -> None:
    with patch("bff_service.sse.SSEBridge", return_value=mock_bridge) as bridge_type:
        await sse_module.init_sse_bridge("redis://localhost:6379/0")

    bridge_type.assert_called_once_with("redis://localhost:6379/0")
    assert sse_module._state.bridge is mock_bridge
    assert isinstance(sse_module._state.shutdown_event, asyncio.Event)
    assert not sse_module._state.shutdown_event.is_set()
    mock_bridge.connect.assert_awaited_once()


def test_get_sse_bridge_raises_before_init() -> None:
    with pytest.raises(RuntimeError, match="SSE bridge not initialized"):
        sse_module.get_sse_bridge()


def test_get_shutdown_event_raises_before_init() -> None:
    with pytest.raises(RuntimeError, match="SSE bridge not initialized"):
        sse_module.get_shutdown_event()


@pytest.mark.asyncio
async def test_public_accessors_return_initialized_state(
    mock_bridge: AsyncMock,
) -> None:
    with patch("bff_service.sse.SSEBridge", return_value=mock_bridge):
        await sse_module.init_sse_bridge("redis://localhost:6379/0")

    shutdown_event = sse_module.get_shutdown_event()

    assert sse_module.get_sse_bridge() is mock_bridge
    assert shutdown_event is sse_module._state.shutdown_event
    assert not shutdown_event.is_set()


@pytest.mark.asyncio
async def test_close_signals_owned_event_closes_bridge_and_clears_state(
    mock_bridge: AsyncMock,
) -> None:
    with patch("bff_service.sse.SSEBridge", return_value=mock_bridge):
        await sse_module.init_sse_bridge("redis://localhost:6379/0")
    shutdown_event = sse_module.get_shutdown_event()

    with patch("bff_service.sse.asyncio.sleep", new=AsyncMock()) as sleep:
        await sse_module.close_sse_bridge()

    assert shutdown_event.is_set()
    sleep.assert_awaited_once_with(1)
    mock_bridge.close.assert_awaited_once()
    assert sse_module._state.bridge is None
    assert sse_module._state.shutdown_event is None


@pytest.mark.asyncio
async def test_close_is_idempotent_after_state_is_cleared(
    mock_bridge: AsyncMock,
) -> None:
    with patch("bff_service.sse.SSEBridge", return_value=mock_bridge):
        await sse_module.init_sse_bridge("redis://localhost:6379/0")

    with patch("bff_service.sse.asyncio.sleep", new=AsyncMock()) as sleep:
        await sse_module.close_sse_bridge()
        await sse_module.close_sse_bridge()

    assert sleep.await_count == 2
    mock_bridge.close.assert_awaited_once()
    assert sse_module._state.bridge is None
    assert sse_module._state.shutdown_event is None
