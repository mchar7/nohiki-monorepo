"""Domain models and result builders for skill normalization.

Contains DTOs (data transfer objects) for normalization requests/results
and pure factory functions for constructing result objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from nohiki.ml.v1 import EmbeddingVector
from nohiki.skill.v1 import (
    CandidateSkill,
    CanonicalSkillMatch,
    JobSkillRequirement,
    MatchConfidence,
    SkillClarificationNeeded,
    SkillMatchType,
    SkillNormalizationResultDetail,
)
from nohiki_kafka_client import CallbackStateMixin

if TYPE_CHECKING:
    from skill_graph_service.db.models import SkillNode


@dataclass(frozen=True, slots=True)
class SkillNormalizationResult:
    """Result of normalizing a single skill."""

    canonical_id: UUID | None
    canonical_name: str | None
    match_type: SkillMatchType
    confidence: MatchConfidence
    similarity_score: float
    candidates: list[CandidateSkill] | None = None


type RawSkillMetadata = tuple[str, int, bool]


@dataclass(frozen=True, slots=True)
class NormalizationEmbeddingState(CallbackStateMixin):
    """Callback state carrying normalisation context through the embedding pipeline.

    Encoded into the batch embedding command's caller_context so that when
    embeddings arrive asynchronously the full normalisation context can be
    reconstructed without any database lookups.
    """

    requester_operation_id: str
    requester_callback_topic: str
    requester_caller_context_b64: str
    requester_attributes: dict[str, str]
    raw_skills: list[str]
    matched_results_by_pos: dict[str, dict]
    unmatched_skill_pairs: list[list]
    collection_version: str
    industry_hint: str | None
    raw_skill_metadata: list[RawSkillMetadata] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DeterministicMatchResult:
    """Result of deterministic skill matching across the input batch.

    Tracks which skills were matched deterministically and which require
    semantic vector search for disambiguation.
    """

    skill_results: list[tuple[int, str, SkillNormalizationResult | None]]
    unmatched: list[tuple[int, str]]
    all_matched: bool


@dataclass(slots=True)
class BatchNormalizationResult:
    """Complete result of batch skill normalization."""

    canonical_skill_ids: list[str]
    matches: list[CanonicalSkillMatch]
    aggregated_embedding: EmbeddingVector | None
    results: list[SkillNormalizationResultDetail]
    requires_clarification: bool
    clarifications: list[SkillClarificationNeeded]
    skill_requirements: list[JobSkillRequirement] = field(default_factory=list)


@dataclass(slots=True)
class BatchAccumulator:
    """Accumulator for batch normalization processing."""

    matches: list[CanonicalSkillMatch] = field(default_factory=list)
    results: list[SkillNormalizationResultDetail] = field(default_factory=list)
    clarifications: list[SkillClarificationNeeded] = field(default_factory=list)
    seen_ids: set[str] = field(default_factory=set)
    canonical_names: list[str] = field(default_factory=list)
    canonical_ids: list[str] = field(default_factory=list)


# Result Builder Functions (Pure)


def build_exact_match_result(skill_node: SkillNode) -> SkillNormalizationResult:
    """Build result for exact match."""
    return SkillNormalizationResult(
        canonical_id=skill_node.id,
        canonical_name=skill_node.normalized_text,
        match_type=SkillMatchType.EXACT,
        confidence=MatchConfidence.CONFIDENT,
        similarity_score=1.0,
    )


def build_alias_match_result(skill_node: SkillNode) -> SkillNormalizationResult:
    """Build result for alias match."""
    return SkillNormalizationResult(
        canonical_id=skill_node.id,
        canonical_name=skill_node.normalized_text,
        match_type=SkillMatchType.ALIAS,
        confidence=MatchConfidence.CONFIDENT,
        similarity_score=1.0,
    )


def build_jaccard_match_result(
    skill_id: str,
    skill_name: str,
    jaccard_score: float,
) -> SkillNormalizationResult:
    """Build result for Jaccard n-gram match."""
    return SkillNormalizationResult(
        canonical_id=UUID(skill_id),
        canonical_name=skill_name,
        match_type=SkillMatchType.JACCARD,
        confidence=MatchConfidence.AUTO_MATCH,
        similarity_score=jaccard_score,
    )


def build_semantic_match_result(
    skill_id: str,
    skill_name: str,
    score: float,
) -> SkillNormalizationResult:
    """Build result for high-confidence semantic match."""
    return SkillNormalizationResult(
        canonical_id=UUID(skill_id),
        canonical_name=skill_name,
        match_type=SkillMatchType.SEMANTIC,
        confidence=MatchConfidence.AUTO_MATCH,
        similarity_score=score,
    )


def build_uncertain_result(
    candidates: list[CandidateSkill],
    top_score: float,
) -> SkillNormalizationResult:
    """Build result for uncertain match requiring LLM clarification."""
    return SkillNormalizationResult(
        canonical_id=None,
        canonical_name=None,
        match_type=SkillMatchType.UNSPECIFIED,
        confidence=MatchConfidence.UNCERTAIN,
        similarity_score=top_score,
        candidates=candidates,
    )


def build_no_match_result() -> SkillNormalizationResult:
    """Build result for no match found."""
    return SkillNormalizationResult(
        canonical_id=None,
        canonical_name=None,
        match_type=SkillMatchType.NEW,
        confidence=MatchConfidence.NO_MATCH,
        similarity_score=0.0,
    )
