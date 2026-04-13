"""Unit tests for SkillRelationshipCache."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from job_correlation_evaluation_service.services.scoring.skill_relationship_cache import (
    SkillRelationshipCache,
    SkillRelationshipData,
    get_relationship_cache,
    reset_relationship_cache,
)
from nohiki.skill.v1 import SkillRelationshipType


class TestSkillRelationshipData:
    """Tests for SkillRelationshipData dataclass."""

    def test_dataclass_is_frozen(self) -> None:
        """Test dataclass is immutable via introspection."""
        import dataclasses

        assert dataclasses.is_dataclass(SkillRelationshipData)
        params = getattr(SkillRelationshipData, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True
        assert params.slots is True

    def test_dataclass_has_slots(self) -> None:
        """Test dataclass uses slots."""
        data = SkillRelationshipData(
            skill_id="python",
            related_skill_id="django",
            relationship_type=SkillRelationshipType.PARENT_OF,
            strength=0.9,
        )
        assert hasattr(data, "__slots__")


class TestSkillRelationshipCacheAdd:
    """Tests for adding relationships to cache."""

    def test_add_requires_relationship(self) -> None:
        """Test adding REQUIRES relationship."""
        cache = SkillRelationshipCache()
        cache.add_relationship(
            source_id="react",
            target_id="javascript",
            relationship_type=SkillRelationshipType.REQUIRES,
        )
        assert cache.relationship_count == 1

    def test_add_parent_of_relationship(self) -> None:
        """Test adding PARENT_OF relationship."""
        cache = SkillRelationshipCache()
        cache.add_relationship(
            source_id="python",
            target_id="django",
            relationship_type=SkillRelationshipType.PARENT_OF,
        )
        assert cache.relationship_count == 1

    def test_add_related_to_relationship(self) -> None:
        """Test adding RELATED_TO relationship."""
        cache = SkillRelationshipCache()
        cache.add_relationship(
            source_id="java",
            target_id="kotlin",
            relationship_type=SkillRelationshipType.RELATED_TO,
        )
        assert cache.relationship_count == 1

    def test_add_multiple_relationships_same_source(self) -> None:
        """Test adding multiple relationships from same source."""
        cache = SkillRelationshipCache()
        cache.add_relationship("python", "django", SkillRelationshipType.PARENT_OF)
        cache.add_relationship("python", "flask", SkillRelationshipType.PARENT_OF)
        cache.add_relationship("python", "fastapi", SkillRelationshipType.PARENT_OF)
        assert cache.relationship_count == 3


class TestSkillRelationshipCacheGetImplied:
    """Tests for getting implied skills."""

    def test_get_implied_skills_requires(self) -> None:
        """Test getting implied skills from REQUIRES relationship."""
        cache = SkillRelationshipCache()
        cache.add_relationship("react", "javascript", SkillRelationshipType.REQUIRES)

        implied = cache.get_implied_skills("react")
        assert "javascript" in implied

    def test_get_implied_skills_parent_of(self) -> None:
        """Test getting implied skills from PARENT_OF relationship."""
        cache = SkillRelationshipCache()
        cache.add_relationship("python", "django", SkillRelationshipType.PARENT_OF)
        cache.add_relationship("python", "flask", SkillRelationshipType.PARENT_OF)

        implied = cache.get_implied_skills("python")
        assert "django" in implied
        assert "flask" in implied

    def test_get_implied_skills_unknown_skill(self) -> None:
        """Test getting implied skills for unknown skill returns empty set."""
        cache = SkillRelationshipCache()
        cache.add_relationship("react", "javascript", SkillRelationshipType.REQUIRES)

        implied = cache.get_implied_skills("unknown")
        assert len(implied) == 0
        assert implied == frozenset()

    def test_get_implied_skills_returns_frozenset(self) -> None:
        """Test get_implied_skills returns frozenset."""
        cache = SkillRelationshipCache()
        cache.add_relationship("react", "javascript", SkillRelationshipType.REQUIRES)

        implied = cache.get_implied_skills("react")
        assert isinstance(implied, frozenset)


class TestSkillRelationshipCacheExpand:
    """Tests for expanding user skills."""

    def test_expand_includes_original_skills(self) -> None:
        """Test expanded skills include original skills."""
        cache = SkillRelationshipCache()
        cache.add_relationship("react", "javascript", SkillRelationshipType.REQUIRES)

        original = frozenset(["react", "python"])
        expanded = cache.expand_user_skills(original)

        assert "react" in expanded
        assert "python" in expanded

    def test_expand_includes_implied_skills(self) -> None:
        """Test expanded skills include implied skills."""
        cache = SkillRelationshipCache()
        cache.add_relationship("react", "javascript", SkillRelationshipType.REQUIRES)
        cache.add_relationship("python", "django", SkillRelationshipType.PARENT_OF)

        original = frozenset(["react", "python"])
        expanded = cache.expand_user_skills(original)

        assert "javascript" in expanded
        assert "django" in expanded

    def test_expand_no_relationships(self) -> None:
        """Test expanding with no relationships returns original."""
        cache = SkillRelationshipCache()

        original = frozenset(["react", "python"])
        expanded = cache.expand_user_skills(original)

        assert expanded == original

    def test_expand_returns_frozenset(self) -> None:
        """Test expand_user_skills returns frozenset."""
        cache = SkillRelationshipCache()

        original = frozenset(["react"])
        expanded = cache.expand_user_skills(original)

        assert isinstance(expanded, frozenset)

    def test_expand_complex_relationships(self) -> None:
        """Test expansion with complex relationship graph."""
        cache = SkillRelationshipCache()
        cache.add_relationship("react", "javascript", SkillRelationshipType.REQUIRES)
        cache.add_relationship("nextjs", "react", SkillRelationshipType.REQUIRES)
        cache.add_relationship("python", "django", SkillRelationshipType.PARENT_OF)
        cache.add_relationship("python", "flask", SkillRelationshipType.PARENT_OF)

        original = frozenset(["react", "python"])
        expanded = cache.expand_user_skills(original)

        assert "react" in expanded
        assert "python" in expanded
        assert "javascript" in expanded
        assert "django" in expanded
        assert "flask" in expanded


class TestSkillRelationshipCacheProperties:
    """Tests for cache properties."""

    def test_relationship_count_empty(self) -> None:
        """Test relationship count on empty cache."""
        cache = SkillRelationshipCache()
        assert cache.relationship_count == 0

    def test_relationship_count_after_adds(self) -> None:
        """Test relationship count after adding relationships."""
        cache = SkillRelationshipCache()
        cache.add_relationship("a", "b", SkillRelationshipType.REQUIRES)
        cache.add_relationship("c", "d", SkillRelationshipType.PARENT_OF)
        cache.add_relationship("e", "f", SkillRelationshipType.RELATED_TO)

        assert cache.relationship_count == 3


class TestAddRelationshipsBatch:
    """Tests for batch adding relationships."""

    def test_add_relationships_from_iterable(self) -> None:
        """Test adding multiple relationships from iterable."""
        cache = SkillRelationshipCache()
        relationships = [
            SkillRelationshipData("react", "js", SkillRelationshipType.REQUIRES, 1.0),
            SkillRelationshipData("python", "django", SkillRelationshipType.PARENT_OF, 0.9),
            SkillRelationshipData("java", "kotlin", SkillRelationshipType.RELATED_TO, 0.8),
        ]
        cache.add_relationships(relationships)

        assert cache.relationship_count == 3
        assert "js" in cache.get_implied_skills("react")
        assert "django" in cache.get_implied_skills("python")


class TestGetRelatedSkills:
    """Tests for get_related_skills method."""

    def test_get_related_skills_exists(self) -> None:
        """Test getting related skills when they exist."""
        cache = SkillRelationshipCache()
        cache.add_relationship("java", "kotlin", SkillRelationshipType.RELATED_TO)
        cache.add_relationship("java", "scala", SkillRelationshipType.RELATED_TO)

        related = cache.get_related_skills("java")

        assert "kotlin" in related
        assert "scala" in related
        assert isinstance(related, frozenset)

    def test_get_related_skills_empty(self) -> None:
        """Test getting related skills when none exist."""
        cache = SkillRelationshipCache()

        related = cache.get_related_skills("unknown")

        assert related == frozenset()


class TestCacheClear:
    """Tests for cache clear method."""

    def test_clear_removes_all_relationships(self) -> None:
        """Test clear removes all relationships."""
        cache = SkillRelationshipCache()
        cache.add_relationship("a", "b", SkillRelationshipType.REQUIRES)
        cache.add_relationship("c", "d", SkillRelationshipType.PARENT_OF)
        cache.add_relationship("e", "f", SkillRelationshipType.RELATED_TO)

        assert cache.relationship_count == 3

        cache.clear()

        assert cache.relationship_count == 0
        assert cache.get_implied_skills("a") == frozenset()
        assert cache.get_related_skills("e") == frozenset()


class TestSingletonFunctions:
    """Tests for singleton cache functions."""

    def test_get_relationship_cache_returns_instance(self) -> None:
        """Test get_relationship_cache returns an instance."""
        reset_relationship_cache()
        cache = get_relationship_cache()
        assert isinstance(cache, SkillRelationshipCache)

    def test_get_relationship_cache_returns_same_instance(self) -> None:
        """Test get_relationship_cache returns the same instance."""
        reset_relationship_cache()
        cache1 = get_relationship_cache()
        cache2 = get_relationship_cache()
        assert cache1 is cache2

    def test_reset_relationship_cache_creates_new_instance(self) -> None:
        """Test reset_relationship_cache creates a new instance."""
        reset_relationship_cache()
        cache1 = get_relationship_cache()
        cache1.add_relationship("a", "b", SkillRelationshipType.REQUIRES)

        reset_relationship_cache()
        cache2 = get_relationship_cache()

        assert cache2.relationship_count == 0
        assert cache1 is not cache2


class TestSkillRelationshipCacheRedisOperations:
    """Tests for Redis cache operations."""

    @pytest.mark.asyncio
    async def test_load_from_redis_cache_miss(self) -> None:
        """Test load_from_redis returns False on cache miss."""
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)

        cache = SkillRelationshipCache(cache=mock_cache)
        result = await cache.load_from_redis()

        assert result is False

    @pytest.mark.asyncio
    async def test_load_from_redis_success(self) -> None:
        """Test load_from_redis loads data successfully."""
        from unittest.mock import AsyncMock, MagicMock

        mock_cache = MagicMock()
        cached_data = {
            "requires": {"react": ["javascript"]},
            "parent_of": {"python": ["django", "flask"]},
            "related_to": {"java": ["kotlin"]},
        }
        mock_cache.get = AsyncMock(return_value=json.dumps(cached_data))

        cache = SkillRelationshipCache(cache=mock_cache)
        result = await cache.load_from_redis()

        assert result is True
        assert "javascript" in cache.get_implied_skills("react")
        assert "django" in cache.get_implied_skills("python")

    @pytest.mark.asyncio
    async def test_load_from_redis_exception(self) -> None:
        """Test load_from_redis propagates exceptions."""
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(side_effect=Exception("Redis error"))

        cache = SkillRelationshipCache(cache=mock_cache)

        with pytest.raises(Exception, match="Redis error"):
            await cache.load_from_redis()

    @pytest.mark.asyncio
    async def test_save_to_redis_with_existing_cache(self) -> None:
        """Test save_to_redis saves existing relationships."""
        mock_cache = MagicMock()
        mock_cache.set = AsyncMock()

        cache = SkillRelationshipCache(cache=mock_cache)
        cache.add_relationship("react", "javascript", SkillRelationshipType.REQUIRES)

        await cache.save_to_redis()

        mock_cache.set.assert_awaited_once()
        call_args = mock_cache.set.call_args
        assert call_args[0][0] == "skill_relationships"
        saved_data = json.loads(call_args[0][1])
        assert "react" in saved_data["requires"]

    @pytest.mark.asyncio
    async def test_save_to_redis_initializes_empty_cache(self) -> None:
        """Test save_to_redis initializes empty cache when None."""
        mock_cache = MagicMock()
        mock_cache.set = AsyncMock()

        cache = SkillRelationshipCache(cache=mock_cache)
        # local_cache is None initially

        await cache.save_to_redis()

        mock_cache.set.assert_awaited_once()
        call_args = mock_cache.set.call_args
        saved_data = json.loads(call_args[0][1])
        assert saved_data == {"requires": {}, "parent_of": {}, "related_to": {}}


class TestSkillRelationshipCacheInvalidate:
    """Tests for cache invalidation."""

    @pytest.mark.asyncio
    async def test_invalidate_clears_cache(self) -> None:
        """Test invalidate clears local cache and deletes from Redis."""
        mock_cache = MagicMock()
        mock_cache.delete = AsyncMock()

        cache = SkillRelationshipCache(cache=mock_cache)
        cache.add_relationship("react", "javascript", SkillRelationshipType.REQUIRES)
        assert cache.relationship_count == 1

        await cache.invalidate()

        mock_cache.delete.assert_awaited_once_with("skill_relationships")
        assert cache.relationship_count == 0
