"""Main FastAPI application for job-ingest-discovery-service."""

from __future__ import annotations

from contextlib import asynccontextmanager
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
from nohiki_redis_utils import CacheFactory, RedisHealthProbe, ensure_redis_ready

from job_ingest_discovery_service.core.config import get_settings
from job_ingest_discovery_service.core.kafka import kafka_client
from job_ingest_discovery_service.events import start_event_consumer
from job_ingest_discovery_service.providers.jsearch.client import reset_jsearch_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

settings = get_settings()
obs = Observability.from_settings(settings)
obs.init()
logger = obs.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifespan events."""
    logger.info("Starting service", service=settings.service_name)
    await initialize_database(settings)

    await ensure_kafka_ready(bootstrap_servers=settings.kafka.bootstrap_servers)
    await ensure_redis_ready(redis_url=settings.redis.connection_string)

    kafka_client.set_db_session_factory(get_async_sessionmaker(settings.database))
    start_event_consumer()

    try:
        async with kafka_client.supervise_consumer_failures():
            logger.info("Application startup complete")
            yield
    finally:
        # 1. Stop Kafka consumers first (stop accepting new work)
        await kafka_client.stop_consumers()
        logger.debug("Kafka consumers stopped")

        # 2. Close Kafka connections
        await kafka_client.close()
        logger.debug("Kafka client closed")

        # 3. Close database connection pools
        await close_all_engines()
        logger.debug("Database engines disposed")

        # 4. Close provider HTTP connections
        await reset_jsearch_client()
        logger.debug("Provider clients closed")

        # 5. Close Redis connections
        await CacheFactory.close_all()
        logger.debug("Redis connections closed")

        # 6. Shutdown observability (flush pending telemetry)
        obs.shutdown()
        logger.debug("Observability shutdown complete")

        logger.info("Service shutdown complete", service=settings.service_name)


root_router = build_root_router(settings.service_name, settings.service_version)
health_router = build_probe_health_router(
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
        RedisHealthProbe(settings.redis.connection_string),
    ],
)
metrics_router = build_metrics_router()


app = FastAPI(
    title=settings.service_name_friendly,
    description=settings.service_desc_friendly,
    version=settings.service_version,
    lifespan=lifespan,
    routes=[*root_router.routes, *health_router.routes, *metrics_router.routes],
)

obs.init_fastapi(app)

setup_error_handlers(app)


logger.info(
    "Service initialized",
    service=settings.service_name,
    version=settings.service_version,
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)
