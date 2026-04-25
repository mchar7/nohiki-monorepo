"""Serialization and deserialization for normalization state transfer.

Handles encoding/decoding of normalization results for ECST callback payloads.
"""

from __future__ import annotations

from uuid import UUID

from nohiki.skill.v1 import MatchConfidence, SkillMatchType

from skill_graph_service.services.normalization.models import (
    DeterministicMatchResult,
    NormalizationEmbeddingState,
    SkillNormalizationResult,
)


def serialize_skill_result(result: SkillNormalizationResult) -> dict:
    """Serialize an internal SkillNormalizationResult to a JSON-safe dict."""
    return {
        "canonical_id": str(result.canonical_id) if result.canonical_id else None,
        "canonical_name": result.canonical_name,
        "confidence": result.confidence.name,
        "match_type": result.match_type.name,
        "similarity_score": result.similarity_score,
    }


def deserialize_skill_result(d: dict) -> SkillNormalizationResult:
    """Deserialize a JSON dict back to an internal SkillNormalizationResult."""
    canonical_id_str: str | None = d.get("canonical_id")
    return SkillNormalizationResult(
        canonical_id=UUID(canonical_id_str) if canonical_id_str else None,
        canonical_name=d.get("canonical_name"),
        confidence=MatchConfidence[d["confidence"]],
        match_type=SkillMatchType[d["match_type"]],
        similarity_score=d["similarity_score"],
    )


def deserialize_deterministic_match_result(
    state: NormalizationEmbeddingState,
) -> DeterministicMatchResult:
    """Reconstruct DeterministicMatchResult from serialized NormalizationEmbeddingState.

    Restores the deterministic match data for the semantic Qdrant search callback.

    Args:
        state: Deserialized ECST state from caller_context.

    Returns:
        DeterministicMatchResult with matched and unmatched entries restored.

    """
    skill_results: list[tuple[int, str, SkillNormalizationResult | None]] = []

    for pos_str, result_dict in state.matched_results_by_pos.items():
        pos = int(pos_str)
        skill_results.append((pos, state.raw_skills[pos], deserialize_skill_result(result_dict)))

    for pair in state.unmatched_skill_pairs:
        pos = int(pair[0])
        skill_results.append((pos, state.raw_skills[pos], None))

    skill_results.sort(key=lambda x: x[0])

    return DeterministicMatchResult(
        skill_results=skill_results,
        unmatched=[(int(pair[0]), str(pair[1])) for pair in state.unmatched_skill_pairs],
        all_matched=False,
    )
