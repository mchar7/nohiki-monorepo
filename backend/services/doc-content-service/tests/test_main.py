"""Tests for main.py application setup and lifespan."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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


class TestAppSetup:
    """Tests for FastAPI application setup."""

    def test_app_exists(self) -> None:
        from doc_content_service.main import app

        assert app is not None
        assert app.title == "Document Content Service"

    def test_settings_initialized(self) -> None:
        from doc_content_service.main import settings

        assert settings is not None
        assert settings.service_name == "doc-content-service"

    def test_observability_initialized(self) -> None:
        from doc_content_service.main import obs

        assert obs is not None

    def test_logger_exists(self) -> None:
        from doc_content_service.main import logger

        assert logger is not None


class TestLifespan:
    """Tests for application lifespan events (stateless service)."""

    @pytest.mark.asyncio
    async def test_lifespan_startup_and_shutdown(self) -> None:
        """Dependencies start before readiness and close in ownership order."""
        from doc_content_service.main import lifespan

        events: list[str] = []

        with (
            patch(
                "doc_content_service.main.ensure_kafka_ready",
                new=AsyncMock(side_effect=lambda **_kwargs: events.append("kafka-ready")),
            ),
            patch(
                "doc_content_service.main.ensure_llm_ready",
                new=AsyncMock(side_effect=lambda *_args, **_kwargs: events.append("llm-ready")),
            ),
            patch(
                "doc_content_service.main.start_event_consumer",
                side_effect=lambda: events.append("consumer-start"),
            ),
            patch("doc_content_service.main.kafka_client") as kafka_client,
            patch(
                "doc_content_service.main.close_llm_client",
                new=AsyncMock(side_effect=lambda: events.append("llm-close")),
            ),
            patch("doc_content_service.main.obs") as obs,
        ):
            kafka_client.supervise_consumer_failures.side_effect = lambda: _consumer_supervision(events)
            kafka_client.stop_consumers = AsyncMock(side_effect=lambda: events.append("consumer-stop"))
            kafka_client.close = AsyncMock(side_effect=lambda: events.append("kafka-close"))
            obs.shutdown.side_effect = lambda: events.append("observability")

            async with lifespan(MagicMock()):
                events.append("serving")

        assert events == [
            "kafka-ready",
            "llm-ready",
            "consumer-start",
            "supervision-enter",
            "serving",
            "supervision-exit",
            "consumer-stop",
            "llm-close",
            "kafka-close",
            "observability",
        ]

    @pytest.mark.asyncio
    async def test_fatal_consumer_interrupts_lifespan_and_preserves_cleanup_order(
        self,
    ) -> None:
        """A fatal owner failure escapes lifespan after all process-owned resources close."""
        from doc_content_service.main import lifespan

        events: list[str] = []
        trigger = asyncio.Event()
        failure = RuntimeError("consumer owner failed")

        async def drive_lifespan_until_failure() -> None:
            async with lifespan(MagicMock()):
                events.append("serving")
                trigger.set()
                await asyncio.Event().wait()

        with (
            patch("doc_content_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch("doc_content_service.main.ensure_llm_ready", new_callable=AsyncMock),
            patch("doc_content_service.main.start_event_consumer"),
            patch("doc_content_service.main.kafka_client") as kafka_client,
            patch(
                "doc_content_service.main.close_llm_client",
                new=AsyncMock(side_effect=lambda: events.append("llm-close")),
            ),
            patch("doc_content_service.main.obs") as obs,
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
            "llm-close",
            "kafka-close",
            "observability",
        ]

    @pytest.mark.asyncio
    async def test_lifespan_closes_llm_after_partial_startup_failure(self) -> None:
        """Startup failure still closes the process-owned model transport."""
        from doc_content_service.main import lifespan

        with (
            patch("doc_content_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch(
                "doc_content_service.main.ensure_llm_ready",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM unavailable"),
            ),
            patch("doc_content_service.main.start_event_consumer") as start_consumer,
            patch("doc_content_service.main.close_llm_client", new_callable=AsyncMock) as close_llm,
            patch("doc_content_service.main.kafka_client") as kafka_client,
            patch("doc_content_service.main.obs") as obs,
        ):
            kafka_client.stop_consumers = AsyncMock()
            kafka_client.close = AsyncMock()
            with pytest.raises(RuntimeError, match="LLM unavailable"):
                async with lifespan(MagicMock()):
                    pytest.fail("lifespan yielded after failed startup")

        start_consumer.assert_not_called()
        close_llm.assert_awaited_once_with()
        kafka_client.close.assert_awaited_once_with()
        obs.shutdown.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_consumer_start_failure_stops_before_dependency_cleanup(self) -> None:
        """A partially started consumer is stopped before LLM and Kafka teardown."""
        from doc_content_service.main import lifespan

        events: list[str] = []
        with (
            patch("doc_content_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch("doc_content_service.main.ensure_llm_ready", new_callable=AsyncMock),
            patch(
                "doc_content_service.main.start_event_consumer",
                side_effect=RuntimeError("consumer start failed"),
            ),
            patch(
                "doc_content_service.main.close_llm_client",
                new=AsyncMock(side_effect=lambda: events.append("llm")),
            ),
            patch("doc_content_service.main.kafka_client") as kafka_client,
            patch("doc_content_service.main.obs") as obs,
        ):
            kafka_client.stop_consumers = AsyncMock(side_effect=lambda: events.append("stop"))
            kafka_client.close = AsyncMock(side_effect=lambda: events.append("kafka"))
            obs.shutdown.side_effect = lambda: events.append("observability")
            with pytest.raises(RuntimeError, match="consumer start failed"):
                async with lifespan(MagicMock()):
                    pytest.fail("lifespan yielded after failed consumer start")

        assert events == ["stop", "llm", "kafka", "observability"]

    @pytest.mark.asyncio
    async def test_close_helper_awaits_public_llm_close(self) -> None:
        """The process owner delegates cleanup to LLMClient.close()."""
        from doc_content_service.events.handlers import close_llm_client

        with patch("doc_content_service.events.handlers._llm_client") as llm_client:
            llm_client.close = AsyncMock()
            await close_llm_client()

        llm_client.close.assert_awaited_once_with()
