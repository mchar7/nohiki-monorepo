"""Tests for doc_process_service.main module."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from doc_process_service.main import app
from fastapi import FastAPI
from fastapi.testclient import TestClient


@asynccontextmanager
async def _consumer_supervision(
    events: list[str],
    *,
    failure: Exception | None = None,
    trigger: asyncio.Event | None = None,
) -> AsyncIterator[None]:
    """Model the client's TaskGroup supervision, including owner-task interruption."""
    if (failure is None) != (trigger is None):
        message = "failure and trigger must be provided together"
        raise ValueError(message)

    async def fail_after_trigger() -> None:
        assert failure is not None
        assert trigger is not None
        await trigger.wait()
        events.append("consumer-fatal")
        raise failure

    async with asyncio.TaskGroup() as tasks:
        monitor = tasks.create_task(fail_after_trigger()) if failure is not None else None
        events.append("supervision-enter")
        try:
            yield
        finally:
            events.append("supervision-exit")
            if monitor is not None and not monitor.done():
                monitor.cancel()


class TestAppCreation:
    """Tests for FastAPI app creation."""

    def test_app_exists(self) -> None:
        """Test that the main app instance exists."""
        assert app is not None
        assert isinstance(app, FastAPI)

    def test_app_has_title(self) -> None:
        """Test app has correct title from settings."""
        assert app.title == "Document Processing Service"

    def test_app_has_version(self) -> None:
        """Test app has version set."""
        assert app.version == "0.1.0"


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_healthz_endpoint_exists(self) -> None:
        """Test healthz endpoint is registered."""
        client = TestClient(app)

        response = client.get("/healthz")

        assert response.status_code == 200

    def test_readyz_endpoint_exists(self) -> None:
        """Test readyz endpoint is registered."""
        client = TestClient(app)

        response = client.get("/readyz")

        assert response.status_code in (200, 503)


class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root_endpoint_returns_service_info(self) -> None:
        """Test root endpoint returns service information."""
        client = TestClient(app)

        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "version" in data


class TestMetricsEndpoint:
    """Tests for metrics endpoint."""

    def test_metrics_endpoint_exists(self) -> None:
        """Test metrics endpoint is registered."""
        client = TestClient(app)

        response = client.get("/metrics")

        assert response.status_code == 200


class TestLifespan:
    """Tests for application lifespan."""

    @pytest.mark.asyncio
    async def test_lifespan_starts_and_stops_resources_in_order(self) -> None:
        """The service enters supervision after startup and closes resources in dependency order."""
        from doc_process_service.main import lifespan

        events: list[str] = []
        with (
            patch(
                "doc_process_service.main.ensure_kafka_ready",
                new=AsyncMock(side_effect=lambda **_kwargs: events.append("kafka-ready")),
            ),
            patch(
                "doc_process_service.main.DocProcessMetrics.initialize",
                side_effect=lambda: events.append("metrics"),
            ),
            patch(
                "doc_process_service.main.start_event_consumer",
                side_effect=lambda: events.append("consumer-start"),
            ),
            patch("doc_process_service.main.kafka_client") as kafka_client,
            patch(
                "doc_process_service.main.CacheFactory.close_all",
                new=AsyncMock(side_effect=lambda: events.append("redis-close")),
            ),
            patch("doc_process_service.main.obs") as obs,
        ):
            kafka_client.supervise_consumer_failures.side_effect = lambda: _consumer_supervision(events)
            kafka_client.stop_consumers = AsyncMock(side_effect=lambda: events.append("consumer-stop"))
            kafka_client.close = AsyncMock(side_effect=lambda: events.append("kafka-close"))
            obs.shutdown.side_effect = lambda: events.append("observability")

            async with lifespan(FastAPI()):
                events.append("serving")

        assert events == [
            "kafka-ready",
            "metrics",
            "consumer-start",
            "supervision-enter",
            "serving",
            "supervision-exit",
            "consumer-stop",
            "kafka-close",
            "redis-close",
            "observability",
        ]

    @pytest.mark.asyncio
    async def test_fatal_consumer_interrupts_lifespan_and_preserves_cleanup_order(
        self,
    ) -> None:
        """A fatal owner failure escapes lifespan after all process-owned resources close."""
        from doc_process_service.main import lifespan

        events: list[str] = []
        trigger = asyncio.Event()
        failure = RuntimeError("consumer owner failed")

        async def drive_lifespan_until_failure() -> None:
            async with lifespan(FastAPI()):
                events.append("serving")
                trigger.set()
                await asyncio.Event().wait()

        with (
            patch("doc_process_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch("doc_process_service.main.DocProcessMetrics.initialize"),
            patch("doc_process_service.main.start_event_consumer"),
            patch("doc_process_service.main.kafka_client") as kafka_client,
            patch(
                "doc_process_service.main.CacheFactory.close_all",
                new=AsyncMock(side_effect=lambda: events.append("redis-close")),
            ),
            patch("doc_process_service.main.obs") as obs,
        ):
            kafka_client.supervise_consumer_failures.side_effect = lambda: _consumer_supervision(
                events,
                failure=failure,
                trigger=trigger,
            )
            kafka_client.stop_consumers = AsyncMock(side_effect=lambda: events.append("consumer-stop"))
            kafka_client.close = AsyncMock(side_effect=lambda: events.append("kafka-close"))
            obs.shutdown.side_effect = lambda: events.append("observability")

            with pytest.raises(ExceptionGroup) as raised:
                await drive_lifespan_until_failure()

        assert raised.value.exceptions == (failure,)
        assert events == [
            "supervision-enter",
            "serving",
            "consumer-fatal",
            "supervision-exit",
            "consumer-stop",
            "kafka-close",
            "redis-close",
            "observability",
        ]
