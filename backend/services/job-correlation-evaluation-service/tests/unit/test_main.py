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

    def test_root_endpoint_reports_running(self) -> None:
        """The public root endpoint reports that the service is running."""
        from job_correlation_evaluation_service.main import app

        response = TestClient(app).get("/")

        assert response.status_code == 200
        assert response.json()["status"] == "running"

    def test_healthz_endpoint_reports_healthy(self) -> None:
        """The liveness endpoint reports a healthy process."""
        from job_correlation_evaluation_service.main import app

        response = TestClient(app).get("/healthz")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestLifespan:
    """Tests for lifespan context manager."""

    @pytest.mark.asyncio
    async def test_startup_initializes_database(self) -> None:
        """Test that startup initializes database."""
        with (
            patch(
                "job_correlation_evaluation_service.main.initialize_database",
                new_callable=AsyncMock,
            ) as mock_init_db,
            patch("job_correlation_evaluation_service.main.get_pipeline_settings") as mock_get_pipeline,
            patch("job_correlation_evaluation_service.main.ScoringPipeline") as mock_scoring_pipeline,
            patch("job_correlation_evaluation_service.main.MLScoringService") as mock_ml_service_cls,
            patch(
                "job_correlation_evaluation_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.start_event_consumer"),
            patch("job_correlation_evaluation_service.main.kafka_client") as mock_kafka,
            patch(
                "job_correlation_evaluation_service.main.close_all_engines",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.obs"),
            patch("job_correlation_evaluation_service.main.get_manifest"),
        ):
            mock_pipeline = MagicMock()
            mock_get_pipeline.return_value = mock_pipeline
            mock_scoring_pipeline.create.return_value = MagicMock()
            mock_ml_service = MagicMock()
            mock_ml_service.close = AsyncMock()
            mock_ml_service_cls.return_value = mock_ml_service
            mock_kafka.ensure_producer_ready = AsyncMock()
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()
            mock_kafka.supervise_consumer_failures = ConsumerSupervision()

            from job_correlation_evaluation_service.main import lifespan

            app = MagicMock(spec=FastAPI)
            app.state = MagicMock()
            app.state.ml_scoring_service = None

            async with lifespan(app):
                ...

            mock_init_db.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_startup_starts_event_consumer(self) -> None:
        """Test that startup starts event consumer."""
        with (
            patch(
                "job_correlation_evaluation_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.get_pipeline_settings") as mock_get_pipeline,
            patch("job_correlation_evaluation_service.main.ScoringPipeline") as mock_scoring_pipeline,
            patch("job_correlation_evaluation_service.main.MLScoringService") as mock_ml_service_cls,
            patch(
                "job_correlation_evaluation_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.start_event_consumer") as mock_start_consumer,
            patch("job_correlation_evaluation_service.main.kafka_client") as mock_kafka,
            patch(
                "job_correlation_evaluation_service.main.close_all_engines",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.obs"),
            patch("job_correlation_evaluation_service.main.get_manifest"),
        ):
            mock_pipeline = MagicMock()
            mock_get_pipeline.return_value = mock_pipeline
            mock_scoring_pipeline.create.return_value = MagicMock()
            mock_ml_service = MagicMock()
            mock_ml_service.close = AsyncMock()
            mock_ml_service_cls.return_value = mock_ml_service
            mock_kafka.ensure_producer_ready = AsyncMock()
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()
            mock_kafka.supervise_consumer_failures = ConsumerSupervision()

            from job_correlation_evaluation_service.main import lifespan

            app = MagicMock(spec=FastAPI)
            app.state = MagicMock()
            app.state.ml_scoring_service = None

            async with lifespan(app):
                ...

            mock_start_consumer.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_kafka_client(self) -> None:
        """Test that shutdown closes Kafka client."""
        with (
            patch(
                "job_correlation_evaluation_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.get_pipeline_settings") as mock_get_pipeline,
            patch("job_correlation_evaluation_service.main.ScoringPipeline") as mock_scoring_pipeline,
            patch("job_correlation_evaluation_service.main.MLScoringService") as mock_ml_service_cls,
            patch(
                "job_correlation_evaluation_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.start_event_consumer"),
            patch("job_correlation_evaluation_service.main.kafka_client") as mock_kafka,
            patch(
                "job_correlation_evaluation_service.main.close_all_engines",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.obs"),
            patch("job_correlation_evaluation_service.main.get_manifest"),
        ):
            mock_pipeline = MagicMock()
            mock_get_pipeline.return_value = mock_pipeline
            mock_scoring_pipeline.create.return_value = MagicMock()
            mock_ml_service = MagicMock()
            mock_ml_service.close = AsyncMock()
            mock_ml_service_cls.return_value = mock_ml_service
            mock_kafka.ensure_producer_ready = AsyncMock()
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()
            mock_kafka.supervise_consumer_failures = ConsumerSupervision()

            from job_correlation_evaluation_service.main import lifespan

            app = MagicMock(spec=FastAPI)
            app.state = MagicMock()
            app.state.ml_scoring_service = None

            async with lifespan(app):
                ...

            mock_kafka.stop_consumers.assert_awaited_once()
            mock_kafka.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_drains_consumers_before_closing_resources(self) -> None:
        """Consumer work is drained before any dependency it may still use is closed."""
        order: list[str] = []

        def tracked(name: str) -> AsyncMock:
            async def record() -> None:
                order.append(name)

            return AsyncMock(side_effect=record)

        qdrant = MagicMock()
        qdrant.close = tracked("qdrant")
        ml_service = MagicMock()
        ml_service.close = tracked("ml")
        database_close = tracked("database")
        cache_close = tracked("cache")

        with (
            patch(
                "job_correlation_evaluation_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.get_pipeline_settings") as get_pipeline,
            patch("job_correlation_evaluation_service.main.ScoringPipeline") as scoring_pipeline,
            patch(
                "job_correlation_evaluation_service.main.MLScoringService",
                return_value=ml_service,
            ),
            patch(
                "job_correlation_evaluation_service.main.create_async_qdrant_client",
                return_value=qdrant,
            ),
            patch(
                "job_correlation_evaluation_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.start_event_consumer"),
            patch("job_correlation_evaluation_service.main.kafka_client") as kafka,
            patch(
                "job_correlation_evaluation_service.main.close_all_engines",
                database_close,
            ),
            patch("job_correlation_evaluation_service.main.close_cache", cache_close),
            patch("job_correlation_evaluation_service.main.obs"),
            patch("job_correlation_evaluation_service.main.get_manifest") as manifest,
        ):
            pipeline_settings = MagicMock()
            get_pipeline.return_value = pipeline_settings
            scoring_pipeline.create.return_value = MagicMock()
            manifest.return_value.get_collection_name.return_value = "jobs"
            kafka.ensure_producer_ready = AsyncMock()
            kafka.stop_consumers = tracked("consumer")
            kafka.close = tracked("kafka")
            kafka.supervise_consumer_failures = ConsumerSupervision()

            from job_correlation_evaluation_service.main import lifespan

            app = MagicMock(spec=FastAPI)
            app.state = MagicMock()
            async with lifespan(app):
                ...

        assert order[0] == "consumer"
        assert set(order[1:]) == {"kafka", "ml", "qdrant", "cache", "database"}

    @pytest.mark.asyncio
    async def test_shutdown_closes_database_engines(self) -> None:
        """Test that shutdown closes database engine connections."""
        with (
            patch(
                "job_correlation_evaluation_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.get_pipeline_settings") as mock_get_pipeline,
            patch("job_correlation_evaluation_service.main.ScoringPipeline") as mock_scoring_pipeline,
            patch("job_correlation_evaluation_service.main.MLScoringService") as mock_ml_service_cls,
            patch(
                "job_correlation_evaluation_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.start_event_consumer"),
            patch("job_correlation_evaluation_service.main.kafka_client") as mock_kafka,
            patch(
                "job_correlation_evaluation_service.main.close_all_engines",
                new_callable=AsyncMock,
            ) as mock_close,
            patch("job_correlation_evaluation_service.main.obs"),
            patch("job_correlation_evaluation_service.main.get_manifest"),
        ):
            mock_pipeline = MagicMock()
            mock_get_pipeline.return_value = mock_pipeline
            mock_scoring_pipeline.create.return_value = MagicMock()
            mock_ml_service = MagicMock()
            mock_ml_service.close = AsyncMock()
            mock_ml_service_cls.return_value = mock_ml_service
            mock_kafka.ensure_producer_ready = AsyncMock()
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()
            mock_kafka.supervise_consumer_failures = ConsumerSupervision()

            from job_correlation_evaluation_service.main import lifespan

            app = MagicMock(spec=FastAPI)
            app.state = MagicMock()
            app.state.ml_scoring_service = None

            async with lifespan(app):
                ...

            mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_ml_scoring_service_when_initialized(self) -> None:
        """Test that shutdown closes ML scoring service when initialized."""
        with (
            patch(
                "job_correlation_evaluation_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.get_pipeline_settings") as mock_get_pipeline,
            patch("job_correlation_evaluation_service.main.ScoringPipeline") as mock_scoring_pipeline,
            patch("job_correlation_evaluation_service.main.MLScoringService") as mock_ml_service_cls,
            patch(
                "job_correlation_evaluation_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.start_event_consumer"),
            patch("job_correlation_evaluation_service.main.kafka_client") as mock_kafka,
            patch(
                "job_correlation_evaluation_service.main.close_all_engines",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.obs"),
            patch("job_correlation_evaluation_service.main.get_manifest"),
        ):
            mock_pipeline = MagicMock()
            mock_get_pipeline.return_value = mock_pipeline
            mock_scoring_pipeline.create.return_value = MagicMock()
            mock_ml_service = MagicMock()
            mock_ml_service.close = AsyncMock()
            mock_ml_service_cls.return_value = mock_ml_service
            mock_kafka.ensure_producer_ready = AsyncMock()
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()
            mock_kafka.supervise_consumer_failures = ConsumerSupervision()

            from job_correlation_evaluation_service.main import lifespan

            app = MagicMock(spec=FastAPI)
            app.state = MagicMock()

            async with lifespan(app):
                ...

            mock_ml_service.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_startup_raises_on_ml_pipeline_init_failure(self) -> None:
        """Test that startup raises RuntimeError when ML pipeline init fails."""
        with (
            patch(
                "job_correlation_evaluation_service.main.initialize_database",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.get_pipeline_settings") as mock_get_pipeline,
            patch(
                "job_correlation_evaluation_service.main.create_async_qdrant_client",
                side_effect=OSError("connection refused"),
            ),
            patch("job_correlation_evaluation_service.main.obs"),
            patch("job_correlation_evaluation_service.main.kafka_client") as mock_kafka,
            patch(
                "job_correlation_evaluation_service.main.close_all_engines",
                new_callable=AsyncMock,
            ),
            patch("job_correlation_evaluation_service.main.get_manifest"),
        ):
            mock_pipeline = MagicMock()
            mock_get_pipeline.return_value = mock_pipeline
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()

            from job_correlation_evaluation_service.main import lifespan

            app = MagicMock(spec=FastAPI)
            app.state = MagicMock()

            with pytest.raises(RuntimeError, match="ML scoring pipeline initialization failed"):
                async with lifespan(app):
                    ...


@pytest.mark.asyncio
async def test_fatal_consumer_failure_stops_consumers_before_cleanup() -> None:
    """A fatal owner failure interrupts runtime and closes every owned resource."""
    failure = RuntimeError("consumer owner failed")
    supervision = ConsumerSupervision(failure)
    order: list[str] = []

    def tracked(name: str) -> AsyncMock:
        async def record() -> None:
            order.append(name)

        return AsyncMock(side_effect=record)

    qdrant = MagicMock()
    qdrant.close = tracked("qdrant")
    ml_service = MagicMock()
    ml_service.close = tracked("ml")

    with (
        patch(
            "job_correlation_evaluation_service.main.initialize_database",
            new_callable=AsyncMock,
        ),
        patch("job_correlation_evaluation_service.main.get_pipeline_settings"),
        patch("job_correlation_evaluation_service.main.ScoringPipeline.create"),
        patch(
            "job_correlation_evaluation_service.main.MLScoringService",
            return_value=ml_service,
        ),
        patch(
            "job_correlation_evaluation_service.main.create_async_qdrant_client",
            return_value=qdrant,
        ),
        patch(
            "job_correlation_evaluation_service.main.ensure_kafka_ready",
            new_callable=AsyncMock,
        ),
        patch("job_correlation_evaluation_service.main.set_ml_scoring_service") as set_matcher_service,
        patch("job_correlation_evaluation_service.main.set_backfill_ml_scoring_service") as set_backfill_service,
        patch("job_correlation_evaluation_service.main.start_event_consumer"),
        patch("job_correlation_evaluation_service.main.kafka_client") as kafka,
        patch(
            "job_correlation_evaluation_service.main.close_all_engines",
            tracked("database"),
        ),
        patch("job_correlation_evaluation_service.main.close_cache", tracked("cache")),
        patch("job_correlation_evaluation_service.main.obs"),
        patch("job_correlation_evaluation_service.main.get_manifest") as manifest,
    ):
        manifest.return_value.get_collection_name.return_value = "jobs"
        kafka.ensure_producer_ready = AsyncMock()
        kafka.stop_consumers = tracked("consumers")
        kafka.close = tracked("kafka")
        kafka.supervise_consumer_failures = supervision
        from job_correlation_evaluation_service.main import lifespan

        app = MagicMock(spec=FastAPI)
        app.state = MagicMock()
        with pytest.raises(ExceptionGroup) as raised:
            await supervision.interrupt(lifespan(app))

    assert raised.value.exceptions == (failure,)

    assert order[0] == "consumers"
    assert set(order) == {"consumers", "kafka", "ml", "qdrant", "cache", "database"}
    assert set_matcher_service.call_args_list == [
        ((ml_service,), {}),
        ((None,), {}),
    ]
    assert set_backfill_service.call_args_list == [
        ((ml_service,), {}),
        ((None,), {}),
    ]


@pytest.mark.asyncio
async def test_stale_manifest_version_fails_before_consumers_start() -> None:
    """An incompatible embedding/model contract fails closed and releases Qdrant."""
    qdrant = MagicMock()
    qdrant.close = AsyncMock()

    with (
        patch(
            "job_correlation_evaluation_service.main.initialize_database",
            new_callable=AsyncMock,
        ),
        patch("job_correlation_evaluation_service.main.get_pipeline_settings"),
        patch(
            "job_correlation_evaluation_service.main.ScoringPipeline.create",
            side_effect=ValueError("manifest/model version mismatch"),
        ),
        patch(
            "job_correlation_evaluation_service.main.create_async_qdrant_client",
            return_value=qdrant,
        ),
        patch(
            "job_correlation_evaluation_service.main.ensure_kafka_ready",
            new_callable=AsyncMock,
        ) as kafka_ready,
        patch("job_correlation_evaluation_service.main.start_event_consumer") as start_consumers,
        patch("job_correlation_evaluation_service.main.kafka_client") as kafka,
        patch(
            "job_correlation_evaluation_service.main.close_all_engines",
            new_callable=AsyncMock,
        ),
        patch(
            "job_correlation_evaluation_service.main.close_cache",
            new_callable=AsyncMock,
        ),
        patch("job_correlation_evaluation_service.main.obs"),
        patch("job_correlation_evaluation_service.main.get_manifest") as manifest,
    ):
        manifest.return_value.get_collection_name.return_value = "jobs-v-old"
        kafka.close = AsyncMock()
        from job_correlation_evaluation_service.main import lifespan

        app = MagicMock(spec=FastAPI)
        app.state = MagicMock()

        with pytest.raises(RuntimeError, match="ML scoring pipeline initialization failed"):
            async with lifespan(app):
                ...

    kafka_ready.assert_not_awaited()
    start_consumers.assert_not_called()
    qdrant.close.assert_awaited_once()
