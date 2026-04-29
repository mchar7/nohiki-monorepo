"""Skill normalization integration for user-pref-service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nohiki.common.v1 import CommandHeader
from nohiki.skill.v1 import SkillNormalizationRequested
from nohiki_db_utils import create_event_metadata
from nohiki_kafka_client import Topics
from nohiki_observability import get_logger
from uuid_utils.compat import uuid7

from user_pref_service.core.config import get_settings
from user_pref_service.core.embedding import PrefEmbeddingState
from user_pref_service.core.kafka import kafka_client

if TYPE_CHECKING:
    from uuid import UUID

logger = get_logger(__name__)


async def request_skill_normalization(
    canonical_skill_ids: list[str],
    profile_id: UUID,
    correlation_id: str,
    *,
    action: str = "create",
    semantic_generation: int = 0,
) -> str:
    """Request skill normalization via async callback to skill-graph-service.

    Profile context is carried in the CommandHeader.caller_context bytes field
    using PrefEmbeddingState, which skill-graph-service echoes back in
    SkillNormalizationCallback, allowing the callback handler to identify the
    target profile without any DB lookups.

    Args:
        canonical_skill_ids: Canonical skill UUIDs to resolve and aggregate.
        profile_id: Target profile ID.
        correlation_id: Correlation ID for tracing.
        action: Lifecycle action ("create" or "update") for event publishing.
        semantic_generation: Persisted semantic generation expected by the callback.

    Returns:
        The operation_id for this request.

    """
    settings = get_settings()
    operation_id = str(uuid7())
    state = PrefEmbeddingState(pref_id=str(profile_id), action=action, semantic_generation=semantic_generation)

    await kafka_client.publish(
        Topics.SKILL_NORMALIZATION_REQUESTED,
        SkillNormalizationRequested(
            metadata=create_event_metadata(settings.service_name, correlation_id),
            command=CommandHeader(
                operation_id=operation_id,
                callback_topic=Topics.USER_PREF_SKILL_CALLBACK,
                caller_context=state.to_bytes(),
            ),
            canonical_skill_ids=canonical_skill_ids,
        ),
    )

    logger.info(
        "Skill normalization requested",
        operation_id=operation_id,
        profile_id=str(profile_id),
        skill_count=len(canonical_skill_ids),
    )
    return operation_id
