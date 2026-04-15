"""Embedding publisher configuration for job-ingest-enrichment-service."""

from functools import cache

from job_ingest_enrichment_service.core.config import get_manifest, get_settings
from nohiki.ml.v1 import EntityType
from nohiki_embedding_client import EmbeddingPublisher
from nohiki_kafka_client import Topics


@cache
def get_embedding_publisher() -> EmbeddingPublisher:
    """Get singleton embedding publisher instance.

    Returns:
        Configured EmbeddingPublisher for job-ingest-enrichment-service.

    """
    manifest = get_manifest()
    return EmbeddingPublisher(
        callback_topic=Topics.JOB_INGEST_ENRICHMENT_EMBEDDING_CALLBACK,
        service_name=get_settings().service_name,
        collection_version=manifest.get_entity_version(EntityType.JOB),
    )
