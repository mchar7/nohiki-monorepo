"""Skill service with Redis caching for high-traffic skill lookups."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from uuid import UUID

from nohiki_observability import get_logger
from nohiki_redis_utils import RedisCache, cached, create_cache
from sqlalchemy import case, func, or_, select

from bff_service.core.config import get_settings
from bff_service.db.models import SkillProjection
from bff_service.services.models import SkillDetail

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

settings = get_settings()
_cache = create_cache(settings.service_name, redis_url=settings.redis.connection_string)

SKILL_SEARCH_TTL = 300
SKILL_BATCH_TTL = 600
SKILL_CATEGORIES_TTL = 1800
SKILL_SEARCH_CANDIDATE_LIMIT = 500
_SEARCH_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_LIKE_ESCAPE = "\\"


def _escape_like(value: str) -> str:
    """Escape PostgreSQL LIKE metacharacters for literal matching."""
    return value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", r"\%").replace("_", r"\_")


def _get_cache() -> RedisCache:
    return _cache


def _search_key_builder(prefix: str, args: tuple[Any, ...], _kwargs: dict[str, Any]) -> str:
    """Build cache key from query params only, excluding the db session."""
    query, limit, category = args[0], args[1], args[2]
    parts = [prefix, str(query).lower(), str(limit)]
    if category:
        parts.append(category)
    return ":".join(parts)


def _batch_key_builder(prefix: str, args: tuple[Any, ...], _kwargs: dict[str, Any]) -> str:
    """Build cache key from skill IDs key, excluding the db session."""
    skill_ids_key = args[0]
    return f"{prefix}:{skill_ids_key}"


def _categories_key_builder(prefix: str, _args: tuple[Any, ...], _kwargs: dict[str, Any]) -> str:
    """Build cache key for categories, excluding the db session."""
    return prefix


def _prefix_tsquery(query: str) -> str:
    """Build a safe prefix tsquery from user-entered words."""
    return " & ".join(f"{token}:*" for token in _SEARCH_TOKEN_RE.findall(query.casefold()))


def _skill_to_detail(s: SkillProjection) -> SkillDetail:
    """Convert a SkillProjection ORM instance to a typed SkillDetail."""
    return SkillDetail(
        id=str(s.id),
        name=s.normalized_text,
        display_name=s.display_name,
        description=s.description,
        category=s.category,
        reuse_level=s.reuse_level,
    )


@cached(
    key_prefix="skill:search:v4",
    ttl=SKILL_SEARCH_TTL,
    cache_factory=_get_cache,
    key_builder=_search_key_builder,
)
async def search_skills_cached(
    query: str,
    limit: int,
    category: str | None,
    db: AsyncSession,
) -> list[SkillDetail]:
    """Search canonical skills using deterministic label-first relevance."""
    normalized_query = query.casefold().strip()
    tsquery_text = _prefix_tsquery(normalized_query)
    if not normalized_query or not tsquery_text:
        return []

    preferred_label = func.lower(func.coalesce(SkillProjection.display_name, SkillProjection.normalized_text))
    canonical_label = func.lower(SkillProjection.normalized_text)
    prefix_pattern = f"{_escape_like(normalized_query)}%"
    # PostgreSQL's word-boundary marker keeps token-prefix matches ahead of
    # incidental description/category FTS matches without rescoring in Python.
    token_pattern = rf"(^|\W){re.escape(normalized_query)}"
    ts_query = func.to_tsquery("english", tsquery_text)
    relevance_tier = case(
        (or_(preferred_label == normalized_query, canonical_label == normalized_query), 0),
        (
            or_(
                preferred_label.like(prefix_pattern, escape=_LIKE_ESCAPE),
                canonical_label.like(prefix_pattern, escape=_LIKE_ESCAPE),
            ),
            1,
        ),
        (or_(preferred_label.op("~")(token_pattern), canonical_label.op("~")(token_pattern)), 2),
        else_=3,
    )
    single_token_tier = case((func.strpos(SkillProjection.normalized_text, " ") == 0, 0), else_=1)
    reuse_tier = case(
        (SkillProjection.reuse_level == "transversal", 0),
        (SkillProjection.reuse_level == "cross-sector", 1),
        (SkillProjection.reuse_level == "sector-specific", 2),
        (SkillProjection.reuse_level == "occupation-specific", 3),
        else_=4,
    )

    candidate_stmt = select(SkillProjection.id).where(
        or_(
            preferred_label.like(prefix_pattern, escape=_LIKE_ESCAPE),
            canonical_label.like(prefix_pattern, escape=_LIKE_ESCAPE),
            SkillProjection.search_vector.op("@@")(ts_query),
        )
    )
    if category:
        candidate_stmt = candidate_stmt.where(SkillProjection.category == category)
    candidates = (
        candidate_stmt.order_by(
            relevance_tier,
            single_token_tier,
            reuse_tier,
            func.length(func.coalesce(SkillProjection.display_name, SkillProjection.normalized_text)),
            (SkillProjection.job_count + SkillProjection.profile_count).desc(),
            SkillProjection.normalized_text,
            SkillProjection.id,
        )
        .limit(SKILL_SEARCH_CANDIDATE_LIMIT)
        .cte("skill_search_candidates")
    )

    stmt = (
        select(SkillProjection)
        .join(candidates, candidates.c.id == SkillProjection.id)
        .order_by(
            relevance_tier,
            single_token_tier,
            reuse_tier,
            func.length(func.coalesce(SkillProjection.display_name, SkillProjection.normalized_text)),
            (SkillProjection.job_count + SkillProjection.profile_count).desc(),
            SkillProjection.normalized_text,
            SkillProjection.id,
        )
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [_skill_to_detail(skill) for skill in result.scalars().all()]


@cached(
    key_prefix="skill:batch",
    ttl=SKILL_BATCH_TTL,
    cache_factory=_get_cache,
    key_builder=_batch_key_builder,
)
async def get_skills_by_ids_cached(
    _skill_ids_key: str,
    skill_ids: list[str],
    db: AsyncSession,
) -> list[SkillDetail]:
    """Get multiple skills by their IDs with caching.

    Args:
        skill_ids_key: Sorted, joined skill IDs for cache key stability
        skill_ids: List of skill UUID strings
        db: Database session

    Results are cached by sorted skill IDs for 10 minutes.

    """
    if not skill_ids:
        return []

    skill_uuids = []
    for sid in skill_ids:
        try:
            skill_uuids.append(UUID(sid))
        except ValueError:
            continue

    if not skill_uuids:
        return []

    stmt = select(SkillProjection).where(SkillProjection.id.in_(skill_uuids))
    result = await db.execute(stmt)
    skills = result.scalars().all()

    return [_skill_to_detail(s) for s in skills]


@cached(
    key_prefix="skill:categories",
    ttl=SKILL_CATEGORIES_TTL,
    cache_factory=_get_cache,
    key_builder=_categories_key_builder,
)
async def get_skill_categories_cached(db: AsyncSession) -> list[str]:
    """Get all skill categories with caching.

    Categories are cached for 30 minutes since they rarely change.
    """
    stmt = (
        select(SkillProjection.category)
        .where(SkillProjection.category.isnot(None))
        .distinct()
        .order_by(SkillProjection.category)
    )
    result = await db.execute(stmt)
    categories = result.scalars().all()
    return [c for c in categories if c]
