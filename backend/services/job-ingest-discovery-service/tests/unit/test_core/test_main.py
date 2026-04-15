"""Unit tests for the job discovery service main application.

This service uses a database-backed idempotency/reservation design (via
DatabaseMixin) alongside Redis for dedup/caching and Kafka for eventing.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.routing import Route


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


class TestAppConfiguration:
    """Tests for FastAPI app configuration."""

    def test_app_exists(self) -> None:
        """Test that the FastAPI app is created."""
        from job_ingest_discovery_service.main import app

        assert isinstance(app, FastAPI)

    def test_app_title(self) -> None:
        """Test that the app has the correct title."""
        from job_ingest_discovery_service.main import app

        assert app.title == "Job Ingest Discovery Service"

    def test_app_has_lifespan(self) -> None:
        """Test that the app has a lifespan context manager."""
        from job_ingest_discovery_service.main import app

        assert app.router.lifespan_context is not None


class TestLifespan:
    """Tests for the lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_startup_test_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test lifespan startup in test mode (no Kafka consumers)."""
        monkeypatch.setenv("TEST_MODE", "true")
        monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

        with (
            patch(
                "job_ingest_discovery_service.main.initialize_database",
                new_callable=AsyncMock,
            ) as mock_init_db,
            patch(
                "job_ingest_discovery_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch(
                "job_ingest_discovery_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ) as mock_kafka_ready,
            patch(
                "job_ingest_discovery_service.main.ensure_redis_ready",
                new_callable=AsyncMock,
            ),
            patch("job_ingest_discovery_service.main.start_event_consumer"),
            patch("job_ingest_discovery_service.main.kafka_client") as kafka_client,
        ):
            kafka_client.stop_consumers = AsyncMock()
            kafka_client.close = AsyncMock()
            kafka_client.supervise_consumer_failures = ConsumerSupervision()

            from job_ingest_discovery_service.main import app, lifespan

            async with lifespan(app):
                mock_init_db.assert_awaited_once()
                mock_kafka_ready.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifespan_startup_with_event_consumer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test lifespan startup with event consumers."""
        monkeypatch.setenv("TEST_MODE", "false")
        monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

        with (
            patch(
                "job_ingest_discovery_service.main.initialize_database",
                new_callable=AsyncMock,
            ) as mock_init_db,
            patch(
                "job_ingest_discovery_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch(
                "job_ingest_discovery_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ) as mock_kafka_ready,
            patch(
                "job_ingest_discovery_service.main.ensure_redis_ready",
                new_callable=AsyncMock,
            ),
            patch("job_ingest_discovery_service.main.start_event_consumer") as mock_start_consumer,
            patch("job_ingest_discovery_service.main.kafka_client") as kafka_client,
        ):
            kafka_client.stop_consumers = AsyncMock()
            kafka_client.close = AsyncMock()
            kafka_client.supervise_consumer_failures = ConsumerSupervision()

            from job_ingest_discovery_service.main import app, lifespan

            async with lifespan(app):
                mock_init_db.assert_awaited_once()
                mock_kafka_ready.assert_awaited_once()
                mock_start_consumer.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_calls_cleanup_methods(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that lifespan shutdown calls all cleanup methods in correct order."""
        monkeypatch.setenv("TEST_MODE", "false")
        monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

        call_order: list[str] = []

        async def track_stop_consumers() -> None:
            await asyncio.sleep(0)
            call_order.append("stop_consumers")

        async def track_kafka_close() -> None:
            await asyncio.sleep(0)
            call_order.append("kafka_close")

        async def track_db_close() -> None:
            await asyncio.sleep(0)
            call_order.append("db_close")

        async def track_jsearch_close() -> None:
            await asyncio.sleep(0)
            call_order.append("jsearch_close")

        async def track_cache_close() -> None:
            await asyncio.sleep(0)
            call_order.append("cache_close")

        def track_obs_shutdown() -> None:
            call_order.append("obs_shutdown")

        mock_kafka = MagicMock()
        mock_kafka.stop_consumers = AsyncMock(side_effect=track_stop_consumers)
        mock_kafka.close = AsyncMock(side_effect=track_kafka_close)
        mock_kafka.supervise_consumer_failures = ConsumerSupervision()

        mock_cache_factory = MagicMock()
        mock_cache_factory.close_all = AsyncMock(side_effect=track_cache_close)

        mock_obs = MagicMock()
        mock_obs.shutdown = MagicMock(side_effect=track_obs_shutdown)

        with (
            patch(
                "job_ingest_discovery_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_discovery_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch(
                "job_ingest_discovery_service.main.close_all_engines",
                new_callable=AsyncMock,
                side_effect=track_db_close,
            ),
            patch(
                "job_ingest_discovery_service.main.reset_jsearch_client",
                new_callable=AsyncMock,
                side_effect=track_jsearch_close,
            ),
            patch(
                "job_ingest_discovery_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_discovery_service.main.ensure_redis_ready",
                new_callable=AsyncMock,
            ),
            patch("job_ingest_discovery_service.main.start_event_consumer"),
            patch("job_ingest_discovery_service.main.kafka_client", mock_kafka),
            patch("job_ingest_discovery_service.main.CacheFactory", mock_cache_factory),
            patch("job_ingest_discovery_service.main.obs", mock_obs),
        ):
            from job_ingest_discovery_service.main import app, lifespan

            async with lifespan(app):
                pass  # Startup and shutdown

        # Verify cleanup was called in correct order: Kafka, then database,
        # then provider HTTP clients, then Redis, then observability.
        mock_kafka.stop_consumers.assert_awaited_once()
        mock_kafka.close.assert_awaited_once()
        mock_cache_factory.close_all.assert_awaited_once()
        mock_obs.shutdown.assert_called_once()

        assert call_order == [
            "stop_consumers",
            "kafka_close",
            "db_close",
            "jsearch_close",
            "cache_close",
            "obs_shutdown",
        ]

    @pytest.mark.asyncio
    async def test_fatal_consumer_failure_interrupts_and_preserves_cleanup_order(
        self,
    ) -> None:
        """A fatal owner failure escapes lifespan after every dependency closes."""
        failure = RuntimeError("consumer owner failed")
        supervision = ConsumerSupervision(failure)
        order: list[str] = []
        kafka_client = MagicMock()
        kafka_client.stop_consumers = AsyncMock(side_effect=lambda: order.append("stop_consumers"))
        kafka_client.close = AsyncMock(side_effect=lambda: order.append("kafka_close"))
        kafka_client.supervise_consumer_failures = supervision
        cache_factory = MagicMock()
        cache_factory.close_all = AsyncMock(side_effect=lambda: order.append("cache_close"))
        observability = MagicMock()
        observability.shutdown.side_effect = lambda: order.append("obs_shutdown")

        with (
            patch(
                "job_ingest_discovery_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_discovery_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_discovery_service.main.ensure_redis_ready",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_discovery_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("job_ingest_discovery_service.main.start_event_consumer"),
            patch("job_ingest_discovery_service.main.kafka_client", kafka_client),
            patch("job_ingest_discovery_service.main.CacheFactory", cache_factory),
            patch(
                "job_ingest_discovery_service.main.close_all_engines",
                new=AsyncMock(side_effect=lambda: order.append("db_close")),
            ),
            patch(
                "job_ingest_discovery_service.main.reset_jsearch_client",
                new=AsyncMock(side_effect=lambda: order.append("provider_close")),
            ),
            patch("job_ingest_discovery_service.main.obs", observability),
        ):
            from job_ingest_discovery_service.main import app, lifespan

            with pytest.raises(ExceptionGroup) as raised:
                await supervision.interrupt(lifespan(app))

        assert raised.value.exceptions == (failure,)
        assert order == [
            "stop_consumers",
            "kafka_close",
            "db_close",
            "provider_close",
            "cache_close",
            "obs_shutdown",
        ]


class TestMiddleware:
    """Tests for middleware configuration."""

    def test_correlation_id_middleware_added(self) -> None:
        """Test that CorrelationIdMiddleware is added to the app."""
        from job_ingest_discovery_service.main import app

        middleware_classes = [m.cls.__name__ for m in app.user_middleware if hasattr(m.cls, "__name__")]
        assert "CorrelationIdMiddleware" in middleware_classes


class TestRouters:
    """Tests for router configuration."""

    def test_health_router_included(self) -> None:
        """Test that health router is included."""
        from job_ingest_discovery_service.main import app

        routes = [r.path for r in app.routes if isinstance(r, Route)]
        assert "/health" in routes or any("/health" in str(r) for r in app.routes)

    def test_root_router_included(self) -> None:
        """Test that root router is included."""
        from job_ingest_discovery_service.main import app

        routes = [r.path for r in app.routes if isinstance(r, Route)]
        assert "/" in routes


class TestServiceConstants:
    """Tests for service constants."""

    def test_service_name_defined(self) -> None:
        """Test that service_name is defined in settings."""
        from job_ingest_discovery_service.core.config import get_settings

        settings = get_settings()
        assert settings.service_name == "job-ingest-discovery-service"

    def test_service_version_defined(self) -> None:
        """Test that service_version is defined in settings."""
        from job_ingest_discovery_service.core.config import get_settings

        settings = get_settings()
        assert settings.service_version is not None
        assert len(settings.service_version) > 0


class TestServiceDependencies:
    """Tests verifying Settings expose the database/Redis/Kafka the service depends on."""

    def test_has_database_mixin(self) -> None:
        """Test that Settings carries the database-backed idempotency/reservation config."""
        from job_ingest_discovery_service.core.config import Settings

        settings = Settings()
        assert hasattr(settings, "database")
        assert settings.database_url == settings.database.connection_string

    def test_has_redis_mixin(self) -> None:
        """Test that Settings class has Redis configuration."""
        from job_ingest_discovery_service.core.config import Settings

        settings = Settings()
        assert hasattr(settings, "redis")

    def test_has_dedup_ttl_setting(self) -> None:
        """Test that dedup_ttl_seconds is configured."""
        from job_ingest_discovery_service.core.config import get_settings

        settings = get_settings()
        assert hasattr(settings.caching, "dedup_ttl_seconds")
        assert settings.caching.dedup_ttl_seconds == 2592000  # 30 days default
