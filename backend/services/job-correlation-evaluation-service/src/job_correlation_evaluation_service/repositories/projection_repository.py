"""Repository for projection table operations with cache-aside pattern.

Cache Strategy: Cache-Aside (Lazy Loading)
- Read: Check Redis cache → if miss, query PostgreSQL → populate cache → return
- Write: Write to PostgreSQL → invalidate cache

PostgreSQL is the source of truth. Redis is a read-through cache layer
that reduces database load for the frequently-accessed active profiles list.
Cache invalidation occurs on every profile create/update/delete.
"""

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_observability import get_logger
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from job_correlation_evaluation_service.core.cache import get_cache
from job_correlation_evaluation_service.core.config import get_settings
from job_correlation_evaluation_service.db.models import ProfileProjection

if TYPE_CHECKING:
    from nohiki_redis_utils import RedisCache
    from sqlalchemy.ext.asyncio import AsyncSession

    from job_correlation_evaluation_service.core.config import Settings


logger = get_logger(__name__)

ACTIVE_PROFILES_CACHE_KEY = "active_profiles"


class ProfileProjectionRepository:
    """Repository for profile projection CRUD with cache-aside pattern.

    PostgreSQL is the source of truth. Redis provides caching for
    get_active_profiles() which is called on every job event.
    """

    def __init__(
        self,
        session: AsyncSession,
        cache: RedisCache | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Initialize with database session and optional cache.

        Args:
            session: SQLAlchemy async session for DB operations.
            cache: Redis cache instance. Uses get_cache() if not provided.
            settings: Settings instance. Uses get_settings() if not provided.

        """
        self._session = session
        self._cache = cache
        self._settings = settings
        self._cache_initialized = False

    def _get_cache(self) -> RedisCache:
        """Lazy-initialize cache to avoid import-time side effects."""
        if self._cache is None:
            self._cache = get_cache()
        return self._cache

    def _get_ttl(self) -> int:
        """Get cache TTL from settings."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings.caching.active_profiles_ttl

    async def get_active_profiles(self) -> list[SearchPrefSnapshot]:
        """Get all active profiles using cache-aside pattern.

        1. Check Redis cache
        2. If cache hit, return cached profiles
        3. If cache miss, query PostgreSQL
        4. Populate cache with result
        5. Return profiles

        Returns:
            List of SearchPrefSnapshot protos.

        """
        cached = await self._try_get_from_cache()
        if cached is not None:
            return cached

        profiles = await self._fetch_from_database()
        await self._populate_cache(profiles)
        return profiles

    async def _try_get_from_cache(self) -> list[SearchPrefSnapshot] | None:
        """Attempt to get active profiles from Redis cache."""
        try:
            cache = self._get_cache()
            cached = await cache.get(ACTIVE_PROFILES_CACHE_KEY)
        except OSError:
            logger.warning("Cache connection failed, falling back to database")
            return None

        if cached is None:
            logger.debug("Active profiles cache miss")
            return None

        try:
            profiles_data: list[dict[str, object]] = json.loads(str(cached))
            profiles = [SearchPrefSnapshot.from_dict(p) for p in profiles_data]
        except json.JSONDecodeError, TypeError, KeyError:
            logger.warning("Cache data corrupted, falling back to database")
            return None

        logger.debug("Active profiles cache hit", count=len(profiles))
        return profiles

    async def _fetch_from_database(self) -> list[SearchPrefSnapshot]:
        """Fetch active profiles from PostgreSQL."""
        result = await self._session.execute(select(ProfileProjection).where(ProfileProjection.is_active.is_(True)))
        projections = result.scalars().all()

        profiles = [self._reconstruct_snapshot(proj.snapshot_data) for proj in projections]
        logger.debug("Retrieved active profiles from database", count=len(profiles))
        return profiles

    async def _populate_cache(self, profiles: list[SearchPrefSnapshot]) -> None:
        """Populate Redis cache with profiles."""
        try:
            cache = self._get_cache()
            profiles_data = [p.to_dict() for p in profiles]
            await cache.set(
                ACTIVE_PROFILES_CACHE_KEY,
                json.dumps(profiles_data),
                ttl=self._get_ttl(),
            )
            logger.debug("Active profiles cached", count=len(profiles), ttl=self._get_ttl())
        except OSError:
            logger.warning("Cache write failed - connection error")

    async def invalidate_cache(self) -> None:
        """Invalidate active profiles cache.

        Called after any profile create/update/delete to ensure
        consistency between PostgreSQL (source of truth) and Redis cache.
        """
        try:
            cache = self._get_cache()
            await cache.delete(ACTIVE_PROFILES_CACHE_KEY)
            logger.debug("Active profiles cache invalidated")
        except OSError:
            logger.warning("Cache invalidation failed - connection error")

    async def get_profile(self, pref_id: uuid.UUID) -> SearchPrefSnapshot | None:
        """Get a specific profile by ID.

        Args:
            pref_id: The profile ID to fetch.

        Returns:
            The SearchPrefSnapshot proto, or None if not found.

        """
        result = await self._session.execute(
            select(ProfileProjection).where(
                ProfileProjection.id == pref_id,
                ProfileProjection.is_active.is_(True),
            )
        )
        projection = result.scalar_one_or_none()

        if projection is None:
            return None

        return self._reconstruct_snapshot(projection.snapshot_data)

    async def upsert_profile(self, profile: SearchPrefSnapshot, source_revision: datetime) -> bool:
        """Store a profile only when its source revision advances.

        Returns ``True`` when the projection changed. PostgreSQL evaluates the
        revision predicate atomically with the upsert, so concurrent duplicate
        or reordered CDC deliveries cannot replace newer state.
        """
        profile_id = uuid.UUID(profile.id)
        user_id = uuid.UUID(profile.user_id)

        stmt = pg_insert(ProfileProjection).values(
            id=profile_id,
            user_id=user_id,
            profile_name=profile.pref_name,
            is_active=profile.is_active,
            source_revision=source_revision,
            snapshot_data=profile.to_dict(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ProfileProjection.id],
            set_={
                "user_id": stmt.excluded.user_id,
                "profile_name": stmt.excluded.profile_name,
                "is_active": stmt.excluded.is_active,
                "source_revision": stmt.excluded.source_revision,
                "snapshot_data": stmt.excluded.snapshot_data,
                "updated_at": func.now(),
            },
            where=stmt.excluded.source_revision > ProfileProjection.source_revision,
        ).returning(ProfileProjection.id)
        result = await self._session.execute(stmt)
        changed = result.scalar_one_or_none() is not None

        logger.debug(
            "Applied profile projection revision" if changed else "Ignored stale profile projection revision",
            pref_id=str(profile_id),
            source_revision=source_revision.isoformat(),
        )
        return changed

    async def tombstone_profile(
        self,
        pref_id: uuid.UUID,
        user_id: uuid.UUID,
        source_revision: datetime,
    ) -> bool:
        """Persist a deletion revision so delayed CDC cannot resurrect state."""
        stmt = pg_insert(ProfileProjection).values(
            id=pref_id,
            user_id=user_id,
            profile_name="<deleted>",
            is_active=False,
            source_revision=source_revision,
            snapshot_data={},
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ProfileProjection.id],
            set_={
                "user_id": stmt.excluded.user_id,
                "is_active": False,
                "source_revision": stmt.excluded.source_revision,
                "updated_at": func.now(),
            },
            where=stmt.excluded.source_revision >= ProfileProjection.source_revision,
        ).returning(ProfileProjection.id)
        result = await self._session.execute(stmt)
        changed = result.scalar_one_or_none() is not None
        logger.debug(
            "Applied profile deletion tombstone" if changed else "Ignored stale profile deletion",
            pref_id=str(pref_id),
            source_revision=source_revision.isoformat(),
        )
        return changed

    def _reconstruct_snapshot(self, snapshot_data: dict[str, object]) -> SearchPrefSnapshot:
        """Reconstruct SearchPrefSnapshot from JSONB data.

        betterproto supports from_dict for reconstruction.
        """
        return SearchPrefSnapshot.from_dict(snapshot_data)
