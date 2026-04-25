"""Unit tests for normalization codec (serialization/deserialization)."""

from __future__ import annotations

import uuid

import pytest
from nohiki.skill.v1 import MatchConfidence, SkillMatchType
from skill_graph_service.services.normalization.codec import (
    deserialize_deterministic_match_result,
    deserialize_skill_result,
    serialize_skill_result,
)
from skill_graph_service.services.normalization.models import (
    NormalizationEmbeddingState,
    SkillNormalizationResult,
)


class TestSerializeSkillResult:
    """Tests for serialize_skill_result."""

    def test_serializes_confident_result(self) -> None:
        skill_id = uuid.uuid4()
        result = SkillNormalizationResult(
            canonical_id=skill_id,
            canonical_name="python",
            match_type=SkillMatchType.EXACT,
            confidence=MatchConfidence.CONFIDENT,
            similarity_score=1.0,
        )

        serialized = serialize_skill_result(result)

        assert serialized["canonical_id"] == str(skill_id)
        assert serialized["canonical_name"] == "python"
        assert serialized["match_type"] == "EXACT"
        assert serialized["confidence"] == "CONFIDENT"
        assert serialized["similarity_score"] == pytest.approx(1.0)

    def test_serializes_no_match_result(self) -> None:
        result = SkillNormalizationResult(
            canonical_id=None,
            canonical_name=None,
            match_type=SkillMatchType.NEW,
            confidence=MatchConfidence.NO_MATCH,
            similarity_score=0.0,
        )

        serialized = serialize_skill_result(result)

        assert serialized["canonical_id"] is None
        assert serialized["canonical_name"] is None


class TestDeserializeSkillResult:
    """Tests for deserialize_skill_result."""

    def test_deserializes_confident_result(self) -> None:
        skill_id = uuid.uuid4()
        data = {
            "canonical_id": str(skill_id),
            "canonical_name": "python",
            "match_type": "EXACT",
            "confidence": "CONFIDENT",
            "similarity_score": 1.0,
        }

        result = deserialize_skill_result(data)

        assert result.canonical_id == skill_id
        assert result.canonical_name == "python"
        assert result.match_type == SkillMatchType.EXACT
        assert result.confidence == MatchConfidence.CONFIDENT

    def test_deserializes_no_match_result(self) -> None:
        data = {
            "canonical_id": None,
            "canonical_name": None,
            "match_type": "NEW",
            "confidence": "NO_MATCH",
            "similarity_score": 0.0,
        }

        result = deserialize_skill_result(data)

        assert result.canonical_id is None
        assert result.confidence == MatchConfidence.NO_MATCH


class TestDeserializeDeterministicMatchResult:
    """Tests for deserialize_deterministic_match_result."""

    def test_reconstructs_from_state(self) -> None:
        skill_id = uuid.uuid4()
        state = NormalizationEmbeddingState(
            requester_operation_id="op-123",
            requester_callback_topic="test.callback",
            requester_caller_context_b64="YWJj",
            requester_attributes={},
            raw_skills=["python", "java", "obscure"],
            matched_results_by_pos={
                "0": {
                    "canonical_id": str(skill_id),
                    "canonical_name": "python",
                    "match_type": "EXACT",
                    "confidence": "CONFIDENT",
                    "similarity_score": 1.0,
                }
            },
            unmatched_skill_pairs=[[1, "java"], [2, "obscure"]],
            collection_version="v1",
            industry_hint=None,
        )

        result = deserialize_deterministic_match_result(state)

        assert result.all_matched is False
        assert len(result.unmatched) == 2
        assert len(result.skill_results) == 3

        matched = [r for r in result.skill_results if r[2] is not None]
        assert len(matched) == 1
        match_result = matched[0][2]
        assert match_result is not None
        assert match_result.canonical_id == skill_id


class TestRoundTrip:
    """Round-trip serialization tests."""

    def test_confident_result_round_trip(self) -> None:
        """Serialize and deserialize a confident result; assert equality."""
        skill_id = uuid.uuid4()
        original = SkillNormalizationResult(
            canonical_id=skill_id,
            canonical_name="python",
            match_type=SkillMatchType.EXACT,
            confidence=MatchConfidence.CONFIDENT,
            similarity_score=1.0,
        )

        serialized = serialize_skill_result(original)
        restored = deserialize_skill_result(serialized)

        assert restored == original

    def test_no_match_result_round_trip(self) -> None:
        """Serialize and deserialize a no-match result; assert equality."""
        original = SkillNormalizationResult(
            canonical_id=None,
            canonical_name=None,
            match_type=SkillMatchType.NEW,
            confidence=MatchConfidence.NO_MATCH,
            similarity_score=0.0,
        )

        serialized = serialize_skill_result(original)
        restored = deserialize_skill_result(serialized)

        assert restored == original
