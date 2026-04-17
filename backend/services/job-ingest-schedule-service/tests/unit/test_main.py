"""Unit tests for main.py module."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class ConsumerSupervision:
    """Async consumer scope that can inject an owner failure during runtime."""

    def __init__(self, failure: RuntimeError | None = None) -> None:
        self._failure = failure
        self._release_failure = asyncio.Event()
        self._entered = False

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[None]:
        self._entered = True
        try:
            failure = self._failure
            if failure is None:
                yield
                return

            async def raise_failure() -> None:
                await self._release_failure.wait()
                raise failure

            async with asyncio.TaskGroup() as tasks:
                monitor = tasks.create_task(raise_failure())
                try:
                    yield
                finally:
                    monitor.cancel()
        finally:
            self._entered = False

    def fail(self) -> None:
        assert self._entered
        self._release_failure.set()

    async def interrupt(
        self,
        lifespan_context: AbstractAsyncContextManager[object],
        *,
        after: asyncio.Event | None = None,
    ) -> None:
        async with lifespan_context:
            if after is not None:
                await after.wait()
            self.fail()
            await asyncio.Event().wait()


class TestLifespan:
    """Tests for lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_startup_initializes_database(self) -> None:
        """Test that lifespan startup initializes database."""
        with (
            patch(
                "job_ingest_schedule_service.main.initialize_database",
                new_callable=AsyncMock,
            ) as mock_init_db,
            patch(
                "job_ingest_schedule_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_schedule_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("job_ingest_schedule_service.main.start_event_consumer") as mock_start_consumer,
            patch("job_ingest_schedule_service.main.kafka_client") as mock_kafka,
            patch(
                "job_ingest_schedule_service.main.close_all_engines",
                new_callable=AsyncMock,
            ),
        ):
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()
            mock_kafka.supervise_consumer_failures = ConsumerSupervision()

            from job_ingest_schedule_service.main import app

            async with app.router.lifespan_context(app):
                mock_init_db.assert_awaited_once()
                mock_start_consumer.assert_called_once()

    @pytest.mark.asyncio
    async def test_fatal_consumer_failure_interrupts_and_preserves_cleanup_order(
        self,
    ) -> None:
        """A fatal owner failure escapes lifespan after ordered cleanup."""
        failure = RuntimeError("consumer owner failed")
        supervision = ConsumerSupervision(failure)
        order: list[str] = []
        kafka_client = MagicMock()
        kafka_client.stop_consumers = AsyncMock(side_effect=lambda: order.append("stop_consumers"))
        kafka_client.close = AsyncMock(side_effect=lambda: order.append("kafka_close"))
        kafka_client.supervise_consumer_failures = supervision
        observability = MagicMock()
        observability.shutdown.side_effect = lambda: order.append("obs_shutdown")

        with (
            patch(
                "job_ingest_schedule_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_schedule_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_schedule_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("job_ingest_schedule_service.main.start_event_consumer"),
            patch("job_ingest_schedule_service.main.kafka_client", kafka_client),
            patch(
                "job_ingest_schedule_service.main.close_all_engines",
                new=AsyncMock(side_effect=lambda: order.append("db_close")),
            ),
            patch("job_ingest_schedule_service.main.obs", observability),
        ):
            from job_ingest_schedule_service.main import app, lifespan

            with pytest.raises(ExceptionGroup) as raised:
                await supervision.interrupt(lifespan(app))

        assert raised.value.exceptions == (failure,)
        assert order == ["stop_consumers", "kafka_close", "db_close", "obs_shutdown"]


class TestHealthEndpoint:
    """Tests for health endpoint via TestClient."""

    def test_health_endpoint_responds(self) -> None:
        """Test that health endpoint returns a response."""
        from job_ingest_schedule_service.main import app

        with (
            patch(
                "job_ingest_schedule_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch("job_ingest_schedule_service.events.handlers.start_event_consumer"),
            patch(
                "job_ingest_schedule_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("job_ingest_schedule_service.main.kafka_client") as mock_kafka,
            patch(
                "job_ingest_schedule_service.main.close_all_engines",
                new_callable=AsyncMock,
            ),
        ):
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()

            client = TestClient(app)
            response = client.get("/healthz")
            assert response.status_code in (200, 503)
