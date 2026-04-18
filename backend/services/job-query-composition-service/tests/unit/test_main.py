"""Unit tests for main application module."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
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
    """Tests for application lifespan management."""

    @pytest.mark.asyncio
    async def test_lifespan_logs_startup(self) -> None:
        """Test that lifespan logs service startup."""
        with (
            patch("job_query_composition_service.main.logger") as mock_logger,
            patch(
                "job_query_composition_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch(
                "job_query_composition_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_query_composition_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("job_query_composition_service.main.start_event_consumer"),
            patch("job_query_composition_service.main.kafka_client") as mock_kafka,
            patch(
                "job_query_composition_service.main.close_all_engines",
                new_callable=AsyncMock,
            ),
            patch("job_query_composition_service.main.obs"),
        ):
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()
            mock_kafka.supervise_consumer_failures = ConsumerSupervision()

            from job_query_composition_service.main import lifespan

            mock_app = MagicMock(spec=FastAPI)
            mock_app.state = MagicMock()

            async with lifespan(mock_app):
                startup_calls = [call for call in mock_logger.info.call_args_list if "Starting" in str(call)]
                assert len(startup_calls) >= 1

    @pytest.mark.asyncio
    async def test_lifespan_logs_shutdown(self) -> None:
        """Test that lifespan logs service shutdown."""
        with (
            patch("job_query_composition_service.main.logger") as mock_logger,
            patch(
                "job_query_composition_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch(
                "job_query_composition_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_query_composition_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("job_query_composition_service.main.start_event_consumer"),
            patch("job_query_composition_service.main.kafka_client") as mock_kafka,
            patch(
                "job_query_composition_service.main.close_all_engines",
                new_callable=AsyncMock,
            ),
            patch("job_query_composition_service.main.obs"),
        ):
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()
            mock_kafka.supervise_consumer_failures = ConsumerSupervision()

            from job_query_composition_service.main import lifespan

            mock_app = MagicMock(spec=FastAPI)
            mock_app.state = MagicMock()

            async with lifespan(mock_app):
                pass

            shutdown_calls = [call for call in mock_logger.info.call_args_list if "shutdown" in str(call).lower()]
            assert len(shutdown_calls) >= 1

    @pytest.mark.asyncio
    async def test_lifespan_initializes_database(self) -> None:
        """Test that lifespan calls initialize_database with settings."""
        with (
            patch(
                "job_query_composition_service.main.initialize_database",
                new_callable=AsyncMock,
            ) as mock_init_db,
            patch(
                "job_query_composition_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_query_composition_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("job_query_composition_service.main.start_event_consumer"),
            patch("job_query_composition_service.main.kafka_client") as mock_kafka,
            patch(
                "job_query_composition_service.main.close_all_engines",
                new_callable=AsyncMock,
            ),
            patch("job_query_composition_service.main.obs"),
        ):
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()
            mock_kafka.supervise_consumer_failures = ConsumerSupervision()

            from job_query_composition_service.main import lifespan, settings

            mock_app = MagicMock(spec=FastAPI)
            mock_app.state = MagicMock()

            async with lifespan(mock_app):
                mock_init_db.assert_awaited_once_with(settings)

    @pytest.mark.asyncio
    async def test_lifespan_handles_db_init_failure(self) -> None:
        """Test that lifespan raises exception on database initialization failure."""
        mock_init_db = AsyncMock(side_effect=RuntimeError("DB init failed"))
        with patch("job_query_composition_service.main.initialize_database", mock_init_db):
            from job_query_composition_service.main import lifespan

            mock_app = MagicMock(spec=FastAPI)
            mock_app.state = MagicMock()

            with pytest.raises(RuntimeError, match="DB init failed"):
                async with lifespan(mock_app):
                    mock_init_db.assert_awaited()

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
                "job_query_composition_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch(
                "job_query_composition_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_query_composition_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("job_query_composition_service.main.start_event_consumer"),
            patch("job_query_composition_service.main.kafka_client", kafka_client),
            patch(
                "job_query_composition_service.main.close_all_engines",
                new=AsyncMock(side_effect=lambda: order.append("db_close")),
            ),
            patch("job_query_composition_service.main.obs", observability),
        ):
            from job_query_composition_service.main import app, lifespan

            with pytest.raises(ExceptionGroup) as raised:
                await supervision.interrupt(lifespan(app))

        assert raised.value.exceptions == (failure,)
        assert order == ["stop_consumers", "kafka_close", "db_close", "obs_shutdown"]


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_healthz_endpoint_exists(self) -> None:
        """Test that /healthz endpoint exists and responds."""
        from job_query_composition_service.main import app

        with patch.dict("os.environ", {"TESTING": "true"}):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/healthz")
            assert response.status_code in (200, 503)

    def test_readyz_endpoint_exists(self) -> None:
        """Test that /readyz endpoint exists and responds."""
        from job_query_composition_service.main import app

        with patch.dict("os.environ", {"TESTING": "true"}):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/readyz")
            assert response.status_code in (200, 503)

    def test_root_endpoint_returns_service_info(self) -> None:
        """Test that root endpoint returns service information."""
        from job_query_composition_service.main import app

        with patch.dict("os.environ", {"TESTING": "true"}):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/")
            assert response.status_code == 200
            data = response.json()
            assert "service" in data or "name" in data
