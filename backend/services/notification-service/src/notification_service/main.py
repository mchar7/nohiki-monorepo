"""Main FastAPI application for notification-service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from nohiki.common.v1 import NotificationChannel
from nohiki_db_utils import (
    DatabaseHealthProbe,
    close_all_engines,
    get_async_engine,
    get_async_sessionmaker,
    initialize_database,
)
from nohiki_fastapi_utils import build_root_router
from nohiki_fastapi_utils.errors import setup_error_handlers
from nohiki_fastapi_utils.health_router import build_probe_health_router
from nohiki_kafka_client import KafkaCapability, KafkaHealthProbe, ensure_kafka_ready
from nohiki_observability import Observability, build_metrics_router
from nohiki_redis_utils import (
    CacheFactory,
    CircuitBreakerConfig,
    RateLimiter,
    create_cache,
    create_token_bucket_limiter,
)

from notification_service.core.config import get_settings
from notification_service.core.kafka import kafka_client
from notification_service.core.providers import (
    EmailConfig,
    configure_email_provider,
    register_provider,
)
from notification_service.events import start_event_consumer
from notification_service.services.outbox import OutboxWorker
from notification_service.services.outbox.provider_router import ProviderRouter
from notification_service.services.provider_clients.resend_email_provider import (
    ResendEmailProvider,
)
from notification_service.services.provider_clients.twilio_email_provider import (
    TwilioSendGridProvider,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


settings = get_settings()
obs = Observability.from_settings(settings)
obs.init()
logger = obs.get_logger(__name__)


@dataclass(slots=True)
class _AppState:
    """Container for application-level state initialized during startup."""

    rate_limiter: RateLimiter | None = field(default=None)
    shutdown_event: asyncio.Event | None = field(default=None)


_app_state = _AppState()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifespan events."""
    logger.info("Starting service", service=settings.service_name)
    worker_task: asyncio.Task[Any] | None = None
    worker_instance: OutboxWorker | None = None

    try:
        await initialize_database(settings)
        _setup_rate_limiter()
        if not _register_providers():
            msg = "Failed to configure notification providers"
            raise RuntimeError(msg)

        if settings.start_workers:
            await ensure_kafka_ready(bootstrap_servers=settings.kafka.bootstrap_servers)
            kafka_client.set_db_session_factory(get_async_sessionmaker(settings.database))
            start_event_consumer()
            async with kafka_client.supervise_consumer_failures():
                worker_task, worker_instance = _start_workers()
                logger.info("Messaging service startup complete")
                yield
        else:
            logger.info("Messaging service startup complete")
            yield
    finally:
        await _shutdown_components(worker_task=worker_task, worker_instance=worker_instance)


def _setup_rate_limiter() -> None:
    """Initialize the rate limiter using nohiki-redis-utils."""
    cache = create_cache(settings.service_name, redis_url=settings.redis.connection_string)

    _app_state.rate_limiter = create_token_bucket_limiter(
        cache=cache,
        requests=settings.rate_limit.requests_per_window,
        window_seconds=settings.rate_limit.window_seconds,
    )
    logger.info(
        "Rate limiter initialized",
        requests=settings.rate_limit.requests_per_window,
        window_seconds=settings.rate_limit.window_seconds,
        algorithm="token_bucket",
    )


def _register_providers() -> bool:
    """Register all email providers and configure the selected default."""
    try:
        register_provider(NotificationChannel.EMAIL, ResendEmailProvider)
        register_provider(NotificationChannel.EMAIL, TwilioSendGridProvider)

        email_config = EmailConfig(
            from_address=settings.email.from_address,
            from_name=settings.email.from_name,
            unsubscribe_domain=settings.email.unsubscribe_domain,
            provider_name=settings.email.provider,
            api_key=settings.email.api_key.get_secret_value(),
        )
        configure_email_provider(email_config, settings.email.provider)
    except (ValueError, ImportError, RuntimeError, OSError) as exc:
        logger.exception("Failed to configure email providers", error_type=type(exc).__name__)
        return False

    logger.info("Configured email providers", provider=settings.email.provider)
    return True


def _build_provider_router() -> ProviderRouter:
    """Build a :class:`ProviderRouter` from ``settings.circuit_breaker``."""
    cb = settings.circuit_breaker
    cb_config = CircuitBreakerConfig(
        failure_threshold=cb.failure_threshold,
        success_threshold=cb.success_threshold,
        timeout_seconds=cb.timeout_seconds,
        half_open_max_calls=cb.half_open_max_calls,
    )
    return ProviderRouter(cb_config=cb_config)


def _start_workers() -> tuple[asyncio.Task[Any], OutboxWorker]:
    """Spin up the outbox worker task and return it alongside the instance."""
    shutdown_event = asyncio.Event()
    _app_state.shutdown_event = shutdown_event

    provider_router = _build_provider_router()

    worker_instance = OutboxWorker(
        provider_router=provider_router,
        rate_limiter=_app_state.rate_limiter,
        shutdown_event=shutdown_event,
    )

    worker_task = asyncio.create_task(worker_instance.start(), name="notification-outbox-worker")
    logger.info("Outbox worker started")

    # AutoKafkaClient starts consumers automatically when handlers register
    # via the decorator in events_boot, so there's nothing to schedule here.
    logger.info("Event consumers registered")

    return worker_task, worker_instance


async def _shutdown_components(
    worker_task: asyncio.Task[Any] | None = None,
    worker_instance: OutboxWorker | None = None,
) -> None:
    """Drain the service in dependency order.

    The outbox worker shuts down cooperatively; we never ``task.cancel()`` it.
    Cancelling between ``provider.send`` and ``db.commit`` would leave a
    message "sent at provider, pending in DB". Worst-case shutdown latency is
    one in-flight ``provider.send`` plus one commit, bounded by the provider
    HTTP timeout.

    Then in order: stop Kafka consumers (no new work), close Kafka, close
    Redis, dispose DB engines, flush observability.

    Args:
        worker_task: Task from :func:`_start_workers`, or ``None`` in tests.
        worker_instance: Worker instance, or ``None`` in tests.

    """
    logger.info("Shutting down service", service=settings.service_name)

    await _stop_outbox_worker(worker_task=worker_task, worker_instance=worker_instance)

    await kafka_client.stop_consumers()
    logger.debug("Kafka consumers stopped")

    await kafka_client.close()
    logger.debug("Kafka client closed")

    await CacheFactory.close_all()
    logger.debug("Redis connections closed")

    await close_all_engines()
    logger.debug("Database engines disposed")

    obs.shutdown()
    logger.debug("Observability shutdown complete")

    logger.info("Service shutdown complete", service=settings.service_name)


async def _stop_outbox_worker(
    worker_task: asyncio.Task[Any] | None,
    worker_instance: OutboxWorker | None,
) -> None:
    """Signal cooperative shutdown and wait for the worker to exit.

    Args:
        worker_task: Task running :meth:`OutboxWorker.start`, or ``None`` if
            workers were never started.
        worker_instance: Worker whose ``stop()`` is invoked, or ``None``.

    """
    if worker_instance is None or worker_task is None:
        return

    worker_instance.stop()
    await worker_task
    logger.info("Outbox worker task exited cleanly")


app = FastAPI(
    title=settings.service_name_friendly,
    description=settings.service_desc_friendly,
    version=settings.service_version,
    lifespan=lifespan,
)

obs.init_fastapi(app)

setup_error_handlers(app)

app.include_router(build_root_router(settings.service_name, settings.service_version))
app.include_router(
    build_probe_health_router(
        settings.service_name,
        lambda: [
            DatabaseHealthProbe(get_async_engine(settings.database)),
            KafkaHealthProbe(
                settings.kafka.bootstrap_servers,
                capabilities={
                    KafkaCapability.BROKER_CONNECTIVITY,
                    KafkaCapability.CONSUMER_READY,
                },
            ),
        ],
    )
)
app.include_router(build_metrics_router())

logger.info(
    "Service initialized",
    service=settings.service_name,
    version=settings.service_version,
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)
