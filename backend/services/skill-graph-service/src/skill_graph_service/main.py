"""Main FastAPI application for skill-graph-service."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
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

from skill_graph_service.core.config import get_readiness_gate, get_settings
from skill_graph_service.core.kafka import kafka_client
from skill_graph_service.events import start_event_consumer

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

settings = get_settings()
obs = Observability.from_settings(settings)
obs.init()
logger = obs.get_logger(__name__)

_readiness_gate = get_readiness_gate()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifespan events."""
    logger.info("Starting service", service=settings.service_name)

    async with AsyncExitStack() as cleanup:
        cleanup.callback(obs.shutdown)

        await initialize_database(settings)
        cleanup.push_async_callback(close_all_engines)

        await ensure_kafka_ready(bootstrap_servers=settings.kafka.bootstrap_servers)

        kafka_client.set_db_session_factory(get_async_sessionmaker(settings.database))
        cleanup.push_async_callback(kafka_client.close)
        cleanup.push_async_callback(kafka_client.stop_consumers)
        start_event_consumer()

        async with kafka_client.supervise_consumer_failures():
            cleanup.push_async_callback(_readiness_gate.stop)
            _readiness_gate.start()

            logger.info("Application startup complete")
            try:
                yield
            finally:
                logger.info("Shutting down service", service=settings.service_name)

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
            DatabaseHealthProbe(get_async_engine(settings.database)),
            KafkaHealthProbe(
                settings.kafka.bootstrap_servers,
                capabilities={
                    KafkaCapability.BROKER_CONNECTIVITY,
                    KafkaCapability.CONSUMER_READY,
                },
            ),
        ],
        readiness_gate=_readiness_gate,
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
