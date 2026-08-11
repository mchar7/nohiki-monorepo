"""Service layer for enrichment persistence.

Persists skill and query embedding data to profiles during the
enrichment callback flow. Profile context is carried via ECST
(PrefEmbeddingState in CommandHeader.caller_context).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from nohiki.ml.v1 import EmbeddingResult, EmbeddingType, EmbeddingVector
from nohiki.skill.v1 import JobSkillRequirement, SkillNormalizationResult, SkillProvenance, UserSkillEntry
from nohiki_observability import get_logger

from user_pref_service.core.embedding import profile_embedding_content_hash
from user_pref_service.services import profile_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from user_pref_service.db.models import SearchPref

logger = get_logger(__name__)


def job_requirement_to_user_skill(req: JobSkillRequirement) -> UserSkillEntry:
    """Convert JobSkillRequirement to UserSkillEntry for user skill tracking."""
    return UserSkillEntry(
        skill_id=req.skill_id,
        skill_name=req.skill_name,
        proficiency=req.proficiency_level,
        provenance=SkillProvenance.USER_DECLARED,
        provenance_confidence=req.extraction_confidence,
    )


def build_user_skills(normalization_result: SkillNormalizationResult) -> list[UserSkillEntry]:
    """Build UserSkillEntry list from skill normalization results in a single pass.

    Args:
        normalization_result: Result from SkillNormalizationCallback.success.

    Returns:
        List of UserSkillEntry proto messages for each normalized skill requirement.

    """
    return [job_requirement_to_user_skill(req) for req in normalization_result.skill_requirements]


async def persist_skill_enrichment(
    db: AsyncSession,
    profile_id: UUID,
    normalization_result: SkillNormalizationResult,
    *,
    expected_generation: int | None = None,
    locked_profile: SearchPref | None = None,
) -> SearchPref | None:
    """Persist full skill normalization results to a profile.

    Stores the dense skills embedding vector, canonical skill IDs, and full
    UserSkillEntry data in the profile row. The UserSkillEntry data is stored
    in user_skills_data (JSONB) so handle_embedding_callback can load it from
    the DB without needing to carry it inline in PrefEmbeddingState (~80 bytes).

    Args:
        db: Active database session.
        profile_id: Target profile ID.
        normalization_result: Full SkillNormalizationResult from skill-graph-service.
        expected_generation: Semantic generation expected by the normalization request, when set.
        locked_profile: Profile already locked by the caller, when available.

    Returns:
        Refreshed profile with updated skill data.

    """
    profile = locked_profile or (
        await profile_service.get_profile_by_id_for_update(db, profile_id)
        if expected_generation is not None
        else await profile_service.get_profile_by_id(db, profile_id)
    )
    if expected_generation is not None and profile.semantic_content_generation != expected_generation:
        return None

    skills_embedding = normalization_result.skills_embedding
    if skills_embedding and skills_embedding.dense:
        profile.user_skills_embedding = list(skills_embedding.dense.values)
        profile.collection_version = normalization_result.collection_version or None

    profile.user_skill_ids = list(normalization_result.canonical_skill_ids)
    profile.user_skills_data = [
        job_requirement_to_user_skill(req).to_dict() for req in normalization_result.skill_requirements
    ]

    await db.flush()
    await db.refresh(profile)
    return profile


def load_user_skills_from_profile(profile: SearchPref) -> list[UserSkillEntry]:
    """Load UserSkillEntry list from a profile's stored user_skills_data JSONB column.

    Args:
        profile: SearchPref model with user_skills_data populated.

    Returns:
        List of UserSkillEntry proto messages, empty if no data stored.

    """
    if not profile.user_skills_data:
        return []
    return [UserSkillEntry.from_dict(d) for d in profile.user_skills_data]


async def _load_query_profile(
    db: AsyncSession,
    profile_or_id: UUID | SearchPref,
    *,
    lock: bool,
) -> SearchPref:
    if not isinstance(profile_or_id, UUID):
        return profile_or_id
    loader = profile_service.get_profile_by_id_for_update if lock else profile_service.get_profile_by_id
    return await loader(db, profile_or_id)


async def persist_query_enrichment(
    db: AsyncSession,
    profile_or_id: UUID | SearchPref,
    result: EmbeddingResult,
    *,
    expected_generation: int | None = None,
    expected_hash: str | None = None,
) -> SearchPref | None:
    """Persist query embedding and retrieval vectors from embedding result.

    Partitions the embedding result in a single pass: the DENSE vector goes to
    the query_embedding column, all other vectors go to query_artifacts_data JSONB.

    Args:
        db: Active database session.
        profile_or_id: Target profile ID, or a profile already locked by the caller.
        result: Embedding result proto from EmbeddingCallback.success.
        expected_generation: Semantic generation expected by the embedding request, when set.
        expected_hash: Semantic text hash expected by the embedding request, when set.


    Returns:
        Refreshed profile with updated embedding data.

    """
    profile = await _load_query_profile(
        db,
        profile_or_id,
        lock=expected_generation is not None or expected_hash is not None,
    )
    if expected_generation is not None and profile.semantic_content_generation != expected_generation:
        return None
    if expected_hash is not None:
        current_hash = profile.semantic_content_hash
        if current_hash is None:
            try:
                current_hash = profile_embedding_content_hash(
                    profile_service.build_profile_embedding_text_from_profile(profile)
                )
            except TypeError, ValueError:
                return None
        if current_hash != expected_hash:
            return None
    profile.collection_version = result.collection_version or None

    dense_vector: EmbeddingVector | None = None
    retrieval_vectors: list[EmbeddingVector] = []
    for emb in result.embeddings:
        if emb.embedding_type == EmbeddingType.DENSE:
            dense_vector = emb
        else:
            retrieval_vectors.append(emb)

    if dense_vector and dense_vector.dense:
        profile.query_embedding = list(dense_vector.dense.values)

    if retrieval_vectors:
        profile.query_artifacts_data = [emb.to_dict() for emb in retrieval_vectors]

    await db.flush()
    await db.refresh(profile)
    return profile
