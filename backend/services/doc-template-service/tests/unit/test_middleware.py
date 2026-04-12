"""Tests for main application lifespan."""

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


class TestLifespan:
    """Tests for lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_starts_and_stops_resources_in_order(self) -> None:
        """The service enters supervision after startup and closes resources in dependency order."""
        from doc_template_service.main import lifespan

        events: list[str] = []
        with (
            patch(
                "doc_template_service.main.initialize_database",
                new=AsyncMock(side_effect=lambda _settings: events.append("database")),
            ),
            patch("doc_template_service.main.create_cache") as create_cache,
            patch(
                "doc_template_service.main.seed_default_templates",
                new=AsyncMock(side_effect=lambda: events.append("seed")),
            ),
            patch(
                "doc_template_service.main.ensure_kafka_ready",
                new=AsyncMock(side_effect=lambda **_kwargs: events.append("kafka-ready")),
            ),
            patch(
                "doc_template_service.main.get_async_sessionmaker",
                return_value=object(),
            ),
            patch(
                "doc_template_service.main.start_event_consumer",
                side_effect=lambda: events.append("consumer-start"),
            ),
            patch("doc_template_service.main.kafka_client") as kafka_client,
            patch(
                "doc_template_service.main.CacheFactory.close_all",
                new=AsyncMock(side_effect=lambda: events.append("redis-close")),
            ),
            patch(
                "doc_template_service.main.close_all_engines",
                new=AsyncMock(side_effect=lambda: events.append("database-close")),
            ),
            patch("doc_template_service.main.obs") as obs,
        ):
            cache = MagicMock()
            lock = MagicMock()
            lock.__aenter__ = AsyncMock(side_effect=lambda: events.append("seed-lock-enter"))
            lock.__aexit__ = AsyncMock(side_effect=lambda *_args: events.append("seed-lock-exit"))
            cache.distributed_lock.return_value = lock
            create_cache.return_value = cache
            kafka_client.set_db_session_factory.side_effect = lambda _factory: events.append("session-factory")
            kafka_client.supervise_consumer_failures.side_effect = lambda: _consumer_supervision(events)
            kafka_client.stop_consumers = AsyncMock(side_effect=lambda: events.append("consumer-stop"))
            kafka_client.close = AsyncMock(side_effect=lambda: events.append("kafka-close"))
            obs.shutdown.side_effect = lambda: events.append("observability")

            async with lifespan(MagicMock()):
                events.append("serving")

        assert events == [
            "database",
            "seed-lock-enter",
            "seed",
            "seed-lock-exit",
            "kafka-ready",
            "session-factory",
            "consumer-start",
            "supervision-enter",
            "serving",
            "supervision-exit",
            "consumer-stop",
            "kafka-close",
            "redis-close",
            "database-close",
            "observability",
        ]

    @pytest.mark.asyncio
    async def test_fatal_consumer_interrupts_lifespan_and_preserves_cleanup_order(
        self,
    ) -> None:
        """A fatal owner failure escapes lifespan after all process-owned resources close."""
        from doc_template_service.main import lifespan

        events: list[str] = []
        trigger = asyncio.Event()
        failure = RuntimeError("consumer owner failed")

        async def drive_lifespan_until_failure() -> None:
            async with lifespan(MagicMock()):
                events.append("serving")
                trigger.set()
                await asyncio.Event().wait()

        with (
            patch("doc_template_service.main.initialize_database", new_callable=AsyncMock),
            patch("doc_template_service.main.create_cache") as create_cache,
            patch(
                "doc_template_service.main.seed_default_templates",
                new_callable=AsyncMock,
            ),
            patch("doc_template_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch(
                "doc_template_service.main.get_async_sessionmaker",
                return_value=object(),
            ),
            patch("doc_template_service.main.start_event_consumer"),
            patch("doc_template_service.main.kafka_client") as kafka_client,
            patch(
                "doc_template_service.main.CacheFactory.close_all",
                new=AsyncMock(side_effect=lambda: events.append("redis-close")),
            ),
            patch(
                "doc_template_service.main.close_all_engines",
                new=AsyncMock(side_effect=lambda: events.append("database-close")),
            ),
            patch("doc_template_service.main.obs") as obs,
        ):
            cache = MagicMock()
            lock = MagicMock()
            lock.__aenter__ = AsyncMock()
            lock.__aexit__ = AsyncMock()
            cache.distributed_lock.return_value = lock
            create_cache.return_value = cache
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
            "database-close",
            "observability",
        ]

    @pytest.mark.asyncio
    async def test_lifespan_handles_db_init_failure(self) -> None:
        """Test lifespan raises exception on database initialization failure."""
        mock_init_db = AsyncMock(side_effect=RuntimeError("DB init failed"))
        with patch("doc_template_service.main.initialize_database", mock_init_db):
            from doc_template_service.main import lifespan

            mock_app = MagicMock()

            with pytest.raises(RuntimeError, match="DB init failed"):
                async with lifespan(mock_app):
                    mock_init_db.assert_awaited()

    @pytest.mark.asyncio
    async def test_lifespan_handles_distributed_lock_error(self) -> None:
        """A competing seeder lock does not prevent the service from becoming ready."""
        from doc_template_service.main import lifespan
        from nohiki_redis_utils import DistributedLockError

        events: list[str] = []
        with (
            patch("doc_template_service.main.initialize_database", new_callable=AsyncMock),
            patch("doc_template_service.main.create_cache") as create_cache,
            patch("doc_template_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch(
                "doc_template_service.main.get_async_sessionmaker",
                return_value=object(),
            ),
            patch("doc_template_service.main.start_event_consumer"),
            patch("doc_template_service.main.kafka_client") as kafka_client,
            patch(
                "doc_template_service.main.CacheFactory.close_all",
                new_callable=AsyncMock,
            ),
            patch("doc_template_service.main.close_all_engines", new_callable=AsyncMock),
            patch("doc_template_service.main.obs"),
        ):
            cache = MagicMock()
            cache.distributed_lock.side_effect = DistributedLockError("Lock failed")
            create_cache.return_value = cache
            kafka_client.supervise_consumer_failures.side_effect = lambda: _consumer_supervision(events)
            kafka_client.stop_consumers = AsyncMock()
            kafka_client.close = AsyncMock()

            async with lifespan(MagicMock()):
                events.append("serving")

        assert events == ["supervision-enter", "serving", "supervision-exit"]

    @pytest.mark.asyncio
    async def test_lifespan_handles_seeding_failure(self) -> None:
        """A failed seed attempt does not prevent the service from becoming ready."""
        from doc_template_service.main import lifespan

        events: list[str] = []
        with (
            patch("doc_template_service.main.initialize_database", new_callable=AsyncMock),
            patch("doc_template_service.main.create_cache") as create_cache,
            patch(
                "doc_template_service.main.seed_default_templates",
                new=AsyncMock(side_effect=RuntimeError("Seeding failed")),
            ),
            patch("doc_template_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch(
                "doc_template_service.main.get_async_sessionmaker",
                return_value=object(),
            ),
            patch("doc_template_service.main.start_event_consumer"),
            patch("doc_template_service.main.kafka_client") as kafka_client,
            patch(
                "doc_template_service.main.CacheFactory.close_all",
                new_callable=AsyncMock,
            ),
            patch("doc_template_service.main.close_all_engines", new_callable=AsyncMock),
            patch("doc_template_service.main.obs"),
        ):
            cache = MagicMock()
            lock = MagicMock()
            lock.__aenter__ = AsyncMock()
            lock.__aexit__ = AsyncMock()
            cache.distributed_lock.return_value = lock
            create_cache.return_value = cache
            kafka_client.supervise_consumer_failures.side_effect = lambda: _consumer_supervision(events)
            kafka_client.stop_consumers = AsyncMock()
            kafka_client.close = AsyncMock()

            async with lifespan(MagicMock()):
                events.append("serving")

        assert events == ["supervision-enter", "serving", "supervision-exit"]
