"""Deterministic skill matching pipeline (exact, alias, jaccard).

Pure matching logic with injected dependencies via ports.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nohiki_observability import get_logger

from skill_graph_service.services.jaccard import find_best_jaccard_match
from skill_graph_service.services.normalization.models import (
    SkillNormalizationResult,
    build_alias_match_result,
    build_exact_match_result,
    build_jaccard_match_result,
)

if TYPE_CHECKING:
    from skill_graph_service.db.models import SkillNode
    from skill_graph_service.services.normalization.ports import SkillCandidate

type ExactMatchFn = Callable[[str], Awaitable[SkillNode | None]]
type AliasMatchFn = Callable[..., Awaitable[SkillNode | None]]

logger = get_logger(__name__)


async def try_exact_match(
    normalized: str,
    *,
    find_exact: ExactMatchFn,
) -> SkillNormalizationResult | None:
    """Try exact case-insensitive match.

    Args:
        normalized: Lowercase normalized skill text.
        find_exact: Async callable that finds skill by exact match.

    Returns:
        SkillNormalizationResult if matched, None otherwise.

    """
    if skill_node := await find_exact(normalized):
        logger.debug("Skill matched via exact lookup", skill=normalized, skill_id=str(skill_node.id))
        return build_exact_match_result(skill_node)
    return None


async def try_alias_match(
    normalized: str,
    *,
    find_alias: AliasMatchFn,
    context_hint: str | None = None,
) -> SkillNormalizationResult | None:
    """Try alias table lookup with optional context disambiguation.

    Args:
        normalized: Lowercase normalized skill text.
        find_alias: Async callable that finds skill by alias.
        context_hint: Optional context (e.g., industry) for disambiguation.

    Returns:
        SkillNormalizationResult if matched, None otherwise.

    """
    skill_node = await find_alias(normalized, context_hint)
    if skill_node:
        logger.debug(
            "Skill matched via alias",
            alias=normalized,
            context=context_hint,
            canonical=skill_node.normalized_text,
            skill_id=str(skill_node.id),
        )
        return build_alias_match_result(skill_node)
    return None


def try_jaccard_match(
    normalized: str,
    candidates: list[SkillCandidate],
    *,
    threshold: float,
) -> SkillNormalizationResult | None:
    """Try Jaccard n-gram similarity match (very conservative threshold).

    Args:
        normalized: Lowercase normalized skill text.
        candidates: List of (skill_id, skill_name) tuples.
        threshold: Minimum Jaccard score for automatic match.

    Returns:
        SkillNormalizationResult if matched above threshold, None otherwise.

    """
    if jaccard_match := find_best_jaccard_match(normalized, candidates, threshold=threshold):
        skill_id, skill_name, jaccard_score = jaccard_match
        logger.debug(
            "Skill matched via Jaccard n-gram",
            skill=normalized,
            matched=skill_name,
            jaccard_score=jaccard_score,
        )
        return build_jaccard_match_result(skill_id, skill_name, jaccard_score)
    return None


@dataclass(frozen=True, slots=True)
class DeterministicMatchContext:
    """Context for deterministic matching cascade."""

    find_exact: ExactMatchFn
    find_alias: AliasMatchFn
    jaccard_candidates: list[SkillCandidate]
    jaccard_threshold: float
    context_hint: str | None = None


async def run_deterministic_cascade(
    normalized: str,
    ctx: DeterministicMatchContext,
) -> SkillNormalizationResult | None:
    """Run exact/alias/jaccard cascade for a single skill.

    Args:
        normalized: Lowercase, stripped skill text.
        ctx: Context containing match functions and configuration.

    Returns:
        SkillNormalizationResult if matched deterministically, None if semantic phase needed.

    """
    if exact := await try_exact_match(normalized, find_exact=ctx.find_exact):
        return exact

    if alias := await try_alias_match(normalized, find_alias=ctx.find_alias, context_hint=ctx.context_hint):
        return alias

    return try_jaccard_match(normalized, ctx.jaccard_candidates, threshold=ctx.jaccard_threshold)
