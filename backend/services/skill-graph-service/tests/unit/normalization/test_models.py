"""Unit tests for normalization models and result builders.

These are pure functions that don't require any mocking.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from nohiki.skill.v1 import CandidateSkill, MatchConfidence, SkillMatchType
from skill_graph_service.db.models import SkillNode
from skill_graph_service.services.normalization.models import (
    BatchAccumulator,
    DeterministicMatchResult,
    NormalizationEmbeddingState,
    SkillNormalizationResult,
    build_alias_match_result,
    build_exact_match_result,
    build_jaccard_match_result,
    build_no_match_result,
    build_semantic_match_result,
    build_uncertain_result,
)


class TestSkillNormalizationResult:
    """Tests for SkillNormalizationResult dataclass."""

    def test_create_with_canonical_match(self) -> None:
        skill_id = uuid.uuid4()
        result = SkillNormalizationResult(
            canonical_id=skill_id,
            canonical_name="python",
            match_type=SkillMatchType.EXACT,
            confidence=MatchConfidence.CONFIDENT,
            similarity_score=1.0,
        )
        assert result.canonical_id == skill_id
        assert result.canonical_name == "python"
        assert result.match_type == SkillMatchType.EXACT
        assert result.confidence == MatchConfidence.CONFIDENT
        assert result.similarity_score == 1.0
        assert result.candidates is None

    def test_create_with_candidates(self) -> None:
        candidates = [
            CandidateSkill(skill_id="1", skill_name="Python", similarity_score=0.9),
            CandidateSkill(skill_id="2", skill_name="PyTorch", similarity_score=0.8),
        ]
        result = SkillNormalizationResult(
            canonical_id=None,
            canonical_name=None,
            match_type=SkillMatchType.UNSPECIFIED,
            confidence=MatchConfidence.UNCERTAIN,
            similarity_score=0.9,
            candidates=candidates,
        )
        assert result.canonical_id is None
        assert result.candidates is not None
        assert len(result.candidates) == 2


class TestResultBuilders:
    """Tests for result builder pure functions."""

    def test_build_exact_match_result(self) -> None:
        skill = MagicMock(spec=SkillNode)
        skill.id = uuid.uuid4()
        skill.normalized_text = "python"

        result = build_exact_match_result(skill)

        assert result.canonical_id == skill.id
        assert result.canonical_name == "python"
        assert result.match_type == SkillMatchType.EXACT
        assert result.confidence == MatchConfidence.CONFIDENT
        assert result.similarity_score == 1.0

    def test_build_alias_match_result(self) -> None:
        skill = MagicMock(spec=SkillNode)
        skill.id = uuid.uuid4()
        skill.normalized_text = "python"

        result = build_alias_match_result(skill)

        assert result.canonical_id == skill.id
        assert result.match_type == SkillMatchType.ALIAS
        assert result.confidence == MatchConfidence.CONFIDENT
        assert result.similarity_score == 1.0

    def test_build_jaccard_match_result(self) -> None:
        skill_id = str(uuid.uuid4())

        result = build_jaccard_match_result(skill_id, "python", 0.95)

        assert result.canonical_id == uuid.UUID(skill_id)
        assert result.canonical_name == "python"
        assert result.match_type == SkillMatchType.JACCARD
        assert result.confidence == MatchConfidence.AUTO_MATCH
        assert result.similarity_score == pytest.approx(0.95)

    def test_build_semantic_match_result(self) -> None:
        skill_id = str(uuid.uuid4())

        result = build_semantic_match_result(skill_id, "python", 0.88)

        assert result.canonical_id == uuid.UUID(skill_id)
        assert result.canonical_name == "python"
        assert result.match_type == SkillMatchType.SEMANTIC
        assert result.confidence == MatchConfidence.AUTO_MATCH
        assert result.similarity_score == pytest.approx(0.88)

    def test_build_uncertain_result(self) -> None:
        candidates = [
            CandidateSkill(skill_id="1", skill_name="Python", similarity_score=0.7),
        ]

        result = build_uncertain_result(candidates, top_score=0.7)

        assert result.canonical_id is None
        assert result.canonical_name is None
        assert result.match_type == SkillMatchType.UNSPECIFIED
        assert result.confidence == MatchConfidence.UNCERTAIN
        assert result.similarity_score == pytest.approx(0.7)
        assert result.candidates is not None
        assert len(result.candidates) == 1

    def test_build_no_match_result(self) -> None:
        result = build_no_match_result()

        assert result.canonical_id is None
        assert result.canonical_name is None
        assert result.match_type == SkillMatchType.NEW
        assert result.confidence == MatchConfidence.NO_MATCH
        assert result.similarity_score == pytest.approx(0.0)


class TestBatchAccumulator:
    """Tests for BatchAccumulator."""

    def test_create_empty(self) -> None:
        acc = BatchAccumulator()

        assert acc.matches == []
        assert acc.results == []
        assert acc.clarifications == []
        assert acc.seen_ids == set()
        assert acc.canonical_names == []
        assert acc.canonical_ids == []


class TestDeterministicMatchResult:
    """Tests for DeterministicMatchResult dataclass."""

    def test_all_matched(self) -> None:
        result = DeterministicMatchResult(
            skill_results=[(0, "python", MagicMock())],
            unmatched=[],
            all_matched=True,
        )
        assert result.all_matched is True
        assert len(result.unmatched) == 0

    def test_partial_match(self) -> None:
        result = DeterministicMatchResult(
            skill_results=[(0, "python", MagicMock()), (1, "obscure", None)],
            unmatched=[(1, "obscure")],
            all_matched=False,
        )
        assert result.all_matched is False
        assert len(result.unmatched) == 1


class TestNormalizationEmbeddingState:
    """Tests for NormalizationEmbeddingState ECST serialization."""

    def test_round_trip_serialization(self) -> None:
        state = NormalizationEmbeddingState(
            requester_operation_id="op-123",
            requester_callback_topic="test.callback",
            requester_caller_context_b64="YWJj",
            requester_attributes={"key": "value"},
            raw_skills=["python", "java"],
            matched_results_by_pos={"0": {"canonical_id": "abc"}},
            unmatched_skill_pairs=[[1, "java"]],
            collection_version="v1",
            industry_hint="tech",
        )

        serialized = state.to_bytes()
        restored = NormalizationEmbeddingState.from_bytes(serialized)

        assert restored.requester_operation_id == state.requester_operation_id
        assert restored.requester_callback_topic == state.requester_callback_topic
        assert restored.raw_skills == state.raw_skills
        assert restored.collection_version == state.collection_version
        assert restored.industry_hint == state.industry_hint
