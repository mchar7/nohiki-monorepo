"""Unit tests for result assembly functions.

Tests the assembly of individual results into batch results.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from nohiki.skill.v1 import CandidateSkill, MatchConfidence, SkillMatchType
from skill_graph_service.db.models import SkillNode
from skill_graph_service.services.normalization.assembly import (
    add_clarification,
    add_confident_match,
    build_result_detail,
    process_result,
)
from skill_graph_service.services.normalization.models import (
    BatchAccumulator,
    SkillNormalizationResult,
    build_exact_match_result,
    build_uncertain_result,
)


class TestBuildResultDetail:
    """Tests for build_result_detail."""

    def test_builds_detail_from_result(self) -> None:
        skill_id = uuid.uuid4()
        result = SkillNormalizationResult(
            canonical_id=skill_id,
            canonical_name="python",
            match_type=SkillMatchType.EXACT,
            confidence=MatchConfidence.CONFIDENT,
            similarity_score=1.0,
        )

        detail = build_result_detail("Python", position=2, result=result)

        assert detail.raw_skill == "Python"
        assert detail.position == 2
        assert detail.confidence == MatchConfidence.CONFIDENT
        assert detail.canonical_skill_id == str(skill_id)
        assert detail.canonical_skill_name == "python"
        assert detail.similarity_score == pytest.approx(1.0)
        assert detail.match_type == SkillMatchType.EXACT


class TestAddClarification:
    """Tests for add_clarification."""

    def test_adds_clarification_for_uncertain_result(self) -> None:
        acc = BatchAccumulator()
        candidates = [CandidateSkill(skill_id="1", skill_name="Python", similarity_score=0.7)]
        result = build_uncertain_result(candidates, top_score=0.7)

        add_clarification(acc, "pythn", position=0, result=result)

        assert len(acc.clarifications) == 1
        assert acc.clarifications[0].extracted_skill == "pythn"
        assert acc.clarifications[0].position == 0
        assert len(acc.clarifications[0].candidate_skills) == 1


class TestAddConfidentMatch:
    """Tests for add_confident_match."""

    def test_adds_match_to_accumulator(self) -> None:
        acc = BatchAccumulator()
        skill = MagicMock(spec=SkillNode)
        skill.id = uuid.uuid4()
        skill.normalized_text = "python"
        result = build_exact_match_result(skill)

        add_confident_match(acc, result)

        assert len(acc.matches) == 1
        assert acc.matches[0].canonical_id == str(skill.id)
        assert acc.matches[0].canonical_name == "python"
        assert str(skill.id) in acc.seen_ids
        assert "python" in acc.canonical_names

    def test_deduplicates_by_canonical_id(self) -> None:
        acc = BatchAccumulator()
        skill = MagicMock(spec=SkillNode)
        skill.id = uuid.uuid4()
        skill.normalized_text = "python"
        result = build_exact_match_result(skill)

        add_confident_match(acc, result)
        add_confident_match(acc, result)

        assert len(acc.matches) == 1


class TestProcessResult:
    """Tests for process_result: main result processing function."""

    def test_processes_confident_match(self) -> None:
        acc = BatchAccumulator()
        skill = MagicMock(spec=SkillNode)
        skill.id = uuid.uuid4()
        skill.normalized_text = "python"
        result = build_exact_match_result(skill)

        process_result(acc, "Python", position=0, result=result)

        assert len(acc.results) == 1
        assert len(acc.matches) == 1
        assert len(acc.clarifications) == 0

    def test_processes_uncertain_match(self) -> None:
        acc = BatchAccumulator()
        candidates = [CandidateSkill(skill_id="1", skill_name="Python", similarity_score=0.7)]
        result = build_uncertain_result(candidates, top_score=0.7)

        process_result(acc, "pythn", position=0, result=result)

        assert len(acc.results) == 1
        assert len(acc.matches) == 0
        assert len(acc.clarifications) == 1
