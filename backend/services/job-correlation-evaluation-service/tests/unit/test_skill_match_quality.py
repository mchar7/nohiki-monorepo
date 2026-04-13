"""Unit tests for advanced skill match quality scoring."""

from __future__ import annotations

import pytest
from job_correlation_evaluation_service.services.scoring.features.skill_match_quality import (
    PROFICIENCY_WEIGHTS,
    PROVENANCE_WEIGHTS,
    SkillMatchQualityCalculator,
    SkillMatchQualityResult,
    SkillMatchWeights,
)
from job_correlation_evaluation_service.services.scoring.skill_relationship_cache import (
    SkillRelationshipCache,
)
from nohiki.skill.v1 import (
    JobSkillRequirement,
    SkillProficiencyLevel,
    SkillProvenance,
    SkillRelationshipType,
    UserSkillEntry,
)


def make_user_skill(
    skill_id: str,
    proficiency: SkillProficiencyLevel = SkillProficiencyLevel.INTERMEDIATE,
    provenance: SkillProvenance = SkillProvenance.USER_DECLARED,
    confidence: float = 1.0,
) -> UserSkillEntry:
    """Create a UserSkillEntry proto for testing."""
    return UserSkillEntry(
        skill_id=skill_id,
        skill_name=f"Skill {skill_id}",
        proficiency=proficiency,
        provenance=provenance,
        provenance_confidence=confidence,
    )


def make_job_skill(
    skill_id: str,
    level: SkillProficiencyLevel = SkillProficiencyLevel.INTERMEDIATE,
    *,
    is_required: bool = True,
    confidence: float = 1.0,
) -> JobSkillRequirement:
    """Create a JobSkillRequirement proto for testing."""
    return JobSkillRequirement(
        skill_id=skill_id,
        skill_name=f"Skill {skill_id}",
        proficiency_level=level,
        is_required=is_required,
        extraction_confidence=confidence,
    )


class TestSkillMatchQualityResult:
    """Tests for SkillMatchQualityResult dataclass."""

    def test_dataclass_is_frozen(self) -> None:
        """Test result dataclass is immutable."""
        import dataclasses

        assert dataclasses.is_dataclass(SkillMatchQualityResult)
        params = getattr(SkillMatchQualityResult, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_dataclass_slots(self) -> None:
        """Test result dataclass uses slots for memory efficiency."""
        import dataclasses

        assert dataclasses.is_dataclass(SkillMatchQualityResult)
        params = getattr(SkillMatchQualityResult, "__dataclass_params__", None)
        assert params is not None
        assert params.slots is True


class TestSkillMatchWeights:
    """Tests for SkillMatchWeights configuration."""

    def test_default_weights_sum_to_one(self) -> None:
        """Test default weights approximately sum to 1 (excluding bonus)."""
        weights = SkillMatchWeights()
        total = weights.proficiency_weight + weights.provenance_weight + weights.coverage_weight
        assert total == pytest.approx(1.0)

    def test_weights_match_spec(self) -> None:
        """Test default weights match architecture specification."""
        weights = SkillMatchWeights()
        assert weights.proficiency_weight == pytest.approx(0.4)
        assert weights.provenance_weight == pytest.approx(0.3)
        assert weights.coverage_weight == pytest.approx(0.3)


class TestProficiencyWeights:
    """Tests for proficiency weight mapping."""

    def test_expert_highest_weight(self) -> None:
        """Test EXPERT has highest proficiency weight."""
        assert PROFICIENCY_WEIGHTS[SkillProficiencyLevel.EXPERT] == pytest.approx(1.0)

    def test_weights_increase_with_level(self) -> None:
        """Test weights increase with proficiency level."""
        levels = [
            SkillProficiencyLevel.UNSPECIFIED,
            SkillProficiencyLevel.BEGINNER,
            SkillProficiencyLevel.INTERMEDIATE,
            SkillProficiencyLevel.ADVANCED,
            SkillProficiencyLevel.EXPERT,
        ]
        weights = [PROFICIENCY_WEIGHTS[lvl] for lvl in levels]
        assert weights == sorted(weights)


class TestProvenanceWeights:
    """Tests for provenance weight mapping."""

    def test_user_declared_highest_weight(self) -> None:
        """Test USER_DECLARED has highest provenance weight."""
        assert PROVENANCE_WEIGHTS[SkillProvenance.USER_DECLARED] == pytest.approx(1.0)

    def test_inferred_lowest_non_unspecified(self) -> None:
        """Test INFERRED has lower weight than USER_DECLARED."""
        assert PROVENANCE_WEIGHTS[SkillProvenance.INFERRED] < PROVENANCE_WEIGHTS[SkillProvenance.USER_DECLARED]


class TestSkillMatchQualityCalculator:
    """Tests for SkillMatchQualityCalculator class."""

    def test_empty_job_requirements_returns_nan(self) -> None:
        """Test empty job requirements returns NaN (no data to score)."""
        import math

        calc = SkillMatchQualityCalculator()
        user_skills = [make_user_skill("python")]
        result = calc.compute(user_skills, [])

        assert math.isnan(result.skill_match_quality)
        assert math.isnan(result.coverage_score)
        assert result.has_skill_data is False

    def test_no_matches_returns_zero(self) -> None:
        """Test no skill matches returns zero quality."""
        calc = SkillMatchQualityCalculator()
        user_skills = [make_user_skill("python")]
        job_skills = [make_job_skill("java")]

        result = calc.compute(user_skills, job_skills)

        assert result.skill_match_quality == pytest.approx(0.0)
        assert result.matched_skill_count == 0
        assert "java" in result.missing_skill_ids

    def test_exact_match_high_proficiency(self) -> None:
        """Test exact match with high proficiency scores well."""
        calc = SkillMatchQualityCalculator()
        user_skills = [
            make_user_skill(
                "python",
                proficiency=SkillProficiencyLevel.EXPERT,
                provenance=SkillProvenance.USER_DECLARED,
            )
        ]
        job_skills = [make_job_skill("python", level=SkillProficiencyLevel.INTERMEDIATE)]

        result = calc.compute(user_skills, job_skills)

        assert result.skill_match_quality > 0.9
        assert result.matched_skill_count == 1
        assert result.coverage_score == pytest.approx(1.0)

    def test_proficiency_gap_penalty(self) -> None:
        """Test proficiency gap reduces score."""
        calc = SkillMatchQualityCalculator()
        user_beginner = [make_user_skill("python", proficiency=SkillProficiencyLevel.BEGINNER)]
        user_expert = [make_user_skill("python", proficiency=SkillProficiencyLevel.EXPERT)]
        job_skills = [make_job_skill("python", level=SkillProficiencyLevel.EXPERT)]

        result_beginner = calc.compute(user_beginner, job_skills)
        result_expert = calc.compute(user_expert, job_skills)

        assert result_beginner.skill_match_quality < result_expert.skill_match_quality

    def test_provenance_weighting(self) -> None:
        """Test provenance affects score."""
        calc = SkillMatchQualityCalculator()
        user_declared = [make_user_skill("python", provenance=SkillProvenance.USER_DECLARED)]
        user_inferred = [make_user_skill("python", provenance=SkillProvenance.INFERRED)]
        job_skills = [make_job_skill("python")]

        result_declared = calc.compute(user_declared, job_skills)
        result_inferred = calc.compute(user_inferred, job_skills)

        assert result_declared.skill_match_quality > result_inferred.skill_match_quality

    def test_required_skill_multiplier(self) -> None:
        """Test required skills are weighted more heavily."""
        calc = SkillMatchQualityCalculator()
        user_skills = [make_user_skill("python")]
        job_required = [make_job_skill("python", is_required=True)]
        job_optional = [make_job_skill("python", is_required=False)]

        result_req = calc.compute(user_skills, job_required)
        result_opt = calc.compute(user_skills, job_optional)

        assert result_req.matched_skill_count == 1
        assert result_opt.matched_skill_count == 1

    def test_partial_coverage(self) -> None:
        """Test partial coverage is reflected in score."""
        calc = SkillMatchQualityCalculator()
        user_skills = [make_user_skill("python")]
        job_skills = [
            make_job_skill("python"),
            make_job_skill("java"),
            make_job_skill("go"),
        ]

        result = calc.compute(user_skills, job_skills)

        assert result.matched_skill_count == 1
        assert result.coverage_score == pytest.approx(1 / 3)
        assert "java" in result.missing_skill_ids
        assert "go" in result.missing_skill_ids


class TestSkillRelationshipExpansion:
    """Tests for skill relationship expansion."""

    def test_relationship_expansion_enables_match(self) -> None:
        """Test relationship expansion allows matching implied skills."""
        cache = SkillRelationshipCache()
        cache.add_relationship("react", "javascript", SkillRelationshipType.REQUIRES)

        calc = SkillMatchQualityCalculator(relationship_cache=cache)
        user_skills = [make_user_skill("react", proficiency=SkillProficiencyLevel.EXPERT)]
        job_skills = [make_job_skill("javascript")]

        result = calc.compute(user_skills, job_skills)

        assert result.matched_skill_count == 1
        assert "javascript" in result.expanded_user_skill_ids

    def test_no_cache_no_expansion(self) -> None:
        """Test without cache, no expansion occurs."""
        calc = SkillMatchQualityCalculator()
        user_skills = [make_user_skill("react")]
        job_skills = [make_job_skill("javascript")]

        result = calc.compute(user_skills, job_skills)

        assert result.matched_skill_count == 0

    def test_relationship_bonus_computed(self) -> None:
        """Test relationship bonus is computed for expanded matches."""
        cache = SkillRelationshipCache()
        cache.add_relationship("react", "javascript", SkillRelationshipType.REQUIRES)

        calc = SkillMatchQualityCalculator(relationship_cache=cache)
        user_skills = [make_user_skill("react")]
        job_skills = [make_job_skill("javascript")]

        result = calc.compute(user_skills, job_skills)

        assert result.relationship_bonus_score > 0


class TestScoringFormula:
    """Tests verifying the scoring formula matches spec."""

    def test_score_components_contribute(self) -> None:
        """Test all score components contribute to final score."""
        calc = SkillMatchQualityCalculator()
        user_skills = [make_user_skill("python", proficiency=SkillProficiencyLevel.EXPERT)]
        job_skills = [make_job_skill("python", level=SkillProficiencyLevel.INTERMEDIATE)]

        result = calc.compute(user_skills, job_skills)

        assert result.proficiency_weighted_score > 0
        assert result.provenance_weighted_score > 0
        assert result.coverage_score > 0

    def test_quality_score_bounded(self) -> None:
        """Test quality score is between 0 and 1."""
        calc = SkillMatchQualityCalculator()

        test_cases = [
            ([make_user_skill("a")], [make_job_skill("a")]),
            ([make_user_skill("a")], [make_job_skill("b")]),
            ([make_user_skill("a", proficiency=SkillProficiencyLevel.BEGINNER)], [make_job_skill("a")]),
        ]

        for user_skills, job_skills in test_cases:
            result = calc.compute(user_skills, job_skills)
            assert 0.0 <= result.skill_match_quality <= 1.0
