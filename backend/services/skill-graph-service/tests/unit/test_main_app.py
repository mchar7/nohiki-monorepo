"""Unit tests for main FastAPI application."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from skill_graph_service.main import app


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


class TestMainApp:
    """Tests for FastAPI app creation and lifespan."""

    def test_app_created(self) -> None:
        """Test that the module-level app has correct configuration."""
        assert isinstance(app, FastAPI)
        assert app.title == "Skill Graph Service"

    @pytest.mark.asyncio
    async def test_normal_lifespan_orders_readiness_supervision_and_cleanup(
        self,
    ) -> None:
        """Readiness lives inside supervision and every resource closes in LIFO order."""
        events: list[str] = []
        supervisor = _ConsumerSupervisor(events)

        with (
            patch(
                "skill_graph_service.main.initialize_database",
                new_callable=AsyncMock,
                side_effect=lambda _: events.append("database_initialized"),
            ),
            patch(
                "skill_graph_service.main.ensure_kafka_ready",
                new_callable=AsyncMock,
                side_effect=lambda **_: events.append("kafka_ready"),
            ),
            patch(
                "skill_graph_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch(
                "skill_graph_service.main.start_event_consumer",
                side_effect=lambda: events.append("consumer_started"),
            ),
            patch("skill_graph_service.main.kafka_client") as mock_kafka,
            patch(
                "skill_graph_service.main.close_all_engines",
                new_callable=AsyncMock,
                side_effect=lambda: events.append("database_closed"),
            ),
            patch("skill_graph_service.main._readiness_gate") as mock_gate,
            patch("skill_graph_service.main.obs") as mock_obs,
        ):
            mock_kafka.supervise_consumer_failures.side_effect = supervisor.context
            mock_kafka.stop_consumers = AsyncMock(side_effect=lambda: events.append("consumers_stopped"))
            mock_kafka.close = AsyncMock(side_effect=lambda: events.append("kafka_closed"))
            mock_gate.start.side_effect = lambda: events.append("readiness_started")
            mock_gate.stop = AsyncMock(side_effect=lambda: events.append("readiness_stopped"))
            mock_obs.shutdown.side_effect = lambda: events.append("observability_shutdown")

            async with app.router.lifespan_context(app):
                events.append("body")

        assert events == [
            "database_initialized",
            "kafka_ready",
            "consumer_started",
            "supervision_entered",
            "readiness_started",
            "body",
            "supervision_exited",
            "readiness_stopped",
            "consumers_stopped",
            "kafka_closed",
            "database_closed",
            "observability_shutdown",
        ]

    @pytest.mark.asyncio
    async def test_fatal_consumer_failure_interrupts_lifespan_and_cleans_up(
        self,
    ) -> None:
        """A body-time owner failure stops readiness and releases all resources."""
        events: list[str] = []
        failure = RuntimeError("consumer owner failed")
        supervisor = _ConsumerSupervisor(events, failure)

        with (
            patch("skill_graph_service.main.initialize_database", new_callable=AsyncMock),
            patch("skill_graph_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch(
                "skill_graph_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("skill_graph_service.main.start_event_consumer"),
            patch("skill_graph_service.main.kafka_client") as mock_kafka,
            patch(
                "skill_graph_service.main.close_all_engines",
                new_callable=AsyncMock,
                side_effect=lambda: events.append("database_closed"),
            ),
            patch("skill_graph_service.main._readiness_gate") as mock_gate,
            patch("skill_graph_service.main.obs") as mock_obs,
        ):
            mock_kafka.supervise_consumer_failures.side_effect = supervisor.context
            mock_kafka.stop_consumers = AsyncMock(side_effect=lambda: events.append("consumers_stopped"))
            mock_kafka.close = AsyncMock(side_effect=lambda: events.append("kafka_closed"))
            mock_gate.stop = AsyncMock(side_effect=lambda: events.append("readiness_stopped"))
            mock_obs.shutdown.side_effect = lambda: events.append("observability_shutdown")

            async def run_lifespan_until_consumer_failure() -> None:
                async with app.router.lifespan_context(app):
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
            "readiness_stopped",
            "consumers_stopped",
            "kafka_closed",
            "database_closed",
            "observability_shutdown",
        ]
