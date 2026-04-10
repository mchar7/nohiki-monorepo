"""Main FastAPI application for doc-content-service (stateless)."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from nohiki_fastapi_utils import build_root_router
from nohiki_fastapi_utils.errors import setup_error_handlers
from nohiki_fastapi_utils.health_router import build_probe_health_router
from nohiki_kafka_client import KafkaCapability, KafkaHealthProbe, ensure_kafka_ready
from nohiki_llm_client import LLMHealthProbe, ensure_llm_ready
from nohiki_observability import Observability, build_metrics_router

from doc_content_service.core.config import get_settings
from doc_content_service.core.kafka import kafka_client
from doc_content_service.events import start_event_consumer
from doc_content_service.events.handlers import close_llm_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

settings = get_settings()
obs = Observability.from_settings(settings)
obs.init()
logger = obs.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Manage startup and deterministic partial/normal shutdown."""
    logger.info("Starting service", service=settings.service_name)
    async with AsyncExitStack() as cleanup:
        cleanup.callback(obs.shutdown)
        cleanup.push_async_callback(kafka_client.close)
        cleanup.push_async_callback(close_llm_client)

        await ensure_kafka_ready(bootstrap_servers=settings.kafka.bootstrap_servers)
        await ensure_llm_ready(settings.llm, chains=("doc_tailoring",))
        cleanup.push_async_callback(kafka_client.stop_consumers)
        start_event_consumer()
        await cleanup.enter_async_context(kafka_client.supervise_consumer_failures())
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
            LLMHealthProbe(settings.llm, chains=("doc_tailoring",)),
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
