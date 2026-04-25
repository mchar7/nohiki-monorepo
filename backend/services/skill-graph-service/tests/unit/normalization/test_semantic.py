"""Unit tests for semantic matching evaluation.

These are pure functions that don't require database or Qdrant mocking.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from nohiki.skill.v1 import MatchConfidence, SkillMatchType
from skill_graph_service.services.normalization.ports import SkillSearchMatch
from skill_graph_service.services.normalization.semantic import (
    build_candidate_list,
    count_matches_above_threshold,
    evaluate_semantic_matches,
)


class TestCountMatchesAboveThreshold:
    """Tests for count_matches_above_threshold helper."""

    def test_all_above(self) -> None:
        matches = [MagicMock(score=0.9), MagicMock(score=0.85), MagicMock(score=0.8)]
        assert count_matches_above_threshold(matches, 0.75) == 3

    def test_some_above(self) -> None:
        matches = [MagicMock(score=0.9), MagicMock(score=0.8), MagicMock(score=0.7)]
        assert count_matches_above_threshold(matches, 0.85) == 1

    def test_none_above(self) -> None:
        matches = [MagicMock(score=0.7), MagicMock(score=0.6)]
        assert count_matches_above_threshold(matches, 0.9) == 0

    def test_empty_list(self) -> None:
        assert count_matches_above_threshold([], 0.5) == 0


class TestBuildCandidateList:
    """Tests for build_candidate_list helper."""

    def test_builds_candidates_from_matches(self) -> None:
        """Skill matches are constructed with validated payload fields."""
        skill_id = str(uuid.uuid4())
        matches = [
            SkillSearchMatch(
                point_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{skill_id}_label")),
                score=0.85,
                skill_id=skill_id,
                name="Python",
                description="Programming language",
            ),
        ]

        candidates = build_candidate_list(matches)

        assert len(candidates) == 1
        assert candidates[0].skill_id == skill_id
        assert candidates[0].skill_name == "Python"
        assert candidates[0].similarity_score == pytest.approx(0.85)
        assert candidates[0].description == "Programming language"

    def test_empty_matches(self) -> None:
        candidates = build_candidate_list([])
        assert candidates == []


class TestEvaluateSemanticMatches:
    """Tests for evaluate_semantic_matches: the core semantic evaluation logic."""

    def test_no_matches_returns_no_match(self) -> None:
        result = evaluate_semantic_matches("python", [], auto_match_threshold=0.85)

        assert result.confidence == MatchConfidence.NO_MATCH
        assert result.similarity_score == 0.0

    def test_single_match_above_threshold_returns_auto_match(self) -> None:
        skill_id = str(uuid.uuid4())
        matches = [
            SkillSearchMatch(
                point_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{skill_id}_label")),
                score=0.9,
                skill_id=skill_id,
                name="Python",
                description="",
            ),
        ]

        result = evaluate_semantic_matches("python", matches, auto_match_threshold=0.85)

        assert result.confidence == MatchConfidence.AUTO_MATCH
        assert result.match_type == SkillMatchType.SEMANTIC
        assert result.canonical_id == uuid.UUID(skill_id)
        assert result.similarity_score == pytest.approx(0.9)

    def test_multiple_above_threshold_returns_uncertain(self) -> None:
        skill1 = str(uuid.uuid4())
        skill2 = str(uuid.uuid4())
        matches = [
            SkillSearchMatch(
                point_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{skill1}_label")),
                score=0.9,
                skill_id=skill1,
                name="Python",
                description="",
            ),
            SkillSearchMatch(
                point_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{skill2}_label")),
                score=0.88,
                skill_id=skill2,
                name="Python3",
                description="",
            ),
        ]

        result = evaluate_semantic_matches("python", matches, auto_match_threshold=0.85)

        assert result.confidence == MatchConfidence.UNCERTAIN
        assert result.candidates is not None
        assert len(result.candidates) == 2

    def test_below_threshold_returns_uncertain_with_candidates(self) -> None:
        skill_id = str(uuid.uuid4())
        matches = [
            SkillSearchMatch(
                point_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{skill_id}_label")),
                score=0.7,
                skill_id=skill_id,
                name="Python",
                description="",
            ),
        ]

        result = evaluate_semantic_matches("python", matches, auto_match_threshold=0.85)

        assert result.confidence == MatchConfidence.UNCERTAIN
        assert result.candidates is not None
        assert len(result.candidates) == 1
        assert result.similarity_score == pytest.approx(0.7)
