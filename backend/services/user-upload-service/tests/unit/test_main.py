"""Unit tests for attachment_service.main module lifespan."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FatalConsumerSupervisor:
    """Interrupt the lifespan body when a simulated consumer owner fails."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self._failure = asyncio.Event()

    @contextlib.asynccontextmanager
    async def context(self) -> AsyncIterator[None]:
        """Enter supervision and convert the injected cancellation to its fatal cause."""
        body_task = asyncio.current_task()
        assert body_task is not None
        self.entered.set()

        async def interrupt_body() -> None:
            await self._failure.wait()
            body_task.cancel()

        monitor = asyncio.create_task(interrupt_body())
        try:
            yield
        except asyncio.CancelledError as error:
            if not self._failure.is_set():
                raise
            message = "consumer owner failed"
            raise RuntimeError(message) from error
        finally:
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor

    def fail(self) -> None:
        """Inject a fatal owner failure into the active lifespan body."""
        self._failure.set()


class TestLifespan:
    """Tests for lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_initializes_database(self) -> None:
        """Lifespan calls initialize_database with settings."""
        with (
            patch(
                "user_upload_service.main.initialize_database",
                new_callable=AsyncMock,
            ) as mock_init_db,
            patch(
                "user_upload_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "user_upload_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("user_upload_service.main.kafka_client") as mock_kafka,
            patch(
                "user_upload_service.main.close_all_engines",
                new_callable=AsyncMock,
            ),
        ):
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()

            from user_upload_service.main import lifespan, settings

            mock_app = MagicMock()

            async with lifespan(mock_app):
                mock_init_db.assert_awaited()

            mock_init_db.assert_awaited_once_with(settings)

    @pytest.mark.asyncio
    async def test_lifespan_handles_db_init_failure(self) -> None:
        """Lifespan raises exception on database initialization failure."""
        mock_init_db = AsyncMock(side_effect=RuntimeError("DB init failed"))
        with (
            patch("user_upload_service.main.initialize_database", mock_init_db),
            patch(
                "user_upload_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
        ):
            from user_upload_service.main import lifespan

            mock_app = MagicMock()

            with pytest.raises(RuntimeError, match="DB init failed"):
                async with lifespan(mock_app):
                    mock_init_db.assert_awaited()

    @pytest.mark.asyncio
    async def test_consumer_owner_failure_propagates_and_cleans_up(self) -> None:
        """A fatal consumer owner failure aborts lifespan and preserves cleanup order."""
        supervisor = _FatalConsumerSupervisor()
        call_order: list[str] = []

        with (
            patch("user_upload_service.main.initialize_database", new_callable=AsyncMock),
            patch("user_upload_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch(
                "user_upload_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("user_upload_service.main.start_event_consumer"),
            patch("user_upload_service.main.kafka_client") as mock_kafka,
            patch("user_upload_service.main.close_all_engines", new_callable=AsyncMock) as mock_close,
            patch("user_upload_service.main.obs") as mock_obs,
        ):
            mock_kafka.supervise_consumer_failures = supervisor.context
            mock_kafka.stop_consumers = AsyncMock(side_effect=lambda: call_order.append("stop"))
            mock_kafka.close = AsyncMock(side_effect=lambda: call_order.append("kafka"))
            mock_close.side_effect = lambda: call_order.append("database")
            mock_obs.shutdown.side_effect = lambda: call_order.append("observability")

            from user_upload_service.main import lifespan

            async def run_lifespan_until_failure() -> None:
                async with lifespan(MagicMock()):
                    assert supervisor.entered.is_set()
                    supervisor.fail()
                    await asyncio.Event().wait()

            with pytest.raises(RuntimeError, match="consumer owner failed"):
                await run_lifespan_until_failure()

        assert call_order == ["stop", "kafka", "database", "observability"]

    @pytest.mark.asyncio
    async def test_consumer_start_failure_never_enters_supervision(self) -> None:
        """Failed consumer registration cleans initialized resources without supervision."""
        supervisor = _FatalConsumerSupervisor()

        with (
            patch("user_upload_service.main.initialize_database", new_callable=AsyncMock),
            patch("user_upload_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch(
                "user_upload_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch(
                "user_upload_service.main.start_event_consumer",
                side_effect=RuntimeError("consumer registration failed"),
            ),
            patch("user_upload_service.main.kafka_client") as mock_kafka,
            patch("user_upload_service.main.close_all_engines", new_callable=AsyncMock) as mock_close,
            patch("user_upload_service.main.obs") as mock_obs,
        ):
            mock_kafka.supervise_consumer_failures = supervisor.context
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()

            from user_upload_service.main import lifespan

            with pytest.raises(RuntimeError, match="consumer registration failed"):
                async with lifespan(MagicMock()):
                    pytest.fail("lifespan yielded after consumer startup failed")

        assert not supervisor.entered.is_set()
        mock_kafka.stop_consumers.assert_not_awaited()
        mock_kafka.close.assert_awaited_once()
        mock_close.assert_awaited_once()
        mock_obs.shutdown.assert_called_once()
