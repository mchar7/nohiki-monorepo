"""Result assembly for batch normalization.

Combines deterministic and semantic match results into final output.
"""

from __future__ import annotations

from nohiki.skill.v1 import (
    CanonicalSkillMatch,
    MatchConfidence,
    SkillClarificationNeeded,
    SkillNormalizationResultDetail,
)

from skill_graph_service.services.normalization.models import (
    BatchAccumulator,
    SkillNormalizationResult,
)


def build_result_detail(
    raw: str,
    position: int,
    result: SkillNormalizationResult,
) -> SkillNormalizationResultDetail:
    """Build a result detail from a single normalization result."""
    return SkillNormalizationResultDetail(
        raw_skill=raw,
        position=position,
        confidence=result.confidence,
        canonical_skill_id=str(result.canonical_id) if result.canonical_id else None,
        canonical_skill_name=result.canonical_name,
        similarity_score=result.similarity_score,
        match_type=result.match_type,
    )


def add_clarification(
    acc: BatchAccumulator,
    raw: str,
    position: int,
    result: SkillNormalizationResult,
) -> None:
    """Add an uncertain result to clarifications."""
    acc.clarifications.append(
        SkillClarificationNeeded(
            extracted_skill=raw,
            position=position,
            candidate_skills=result.candidates or [],
        )
    )


def add_confident_match(
    acc: BatchAccumulator,
    result: SkillNormalizationResult,
) -> None:
    """Add a confident/auto-matched result to matches."""
    canonical_id_str = str(result.canonical_id)

    if canonical_id_str in acc.seen_ids:
        return

    acc.seen_ids.add(canonical_id_str)
    acc.matches.append(
        CanonicalSkillMatch(
            canonical_id=canonical_id_str,
            canonical_name=result.canonical_name or "",
            match_type=result.match_type,
            similarity_score=result.similarity_score,
        )
    )

    if result.canonical_name:
        acc.canonical_names.append(result.canonical_name)
    acc.canonical_ids.append(canonical_id_str)


def process_result(
    acc: BatchAccumulator,
    raw: str,
    position: int,
    result: SkillNormalizationResult,
) -> None:
    """Process a single normalization result into the accumulator."""
    acc.results.append(build_result_detail(raw, position, result))

    if result.confidence == MatchConfidence.UNCERTAIN and result.candidates:
        add_clarification(acc, raw, position, result)
    elif result.canonical_id:
        add_confident_match(acc, result)
