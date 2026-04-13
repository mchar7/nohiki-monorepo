"""Advanced skill match quality scoring with proficiency, provenance, and relationships.

Implements the full scoring algorithm from SKILL_CANONICALIZATION_ARCHITECTURE.md
Section 10.3:
- Proficiency-weighted scoring (user skill level vs job requirement level)
- Provenance-weighted scoring (trust based on skill source)
- Requirement importance weighting (required vs nice-to-have)
- Skill relationship expansion (implied skills from REQUIRES/PARENT_OF)

Formula:
    skill_match_quality = (
        0.4 * proficiency_weighted +
        0.3 * provenance_weighted +
        0.3 * coverage
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nohiki.skill.v1 import (
    JobSkillRequirement,
    SkillProficiencyLevel,
    SkillProvenance,
    UserSkillEntry,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from job_correlation_evaluation_service.services.scoring.skill_relationship_cache import (
        SkillRelationshipCache,
    )


@dataclass(frozen=True, slots=True)
class SkillMatchQualityResult:
    """Complete result of skill match quality computation.

    Attributes:
        matched_skill_count: Number of job skills matched by user.
        total_job_required_skills: Total skills required by job.
        total_user_skills: Total skills declared by user.
        coverage_score: Fraction of job skills covered (0.0-1.0).
        proficiency_weighted_score: Score weighted by proficiency match (0.0-1.0).
        provenance_weighted_score: Score weighted by provenance quality (0.0-1.0).
        relationship_bonus_score: Bonus for matches via skill relationships (0.0-1.0).
        skill_match_quality: Final composite quality score (0.0-1.0).
        has_skill_data: True if both user and job have skill data.
        matched_skill_ids: Skill IDs that matched.
        missing_skill_ids: Job skill IDs not matched by user.
        expanded_user_skill_ids: User skills including relationship expansions.

    """

    matched_skill_count: int
    total_job_required_skills: int
    total_user_skills: int
    coverage_score: float
    proficiency_weighted_score: float
    provenance_weighted_score: float
    relationship_bonus_score: float
    skill_match_quality: float
    has_skill_data: bool
    matched_skill_ids: frozenset[str]
    missing_skill_ids: frozenset[str]
    expanded_user_skill_ids: frozenset[str]


_DEFAULT_UNKNOWN_SKILL_PROFICIENCY_SCORE: float = 0.6
_DEFAULT_UNKNOWN_SKILL_PROVENANCE_SCORE: float = 0.5

PROFICIENCY_WEIGHTS: Mapping[SkillProficiencyLevel, float] = {
    SkillProficiencyLevel.UNSPECIFIED: 0.2,
    SkillProficiencyLevel.BEGINNER: 0.4,
    SkillProficiencyLevel.INTERMEDIATE: 0.6,
    SkillProficiencyLevel.ADVANCED: 0.8,
    SkillProficiencyLevel.EXPERT: 1.0,
}

# Explicit ordinal ranking for gap-penalty arithmetic. Decoupled from the
# proto enum integer value so reordering enum members in the schema does not
# silently change scoring behavior.
PROFICIENCY_ORDER: Mapping[SkillProficiencyLevel, int] = {
    SkillProficiencyLevel.UNSPECIFIED: 0,
    SkillProficiencyLevel.BEGINNER: 1,
    SkillProficiencyLevel.INTERMEDIATE: 2,
    SkillProficiencyLevel.ADVANCED: 3,
    SkillProficiencyLevel.EXPERT: 4,
}

PROVENANCE_WEIGHTS: Mapping[SkillProvenance, float] = {
    SkillProvenance.UNSPECIFIED: 0.3,
    SkillProvenance.USER_DECLARED: 1.0,
    SkillProvenance.USER_INFERRED: 0.8,
    SkillProvenance.JOB_EXTRACTED: 0.6,
    SkillProvenance.INFERRED: 0.5,
}


@dataclass(frozen=True, slots=True)
class SkillMatchWeights:
    """Configurable weights for skill match scoring.

    Attributes:
        proficiency_weight: Weight for proficiency score in final calculation.
        provenance_weight: Weight for provenance score in final calculation.
        coverage_weight: Weight for coverage score in final calculation.
        required_skill_multiplier: Multiplier for required skills (vs nice-to-have).
        gap_penalty_per_level: Penalty per proficiency level gap.
        min_gap_multiplier: Minimum multiplier after gap penalty.
        relationship_bonus_weight: Weight for relationship expansion bonus.

    """

    proficiency_weight: float = 0.4
    provenance_weight: float = 0.3
    coverage_weight: float = 0.3
    required_skill_multiplier: float = 1.5
    gap_penalty_per_level: float = 0.2
    min_gap_multiplier: float = 0.3
    relationship_bonus_weight: float = 0.1


class SkillMatchQualityCalculator:
    """Computes skill match quality with proficiency, provenance, and relationships.

    Implements the full scoring algorithm:
    1. Match user skills to job requirements by canonical ID
    2. Weight matches by proficiency, provenance, and requirement importance
    3. Expand user skills via relationship graph (REQUIRES, PARENT_OF)
    4. Compute final composite score

    Attributes:
        _relationship_cache: Optional cache for skill relationship expansion.
        _weights: Configurable scoring weights.

    """

    def __init__(
        self,
        relationship_cache: SkillRelationshipCache | None = None,
        weights: SkillMatchWeights | None = None,
    ) -> None:
        """Initialize the skill match quality calculator.

        Args:
            relationship_cache: Optional cache for skill relationship expansion.
            weights: Optional custom scoring weights.

        """
        self._relationship_cache = relationship_cache
        self._weights = weights or SkillMatchWeights()

    def compute(
        self,
        user_skills: Sequence[UserSkillEntry],
        job_requirements: Sequence[JobSkillRequirement],
    ) -> SkillMatchQualityResult:
        """Compute skill match quality between user skills and job requirements.

        Args:
            user_skills: User's skills with proficiency and provenance.
            job_requirements: Job's skill requirements with levels.

        Returns:
            Complete skill match quality result with all scoring components.

        """
        if not job_requirements:
            return self._neutral_result(user_skills)

        user_skill_map = {s.skill_id: s for s in user_skills}
        original_user_ids = frozenset(user_skill_map.keys())
        expanded_user_ids = self._expand_user_skills(original_user_ids)

        matches = self._find_matches(job_requirements, user_skill_map, expanded_user_ids)

        if not matches:
            return self._zero_result(user_skills, job_requirements, expanded_user_ids)

        proficiency_score, provenance_score = self._compute_weighted_scores(matches)
        coverage = len(matches) / len(job_requirements)
        relationship_bonus = self._compute_relationship_bonus(expanded_user_ids, matches)

        skill_match_quality = self._compute_final_score(
            proficiency_score, provenance_score, coverage, relationship_bonus
        )

        matched_ids = frozenset(req.skill_id for req, _ in matches)
        missing_ids = frozenset(req.skill_id for req in job_requirements if req.skill_id not in matched_ids)

        return SkillMatchQualityResult(
            matched_skill_count=len(matches),
            total_job_required_skills=len(job_requirements),
            total_user_skills=len(user_skills),
            coverage_score=coverage,
            proficiency_weighted_score=proficiency_score,
            provenance_weighted_score=provenance_score,
            relationship_bonus_score=relationship_bonus,
            skill_match_quality=skill_match_quality,
            has_skill_data=True,
            matched_skill_ids=matched_ids,
            missing_skill_ids=missing_ids,
            expanded_user_skill_ids=expanded_user_ids,
        )

    def _expand_user_skills(self, user_skill_ids: frozenset[str]) -> frozenset[str]:
        """Expand user skills to include implied skills from relationships."""
        if not self._relationship_cache:
            return user_skill_ids
        return self._relationship_cache.expand_user_skills(user_skill_ids)

    def _find_matches(
        self,
        job_requirements: Sequence[JobSkillRequirement],
        user_skill_map: Mapping[str, UserSkillEntry],
        expanded_user_ids: frozenset[str],
    ) -> list[tuple[JobSkillRequirement, UserSkillEntry | None]]:
        """Find matches between job requirements and user skills."""
        matches: list[tuple[JobSkillRequirement, UserSkillEntry | None]] = []
        for req in job_requirements:
            if req.skill_id in user_skill_map:
                matches.append((req, user_skill_map[req.skill_id]))
            elif req.skill_id in expanded_user_ids:
                matches.append((req, None))
        return matches

    def _compute_weighted_scores(
        self,
        matches: list[tuple[JobSkillRequirement, UserSkillEntry | None]],
    ) -> tuple[float, float]:
        """Compute proficiency and provenance weighted scores."""
        proficiency_scores: list[float] = []
        provenance_scores: list[float] = []
        weights: list[float] = []

        for req, user_skill in matches:
            req_weight = self._weights.required_skill_multiplier if req.is_required else 1.0
            weights.append(req_weight)

            if user_skill is not None:
                prof_score = self._compute_proficiency_score(user_skill, req)
                prov_score = self._compute_provenance_score(user_skill)
            else:
                prof_score = _DEFAULT_UNKNOWN_SKILL_PROFICIENCY_SCORE
                prov_score = _DEFAULT_UNKNOWN_SKILL_PROVENANCE_SCORE

            proficiency_scores.append(prof_score * req_weight)
            provenance_scores.append(prov_score * req_weight)

        total_weight = sum(weights)
        proficiency_weighted = sum(proficiency_scores) / total_weight
        provenance_weighted = sum(provenance_scores) / total_weight

        return proficiency_weighted, provenance_weighted

    def _compute_proficiency_score(
        self,
        user_skill: UserSkillEntry,
        job_req: JobSkillRequirement,
    ) -> float:
        """Compute proficiency score with gap penalty."""
        base_score = PROFICIENCY_WEIGHTS.get(user_skill.proficiency, 0.5)
        user_level = PROFICIENCY_ORDER[user_skill.proficiency]
        req_level = PROFICIENCY_ORDER[job_req.proficiency_level]

        if user_level < req_level:
            gap = req_level - user_level
            penalty = gap * self._weights.gap_penalty_per_level
            multiplier = max(self._weights.min_gap_multiplier, 1.0 - penalty)
            base_score *= multiplier

        return base_score

    def _compute_provenance_score(self, user_skill: UserSkillEntry) -> float:
        """Compute provenance score based on source and confidence."""
        base_score = PROVENANCE_WEIGHTS.get(user_skill.provenance, 0.5)
        return base_score * user_skill.provenance_confidence

    def _compute_relationship_bonus(
        self,
        expanded_user_ids: frozenset[str],
        matches: list[tuple[JobSkillRequirement, UserSkillEntry | None]],
    ) -> float:
        """Compute bonus for matches via skill relationships."""
        if not self._relationship_cache or not matches:
            return 0.0

        relationship_matches = sum(
            1 for req, user_skill in matches if user_skill is None and req.skill_id in expanded_user_ids
        )

        return relationship_matches / len(matches) * 0.5

    def _compute_final_score(
        self,
        proficiency_score: float,
        provenance_score: float,
        coverage: float,
        relationship_bonus: float,
    ) -> float:
        """Compute final skill match quality score."""
        skill_match_quality = (
            self._weights.proficiency_weight * proficiency_score
            + self._weights.provenance_weight * provenance_score
            + self._weights.coverage_weight * coverage
            + self._weights.relationship_bonus_weight * relationship_bonus
        )
        return max(0.0, min(1.0, skill_match_quality))

    def _neutral_result(
        self,
        user_skills: Sequence[UserSkillEntry],
    ) -> SkillMatchQualityResult:
        """Return result when job has no skill requirements.

        Since there are no job requirements, we cannot compute a meaningful
        skill match score. Returns NaN with has_skill_data=False.
        """
        return SkillMatchQualityResult(
            matched_skill_count=0,
            total_job_required_skills=0,
            total_user_skills=len(user_skills),
            coverage_score=math.nan,
            proficiency_weighted_score=math.nan,
            provenance_weighted_score=math.nan,
            relationship_bonus_score=0.0,
            skill_match_quality=math.nan,
            has_skill_data=False,
            matched_skill_ids=frozenset(),
            missing_skill_ids=frozenset(),
            expanded_user_skill_ids=frozenset(s.skill_id for s in user_skills),
        )

    def _zero_result(
        self,
        user_skills: Sequence[UserSkillEntry],
        job_requirements: Sequence[JobSkillRequirement],
        expanded_user_ids: frozenset[str],
    ) -> SkillMatchQualityResult:
        """Return zero result when no skills match."""
        return SkillMatchQualityResult(
            matched_skill_count=0,
            total_job_required_skills=len(job_requirements),
            total_user_skills=len(user_skills),
            coverage_score=0.0,
            proficiency_weighted_score=0.0,
            provenance_weighted_score=0.0,
            relationship_bonus_score=0.0,
            skill_match_quality=0.0,
            has_skill_data=bool(user_skills),
            matched_skill_ids=frozenset(),
            missing_skill_ids=frozenset(r.skill_id for r in job_requirements),
            expanded_user_skill_ids=expanded_user_ids,
        )
