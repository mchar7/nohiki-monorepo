"""Main FastAPI application for job-ingest-enrichment-service."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from typing import TYPE_CHECKING

from fastapi import FastAPI
from nohiki_db_utils import (
    close_all_engines,
    get_async_sessionmaker,
    initialize_database,
)
from nohiki_fastapi_utils import build_root_router, setup_error_handlers
from nohiki_fastapi_utils.health_router import build_probe_health_router
from nohiki_kafka_client import KafkaCapability, KafkaHealthProbe, ensure_kafka_ready
from nohiki_llm_client import LLMHealthProbe, ensure_llm_ready
from nohiki_observability import Observability, build_metrics_router
from nohiki_redis_utils import CacheFactory, RedisHealthProbe, ensure_redis_ready

from job_ingest_enrichment_service.core.config import get_settings
from job_ingest_enrichment_service.core.kafka import kafka_client
from job_ingest_enrichment_service.events import start_event_consumer
from job_ingest_enrichment_service.events.callbacks import expire_stale_embedding_sagas
from job_ingest_enrichment_service.services.extraction_agent import (
    close_extraction_llm_client,
)
from job_ingest_enrichment_service.services.skill_clarification import (
    close_skill_clarification_service,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

settings = get_settings()
obs = Observability.from_settings(settings)
obs.init()
logger = obs.get_logger(__name__)
_STALE_SAGA_INTERVAL_SECONDS = 5 * 60


async def _stale_saga_loop(shutdown_event: asyncio.Event) -> None:
    """Expire embedding sagas whose persisted deadline has passed."""
    sessionmaker = get_async_sessionmaker(settings.database)
    while not shutdown_event.is_set():
        try:
            async with sessionmaker() as db:
                await expire_stale_embedding_sagas(db)
                await db.commit()
        except Exception:
            logger.exception("Stale enrichment saga sweep failed; will retry")
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=_STALE_SAGA_INTERVAL_SECONDS)
        except TimeoutError:
            continue


async def _stop_stale_saga_task(task: asyncio.Task[None]) -> None:
    """Cancel and join the background stale-saga sweep."""
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Manage startup and deterministic partial/normal shutdown."""
    logger.info("Starting service", service=settings.service_name)
    async with AsyncExitStack() as cleanup:
        cleanup.callback(obs.shutdown)
        cleanup.push_async_callback(close_all_engines)
        cleanup.push_async_callback(CacheFactory.close_all)
        cleanup.push_async_callback(kafka_client.close)
        cleanup.push_async_callback(close_skill_clarification_service)
        cleanup.push_async_callback(close_extraction_llm_client)

        await initialize_database(settings)
        await ensure_kafka_ready(bootstrap_servers=settings.kafka.bootstrap_servers)
        await ensure_llm_ready(settings.llm, chains=("extraction", "skill_clarification"))
        await ensure_redis_ready(redis_url=settings.redis.connection_string)

        kafka_client.set_db_session_factory(get_async_sessionmaker(settings.database))
        cleanup.push_async_callback(kafka_client.stop_consumers)
        start_event_consumer()
        async with kafka_client.supervise_consumer_failures():
            shutdown_event = asyncio.Event()
            stale_saga_task = asyncio.create_task(
                _stale_saga_loop(shutdown_event),
                name="job-ingest-enrichment-stale-saga-sweep",
            )
            cleanup.push_async_callback(_stop_stale_saga_task, stale_saga_task)

            logger.info("Application startup complete")
            yield

    logger.info("Service shutdown complete", service=settings.service_name)


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
            KafkaHealthProbe(
                settings.kafka.bootstrap_servers,
                capabilities={
                    KafkaCapability.BROKER_CONNECTIVITY,
                    KafkaCapability.CONSUMER_READY,
                },
            ),
            LLMHealthProbe(settings.llm, chains=("extraction", "skill_clarification")),
            RedisHealthProbe(settings.redis.connection_string),
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
