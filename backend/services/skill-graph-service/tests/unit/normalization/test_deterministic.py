"""Unit tests for deterministic matching functions."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki.skill.v1 import MatchConfidence, SkillMatchType
from skill_graph_service.db.models import SkillNode
from skill_graph_service.services.normalization.deterministic import (
    DeterministicMatchContext,
    run_deterministic_cascade,
    try_alias_match,
    try_exact_match,
    try_jaccard_match,
)


class TestTryExactMatch:
    """Tests for try_exact_match."""

    @pytest.mark.asyncio
    async def test_returns_result_when_found(self) -> None:
        skill = MagicMock(spec=SkillNode)
        skill.id = uuid.uuid4()
        skill.normalized_text = "python"
        find_exact = AsyncMock(return_value=skill)

        result = await try_exact_match("python", find_exact=find_exact)

        assert result is not None
        assert result.match_type == SkillMatchType.EXACT
        assert result.confidence == MatchConfidence.CONFIDENT
        assert result.canonical_id == skill.id

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        find_exact = AsyncMock(return_value=None)

        result = await try_exact_match("unknown", find_exact=find_exact)

        assert result is None


class TestTryAliasMatch:
    """Tests for try_alias_match."""

    @pytest.mark.asyncio
    async def test_returns_result_when_found(self) -> None:
        skill = MagicMock(spec=SkillNode)
        skill.id = uuid.uuid4()
        skill.normalized_text = "python"
        find_alias = AsyncMock(return_value=skill)

        result = await try_alias_match("py", find_alias=find_alias)

        assert result is not None
        assert result.match_type == SkillMatchType.ALIAS
        assert result.confidence == MatchConfidence.CONFIDENT

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        find_alias = AsyncMock(return_value=None)

        result = await try_alias_match("unknown", find_alias=find_alias)

        assert result is None

    @pytest.mark.asyncio
    async def test_passes_context_hint(self) -> None:
        find_alias = AsyncMock(return_value=None)

        await try_alias_match("py", find_alias=find_alias, context_hint="tech")

        find_alias.assert_called_once_with("py", "tech")


class TestTryJaccardMatch:
    """Tests for try_jaccard_match."""

    def test_returns_result_when_match_found(self) -> None:
        skill_id = str(uuid.uuid4())
        candidates = [(skill_id, "python")]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "skill_graph_service.services.normalization.deterministic.find_best_jaccard_match",
                MagicMock(return_value=(skill_id, "python", 0.95)),
            )
            result = try_jaccard_match("pythn", candidates, threshold=0.92)

        assert result is not None
        assert result.match_type == SkillMatchType.JACCARD
        assert result.similarity_score == pytest.approx(0.95)

    def test_returns_none_when_no_match(self) -> None:
        candidates = [(str(uuid.uuid4()), "completely_different")]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "skill_graph_service.services.normalization.deterministic.find_best_jaccard_match",
                MagicMock(return_value=None),
            )
            result = try_jaccard_match("python", candidates, threshold=0.92)

        assert result is None


class TestRunDeterministicCascade:
    """Tests for run_deterministic_cascade: the cascade orchestrator."""

    @pytest.mark.asyncio
    async def test_returns_exact_match_first(self) -> None:
        skill = MagicMock(spec=SkillNode)
        skill.id = uuid.uuid4()
        skill.normalized_text = "python"

        ctx = DeterministicMatchContext(
            find_exact=AsyncMock(return_value=skill),
            find_alias=AsyncMock(return_value=None),
            jaccard_candidates=[],
            jaccard_threshold=0.92,
        )

        result = await run_deterministic_cascade("python", ctx)

        assert result is not None
        assert result.match_type == SkillMatchType.EXACT

    @pytest.mark.asyncio
    async def test_falls_back_to_alias(self) -> None:
        skill = MagicMock(spec=SkillNode)
        skill.id = uuid.uuid4()
        skill.normalized_text = "python"

        ctx = DeterministicMatchContext(
            find_exact=AsyncMock(return_value=None),
            find_alias=AsyncMock(return_value=skill),
            jaccard_candidates=[],
            jaccard_threshold=0.92,
        )

        result = await run_deterministic_cascade("py", ctx)

        assert result is not None
        assert result.match_type == SkillMatchType.ALIAS

    @pytest.mark.asyncio
    async def test_falls_back_to_jaccard(self) -> None:
        skill_id = str(uuid.uuid4())

        ctx = DeterministicMatchContext(
            find_exact=AsyncMock(return_value=None),
            find_alias=AsyncMock(return_value=None),
            jaccard_candidates=[(skill_id, "python")],
            jaccard_threshold=0.92,
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "skill_graph_service.services.normalization.deterministic.find_best_jaccard_match",
                MagicMock(return_value=(skill_id, "python", 0.95)),
            )
            result = await run_deterministic_cascade("pythn", ctx)

        assert result is not None
        assert result.match_type == SkillMatchType.JACCARD

    @pytest.mark.asyncio
    async def test_returns_none_when_all_fail(self) -> None:
        ctx = DeterministicMatchContext(
            find_exact=AsyncMock(return_value=None),
            find_alias=AsyncMock(return_value=None),
            jaccard_candidates=[],
            jaccard_threshold=0.92,
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "skill_graph_service.services.normalization.deterministic.find_best_jaccard_match",
                MagicMock(return_value=None),
            )
            result = await run_deterministic_cascade("unknown", ctx)

        assert result is None
