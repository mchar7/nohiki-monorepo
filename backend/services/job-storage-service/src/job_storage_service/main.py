"""Main FastAPI application for job-storage-service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from typing import TYPE_CHECKING

from fastapi import FastAPI
from nohiki_db_utils import (
    DatabaseHealthProbe,
    StaleSagaDetector,
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

from job_storage_service.core.config import (
    get_jobs_collection_name,
    get_qdrant_client,
    get_settings,
)
from job_storage_service.core.kafka import kafka_client
from job_storage_service.db.models import ListingIngestSaga
from job_storage_service.events import start_event_consumer
from job_storage_service.metrics.ingest import get_ingest_metrics

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

settings = get_settings()
obs = Observability.from_settings(settings)
obs.init()
logger = obs.get_logger(__name__)

# Saga rows already carry their absolute TTL in ``expires_at``. The detector's
# max_age is an additional grace period, so zero expires rows as soon as that
# persisted deadline passes.
_STALE_SAGA_MAX_AGE = timedelta(0)
_STALE_SAGA_INTERVAL_SECONDS = 5 * 60


async def _stale_saga_loop(shutdown_event: asyncio.Event) -> None:
    """Periodic background task that expires stuck PENDING ingest sagas.

    Sleeps via ``shutdown_event.wait`` so a service shutdown short-circuits
    the wait instead of forcing the lifespan to wait up to a full interval.
    """
    sessionmaker = get_async_sessionmaker(settings.database)
    detector = StaleSagaDetector(ListingIngestSaga, max_age=_STALE_SAGA_MAX_AGE)
    while not shutdown_event.is_set():
        try:
            async with sessionmaker() as db:
                await detector.run(db)
                await db.commit()
        except Exception:
            logger.exception("Stale saga sweep failed; will retry on next interval")
            get_ingest_metrics().record_stale_saga_sweep_failure()
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=_STALE_SAGA_INTERVAL_SECONDS)
        except TimeoutError:
            continue


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifespan events."""
    logger.info("Starting service", service=settings.service_name)

    await initialize_database(settings)
    qdrant_client = get_qdrant_client()

    await ensure_kafka_ready(bootstrap_servers=settings.kafka.bootstrap_servers)

    kafka_client.set_db_session_factory(get_async_sessionmaker(settings.database))
    start_event_consumer()

    shutdown_event = asyncio.Event()
    stale_saga_task: asyncio.Task[None] | None = None
    try:
        async with kafka_client.supervise_consumer_failures():
            stale_saga_task = asyncio.create_task(
                _stale_saga_loop(shutdown_event),
                name="job-storage-stale-saga-sweep",
            )

            logger.info("Application startup complete")
            yield
    finally:
        logger.info("Shutting down service", service=settings.service_name)

        # Stop accepting work and wait for consumer handlers before tearing down
        # the sweep or database connections they may still need.
        await kafka_client.stop_consumers()
        logger.debug("Kafka consumers stopped")

        shutdown_event.set()
        if stale_saga_task is not None:
            stale_saga_task.cancel()
            with suppress(asyncio.CancelledError):
                await stale_saga_task
        logger.debug("Stale saga sweep stopped")

        # 2. Close Kafka connections
        await kafka_client.close()
        logger.debug("Kafka client closed")

        await qdrant_client.raw_client.close()
        logger.debug("Qdrant client closed")

        # 3. Close database connection pools
        await close_all_engines()
        logger.debug("Database engines disposed")

        # 4. Shutdown observability (flush pending telemetry)
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
                collection_names=[get_jobs_collection_name()],
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
