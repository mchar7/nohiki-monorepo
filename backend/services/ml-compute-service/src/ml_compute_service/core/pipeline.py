"""Pipeline wrapper for nohiki-ml-core integration."""

from __future__ import annotations

from functools import cache

from nohiki_ml_core.pipeline import MLEncodingPipeline
from nohiki_observability import get_logger

from ml_compute_service.core.config import get_manifest

logger = get_logger(__name__)


@cache
def get_encoding_pipeline() -> MLEncodingPipeline:
    """Get the encoding pipeline singleton.

    Lazily initializes the pipeline with SemanticRepresentationManifest.
    All embeddings returned inline - Qdrant is canonical store via Kafka sink.
    """
    manifest = get_manifest()

    logger.info(
        "Initializing ML encoding pipeline",
        jobs_version=manifest.collections.jobs.version,
        profiles_version=manifest.collections.profiles.version,
        skills_version=manifest.collections.skills.version,
        model_id=manifest.late_interaction.model_id,
    )

    pipeline = MLEncodingPipeline(manifest=manifest)

    logger.info("ML encoding pipeline ready")

    return pipeline


def reset_pipeline() -> None:
    """Reset the pipeline singleton (for testing)."""
    get_encoding_pipeline.cache_clear()
