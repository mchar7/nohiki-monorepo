"""Embedding publisher configuration for skill-graph-service."""

from __future__ import annotations

from functools import cache

from nohiki.ml.v1 import EntityType
from nohiki_embedding_client import EmbeddingPublisher
from nohiki_kafka_client import Topics

from skill_graph_service.core.config import get_manifest, get_settings


@cache
def get_batch_embedding_publisher() -> EmbeddingPublisher:
    """Get singleton embedding publisher for batch skill embedding operations.

    Batch embedding amortises per-skill cost for operations that vectorise
    many skills at once. The callback topic is owned by this service so that
    the response is routed back to the correct consumer group.

    Returns:
        EmbeddingPublisher configured for batch SKILL embedding.

    """
    manifest = get_manifest()
    collection_version = manifest.get_entity_version(EntityType.SKILL)
    return EmbeddingPublisher(
        callback_topic=Topics.SKILL_BATCH_EMBEDDING_CALLBACK,
        service_name=get_settings().service_name,
        collection_version=collection_version,
    )


@cache
def get_normalization_embedding_publisher() -> EmbeddingPublisher:
    """Get singleton embedding publisher for skill normalisation semantic matching.

    A separate callback topic is used so that normalisation embedding callbacks
    are routed to the normalisation handler independently of bootstrap batch
    callbacks, keeping the two flows isolated.

    Returns:
        EmbeddingPublisher configured for normalisation batch embedding.

    """
    manifest = get_manifest()
    collection_version = manifest.get_entity_version(EntityType.SKILL)
    return EmbeddingPublisher(
        callback_topic=Topics.SKILL_NORMALIZATION_EMBEDDING_CALLBACK,
        service_name=get_settings().service_name,
        collection_version=collection_version,
    )


@cache
def get_skill_embedding_publisher() -> EmbeddingPublisher:
    """Get singleton embedding publisher for newly created skill nodes.

    Single-item embedding is used because skill creation is infrequent and
    does not justify the overhead of a batch request.

    Returns:
        EmbeddingPublisher configured for single SKILL embedding.

    """
    manifest = get_manifest()
    collection_version = manifest.get_entity_version(EntityType.SKILL)
    return EmbeddingPublisher(
        callback_topic=Topics.SKILL_EMBEDDING_CALLBACK,
        service_name=get_settings().service_name,
        collection_version=collection_version,
    )
