"""Redis-backed skill relationship cache for expanding user skills via graph relationships.

Provides O(1) lookups for skill relationships (REQUIRES, PARENT_OF, RELATED_TO)
to expand a user's declared skills to include implied skills. For example,
if a user has React, they implicitly have JavaScript (via REQUIRES relationship).

Uses Redis for multi-pod cache sharing. Falls back to local cache on Redis failure.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nohiki.skill.v1 import SkillRelationshipType
from nohiki_observability import get_logger

from job_correlation_evaluation_service.core.cache import get_cache
from job_correlation_evaluation_service.core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterable

    from nohiki_redis_utils import RedisCache

    from job_correlation_evaluation_service.core.config import Settings

logger = get_logger(__name__)

SKILL_CACHE_KEY = "skill_relationships"


@dataclass(frozen=True, slots=True)
class SkillRelationshipData:
    """Cached skill relationship data for expansion.

    Attributes:
        skill_id: Source skill UUID.
        related_skill_id: Target skill UUID.
        relationship_type: Type of relationship (REQUIRES, PARENT_OF, etc.).
        strength: Relationship strength (0.0-1.0).

    """

    skill_id: str
    related_skill_id: str
    relationship_type: SkillRelationshipType
    strength: float


class SkillRelationshipCache:
    """Redis-backed cache for skill relationships.

    Populated from skill-graph-service via Kafka events.
    Used for expanding user skills to include implied skills.
    Shared across all pods via Redis.

    """

    def __init__(self, cache: RedisCache | None = None, settings: Settings | None = None) -> None:
        """Initialize with Redis cache.

        Args:
            cache: Redis cache instance. Uses get_cache() if not provided.
            settings: Settings instance. Uses get_settings() if not provided.

        """
        self._cache = cache if cache is not None else get_cache()
        self._settings = settings if settings is not None else get_settings()
        self._ttl = self._settings.caching.skill_relationships_ttl
        self._local_cache: dict[str, defaultdict[str, set[str]]] | None = None

    async def load_from_redis(self) -> bool:
        """Load relationships from Redis into local cache.

        Returns:
            True if loaded successfully, False on cache miss.

        """
        cached = await self._cache.get(SKILL_CACHE_KEY)
        if cached is None:
            logger.debug("Skill relationships cache miss")
            return False

        data = json.loads(str(cached))
        self._local_cache = {
            "requires": defaultdict(set, {k: set(v) for k, v in data.get("requires", {}).items()}),
            "parent_of": defaultdict(set, {k: set(v) for k, v in data.get("parent_of", {}).items()}),
            "related_to": defaultdict(set, {k: set(v) for k, v in data.get("related_to", {}).items()}),
        }
        logger.debug("Skill relationships loaded from Redis", count=self.relationship_count)
        return True

    async def save_to_redis(self) -> None:
        """Save current relationships to Redis."""
        cache = self._ensure_local_cache()
        data = {
            "requires": {k: list(v) for k, v in cache["requires"].items()},
            "parent_of": {k: list(v) for k, v in cache["parent_of"].items()},
            "related_to": {k: list(v) for k, v in cache["related_to"].items()},
        }
        await self._cache.set(SKILL_CACHE_KEY, json.dumps(data), ttl=self._ttl)
        logger.debug("Skill relationships saved to Redis", count=self.relationship_count)

    def _ensure_local_cache(self) -> dict[str, defaultdict[str, set[str]]]:
        """Ensure local cache is initialized."""
        if self._local_cache is None:
            self._local_cache = {
                "requires": defaultdict(set),
                "parent_of": defaultdict(set),
                "related_to": defaultdict(set),
            }
        return self._local_cache

    def add_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: SkillRelationshipType,
    ) -> None:
        """Add a relationship to the local cache.

        Call save_to_redis() after adding relationships to persist.

        Args:
            source_id: Source skill UUID.
            target_id: Target skill UUID.
            relationship_type: Type of relationship.

        """
        cache = self._ensure_local_cache()
        match relationship_type:
            case SkillRelationshipType.REQUIRES:
                cache["requires"][source_id].add(target_id)
            case SkillRelationshipType.PARENT_OF:
                cache["parent_of"][source_id].add(target_id)
            case SkillRelationshipType.RELATED_TO:
                cache["related_to"][source_id].add(target_id)

    def add_relationships(self, relationships: Iterable[SkillRelationshipData]) -> None:
        """Add multiple relationships to the local cache.

        Call save_to_redis() after adding relationships to persist.

        Args:
            relationships: Iterable of relationship data to add.

        """
        for rel in relationships:
            self.add_relationship(rel.skill_id, rel.related_skill_id, rel.relationship_type)

    def get_implied_skills(self, skill_id: str) -> frozenset[str]:
        """Get skills implied by having this skill.

        Args:
            skill_id: The skill UUID to expand.

        Returns:
            Frozenset of implied skill UUIDs (not including the input skill).

        """
        if self._local_cache is None:
            return frozenset()

        implied: set[str] = set()
        if requires := self._local_cache["requires"].get(skill_id):
            implied.update(requires)
        if children := self._local_cache["parent_of"].get(skill_id):
            implied.update(children)

        return frozenset(implied)

    def expand_user_skills(self, skill_ids: frozenset[str]) -> frozenset[str]:
        """Expand user skills to include all implied skills.

        Args:
            skill_ids: Original user skill UUIDs.

        Returns:
            Union of original skills and all implied skills.

        """
        expanded: set[str] = set(skill_ids)
        for skill_id in skill_ids:
            if implied := self.get_implied_skills(skill_id):
                expanded.update(implied)
        return frozenset(expanded)

    def get_related_skills(self, skill_id: str) -> frozenset[str]:
        """Get skills related to this skill (weaker relationship than REQUIRES).

        Args:
            skill_id: The skill UUID to look up.

        Returns:
            Frozenset of related skill UUIDs.

        """
        if self._local_cache is None:
            return frozenset()
        return frozenset(self._local_cache["related_to"].get(skill_id, set()))

    @property
    def relationship_count(self) -> int:
        """Total number of relationships in cache."""
        if self._local_cache is None:
            return 0
        return (
            sum(len(v) for v in self._local_cache["requires"].values())
            + sum(len(v) for v in self._local_cache["parent_of"].values())
            + sum(len(v) for v in self._local_cache["related_to"].values())
        )

    def clear(self) -> None:
        """Clear local cache."""
        self._local_cache = None

    async def invalidate(self) -> None:
        """Invalidate Redis cache."""
        await self._cache.delete(SKILL_CACHE_KEY)
        self._local_cache = None
        logger.debug("Skill relationships cache invalidated")


class _CacheHolder:
    """Holder for singleton cache instance."""

    instance: SkillRelationshipCache | None = None


def get_relationship_cache() -> SkillRelationshipCache:
    """Get the singleton relationship cache.

    Returns:
        The global SkillRelationshipCache instance.

    """
    if _CacheHolder.instance is None:
        _CacheHolder.instance = SkillRelationshipCache()
    return _CacheHolder.instance


def reset_relationship_cache() -> None:
    """Reset the singleton cache (for testing)."""
    _CacheHolder.instance = None
