"""Unit tests for main.py module."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
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


class TestAppStructure:
    """Tests for app structure."""

    def test_creates_fastapi_app(self) -> None:
        """Test that app is a FastAPI instance."""
        from job_storage_service.main import app

        assert isinstance(app, FastAPI)

    def test_app_has_correct_title(self) -> None:
        """Test that app has the correct title from settings."""
        from job_storage_service.main import app

        assert app.title == "Listing Store Service"

    def test_app_has_correct_version(self) -> None:
        """Test that app has the correct version."""
        from job_storage_service.main import app

        assert app.version == "0.1.0"

    def test_app_has_lifespan(self) -> None:
        """Test that app has a lifespan context manager."""
        from job_storage_service.main import app

        assert app.router.lifespan_context is not None

    def test_root_endpoint_exists(self) -> None:
        """Test that root endpoint is reachable through mounted routers."""
        from job_storage_service.main import app

        response = TestClient(app).get("/")
        assert response.status_code == 200

    def test_healthz_endpoint_exists(self) -> None:
        """Test that health endpoint is reachable through mounted routers."""
        from job_storage_service.main import app

        response = TestClient(app, raise_server_exceptions=False).get("/healthz")
        assert response.status_code in (200, 503)


class TestLifespan:
    """Tests for the lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_startup_and_shutdown(self) -> None:
        """Lifespan initializes DB, Kafka, consumers on startup and cleans up on shutdown."""
        from job_storage_service.main import lifespan

        mock_app = MagicMock(spec=FastAPI)

        with (
            patch(
                "job_storage_service.main.initialize_database",
                new_callable=AsyncMock,
            ) as mock_init_db,
            patch(
                "job_storage_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ) as mock_kafka_ready,
            patch(
                "job_storage_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch(
                "job_storage_service.main.start_event_consumer",
            ) as mock_start_consumer,
            patch(
                "job_storage_service.main.kafka_client",
            ) as mock_kafka_client,
            patch(
                "job_storage_service.main.close_all_engines",
                new_callable=AsyncMock,
            ) as mock_close_engines,
            patch("job_storage_service.main.obs") as mock_obs,
        ):
            mock_kafka_client.stop_consumers = AsyncMock()
            mock_kafka_client.close = AsyncMock()
            mock_kafka_client.supervise_consumer_failures = ConsumerSupervision()

            async with lifespan(mock_app):
                mock_init_db.assert_called_once()
                mock_kafka_ready.assert_called_once()
                mock_start_consumer.assert_called_once()

            mock_kafka_client.stop_consumers.assert_called_once()
            mock_kafka_client.close.assert_called_once()
            mock_close_engines.assert_called_once()
            mock_obs.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_fatal_consumer_failure_joins_saga_task_and_preserves_cleanup_order(
        self,
    ) -> None:
        """Fatal consumer failure interrupts runtime and joins the saga sweep."""
        from job_storage_service.main import lifespan

        failure = RuntimeError("consumer owner failed")
        supervision = ConsumerSupervision(failure)
        saga_started = asyncio.Event()
        order: list[str] = []

        async def stale_saga_loop(_: asyncio.Event) -> None:
            saga_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                order.append("saga")

        kafka_client = MagicMock()
        kafka_client.stop_consumers = AsyncMock(side_effect=lambda: order.append("stop"))
        kafka_client.close = AsyncMock(side_effect=lambda: order.append("kafka"))
        kafka_client.supervise_consumer_failures = supervision
        qdrant_client = MagicMock()
        qdrant_client.raw_client.close = AsyncMock(side_effect=lambda: order.append("qdrant"))
        observability = MagicMock()
        observability.shutdown.side_effect = lambda: order.append("observability")

        with (
            patch(
                "job_storage_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch(
                "job_storage_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_storage_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("job_storage_service.main.get_qdrant_client", return_value=qdrant_client),
            patch("job_storage_service.main.start_event_consumer"),
            patch("job_storage_service.main.kafka_client", kafka_client),
            patch(
                "job_storage_service.main.close_all_engines",
                new=AsyncMock(side_effect=lambda: order.append("database")),
            ),
            patch("job_storage_service.main._stale_saga_loop", new=stale_saga_loop),
            patch("job_storage_service.main.obs", observability),
        ):
            lifespan_context = lifespan(MagicMock(spec=FastAPI))
            with pytest.raises(ExceptionGroup) as raised:
                await supervision.interrupt(lifespan_context, after=saga_started)

        assert raised.value.exceptions == (failure,)
        assert order == [
            "stop",
            "saga",
            "kafka",
            "qdrant",
            "database",
            "observability",
        ]


class TestStaleSagaLoop:
    """Tests for the _stale_saga_loop background task."""

    @pytest.mark.asyncio
    async def test_stale_saga_loop_runs_detector_and_commits(self) -> None:
        """Happy path: detector runs and db.commit() is called."""
        from job_storage_service.main import _stale_saga_loop

        shutdown_event = asyncio.Event()
        mock_db = AsyncMock()

        # Create a proper async context manager mock
        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_db
        mock_session_context.__aexit__.return_value = None

        # sessionmaker is a callable that returns the context manager
        mock_sessionmaker = MagicMock(return_value=mock_session_context)

        mock_detector = AsyncMock()

        with (
            patch(
                "job_storage_service.main.get_async_sessionmaker",
                return_value=mock_sessionmaker,
            ),
            patch(
                "job_storage_service.main.StaleSagaDetector",
                return_value=mock_detector,
            ),
            patch("job_storage_service.main.get_ingest_metrics") as mock_metrics,
            patch("job_storage_service.main._STALE_SAGA_INTERVAL_SECONDS", 0),
        ):
            mock_metrics.return_value = MagicMock()

            # Set shutdown event after first detector.run call
            async def set_shutdown_after_run(*_args: object, **_kwargs: object) -> None:
                shutdown_event.set()

            mock_detector.run.side_effect = set_shutdown_after_run

            # Run the loop
            task = asyncio.create_task(_stale_saga_loop(shutdown_event))
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except TimeoutError:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

            # Verify detector.run was called
            mock_detector.run.assert_called_once_with(mock_db)

            # Verify commit was called
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_stale_saga_loop_handles_exception_and_retries(self) -> None:
        """Error path: exception is caught, metrics recorded, and loop continues."""
        from job_storage_service.main import _stale_saga_loop

        shutdown_event = asyncio.Event()
        mock_db = AsyncMock()

        # Create a proper async context manager mock
        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_db
        mock_session_context.__aexit__.return_value = None

        # sessionmaker is a callable that returns the context manager
        mock_sessionmaker = MagicMock(return_value=mock_session_context)

        mock_detector = AsyncMock()
        call_count = 0
        detector_failed_msg = "Detector failed"

        async def raise_then_shutdown(*_args: object, **_kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = detector_failed_msg
                raise RuntimeError(msg)
            shutdown_event.set()

        mock_detector.run.side_effect = raise_then_shutdown

        with (
            patch(
                "job_storage_service.main.get_async_sessionmaker",
                return_value=mock_sessionmaker,
            ),
            patch(
                "job_storage_service.main.StaleSagaDetector",
                return_value=mock_detector,
            ),
            patch("job_storage_service.main.get_ingest_metrics") as mock_metrics,
            patch("job_storage_service.main.logger") as mock_logger,
            patch("job_storage_service.main._STALE_SAGA_INTERVAL_SECONDS", 0),
        ):
            mock_metrics_instance = MagicMock()
            mock_metrics.return_value = mock_metrics_instance

            # Run the loop
            task = asyncio.create_task(_stale_saga_loop(shutdown_event))
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except TimeoutError:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

            # Verify exception was logged
            mock_logger.exception.assert_called()

            # Verify metrics recorded failure
            mock_metrics_instance.record_stale_saga_sweep_failure.assert_called()

            # Verify detector was called twice (error on first, success on second)
            assert mock_detector.run.call_count == 2

    @pytest.mark.asyncio
    async def test_stale_saga_loop_exits_on_shutdown_event(self) -> None:
        """Shutdown path: loop exits immediately when shutdown event is set."""
        from job_storage_service.main import _stale_saga_loop

        shutdown_event = asyncio.Event()
        shutdown_event.set()  # Set immediately

        mock_detector = AsyncMock()
        mock_db = AsyncMock()

        # Create a proper async context manager mock
        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_db
        mock_session_context.__aexit__.return_value = None

        # sessionmaker is a callable that returns the context manager
        mock_sessionmaker = MagicMock(return_value=mock_session_context)

        with (
            patch(
                "job_storage_service.main.get_async_sessionmaker",
                return_value=mock_sessionmaker,
            ),
            patch(
                "job_storage_service.main.StaleSagaDetector",
                return_value=mock_detector,
            ),
            patch("job_storage_service.main.get_ingest_metrics") as mock_metrics,
        ):
            mock_metrics.return_value = MagicMock()

            # Run with timeout
            await asyncio.wait_for(
                _stale_saga_loop(shutdown_event),
                timeout=1.0,
            )

            # Verify detector.run was never called (loop exited immediately)
            mock_detector.run.assert_not_called()
