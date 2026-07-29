"""Unit tests for the main.py module."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from fastapi import FastAPI

from fastapi.testclient import TestClient
from nohiki_redis_utils import RateLimitFailurePolicy
from notification_service.main import app


class _FatalConsumerSupervisor:
    """Interrupt the lifespan body when a simulated consumer owner fails."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self._failure = asyncio.Event()

    @contextlib.asynccontextmanager
    async def context(self) -> AsyncIterator[None]:
        """Enter supervision and convert the injected cancellation to its fatal cause."""
        body_task = asyncio.current_task()
        assert body_task is not None
        self.entered.set()

        async def interrupt_body() -> None:
            await self._failure.wait()
            body_task.cancel()

        monitor = asyncio.create_task(interrupt_body())
        try:
            yield
        except asyncio.CancelledError as error:
            if not self._failure.is_set():
                raise
            message = "consumer owner failed"
            raise RuntimeError(message) from error
        finally:
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor

    def fail(self) -> None:
        """Inject a fatal owner failure into the active lifespan body."""
        self._failure.set()


@pytest.fixture
def test_app() -> FastAPI:
    """Create a test FastAPI app."""
    return app


@pytest.fixture
def test_client(test_app: FastAPI) -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(test_app)


def test_root_endpoint(test_client: TestClient) -> None:
    """Test the root endpoint."""
    response = test_client.get("/")
    assert response.status_code == 200

    data = response.json()
    assert "service" in data
    assert data["service"] == "notification-service"
    assert "version" in data
    assert "status" in data
    assert data["status"] == "running"


def test_health_endpoint(test_client: TestClient) -> None:
    """Test the health endpoint."""
    response = test_client.get("/healthz")
    assert response.status_code == 200

    data = response.json()
    assert "status" in data


class TestLifespanShutdown:
    """Tests for lifespan shutdown cleanup."""

    @pytest.mark.asyncio
    async def test_shutdown_components_calls_cleanup_methods(self) -> None:
        """Test that _shutdown_components calls all cleanup methods."""
        call_order: list[str] = []

        def track_stop_consumers() -> None:
            call_order.append("stop_consumers")

        def track_kafka_close() -> None:
            call_order.append("kafka_close")

        def track_cache_close() -> None:
            call_order.append("cache_close")

        def track_engine_close() -> None:
            call_order.append("engine_close")

        def track_obs_shutdown() -> None:
            call_order.append("obs_shutdown")

        mock_kafka = MagicMock()
        mock_kafka.stop_consumers = AsyncMock(side_effect=track_stop_consumers)
        mock_kafka.close = AsyncMock(side_effect=track_kafka_close)

        mock_cache_factory = MagicMock()
        mock_cache_factory.close_all = AsyncMock(side_effect=track_cache_close)

        mock_obs = MagicMock()
        mock_obs.shutdown = MagicMock(side_effect=track_obs_shutdown)

        with (
            patch("notification_service.main.kafka_client", mock_kafka),
            patch("notification_service.main.CacheFactory", mock_cache_factory),
            patch(
                "notification_service.main.close_all_engines",
                new_callable=AsyncMock,
                side_effect=track_engine_close,
            ),
            patch("notification_service.main.obs", mock_obs),
        ):
            from notification_service.main import _shutdown_components

            await _shutdown_components(worker_task=None, worker_instance=None)

        mock_kafka.stop_consumers.assert_awaited_once()
        mock_kafka.close.assert_awaited_once()
        mock_cache_factory.close_all.assert_awaited_once()
        mock_obs.shutdown.assert_called_once()

        assert call_order == [
            "stop_consumers",
            "kafka_close",
            "cache_close",
            "engine_close",
            "obs_shutdown",
        ]

    @pytest.mark.asyncio
    async def test_shutdown_cooperatively_drains_worker(self) -> None:
        """Shutdown signals the worker and awaits its clean exit, never cancelling."""
        # A worker that respects an Event-based stop and exits cleanly.
        stop_signal = asyncio.Event()

        async def cooperative_worker() -> None:
            await stop_signal.wait()

        task = asyncio.create_task(cooperative_worker())
        mock_worker = MagicMock()
        mock_worker.stop = MagicMock(side_effect=stop_signal.set)

        with (
            patch("notification_service.main.kafka_client") as mock_kafka,
            patch("notification_service.main.CacheFactory") as mock_cache,
            patch("notification_service.main.close_all_engines", new_callable=AsyncMock),
            patch("notification_service.main.obs") as mock_obs,
        ):
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()
            mock_cache.close_all = AsyncMock()
            mock_obs.shutdown = MagicMock()

            from notification_service.main import _shutdown_components

            await _shutdown_components(worker_task=task, worker_instance=mock_worker)

        mock_worker.stop.assert_called_once()
        assert task.done()
        assert not task.cancelled()

    @pytest.mark.asyncio
    async def test_shutdown_without_worker_is_noop_for_worker_step(self) -> None:
        """Lifespan paths without a worker (tests) skip the worker shutdown step."""
        with (
            patch("notification_service.main.kafka_client") as mock_kafka,
            patch("notification_service.main.CacheFactory") as mock_cache,
            patch("notification_service.main.close_all_engines", new_callable=AsyncMock),
            patch("notification_service.main.obs") as mock_obs,
        ):
            mock_kafka.stop_consumers = AsyncMock()
            mock_kafka.close = AsyncMock()
            mock_cache.close_all = AsyncMock()
            mock_obs.shutdown = MagicMock()

            from notification_service.main import _shutdown_components

            await _shutdown_components(worker_task=None, worker_instance=None)

        mock_kafka.stop_consumers.assert_awaited_once()


class TestSetupFunctions:
    """Tests for setup functions in main.py."""

    def test_setup_rate_limiter(self) -> None:
        """Test rate limiter initialization."""
        with (
            patch("notification_service.main.create_cache") as mock_create_cache,
            patch("notification_service.main.create_token_bucket_limiter") as mock_create_limiter,
            patch("notification_service.main.settings") as mock_settings,
        ):
            mock_settings.service_name = "test-service"
            mock_settings.redis.connection_string = "redis://localhost"
            mock_settings.rate_limit.requests_per_window = 100
            mock_settings.rate_limit.window_seconds = 60

            mock_cache = MagicMock()
            mock_create_cache.return_value = mock_cache

            from notification_service.main import _setup_rate_limiter

            _setup_rate_limiter()

            mock_create_cache.assert_called_once_with(
                "test-service",
                redis_url="redis://localhost",
            )
            mock_create_limiter.assert_called_once()

    def test_provider_limiter_keeps_failing_open(self) -> None:
        """The provider bucket protects a vendor quota, so availability wins."""
        with (
            patch("notification_service.main.create_cache"),
            patch("notification_service.main.create_token_bucket_limiter") as mock_create_limiter,
            patch("notification_service.main.settings") as mock_settings,
        ):
            mock_settings.rate_limit.requests_per_window = 100
            mock_settings.rate_limit.window_seconds = 60

            from notification_service.main import _setup_rate_limiter

            _setup_rate_limiter()

            assert "failure_policy" not in mock_create_limiter.call_args.kwargs

    def test_frequency_cap_fails_closed(self) -> None:
        """A Redis outage must not lift the per-user inbox bound."""
        with (
            patch("notification_service.main.create_cache"),
            patch("notification_service.main.create_token_bucket_limiter") as mock_create_limiter,
            patch("notification_service.main.settings") as mock_settings,
        ):
            mock_settings.frequency_cap.enabled = True
            mock_settings.frequency_cap.max_per_window = 5
            mock_settings.frequency_cap.window_seconds = 3600

            from notification_service.main import _setup_frequency_checker

            _setup_frequency_checker()

            assert mock_create_limiter.call_args.kwargs["failure_policy"] is RateLimitFailurePolicy.FAIL_CLOSED

    def test_register_providers_success(self) -> None:
        """Test successful provider registration."""
        with (
            patch("notification_service.main.register_provider") as mock_register,
            patch("notification_service.main.configure_email_provider") as mock_configure,
            patch("notification_service.main.settings") as mock_settings,
        ):
            mock_settings.email.from_address = "test@example.com"
            mock_settings.email.from_name = "Test Sender"
            mock_settings.email.unsubscribe_domain = "example.com"
            mock_settings.email.provider = "resend"

            from notification_service.main import _register_providers

            _register_providers()

            assert mock_register.call_count == 2
            mock_configure.assert_called_once()

    def test_register_providers_value_error(self) -> None:
        """Test provider registration handles ValueError without crashing."""
        with patch("notification_service.main.register_provider") as mock_register:
            mock_register.side_effect = ValueError("Invalid provider")

            from notification_service.main import _register_providers

            _register_providers()

    def test_register_providers_import_error(self) -> None:
        """Test provider registration handles ImportError without crashing."""
        with patch("notification_service.main.register_provider") as mock_register:
            mock_register.side_effect = ImportError("Module not found")

            from notification_service.main import _register_providers

            _register_providers()

    def test_register_providers_permission_error(self) -> None:
        """Test provider registration handles PermissionError without crashing."""
        with patch("notification_service.main.register_provider") as mock_register:
            mock_register.side_effect = PermissionError("Access denied")

            from notification_service.main import _register_providers

            _register_providers()

    def test_register_providers_runtime_error(self) -> None:
        """Test provider registration handles RuntimeError without crashing."""
        with patch("notification_service.main.register_provider") as mock_register:
            mock_register.side_effect = RuntimeError("Runtime issue")

            from notification_service.main import _register_providers

            _register_providers()

    def test_register_providers_os_error(self) -> None:
        """Test provider registration handles OSError without crashing."""
        with patch("notification_service.main.register_provider") as mock_register:
            mock_register.side_effect = OSError("OS error")

            from notification_service.main import _register_providers

            _register_providers()

    @pytest.mark.asyncio
    async def test_start_workers(self) -> None:
        """Worker is constructed with router + shared shutdown event."""
        with (
            patch("notification_service.main.OutboxWorker") as mock_worker_class,
            patch("notification_service.main._build_provider_router") as mock_build_router,
            patch("notification_service.main._app_state") as mock_state,
        ):
            mock_worker = MagicMock()
            mock_worker.start = AsyncMock()
            mock_worker_class.return_value = mock_worker
            mock_router = MagicMock()
            mock_build_router.return_value = mock_router
            mock_state.rate_limiter = MagicMock()

            from notification_service.main import _start_workers

            result_task, result_worker = _start_workers()
            # Cleanly cancel the spawned start task so it doesn't leak.
            result_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, BaseException):
                await result_task

            mock_worker_class.assert_called_once()
            kwargs = mock_worker_class.call_args.kwargs
            assert kwargs["provider_router"] is mock_router
            assert kwargs["rate_limiter"] is mock_state.rate_limiter
            assert isinstance(kwargs["shutdown_event"], asyncio.Event)
            assert kwargs["shutdown_event"] is mock_state.shutdown_event
            assert result_worker is mock_worker

    @pytest.mark.asyncio
    async def test_stop_outbox_worker_calls_stop_and_awaits_task(self) -> None:
        """``_stop_outbox_worker`` signals stop then waits, never cancelling."""
        stop_signal = asyncio.Event()

        async def cooperative_worker() -> None:
            await stop_signal.wait()

        task = asyncio.create_task(cooperative_worker())
        mock_worker = MagicMock()
        mock_worker.stop = MagicMock(side_effect=stop_signal.set)

        from notification_service.main import _stop_outbox_worker

        await _stop_outbox_worker(worker_task=task, worker_instance=mock_worker)

        mock_worker.stop.assert_called_once()
        assert task.done()
        assert not task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_outbox_worker_noop_when_missing(self) -> None:
        """No worker started: helper is a no-op."""
        from notification_service.main import _stop_outbox_worker

        await _stop_outbox_worker(worker_task=None, worker_instance=None)


class TestLifespanContext:
    """Tests for lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_without_workers(self) -> None:
        """Test lifespan when start_workers is False."""
        with (
            patch("notification_service.main.initialize_database", new_callable=AsyncMock) as mock_init_db,
            patch("notification_service.main._setup_rate_limiter") as mock_rate_limiter,
            patch("notification_service.main._setup_frequency_checker"),
            patch("notification_service.main._register_providers"),
            patch("notification_service.main._shutdown_components", new_callable=AsyncMock),
            patch("notification_service.main.settings") as mock_settings,
        ):
            mock_settings.start_workers = False

            from notification_service.main import lifespan

            mock_app = MagicMock()

            async with lifespan(mock_app):
                mock_init_db.assert_called_once()
                mock_rate_limiter.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_failure_still_runs_shutdown_cleanup(self) -> None:
        """Partially initialized resources are closed when startup raises."""
        with (
            patch(
                "notification_service.main.initialize_database",
                new_callable=AsyncMock,
                side_effect=RuntimeError("database unavailable"),
            ),
            patch("notification_service.main._shutdown_components", new_callable=AsyncMock) as mock_shutdown,
        ):
            from notification_service.main import lifespan

            with pytest.raises(RuntimeError, match="database unavailable"):
                async with lifespan(MagicMock()):
                    pytest.fail("lifespan yielded after startup failed")

        mock_shutdown.assert_awaited_once_with(worker_task=None, worker_instance=None)

    @pytest.mark.asyncio
    async def test_lifespan_with_workers(self) -> None:
        """Test lifespan when start_workers is True."""
        mock_events_boot = MagicMock()
        mock_events_boot.start_event_consumer = MagicMock()

        with (
            patch("notification_service.main.initialize_database", new_callable=AsyncMock),
            patch("notification_service.main._setup_rate_limiter"),
            patch("notification_service.main._setup_frequency_checker"),
            patch("notification_service.main._register_providers"),
            patch("notification_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch("notification_service.main.get_async_sessionmaker") as mock_get_sessionmaker,
            patch("notification_service.main.kafka_client") as mock_kafka_client,
            patch.dict("sys.modules", {"notification_service.events_boot": mock_events_boot}),
            patch("notification_service.main._start_workers") as mock_start_workers,
            patch("notification_service.main._shutdown_components", new_callable=AsyncMock),
            patch("notification_service.main.settings") as mock_settings,
        ):
            mock_settings.start_workers = True
            mock_settings.kafka.bootstrap_servers = "localhost:29092"
            mock_settings.database = MagicMock()
            mock_get_sessionmaker.return_value = MagicMock()

            mock_task = MagicMock()
            mock_worker = MagicMock()
            mock_start_workers.return_value = (mock_task, mock_worker)

            from notification_service.main import lifespan

            mock_app = MagicMock()

            async with lifespan(mock_app):
                mock_get_sessionmaker.assert_called_once_with(mock_settings.database)
                mock_kafka_client.set_db_session_factory.assert_called_once()
                mock_start_workers.assert_called_once()

    @pytest.mark.asyncio
    async def test_started_consumer_failure_propagates_and_cleans_up(self) -> None:
        """A fatal consumer owner failure aborts lifespan and preserves cleanup order."""
        supervisor = _FatalConsumerSupervisor()
        call_order: list[str] = []

        with (
            patch("notification_service.main.initialize_database", new_callable=AsyncMock),
            patch("notification_service.main._setup_rate_limiter"),
            patch("notification_service.main._setup_frequency_checker"),
            patch("notification_service.main._register_providers", return_value=True),
            patch("notification_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch(
                "notification_service.main.get_async_sessionmaker",
                return_value=MagicMock(),
            ),
            patch("notification_service.main.start_event_consumer"),
            patch("notification_service.main._start_workers", return_value=(None, None)),
            patch("notification_service.main.kafka_client") as mock_kafka,
            patch("notification_service.main.CacheFactory") as mock_cache,
            patch("notification_service.main.close_all_engines", new_callable=AsyncMock) as mock_close,
            patch("notification_service.main.obs") as mock_obs,
            patch("notification_service.main.settings") as mock_settings,
        ):
            mock_settings.start_workers = True
            mock_settings.kafka.bootstrap_servers = "localhost:29092"
            mock_settings.database = MagicMock()
            mock_kafka.supervise_consumer_failures = supervisor.context
            mock_kafka.stop_consumers = AsyncMock(side_effect=lambda: call_order.append("stop"))
            mock_kafka.close = AsyncMock(side_effect=lambda: call_order.append("kafka"))
            mock_cache.close_all = AsyncMock(side_effect=lambda: call_order.append("redis"))
            mock_close.side_effect = lambda: call_order.append("database")
            mock_obs.shutdown.side_effect = lambda: call_order.append("observability")

            from notification_service.main import lifespan

            async def run_lifespan_until_failure() -> None:
                async with lifespan(MagicMock()):
                    assert supervisor.entered.is_set()
                    supervisor.fail()
                    await asyncio.Event().wait()

            with pytest.raises(RuntimeError, match="consumer owner failed"):
                await run_lifespan_until_failure()

        assert call_order == ["stop", "kafka", "redis", "database", "observability"]

    @pytest.mark.asyncio
    async def test_disabled_workers_never_enter_consumer_supervision(self) -> None:
        """Worker-disabled startup yields normally without creating a supervisor scope."""
        supervisor = _FatalConsumerSupervisor()

        with (
            patch("notification_service.main.initialize_database", new_callable=AsyncMock),
            patch("notification_service.main._setup_rate_limiter"),
            patch("notification_service.main._setup_frequency_checker"),
            patch("notification_service.main._register_providers", return_value=True),
            patch("notification_service.main.kafka_client") as mock_kafka,
            patch("notification_service.main._shutdown_components", new_callable=AsyncMock),
            patch("notification_service.main.settings") as mock_settings,
        ):
            mock_settings.start_workers = False
            mock_kafka.supervise_consumer_failures = supervisor.context

            from notification_service.main import lifespan

            async with lifespan(MagicMock()):
                assert not supervisor.entered.is_set()

        assert not supervisor.entered.is_set()
