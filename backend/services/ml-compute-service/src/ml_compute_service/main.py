"""Main FastAPI application for ml-compute-service."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from nohiki_fastapi_utils import build_root_router
from nohiki_fastapi_utils.errors import setup_error_handlers
from nohiki_fastapi_utils.health_router import build_probe_health_router
from nohiki_kafka_client import KafkaCapability, KafkaHealthProbe, ensure_kafka_ready
from nohiki_ml_core import (
    ComputeBackend,
    GpuNotAvailableError,
    ModelCacheManager,
    detect_gpu_capabilities,
    get_available_backend,
    validate_compute_backend,
)
from nohiki_ml_core.model_cache import ModelArchive
from nohiki_observability import Observability, build_metrics_router
from nohiki_redis_utils import CacheFactory
from nohiki_s3_client import S3Client

from ml_compute_service.core.config import (
    ComputeBackendConfig,
    get_manifest,
    get_settings,
)
from ml_compute_service.core.kafka import kafka_client
from ml_compute_service.core.readiness import readiness_gate

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from nohiki_ml_core.pipeline import MLEncodingPipeline


settings = get_settings()


def _configure_model_caches(cache_dir: Path) -> None:
    """Point every local model loader at the configured processing cache."""
    huggingface_dir = cache_dir / "huggingface"
    hub_dir = huggingface_dir / "hub"
    os.environ["HF_HOME"] = str(huggingface_dir)
    os.environ["HF_HUB_CACHE"] = str(hub_dir)
    os.environ["TRANSFORMERS_CACHE"] = str(hub_dir)
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(hub_dir)
    os.environ["FASTEMBED_CACHE_PATH"] = str(cache_dir / "fastembed")


# Configure cache environment before importing libraries that capture cache constants.
_configure_model_caches(settings.processing.cache_dir)
snapshot_download = importlib.import_module("huggingface_hub").snapshot_download


def get_encoding_pipeline() -> MLEncodingPipeline:
    """Load the pipeline only after model cache environment is configured."""
    from ml_compute_service.core.pipeline import get_encoding_pipeline as build_pipeline  # noqa: PLC0415

    return build_pipeline()


def start_event_consumer() -> None:
    """Register Kafka consumers only after model cache environment is configured."""
    from ml_compute_service.events import start_event_consumer as start_consumers  # noqa: PLC0415

    start_consumers()


obs = Observability.from_settings(settings)
obs.init()
logger = obs.get_logger(__name__)


def _validate_compute_backend_on_startup() -> ComputeBackend:
    """Validate compute backend configuration and fail fast if invalid.

    This runs synchronously at module load time to ensure we fail fast
    before accepting any requests if GPU is configured but unavailable.

    Returns:
        The actual ComputeBackend that will be used

    Raises:
        GpuNotAvailableError: If GPU is configured but not available

    """
    backend_config = settings.processing.compute_backend

    if backend_config == ComputeBackendConfig.GPU:
        # GPU explicitly requested - fail fast if not available
        try:
            validate_compute_backend(ComputeBackend.CUDA)
        except GpuNotAvailableError:
            logger.exception(
                "GPU compute backend configured but GPU not available",
                configured_backend=backend_config,
            )
            raise
        return ComputeBackend.CUDA

    if backend_config == ComputeBackendConfig.AUTO:
        # Auto-detect - use GPU if available, else CPU
        actual = get_available_backend()
        caps = detect_gpu_capabilities()
        logger.info(
            "Auto-detected compute backend",
            backend=actual.value,
            cuda_available=caps.cuda_available,
            device_count=caps.device_count,
        )
        return actual

    # CPU explicitly requested or default
    logger.info("Using CPU compute backend", configured_backend=backend_config)
    return ComputeBackend.CPU


# Validate compute backend at module load time (fail fast)
_active_compute_backend = _validate_compute_backend_on_startup()


def _contains_files(directory: Path) -> bool:
    return any(path.is_file() for path in directory.rglob("*"))


async def _download_model_from_source(archive: ModelArchive, target_dir: Path) -> None:
    """Download a model from its upstream source (HuggingFace Hub / PyPI).

    This callback is invoked by ModelCacheManager when a model archive is
    not yet present in S3. It uses the heavy ML libraries available in
    ml-compute-service to download the model files into *target_dir*.
    """
    if archive.extract_dir == "fastembed":
        module = importlib.import_module("fastembed")
        model_class = module.SparseTextEmbedding
        await asyncio.to_thread(model_class, model_name=archive.model_id, cache_dir=str(target_dir))

    else:  # noqa: PLR5501 - revision changes the downloader call signature
        if archive.revision is None:
            await asyncio.to_thread(
                snapshot_download,
                repo_id=archive.model_id,
                cache_dir=target_dir / "hub",
            )
        else:
            await asyncio.to_thread(
                snapshot_download,
                repo_id=archive.model_id,
                revision=archive.revision,
                cache_dir=target_dir / "hub",
            )

    if not await asyncio.to_thread(_contains_files, target_dir):
        msg = f"Source download produced no model files for {archive.model_id} in {target_dir}"
        raise RuntimeError(msg)

    logger.info("Model downloaded from upstream source", model_id=archive.model_id)


async def _ensure_models_cached() -> None:
    manifest = get_manifest()

    cache_dir = settings.processing.cache_dir
    _configure_model_caches(cache_dir)
    s3_client = S3Client(settings.s3)
    redis_cache = CacheFactory.create_cache("model-cache", redis_url=settings.redis_url)

    manager = ModelCacheManager(
        s3_client=s3_client,
        redis_cache=redis_cache,
        cache_dir=cache_dir,
        manifest=manifest,
        source_downloader=_download_model_from_source,
    )
    await manager.ensure_models_available()


async def _warm_up_models_and_start_consumers() -> None:
    """Download/warm ML models then start Kafka consumers.

    Runs as a background task so the /readyz endpoint is reachable
    during model download (returning 503 with reason 'models_loading').
    """
    try:
        await _ensure_models_cached()

        logger.info("Pre-warming ML encoding pipeline (this may take several minutes on first run)...")
        pipeline = await asyncio.to_thread(get_encoding_pipeline)
        await asyncio.to_thread(pipeline.colbert.warm_up)
        await asyncio.to_thread(pipeline.sparse.warm_up)
        logger.info("ML encoding pipeline warmed up and ready")

        start_event_consumer()
        readiness_gate.mark_ready()
        logger.info("ML compute service fully ready")
    except Exception:
        readiness_gate.mark_failed()
        logger.exception("Failed to warm up ML models")
        raise


async def _supervise_consumers_after_warmup(warmup_task: asyncio.Task[None]) -> None:
    """Propagate consumer failure only after model warmup succeeds."""
    await asyncio.wait((warmup_task,))
    if warmup_task.cancelled() or warmup_task.exception() is not None:
        return

    await kafka_client.wait_for_consumers()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifespan events."""
    logger.info("Starting service", service=settings.service_name)
    await ensure_kafka_ready(bootstrap_servers=settings.kafka.bootstrap_servers)
    warmup_task = asyncio.create_task(_warm_up_models_and_start_consumers())
    logger.info("Application startup complete")

    try:
        async with asyncio.TaskGroup() as task_group:
            consumer_supervisor = task_group.create_task(_supervise_consumers_after_warmup(warmup_task))
            try:
                yield
            finally:
                consumer_supervisor.cancel()
    finally:
        logger.info("Shutting down service", service=settings.service_name)
        if not warmup_task.done():
            warmup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await warmup_task
        else:
            with contextlib.suppress(Exception):
                warmup_task.result()

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
        readiness_gate=readiness_gate,
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
