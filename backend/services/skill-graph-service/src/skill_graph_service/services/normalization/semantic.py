"""Semantic skill matching using vector similarity.

Evaluates Qdrant search results and determines match confidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nohiki.skill.v1 import CandidateSkill
from nohiki_observability import get_logger

from skill_graph_service.services.normalization.models import (
    SkillNormalizationResult,
    build_no_match_result,
    build_semantic_match_result,
    build_uncertain_result,
)
from skill_graph_service.services.normalization.ports import SkillSearchMatch

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = get_logger(__name__)


def count_matches_above_threshold(matches: Sequence[SkillSearchMatch], threshold: float) -> int:
    """Count how many matches are at or above the threshold."""
    return sum(1 for m in matches if m.score >= threshold)


def build_candidate_list(matches: Sequence[SkillSearchMatch]) -> list[CandidateSkill]:
    """Build candidate skill list from skill search results.

    All payload fields are validated at match construction time, so we
    access them directly without fallback.
    """
    return [
        CandidateSkill(
            skill_id=m.skill_id,
            skill_name=m.name,
            similarity_score=m.score,
            description=m.description,
        )
        for m in matches
    ]


def evaluate_semantic_matches(
    normalized: str,
    matches: Sequence[SkillSearchMatch],
    auto_match_threshold: float,
) -> SkillNormalizationResult:
    """Evaluate semantic matches and return the appropriate result.

    Returns AUTO_MATCH if exactly one candidate passes the threshold,
    UNCERTAIN if multiple pass (ambiguous), or UNCERTAIN with lower-confidence
    candidates if none pass the auto-match threshold.

    Args:
        normalized: Lowercase normalized skill text.
        matches: Skill search results sorted by score descending.
        auto_match_threshold: Score threshold for automatic matching.

    Returns:
        SkillNormalizationResult for this skill.

    """
    if not matches:
        return build_no_match_result()

    top_score = matches[0].score

    if top_score >= auto_match_threshold:
        above_threshold = count_matches_above_threshold(matches, auto_match_threshold)

        if above_threshold > 1:
            logger.warning(
                "Multiple candidates above auto-match threshold -- deferring to LLM",
                skill=normalized,
                above_threshold_count=above_threshold,
                top_score=top_score,
            )
            return build_uncertain_result(build_candidate_list(matches), top_score)

        top_match = matches[0]
        canonical_name = top_match.name or normalized
        logger.debug(
            "Skill matched via high semantic similarity",
            skill=normalized,
            matched=canonical_name,
            score=top_score,
        )
        return build_semantic_match_result(
            top_match.skill_id,
            canonical_name,
            top_score,
        )

    logger.debug(
        "Skill requires LLM clarification",
        skill=normalized,
        top_score=top_score,
        candidate_count=len(matches),
    )
    return build_uncertain_result(build_candidate_list(matches), top_score)
