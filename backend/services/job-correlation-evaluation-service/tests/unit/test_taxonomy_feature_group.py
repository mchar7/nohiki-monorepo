"""Unit tests for TaxonomyFeatureGroup and BFS distance computation."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import numpy as np
import pytest
from job_correlation_evaluation_service.services.scoring.constants import (
    FEATURE_COUNT,
    FeatureIndex,
)
from job_correlation_evaluation_service.services.scoring.features.base import (
    FeatureExtractionContext,
    PipelineScores,
)
from job_correlation_evaluation_service.services.scoring.features.groups.taxonomy import (
    TaxonomyFeatureGroup,
    _extract_skill_ids,
    _min_distance_to_set,
)
from job_correlation_evaluation_service.services.scoring.skill_relationship_cache import (
    SkillRelationshipCache,
)
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.skill.v1 import JobSkillRequirement, UserSkillEntry
from nohiki.user.pref.v1 import SearchPrefSnapshot


def _make_context(
    job_skills: list[str] | None = None,
    user_skills: list[str] | None = None,
) -> FeatureExtractionContext:
    """Create a FeatureExtractionContext with current snapshot skill entries."""
    job = ListingSnapshot(
        skill_requirements=[JobSkillRequirement(skill_id=skill_id) for skill_id in (job_skills or [])]
    )
    profile = SearchPrefSnapshot(user_skills=[UserSkillEntry(skill_id=skill_id) for skill_id in (user_skills or [])])
    return FeatureExtractionContext(
        job=job,
        profile=profile,
        pipeline_scores=PipelineScores(maxsim_score=0.5, rerank_score=0.0),
    )


def _make_cache_with_graph(
    edges: dict[str, set[str]],
    related: dict[str, set[str]] | None = None,
) -> SkillRelationshipCache:
    """Create a SkillRelationshipCache with pre-populated local cache."""
    cache = MagicMock(spec=SkillRelationshipCache)
    cache.relationship_count = sum(len(v) for v in edges.values()) + (
        sum(len(v) for v in related.values()) if related else 0
    )

    def get_implied(skill_id: str) -> frozenset[str]:
        return frozenset(edges.get(skill_id, set()))

    def get_related(skill_id: str) -> frozenset[str]:
        if related is None:
            return frozenset()
        return frozenset(related.get(skill_id, set()))

    cache.get_implied_skills = get_implied
    cache.get_related_skills = get_related
    return cache


class TestExtractSkillIds:
    """Tests for current canonical skill entries."""

    def test_extracts_job_skill_ids(self) -> None:
        skills = [JobSkillRequirement(skill_id="s1"), JobSkillRequirement(skill_id="s2")]

        assert _extract_skill_ids(skills) == frozenset({"s1", "s2"})

    def test_extracts_user_skill_ids(self) -> None:
        skills = [UserSkillEntry(skill_id="s1"), UserSkillEntry(skill_id="s2")]

        assert _extract_skill_ids(skills) == frozenset({"s1", "s2"})

    def test_skips_empty_skill_ids(self) -> None:
        assert _extract_skill_ids([JobSkillRequirement()]) == frozenset()

    def test_returns_empty_for_empty_input(self) -> None:
        assert _extract_skill_ids([]) == frozenset()


class TestMinDistanceToSet:
    """Tests for _min_distance_to_set BFS function."""

    def test_direct_match_returns_zero(self) -> None:
        """Source skill in target set should return distance 0."""
        cache = _make_cache_with_graph({})
        result = _min_distance_to_set("s1", frozenset({"s1", "s2"}), cache)
        assert result == 0.0

    def test_one_hop_via_implied(self) -> None:
        """Should find neighbor at distance 1 via implied skills."""
        cache = _make_cache_with_graph({"s1": {"s2"}})
        result = _min_distance_to_set("s1", frozenset({"s2"}), cache)
        assert result == 1.0

    def test_one_hop_via_related(self) -> None:
        """Should find neighbor at distance 1 via related skills."""
        cache = _make_cache_with_graph({}, related={"s1": {"s2"}})
        result = _min_distance_to_set("s1", frozenset({"s2"}), cache)
        assert result == 1.0

    def test_multi_hop_path(self) -> None:
        """Should find multi-hop path through graph."""
        cache = _make_cache_with_graph({"s1": {"s2"}, "s2": {"s3"}})
        result = _min_distance_to_set("s1", frozenset({"s3"}), cache)
        assert result == 2.0

    def test_no_path_returns_none(self) -> None:
        """Should return None when no path exists."""
        cache = _make_cache_with_graph({"s1": {"s2"}})
        result = _min_distance_to_set("s1", frozenset({"s99"}), cache)
        assert result is None

    def test_respects_max_bfs_depth(self) -> None:
        """Should not traverse beyond _MAX_BFS_DEPTH."""
        # Build a chain longer than _MAX_BFS_DEPTH (10)
        edges: dict[str, set[str]] = {}
        for i in range(15):
            edges[f"s{i}"] = {f"s{i + 1}"}

        cache = _make_cache_with_graph(edges)
        result = _min_distance_to_set("s0", frozenset({"s12"}), cache)
        assert result is None

    def test_handles_cycles(self) -> None:
        """Should handle cycles without infinite loop."""
        cache = _make_cache_with_graph({"s1": {"s2"}, "s2": {"s1", "s3"}})
        result = _min_distance_to_set("s1", frozenset({"s3"}), cache)
        assert result == 2.0


class TestTaxonomyFeatureGroupExtract:
    """Tests for TaxonomyFeatureGroup.extract method."""

    def test_nan_when_no_job_skills(self) -> None:
        """Should set NaN when job has no skills."""
        group = TaxonomyFeatureGroup(relationship_cache=None)
        features = np.full(FEATURE_COUNT, 0.0, dtype=np.float32)
        ctx = _make_context(job_skills=None, user_skills=["s1"])

        group.extract(features, ctx)

        assert math.isnan(features[FeatureIndex.SKILL_GRAPH_MIN_DISTANCE])
        assert math.isnan(features[FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE])

    def test_nan_when_no_user_skills(self) -> None:
        """Should set NaN when user has no skills."""
        group = TaxonomyFeatureGroup(relationship_cache=None)
        features = np.full(FEATURE_COUNT, 0.0, dtype=np.float32)
        ctx = _make_context(job_skills=["s1"], user_skills=None)

        group.extract(features, ctx)

        assert math.isnan(features[FeatureIndex.SKILL_GRAPH_MIN_DISTANCE])
        assert math.isnan(features[FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE])

    def test_nan_when_cache_is_none(self) -> None:
        """Should set NaN when cache is not available."""
        group = TaxonomyFeatureGroup(relationship_cache=None)
        features = np.full(FEATURE_COUNT, 0.0, dtype=np.float32)
        ctx = _make_context(job_skills=["s1"], user_skills=["s2"])

        group.extract(features, ctx)

        assert math.isnan(features[FeatureIndex.SKILL_GRAPH_MIN_DISTANCE])
        assert math.isnan(features[FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE])

    def test_nan_when_cache_empty(self) -> None:
        """Should set NaN when cache has no relationships."""
        cache = MagicMock(spec=SkillRelationshipCache)
        cache.relationship_count = 0

        group = TaxonomyFeatureGroup(relationship_cache=cache)
        features = np.full(FEATURE_COUNT, 0.0, dtype=np.float32)
        ctx = _make_context(job_skills=["s1"], user_skills=["s2"])

        group.extract(features, ctx)

        assert math.isnan(features[FeatureIndex.SKILL_GRAPH_MIN_DISTANCE])
        assert math.isnan(features[FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE])

    def test_nan_when_no_distances_found(self) -> None:
        """Should set NaN when no paths exist between job and user skills."""
        cache = _make_cache_with_graph({"s1": {"unrelated"}})
        group = TaxonomyFeatureGroup(relationship_cache=cache)
        features = np.full(FEATURE_COUNT, 0.0, dtype=np.float32)
        ctx = _make_context(job_skills=["job_skill"], user_skills=["user_skill"])

        group.extract(features, ctx)

        assert math.isnan(features[FeatureIndex.SKILL_GRAPH_MIN_DISTANCE])
        assert math.isnan(features[FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE])

    def test_computes_distances_for_direct_match(self) -> None:
        """Should compute distance 0 for direct skill match."""
        cache = _make_cache_with_graph({"shared": {"other"}})
        group = TaxonomyFeatureGroup(relationship_cache=cache)
        features = np.full(FEATURE_COUNT, 0.0, dtype=np.float32)
        ctx = _make_context(job_skills=["shared"], user_skills=["shared"])

        group.extract(features, ctx)

        assert features[FeatureIndex.SKILL_GRAPH_MIN_DISTANCE] == pytest.approx(0.0)
        assert features[FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE] == pytest.approx(0.0)

    def test_computes_distances_for_graph_path(self) -> None:
        """Should compute correct min and mean distances via graph."""
        # job_a -> user_a: distance 1 (direct edge)
        # job_b -> user_a: distance 2 (via intermediate)
        cache = _make_cache_with_graph(
            {
                "job_a": {"user_a"},
                "job_b": {"mid"},
                "mid": {"user_a"},
            }
        )
        group = TaxonomyFeatureGroup(relationship_cache=cache)
        features = np.full(FEATURE_COUNT, 0.0, dtype=np.float32)
        ctx = _make_context(job_skills=["job_a", "job_b"], user_skills=["user_a"])

        group.extract(features, ctx)

        assert features[FeatureIndex.SKILL_GRAPH_MIN_DISTANCE] == pytest.approx(1.0)
        assert features[FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE] == pytest.approx(1.5)

    def test_computes_mean_with_multiple_distances(self) -> None:
        """Should correctly average when multiple job skills have paths."""
        # 3 job skills: distances 1, 2, 3 → min=1, mean=2.0
        cache = _make_cache_with_graph(
            {
                "j1": {"u1"},
                "j2": {"m1"},
                "m1": {"u1"},
                "j3": {"m2"},
                "m2": {"m3"},
                "m3": {"u1"},
            }
        )
        group = TaxonomyFeatureGroup(relationship_cache=cache)
        features = np.full(FEATURE_COUNT, 0.0, dtype=np.float32)
        ctx = _make_context(job_skills=["j1", "j2", "j3"], user_skills=["u1"])

        group.extract(features, ctx)

        assert features[FeatureIndex.SKILL_GRAPH_MIN_DISTANCE] == pytest.approx(1.0)
        assert features[FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE] == pytest.approx(2.0)
