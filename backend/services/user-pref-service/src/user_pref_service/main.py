"""Main FastAPI application for user-pref-service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from fastapi import FastAPI
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
from nohiki_qdrant_client import QdrantHealthProbe

from user_pref_service.core.config import (
    get_profiles_collection_name,
    get_qdrant_client,
    get_settings,
)
from user_pref_service.core.kafka import kafka_client
from user_pref_service.core.saga_policy import SWEEP_INTERVAL_SECONDS
from user_pref_service.events import start_event_consumer
from user_pref_service.events.saga_sweeper import sweep_pref_enrichment_sagas

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

settings = get_settings()
obs = Observability.from_settings(settings)
obs.init()
logger = obs.get_logger(__name__)


async def _pref_enrichment_saga_loop(shutdown_event: asyncio.Event) -> None:
    """Retry or expire durable preference sagas until shutdown."""
    sessionmaker = get_async_sessionmaker(settings.database)
    while not shutdown_event.is_set():
        with suppress(TimeoutError):
            await asyncio.wait_for(shutdown_event.wait(), timeout=SWEEP_INTERVAL_SECONDS)
        if shutdown_event.is_set():
            return
        try:
            async with sessionmaker() as db:
                await sweep_pref_enrichment_sagas(db)
                await db.commit()
        except Exception:
            logger.exception("Preference enrichment saga sweep failed; will retry")


@asynccontextmanager
async def _run_saga_sweeper() -> AsyncGenerator[None]:
    """Start and stop the local durable-saga scheduler."""
    shutdown_event = asyncio.Event()
    saga_task = asyncio.create_task(
        _pref_enrichment_saga_loop(shutdown_event),
        name="user-pref-enrichment-saga-sweep",
    )
    try:
        yield
    finally:
        shutdown_event.set()
        saga_task.cancel()
        with suppress(asyncio.CancelledError):
            await saga_task


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifespan events."""
    logger.info("Starting service", service=settings.service_name)
    database_initialized = False
    consumers_started = False
    qdrant_client = None

    try:
        await initialize_database(settings)
        database_initialized = True
        qdrant_client = get_qdrant_client()

        await ensure_kafka_ready(bootstrap_servers=settings.kafka.bootstrap_servers)

        kafka_client.set_db_session_factory(get_async_sessionmaker(settings.database))
        start_event_consumer()
        consumers_started = True

        async with kafka_client.supervise_consumer_failures(), _run_saga_sweeper():
            logger.info("Application startup complete")
            yield
    finally:
        logger.info("Shutting down service", service=settings.service_name)
        try:
            if consumers_started:
                await kafka_client.stop_consumers()
                logger.debug("Kafka consumers stopped")
        finally:
            try:
                if consumers_started:
                    await kafka_client.close()
                    logger.debug("Kafka client closed")
            finally:
                try:
                    if qdrant_client is not None:
                        await qdrant_client.raw_client.close()
                        logger.debug("Qdrant client closed")
                    if database_initialized:
                        await close_all_engines()
                        logger.debug("Database engines disposed")
                finally:
                    obs.shutdown()
                    logger.debug("Observability shutdown complete")

        logger.info("Service shutdown complete", service=settings.service_name)


app = FastAPI(
    title=settings.service_name_friendly,
    description=settings.service_desc_friendly,
    version=settings.service_version,
    lifespan=lifespan,
)

obs.init_fastapi(app)

setup_error_handlers(app)

# shared routers (health and root only - event-driven service)
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
            QdrantHealthProbe(
                get_qdrant_client().raw_client,
                collection_names=[get_profiles_collection_name()],
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
