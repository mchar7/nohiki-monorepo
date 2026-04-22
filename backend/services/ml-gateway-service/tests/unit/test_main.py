"""Unit tests for ml_gateway_service.main module."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI


class _ConsumerSupervisor:
    def __init__(self, events: list[str], failure: RuntimeError | None = None) -> None:
        self.events = events
        self.failure = failure
        self.release_failure = asyncio.Event()

    @asynccontextmanager
    async def context(self) -> AsyncIterator[None]:
        self.events.append("supervision_entered")
        try:
            failure = self.failure
            if failure is None:
                yield
                return

            async def fail_when_released() -> None:
                await self.release_failure.wait()
                raise failure

            async with asyncio.TaskGroup() as tasks:
                failure_task = tasks.create_task(fail_when_released())
                try:
                    yield
                finally:
                    failure_task.cancel()
        finally:
            self.events.append("supervision_exited")


def _exception_group_contains(group: BaseExceptionGroup, expected: BaseException) -> bool:
    return any(
        error is expected or (isinstance(error, BaseExceptionGroup) and _exception_group_contains(error, expected))
        for error in group.exceptions
    )


class TestLifespan:
    """Tests for lifespan context manager."""

    @pytest.mark.asyncio
    async def test_normal_lifespan_orders_startup_supervision_and_cleanup(self) -> None:
        """Consumers start before supervision and shutdown releases resources in order."""
        events: list[str] = []
        supervisor = _ConsumerSupervisor(events)

        with (
            patch(
                "ml_gateway_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
                side_effect=lambda **_: events.append("kafka_ready"),
            ),
            patch(
                "ml_gateway_service.main.start_event_consumer",
                side_effect=lambda: events.append("consumer_started"),
            ),
            patch("ml_gateway_service.main.kafka_client") as mock_kafka,
            patch("ml_gateway_service.main.CacheFactory") as mock_cache_factory,
            patch("ml_gateway_service.main.obs") as mock_obs,
        ):
            mock_kafka.supervise_consumer_failures.side_effect = supervisor.context
            mock_kafka.stop_consumers = AsyncMock(side_effect=lambda: events.append("consumers_stopped"))
            mock_kafka.close = AsyncMock(side_effect=lambda: events.append("kafka_closed"))
            mock_cache_factory.close_all = AsyncMock(side_effect=lambda: events.append("redis_closed"))
            mock_obs.shutdown.side_effect = lambda: events.append("observability_shutdown")

            from ml_gateway_service.main import lifespan

            async with lifespan(MagicMock(spec=FastAPI)):
                events.append("body")

        assert events == [
            "kafka_ready",
            "consumer_started",
            "supervision_entered",
            "body",
            "supervision_exited",
            "consumers_stopped",
            "kafka_closed",
            "redis_closed",
            "observability_shutdown",
        ]

    @pytest.mark.asyncio
    async def test_fatal_consumer_failure_interrupts_lifespan_and_cleans_up(
        self,
    ) -> None:
        """A body-time consumer failure escapes lifespan after ordered cleanup."""
        events: list[str] = []
        failure = RuntimeError("consumer owner failed")
        supervisor = _ConsumerSupervisor(events, failure)

        with (
            patch("ml_gateway_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch("ml_gateway_service.main.start_event_consumer"),
            patch("ml_gateway_service.main.kafka_client") as mock_kafka,
            patch("ml_gateway_service.main.CacheFactory") as mock_cache_factory,
            patch("ml_gateway_service.main.obs") as mock_obs,
        ):
            mock_kafka.supervise_consumer_failures.side_effect = supervisor.context
            mock_kafka.stop_consumers = AsyncMock(side_effect=lambda: events.append("consumers_stopped"))
            mock_kafka.close = AsyncMock(side_effect=lambda: events.append("kafka_closed"))
            mock_cache_factory.close_all = AsyncMock(side_effect=lambda: events.append("redis_closed"))
            mock_obs.shutdown.side_effect = lambda: events.append("observability_shutdown")

            from ml_gateway_service.main import lifespan

            async def run_lifespan_until_consumer_failure() -> None:
                async with lifespan(MagicMock(spec=FastAPI)):
                    supervisor.release_failure.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        events.append("body_cancelled")

            with pytest.raises(BaseExceptionGroup) as raised:
                await run_lifespan_until_consumer_failure()

        assert _exception_group_contains(raised.value, failure)
        assert events == [
            "supervision_entered",
            "body_cancelled",
            "supervision_exited",
            "consumers_stopped",
            "kafka_closed",
            "redis_closed",
            "observability_shutdown",
        ]


class TestAppConfiguration:
    """Tests for app module-level configuration."""

    def test_app_is_fastapi_instance(self) -> None:
        """Module-level app is a FastAPI instance."""
        from ml_gateway_service.main import app

        assert isinstance(app, FastAPI)

    def test_app_has_title(self) -> None:
        """App has a title configured."""
        from ml_gateway_service.main import app

        assert app.title is not None
        assert len(app.title) > 0

    def test_app_has_version(self) -> None:
        """App has a version configured."""
        from ml_gateway_service.main import app

        assert app.version is not None
