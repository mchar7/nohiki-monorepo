"""Top-level orchestration workflows for skill normalization.

These are the public entry points that handlers call. They coordinate
the deterministic and semantic matching pipelines using injected adapters.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID

from nohiki.ml.v1 import EmbeddingType, EntityType
from nohiki.skill.v1 import (
    CanonicalSkillMatch,
    JobSkillRequirement,
    MatchConfidence,
    SkillMatchType,
    SkillNormalizationResultDetail,
    SkillProficiencyLevel,
)
from nohiki_common_exceptions import ValidationError
from nohiki_observability import get_logger
from sqlalchemy import func, select

from skill_graph_service.core.config import get_manifest, get_settings
from skill_graph_service.db.models import SkillNode
from skill_graph_service.seeding.normalizer import normalize_skill_text
from skill_graph_service.services.alias_service import resolve_alias
from skill_graph_service.services.normalization.aggregation import compute_aggregated_embedding
from skill_graph_service.services.normalization.assembly import process_result
from skill_graph_service.services.normalization.deterministic import (
    DeterministicMatchContext,
    run_deterministic_cascade,
)
from skill_graph_service.services.normalization.models import (
    BatchAccumulator,
    BatchNormalizationResult,
    DeterministicMatchResult,
    RawSkillMetadata,
    SkillNormalizationResult,
    build_no_match_result,
)
from skill_graph_service.services.normalization.semantic import evaluate_semantic_matches

if TYPE_CHECKING:
    from nohiki_qdrant_client import QdrantVectorClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from skill_graph_service.services.normalization.ports import SemanticSearchPort

logger = get_logger(__name__)
settings = get_settings()


async def run_deterministic_matching(
    raw_skills: list[str],
    session_factory: async_sessionmaker[AsyncSession],
    *,
    context_hint: str | None = None,
) -> DeterministicMatchResult:
    """Run deterministic skill matching across the input batch (exact/alias/jaccard).

    Runs all skills concurrently with dedicated DB sessions to avoid
    shared-session contention. Returns matched results and identifies
    skills that need semantic vector search.

    Args:
        raw_skills: Raw skill strings from the normalization request.
        session_factory: Factory for creating per-skill async sessions.
        context_hint: Optional industry hint for alias disambiguation.

    Returns:
        DeterministicMatchResult with per-skill match data and unmatched positions.

    """
    norm_config = settings.normalization

    valid_skills: list[tuple[int, str]] = [
        (i, norm)
        for i, raw in enumerate(raw_skills)
        if (norm := normalize_skill_text(raw)) and len(norm) >= norm_config.min_skill_length
    ]

    if not valid_skills:
        return DeterministicMatchResult(skill_results=[], unmatched=[], all_matched=True)

    unique_normalized_skills = list(dict.fromkeys(norm for _, norm in valid_skills))
    jaccard_candidates = await _load_jaccard_candidates(session_factory)

    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(
                _deterministic_with_session(
                    norm,
                    session_factory,
                    context_hint=context_hint,
                    jaccard_candidates=jaccard_candidates,
                )
            )
            for norm in unique_normalized_skills
        ]

    results_by_normalized = {norm: task.result() for norm, task in zip(unique_normalized_skills, tasks, strict=True)}

    skill_results: list[tuple[int, str, SkillNormalizationResult | None]] = [
        (pos, raw_skills[pos], results_by_normalized[norm]) for pos, norm in valid_skills
    ]
    unmatched: list[tuple[int, str]] = [
        (pos, norm) for pos, norm in valid_skills if results_by_normalized[norm] is None
    ]

    return DeterministicMatchResult(
        skill_results=skill_results,
        unmatched=unmatched,
        all_matched=not bool(unmatched),
    )


async def run_semantic_qdrant_search(
    unmatched: list[tuple[int, str]],
    embedding_results: list,
    qdrant: SemanticSearchPort,
) -> dict[int, SkillNormalizationResult]:
    """Run Qdrant semantic search using pre-computed batch embeddings.

    Called from handle_normalization_embedding_callback after receiving
    BatchEmbeddingCallback with dense embeddings for unmatched skills.

    Args:
        unmatched: List of (original_position, normalized_text) pairs.
        embedding_results: BatchEmbeddingResultItem list from BatchEmbeddingCallback.
        qdrant: Qdrant vector client.

    Returns:
        Dict mapping original_position to SkillNormalizationResult.

    """
    embeddings_by_pos: dict[int, list[float]] = {}
    for item in embedding_results:
        pos_str = item.item_attributes.get("position")
        if pos_str is None:
            continue
        pos = int(pos_str)
        dense_vec = next(
            (e for e in item.embeddings if e.embedding_type == EmbeddingType.DENSE),
            None,
        )
        if dense_vec and dense_vec.dense:
            embeddings_by_pos[pos] = dense_vec.dense.values

    valid_triples: list[tuple[int, str, list[float]]] = [
        (pos, norm, embeddings_by_pos[pos]) for pos, norm in unmatched if pos in embeddings_by_pos
    ]

    if not valid_triples:
        return {}

    manifest = get_manifest()
    norm_config = settings.normalization

    batch_results = await qdrant.search_dense_batch(
        queries=[emb for _, _, emb in valid_triples],
        limit=norm_config.top_n_candidates,
        score_threshold=manifest.dense.normalization.uncertain_min_threshold,
    )

    auto_threshold = manifest.dense.normalization.auto_match_threshold

    return {
        pos: (evaluate_semantic_matches(norm, matches, auto_threshold) if matches else build_no_match_result())
        for (pos, norm, _), matches in zip(valid_triples, batch_results, strict=True)
    }


async def _retrieve_skill_vectors(
    qdrant: QdrantVectorClient,
    point_ids: list[str],
) -> dict[str, list[float]]:
    manifest = get_manifest()
    return await qdrant.retrieve_vectors(
        collection_name=manifest.get_collection_name(EntityType.SKILL),
        point_ids=point_ids,
    )


async def resolve_canonical_skill_ids(
    canonical_ids: list[str],
    session_factory: async_sessionmaker[AsyncSession],
    collection_version: str,
    qdrant: QdrantVectorClient,
) -> BatchNormalizationResult:
    """Resolve canonical IDs in first-seen order, failing when any are absent."""
    ordered_ids = list(dict.fromkeys(canonical_ids))
    parsed_ids = [UUID(skill_id) for skill_id in ordered_ids]
    async with session_factory() as session:
        result = await session.execute(select(SkillNode).where(SkillNode.id.in_(parsed_ids)).limit(len(parsed_ids)))
        nodes_by_id = {node.id: node for node in result.scalars().all()}

    missing_ids = [
        skill_id for skill_id, parsed_id in zip(ordered_ids, parsed_ids, strict=True) if parsed_id not in nodes_by_id
    ]
    if missing_ids:
        msg = f"Canonical skills do not exist: {', '.join(missing_ids)}"
        raise ValidationError(msg)

    details: list[SkillNormalizationResultDetail] = []
    matches: list[CanonicalSkillMatch] = []
    requirements: list[JobSkillRequirement] = []
    for position, (skill_id, parsed_id) in enumerate(zip(ordered_ids, parsed_ids, strict=True)):
        node = nodes_by_id[parsed_id]
        name = node.display_name or node.normalized_text
        matches.append(
            CanonicalSkillMatch(
                canonical_id=skill_id,
                canonical_name=name,
                match_type=SkillMatchType.EXACT,
                similarity_score=1.0,
            )
        )
        details.append(
            SkillNormalizationResultDetail(
                raw_skill=name,
                position=position,
                confidence=MatchConfidence.CONFIDENT,
                canonical_skill_id=skill_id,
                canonical_skill_name=name,
                similarity_score=1.0,
                match_type=SkillMatchType.EXACT,
            )
        )
        requirements.append(
            JobSkillRequirement(
                skill_id=skill_id,
                skill_name=name,
                extraction_confidence=1.0,
            )
        )

    embedding = await compute_aggregated_embedding(
        ordered_ids,
        collection_version,
        retrieve_vectors=lambda point_ids: _retrieve_skill_vectors(qdrant, point_ids),
    )
    return BatchNormalizationResult(
        canonical_skill_ids=ordered_ids,
        matches=matches,
        aggregated_embedding=embedding,
        results=details,
        requires_clarification=False,
        clarifications=[],
        skill_requirements=requirements,
    )


def _build_skill_requirements(
    deterministic_result: DeterministicMatchResult,
    semantic_results: dict[int, SkillNormalizationResult],
    raw_skill_metadata: list[RawSkillMetadata] | None,
) -> list[JobSkillRequirement]:
    """Build one requirement per confident input match, retaining input metadata."""
    metadata_by_position = dict(enumerate(raw_skill_metadata or []))
    requirements: list[JobSkillRequirement] = []
    for position, raw, deterministic_match in deterministic_result.skill_results:
        result = deterministic_match or semantic_results.get(position)
        if (
            result is None
            or result.canonical_id is None
            or result.confidence not in (MatchConfidence.CONFIDENT, MatchConfidence.AUTO_MATCH)
            or not result.canonical_name
        ):
            continue

        _, level_value, is_required = metadata_by_position.get(
            position,
            (raw, int(SkillProficiencyLevel.UNSPECIFIED), False),
        )
        try:
            proficiency_level = SkillProficiencyLevel(level_value)
        except ValueError:
            proficiency_level = SkillProficiencyLevel.UNSPECIFIED
        requirements.append(
            JobSkillRequirement(
                skill_id=str(result.canonical_id),
                skill_name=result.canonical_name,
                proficiency_level=proficiency_level,
                is_required=is_required,
                extraction_confidence=result.similarity_score,
            )
        )
    return requirements


async def assemble_batch_normalization_result(
    deterministic_result: DeterministicMatchResult,
    semantic_results: dict[int, SkillNormalizationResult],
    collection_version: str,
    qdrant: QdrantVectorClient,
    raw_skill_metadata: list[RawSkillMetadata] | None = None,
) -> BatchNormalizationResult:
    """Combine deterministic and semantic match results into a final BatchNormalizationResult."""
    acc = BatchAccumulator()

    for pos, raw, det_result in deterministic_result.skill_results:
        result = det_result or semantic_results.get(pos) or build_no_match_result()
        process_result(acc, raw, pos, result)

    agg_embedding = await compute_aggregated_embedding(
        acc.canonical_ids,
        collection_version,
        retrieve_vectors=lambda point_ids: _retrieve_skill_vectors(qdrant, point_ids),
    )

    return BatchNormalizationResult(
        canonical_skill_ids=[m.canonical_id for m in acc.matches],
        matches=acc.matches,
        aggregated_embedding=agg_embedding,
        results=acc.results,
        requires_clarification=bool(acc.clarifications),
        clarifications=acc.clarifications,
        skill_requirements=_build_skill_requirements(
            deterministic_result,
            semantic_results,
            raw_skill_metadata,
        ),
    )


# Internal Helpers

type SkillCandidate = tuple[str, str]


async def _load_jaccard_candidates(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[SkillCandidate]:
    """Load Jaccard candidate skill corpus once for a normalization batch."""
    norm_config = settings.normalization

    async with session_factory() as session:
        stmt = select(SkillNode.id, SkillNode.normalized_text).limit(norm_config.max_jaccard_candidates)
        result = await session.execute(stmt)

    return [(str(row.id), row.normalized_text) for row in result.fetchall()]


async def _deterministic_with_session(
    normalized: str,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    context_hint: str | None,
    jaccard_candidates: list[SkillCandidate],
) -> SkillNormalizationResult | None:
    """Run deterministic matching using a dedicated database session."""
    norm_config = settings.normalization

    async with session_factory() as session:

        async def find_exact(norm: str) -> SkillNode | None:
            stmt = select(SkillNode).where(func.lower(SkillNode.normalized_text) == norm)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

        async def find_alias(norm: str, hint: str | None) -> SkillNode | None:
            return await resolve_alias(norm, session, context_hint=hint)

        ctx = DeterministicMatchContext(
            find_exact=find_exact,
            find_alias=find_alias,
            jaccard_candidates=jaccard_candidates,
            jaccard_threshold=norm_config.jaccard_auto_match,
            context_hint=context_hint,
        )
        return await run_deterministic_cascade(normalized, ctx)
