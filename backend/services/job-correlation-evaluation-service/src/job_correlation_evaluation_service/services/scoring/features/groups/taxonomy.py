"""Taxonomy feature extraction using ESCO skill graph distances."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from typing import TYPE_CHECKING

import numpy as np

from job_correlation_evaluation_service.services.scoring.constants import FeatureIndex
from job_correlation_evaluation_service.services.scoring.features.base import FeatureGroup

if TYPE_CHECKING:
    from nohiki.skill.v1 import JobSkillRequirement, UserSkillEntry
    from numpy.typing import NDArray

    from job_correlation_evaluation_service.services.scoring.features.base import (
        FeatureExtractionContext,
    )
    from job_correlation_evaluation_service.services.scoring.skill_relationship_cache import (
        SkillRelationshipCache,
    )

# Maximum BFS depth to prevent unbounded traversal in large graphs
_MAX_BFS_DEPTH: int = 10


class TaxonomyFeatureGroup(FeatureGroup):
    """Extract taxonomy features from ESCO skill graph (indices 30-31).

    Features:
        - SKILL_GRAPH_MIN_DISTANCE: Minimum shortest-path distance between any
          user skill and any job skill in the ESCO skill graph. 0 means exact
          skill match, higher values indicate more distant relationship.
        - SKILL_GRAPH_MEAN_DISTANCE: Mean shortest-path distance across all
          matched user-job skill pairs.

    Both features are NaN when either the job or user has no skill data, or
    when the relationship cache is empty/unavailable.

    Design: Raw graph distance values: LightGBM learns optimal thresholds.
    Monotone constraint: -1 (shorter distance = better match).
    """

    def __init__(self, relationship_cache: SkillRelationshipCache | None = None) -> None:
        """Initialize with skill relationship cache.

        Args:
            relationship_cache: Cache providing skill graph adjacency data.
                If None, features default to NaN (cache not populated).
        """
        self._cache = relationship_cache

    def extract(
        self,
        features: NDArray[np.float32],
        context: FeatureExtractionContext,
    ) -> None:
        """Extract taxonomy features into feature vector."""
        job = context.job
        profile = context.profile

        job_skill_ids = _extract_skill_ids(job.skill_requirements)
        user_skill_ids = _extract_skill_ids(profile.user_skills)

        if not job_skill_ids or not user_skill_ids or self._cache is None or self._cache.relationship_count == 0:
            features[FeatureIndex.SKILL_GRAPH_MIN_DISTANCE] = math.nan
            features[FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE] = math.nan
            return

        # Compute pairwise shortest-path distances
        distances: list[float] = []
        for job_skill in job_skill_ids:
            min_dist = _min_distance_to_set(job_skill, user_skill_ids, self._cache)
            if min_dist is not None:
                distances.append(min_dist)

        if not distances:
            features[FeatureIndex.SKILL_GRAPH_MIN_DISTANCE] = math.nan
            features[FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE] = math.nan
            return

        features[FeatureIndex.SKILL_GRAPH_MIN_DISTANCE] = float(min(distances))
        features[FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE] = float(sum(distances) / len(distances))


def _extract_skill_ids(
    skills: Iterable[JobSkillRequirement | UserSkillEntry],
) -> frozenset[str]:
    """Extract populated canonical skill IDs from current snapshot entries."""
    return frozenset(skill.skill_id for skill in skills if skill.skill_id)


def _min_distance_to_set(
    source_skill: str,
    target_skills: frozenset[str],
    cache: SkillRelationshipCache,
) -> float | None:
    """BFS shortest path from source_skill to any skill in target_skills.

    Uses the skill relationship cache for adjacency. Returns None if no
    path exists within _MAX_BFS_DEPTH hops.

    Args:
        source_skill: Starting skill UUID.
        target_skills: Set of target skill UUIDs to reach.
        cache: Skill relationship cache providing graph adjacency.

    Returns:
        Shortest path distance, or None if unreachable.
    """
    # Direct match = distance 0
    if source_skill in target_skills:
        return 0.0

    visited: set[str] = {source_skill}
    queue: deque[tuple[str, int]] = deque([(source_skill, 0)])

    while queue:
        current, depth = queue.popleft()
        if depth >= _MAX_BFS_DEPTH:
            continue

        # Get all adjacent skills (requires + parent_of + related_to)
        neighbors: set[str] = set()
        neighbors.update(cache.get_implied_skills(current))
        neighbors.update(cache.get_related_skills(current))

        for neighbor in neighbors:
            if neighbor in target_skills:
                return float(depth + 1)
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))

    return None
