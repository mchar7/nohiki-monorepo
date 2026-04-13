"""Stage 4 deterministic fit ranking."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot

from job_correlation_evaluation_service.services.scoring.features import FeatureComposer, PipelineScores
from job_correlation_evaluation_service.services.scoring.features.base import FactorName, FeatureComposition
from job_correlation_evaluation_service.services.scoring.stages.llm_rerank import RerankCandidate

_PERCENT_MAX = 100
_FACTOR_COUNT = 6.0

_IMPORTANCE_FIELDS: dict[FactorName, str] = {
    "skills": "skill_match_importance",
    "location": "location_importance",
    "work_arrangement": "work_arrangement_importance",
    "experience": "experience_importance",
    "salary": "salary_importance",
    "recency": "recency_importance",
}


@dataclass(frozen=True, slots=True)
class FactorAttribution:
    """Available preference factor and its auditable effect on the index."""

    name: FactorName
    compatibility: float
    importance: int
    contribution_points: float


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    """Candidate scored by semantic relevance and available stated preferences."""

    entity_id: str
    maxsim_score: float
    rerank_score: float
    rank_index: float
    final_score: int
    feature_vector: tuple[float, ...]
    factor_attributions: tuple[FactorAttribution, ...]
    role_relevance_raw: float | None = None


def _resolved_importance(profile: SearchPrefSnapshot, factor: FactorName) -> int:
    prefs = profile.feature_importance
    value = getattr(prefs, _IMPORTANCE_FIELDS[factor]) if prefs is not None else None
    resolved = 50 if value is None else value
    if not 0 <= resolved <= _PERCENT_MAX:
        message = f"{_IMPORTANCE_FIELDS[factor]} must be between 0 and {_PERCENT_MAX}"
        raise ValueError(message)
    return resolved


def _score_composition(
    entity_id: str,
    maxsim_score: float,
    rerank_score: float,
    composition: FeatureComposition,
    profile: SearchPrefSnapshot,
) -> ScoredCandidate:
    if not math.isfinite(maxsim_score):
        message = f"Non-finite MaxSim score for candidate {entity_id}"
        raise ValueError(message)
    semantic = min(1.0, max(0.0, maxsim_score))
    role_relevance = composition.role_relevance
    if role_relevance is not None:
        if not math.isfinite(role_relevance) or not 0.0 <= role_relevance <= 1.0:
            message = f"Invalid role relevance for candidate {entity_id}: {role_relevance}"
            raise ValueError(message)
        # Equal fusion preserves semantic adjacency while requiring title role
        # identity to support generic keyword overlap.
        semantic = (semantic + role_relevance) / 2.0
    weighted_sum = 0.0
    role_mismatch = role_relevance == 0.0
    total_weight = 0.0
    weighted: list[tuple[FactorName, float, int, float]] = []
    for name, compatibility in composition.factor_scores.items():
        if not math.isfinite(compatibility) or not 0.0 <= compatibility <= 1.0:
            message = f"Invalid {name} compatibility for candidate {entity_id}: {compatibility}"
            raise ValueError(message)
        importance = _resolved_importance(profile, name)
        weight = (importance / _PERCENT_MAX) / _FACTOR_COUNT
        weighted.append((name, compatibility, importance, weight))
        if role_mismatch or weight == 0.0:
            continue
        weighted_sum += weight * compatibility
        total_weight += weight

    denominator = 1.0 + total_weight
    rank_index = (semantic + weighted_sum) / denominator
    attributions = tuple(
        FactorAttribution(
            name=name,
            compatibility=compatibility,
            importance=importance,
            contribution_points=100.0 * weight * ((0.0 if role_mismatch else compatibility) - semantic) / denominator,
        )
        for name, compatibility, importance, weight in weighted
    )
    final_score = min(100, max(0, math.floor(100.0 * rank_index + 0.5)))
    return ScoredCandidate(
        entity_id=entity_id,
        maxsim_score=min(1.0, max(0.0, maxsim_score)),
        rerank_score=rerank_score,
        rank_index=rank_index,
        final_score=final_score,
        feature_vector=tuple(float(value) for value in composition.raw_features),
        factor_attributions=attributions,
        role_relevance_raw=(100.0 * role_relevance if role_relevance is not None else 100.0 * semantic),
    )


class DeterministicFinalStage:
    """Deterministic Stage 4 fit ranker; no model artifacts or calibration."""

    def __init__(self, feature_composer: FeatureComposer) -> None:
        """Initialize with the single-pass feature composer."""
        self._feature_composer = feature_composer

    @classmethod
    def create(cls, feature_composer: FeatureComposer | None = None) -> DeterministicFinalStage:
        """Create a stage with the production feature composer by default."""
        return cls(feature_composer or FeatureComposer.create_default())

    def score_single(
        self,
        candidate: RerankCandidate,
        listing: ListingSnapshot,
        profile: SearchPrefSnapshot,
    ) -> ScoredCandidate:
        """Score one Stage 3-shaped candidate."""
        return self._score(
            candidate.entity_id,
            listing,
            profile,
            PipelineScores(maxsim_score=candidate.maxsim_score, rerank_score=candidate.rerank_score),
        )

    def score_with_inline_maxsim(
        self,
        listing: ListingSnapshot,
        profile: SearchPrefSnapshot,
        maxsim_score: float,
    ) -> ScoredCandidate:
        """Score a listing from its already normalized inline MaxSim."""
        return self._score(
            listing.id,
            listing,
            profile,
            PipelineScores(maxsim_score=maxsim_score, rerank_score=0.0),
        )

    def _score(
        self,
        entity_id: str,
        listing: ListingSnapshot,
        profile: SearchPrefSnapshot,
        pipeline_scores: PipelineScores,
    ) -> ScoredCandidate:
        composition = self._feature_composer.extract(listing, profile, pipeline_scores)
        return _score_composition(
            entity_id, pipeline_scores.maxsim_score, pipeline_scores.rerank_score, composition, profile
        )

    def score_batch(
        self,
        candidates: list[RerankCandidate],
        listings: Mapping[str, ListingSnapshot],
        profile: SearchPrefSnapshot,
    ) -> list[ScoredCandidate]:
        """Score and deterministically order all candidates with listings."""
        results = [
            self.score_single(candidate, listing, profile)
            for candidate in candidates
            if (listing := listings.get(candidate.entity_id)) is not None
        ]
        results.sort(key=lambda candidate: (-candidate.rank_index, -candidate.maxsim_score, candidate.entity_id))
        return results
