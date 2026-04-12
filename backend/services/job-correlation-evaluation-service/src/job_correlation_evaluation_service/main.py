"""Main FastAPI application for job-correlation-evaluation-service."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from nohiki.ml.v1 import EntityType
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
from nohiki_qdrant_client import QdrantHealthProbe, create_async_qdrant_client
from nohiki_redis_utils import RedisHealthProbe

from job_correlation_evaluation_service.core.cache import close_cache
from job_correlation_evaluation_service.core.config import get_manifest, get_settings
from job_correlation_evaluation_service.core.kafka import kafka_client
from job_correlation_evaluation_service.events.backfill_handler import (
    set_backfill_ml_scoring_service,
)
from job_correlation_evaluation_service.events.handlers import (
    set_ml_scoring_service,
    start_event_consumer,
)
from job_correlation_evaluation_service.services.scoring.pipeline import ScoringPipeline
from job_correlation_evaluation_service.services.scoring.pipeline_config import (
    get_pipeline_settings,
)
from job_correlation_evaluation_service.services.scoring_service import MLScoringService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from nohiki_ml_manifest import SemanticRepresentationManifest

    from job_correlation_evaluation_service.services.scoring.pipeline_config import (
        PipelineSettings,
    )

settings = get_settings()
obs = Observability.from_settings(settings)
obs.init()
logger = obs.get_logger(__name__)


def _load_pipeline_assets() -> tuple[SemanticRepresentationManifest, PipelineSettings]:
    """Load manifest-backed pipeline settings."""
    pipeline_settings = get_pipeline_settings()
    logger.info(
        "Initializing scoring pipeline",
        qdrant_host=settings.qdrant.host,
    )
    return get_manifest(), pipeline_settings


def _initialize_scoring(app: FastAPI, cleanup: AsyncExitStack) -> None:
    """Create and register the lifecycle-owned scoring resources."""
    manifest, pipeline_settings = _load_pipeline_assets()
    try:
        qdrant_client = create_async_qdrant_client(settings.qdrant)
        cleanup.push_async_callback(qdrant_client.close)
        jobs_collection = manifest.get_collection_name(EntityType.JOB)
        scoring_pipeline = ScoringPipeline.create(
            qdrant_client=qdrant_client,
            collection_name=jobs_collection,
            settings=pipeline_settings,
        )
        ml_scoring_service = MLScoringService(scoring_pipeline)
        ml_scoring_service.initialize()
        cleanup.push_async_callback(ml_scoring_service.close)
    except (OSError, RuntimeError, ValueError) as exc:
        msg = f"ML scoring pipeline initialization failed: {exc}"
        logger.exception(
            msg,
            error_type=type(exc).__name__,
            qdrant_host=settings.qdrant.host,
        )
        raise RuntimeError(msg) from exc

    app.state.ml_scoring_service = ml_scoring_service
    app.state.qdrant_client = qdrant_client
    set_ml_scoring_service(ml_scoring_service)
    set_backfill_ml_scoring_service(ml_scoring_service)
    logger.info(
        "ML scoring pipeline ready",
        qdrant_host=settings.qdrant.host,
        collection_name=jobs_collection,
    )


async def _start_event_consumers(cleanup: AsyncExitStack) -> None:
    """Initialize the Kafka producer/session factory and start consumers."""
    cleanup.push_async_callback(kafka_client.close)
    await ensure_kafka_ready(bootstrap_servers=settings.kafka.bootstrap_servers)
    await kafka_client.ensure_producer_ready()
    kafka_client.set_db_session_factory(get_async_sessionmaker(settings.database))
    start_event_consumer()


async def _shutdown_runtime(
    app: FastAPI,
    cleanup: AsyncExitStack,
    *,
    consumers_started: bool,
) -> None:
    """Stop event intake, detach handler state, and close owned resources."""
    try:
        if consumers_started:
            await kafka_client.stop_consumers()
            logger.debug("Kafka consumers stopped")
    finally:
        set_ml_scoring_service(None)
        set_backfill_ml_scoring_service(None)
        app.state.ml_scoring_service = None
        app.state.qdrant_client = None
        await cleanup.aclose()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Manage startup and close every initialized dependency on all exit paths."""
    logger.info("Starting service", service=settings.service_name)
    consumers_started = False
    cleanup = AsyncExitStack()
    await cleanup.__aenter__()
    cleanup.callback(obs.shutdown)
    cleanup.push_async_callback(close_all_engines)
    cleanup.push_async_callback(close_cache)

    try:
        await initialize_database(settings)
        _initialize_scoring(app, cleanup)
        await _start_event_consumers(cleanup)
        consumers_started = True
        async with kafka_client.supervise_consumer_failures():
            logger.info("Application startup complete")
            yield
    finally:
        logger.info("Shutting down service", service=settings.service_name)
        await _shutdown_runtime(
            app,
            cleanup,
            consumers_started=consumers_started,
        )
        logger.info("Service shutdown complete", service=settings.service_name)


app = FastAPI(
    title=settings.service_name_friendly,
    description=settings.service_desc_friendly,
    version=settings.service_version,
    lifespan=lifespan,
)

obs.init_fastapi(app)

setup_error_handlers(app)

# shared routers (health/metrics only - no business logic endpoints)
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
                app.state.qdrant_client,
                collection_names=[get_manifest().get_collection_name(EntityType.JOB)],
            ),
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
