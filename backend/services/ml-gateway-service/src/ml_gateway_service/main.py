"""ML Gateway Service - FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from nohiki_fastapi_utils import build_root_router
from nohiki_fastapi_utils.errors import setup_error_handlers
from nohiki_fastapi_utils.health_router import build_probe_health_router
from nohiki_kafka_client import KafkaCapability, KafkaHealthProbe, ensure_kafka_ready
from nohiki_observability import Observability, build_metrics_router
from nohiki_redis_utils import CacheFactory

from ml_gateway_service.core.config import get_settings
from ml_gateway_service.core.kafka import kafka_client
from ml_gateway_service.events import start_event_consumer

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
    await ensure_kafka_ready(bootstrap_servers=settings.kafka.bootstrap_servers)
    start_event_consumer()
    logger.info("Application startup complete")

    try:
        async with kafka_client.supervise_consumer_failures():
            yield
    finally:
        logger.info("Shutting down service", service=settings.service_name)
        try:
            await kafka_client.stop_consumers()
            logger.debug("Kafka consumers stopped")
        finally:
            try:
                await kafka_client.close()
                logger.debug("Kafka client closed")
            finally:
                try:
                    await CacheFactory.close_all()
                    logger.debug("Redis connections closed")
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

# Shared routers (health and root only - event-driven service)
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
