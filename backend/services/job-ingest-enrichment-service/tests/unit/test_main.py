"""Unit tests for main.py module."""

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


class TestAppStructure:
    """Tests for app structure."""

    def test_creates_fastapi_app(self) -> None:
        """App is a FastAPI instance."""
        from job_ingest_enrichment_service.main import app

        assert isinstance(app, FastAPI)

    def test_app_has_correct_title(self) -> None:
        """App has the correct title from settings."""
        from job_ingest_enrichment_service.main import app

        assert app.title == "Listing Parser Service"

    def test_app_has_correct_version(self) -> None:
        """App has the correct version."""
        from job_ingest_enrichment_service.main import app

        assert app.version == "0.1.0"

    def test_app_has_lifespan(self) -> None:
        """App has a lifespan context manager."""
        from job_ingest_enrichment_service.main import app

        assert app.router.lifespan_context is not None

    def test_root_endpoint_exists(self) -> None:
        """Root endpoint is reachable through mounted routers."""
        from job_ingest_enrichment_service.main import app

        response = TestClient(app).get("/")
        assert response.status_code == 200

    def test_healthz_endpoint_exists(self) -> None:
        """Health endpoint is reachable through mounted routers."""
        from job_ingest_enrichment_service.main import app

        response = TestClient(app, raise_server_exceptions=False).get("/healthz")
        assert response.status_code in (200, 503)


class TestLifespan:
    """Tests for the lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_startup_and_shutdown(self) -> None:
        """Lifespan initializes DB, Kafka, starts consumers, and cleans up on shutdown."""
        from job_ingest_enrichment_service.main import app, settings

        with (
            patch(
                "job_ingest_enrichment_service.main.initialize_database",
                new_callable=AsyncMock,
            ) as mock_init_db,
            patch(
                "job_ingest_enrichment_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ) as mock_kafka_ready,
            patch(
                "job_ingest_enrichment_service.main.ensure_llm_ready",
                new_callable=AsyncMock,
            ) as mock_llm_ready,
            patch(
                "job_ingest_enrichment_service.main.ensure_redis_ready",
                new_callable=AsyncMock,
            ) as _mock_redis_ready,
            patch(
                "job_ingest_enrichment_service.main.get_async_sessionmaker",
            ) as mock_get_sessionmaker,
            patch(
                "job_ingest_enrichment_service.main.start_event_consumer",
            ) as mock_start_consumer,
            patch(
                "job_ingest_enrichment_service.main.kafka_client",
            ) as mock_kafka_client,
            patch(
                "job_ingest_enrichment_service.main.CacheFactory",
            ) as _mock_cache_factory,
            patch(
                "job_ingest_enrichment_service.main.close_extraction_llm_client",
                new_callable=AsyncMock,
            ) as close_extraction,
            patch(
                "job_ingest_enrichment_service.main.close_skill_clarification_service",
                new_callable=AsyncMock,
            ) as close_clarification,
            patch("job_ingest_enrichment_service.main.obs") as mock_obs,
        ):
            mock_kafka_client.stop_consumers = AsyncMock()
            mock_kafka_client.close = AsyncMock()
            mock_kafka_client.supervise_consumer_failures = ConsumerSupervision()
            _mock_cache_factory.close_all = AsyncMock()

            async with app.router.lifespan_context(app):
                mock_init_db.assert_called_once()
                mock_kafka_ready.assert_called_once()
                mock_llm_ready.assert_awaited_once_with(
                    settings.llm,
                    chains=("extraction", "skill_clarification"),
                )
                mock_get_sessionmaker.assert_called_once()
                mock_kafka_client.set_db_session_factory.assert_called_once()
                mock_start_consumer.assert_called_once()

            mock_kafka_client.stop_consumers.assert_called_once()
            mock_kafka_client.close.assert_called_once()
            mock_obs.shutdown.assert_called_once()
            close_extraction.assert_awaited_once_with()
            close_clarification.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_lifespan_closes_llm_owners_after_partial_startup_failure(
        self,
    ) -> None:
        """Registered LLM owners close even when readiness fails before consumers start."""
        from job_ingest_enrichment_service.main import app

        with (
            patch(
                "job_ingest_enrichment_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_enrichment_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_enrichment_service.main.ensure_llm_ready",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM unavailable"),
            ),
            patch("job_ingest_enrichment_service.main.start_event_consumer") as start_consumer,
            patch(
                "job_ingest_enrichment_service.main.close_extraction_llm_client",
                new_callable=AsyncMock,
            ) as close_extraction,
            patch(
                "job_ingest_enrichment_service.main.close_skill_clarification_service",
                new_callable=AsyncMock,
            ) as close_clarification,
            patch("job_ingest_enrichment_service.main.kafka_client") as kafka_client,
            patch(
                "job_ingest_enrichment_service.main.CacheFactory.close_all",
                new_callable=AsyncMock,
            ) as close_cache,
            patch(
                "job_ingest_enrichment_service.main.close_all_engines",
                new_callable=AsyncMock,
            ) as close_engines,
            patch("job_ingest_enrichment_service.main.obs") as obs,
        ):
            kafka_client.close = AsyncMock()
            with pytest.raises(RuntimeError, match="LLM unavailable"):
                async with app.router.lifespan_context(app):
                    pytest.fail("lifespan yielded after failed startup")

        start_consumer.assert_not_called()
        close_extraction.assert_awaited_once_with()
        close_clarification.assert_awaited_once_with()
        kafka_client.close.assert_awaited_once_with()
        close_cache.assert_awaited_once_with()
        close_engines.assert_awaited_once_with()
        obs.shutdown.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_consumer_start_failure_stops_before_all_dependency_cleanup(
        self,
    ) -> None:
        """A partially started consumer is stopped before every dependency is closed."""
        from job_ingest_enrichment_service.main import app

        events: list[str] = []
        with (
            patch(
                "job_ingest_enrichment_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_enrichment_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_enrichment_service.main.ensure_llm_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_enrichment_service.main.ensure_redis_ready",
                new_callable=AsyncMock,
            ),
            patch("job_ingest_enrichment_service.main.get_async_sessionmaker"),
            patch(
                "job_ingest_enrichment_service.main.start_event_consumer",
                side_effect=RuntimeError("consumer start failed"),
            ),
            patch(
                "job_ingest_enrichment_service.main.close_extraction_llm_client",
                new=AsyncMock(side_effect=lambda: events.append("extraction-llm")),
            ),
            patch(
                "job_ingest_enrichment_service.main.close_skill_clarification_service",
                new=AsyncMock(side_effect=lambda: events.append("clarification-llm")),
            ),
            patch("job_ingest_enrichment_service.main.kafka_client") as kafka_client,
            patch(
                "job_ingest_enrichment_service.main.CacheFactory.close_all",
                new=AsyncMock(side_effect=lambda: events.append("cache")),
            ),
            patch(
                "job_ingest_enrichment_service.main.close_all_engines",
                new=AsyncMock(side_effect=lambda: events.append("database")),
            ),
            patch("job_ingest_enrichment_service.main.obs") as obs,
        ):
            kafka_client.stop_consumers = AsyncMock(side_effect=lambda: events.append("stop"))
            kafka_client.close = AsyncMock(side_effect=lambda: events.append("kafka"))
            obs.shutdown.side_effect = lambda: events.append("observability")
            with pytest.raises(RuntimeError, match="consumer start failed"):
                async with app.router.lifespan_context(app):
                    pytest.fail("lifespan yielded after failed consumer start")

        assert events == [
            "stop",
            "extraction-llm",
            "clarification-llm",
            "kafka",
            "cache",
            "database",
            "observability",
        ]

    @pytest.mark.asyncio
    async def test_fatal_consumer_failure_cancels_saga_task_before_cleanup(
        self,
    ) -> None:
        """Fatal consumer failure interrupts runtime and joins the saga sweep first."""
        from job_ingest_enrichment_service.main import app

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
        cache_factory = MagicMock()
        cache_factory.close_all = AsyncMock(side_effect=lambda: order.append("cache"))
        observability = MagicMock()
        observability.shutdown.side_effect = lambda: order.append("observability")

        with (
            patch(
                "job_ingest_enrichment_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_enrichment_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_enrichment_service.main.ensure_llm_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_enrichment_service.main.ensure_redis_ready",
                new_callable=AsyncMock,
            ),
            patch("job_ingest_enrichment_service.main.get_async_sessionmaker"),
            patch("job_ingest_enrichment_service.main.start_event_consumer"),
            patch("job_ingest_enrichment_service.main.kafka_client", kafka_client),
            patch("job_ingest_enrichment_service.main.CacheFactory", cache_factory),
            patch(
                "job_ingest_enrichment_service.main.close_extraction_llm_client",
                new=AsyncMock(side_effect=lambda: order.append("extraction-llm")),
            ),
            patch(
                "job_ingest_enrichment_service.main.close_skill_clarification_service",
                new=AsyncMock(side_effect=lambda: order.append("clarification-llm")),
            ),
            patch(
                "job_ingest_enrichment_service.main.close_all_engines",
                new=AsyncMock(side_effect=lambda: order.append("database")),
            ),
            patch(
                "job_ingest_enrichment_service.main._stale_saga_loop",
                new=stale_saga_loop,
            ),
            patch("job_ingest_enrichment_service.main.obs", observability),
        ):
            lifespan_context = app.router.lifespan_context(app)
            with pytest.raises(ExceptionGroup) as raised:
                await supervision.interrupt(lifespan_context, after=saga_started)

        assert raised.value.exceptions == (failure,)
        assert order == [
            "saga",
            "stop",
            "extraction-llm",
            "clarification-llm",
            "kafka",
            "cache",
            "database",
            "observability",
        ]
