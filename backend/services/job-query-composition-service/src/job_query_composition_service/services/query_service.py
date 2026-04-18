"""Query service for managing scrape queries and contributors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from nohiki.common.v1 import JobBoardSource, WorkArrangement
from nohiki_observability import get_logger
from sqlalchemy import CursorResult, Result, Sequence, column, delete, func, select, table, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from job_query_composition_service.core.config import get_settings
from job_query_composition_service.db.models import IngestionQuery, QueryContributor
from job_query_composition_service.services.normalization import (
    canonicalize_locations,
    extract_remote_pref,
    normalize_keywords,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ContributorInput:
    """Input data for creating or updating a contributor."""

    query_id: UUID
    pref_id: UUID
    user_id: UUID
    work_arrangements: list[WorkArrangement]
    locations: list[dict[str, Any]]
    sources: list[JobBoardSource]
    frequency_tier: str
    is_active: bool


async def get_query_by_id(db: AsyncSession, query_id: UUID) -> IngestionQuery | None:
    """Get a scrape query by ID.

    Args:
        db: Database session.
        query_id: Query ID.

    Returns:
        IngestionQuery or None if not found.

    """
    return await db.get(IngestionQuery, query_id)


async def get_queries_by_ids(db: AsyncSession, query_ids: set[UUID]) -> dict[UUID, IngestionQuery]:
    """Get multiple scrape queries by IDs in a single batch query.

    Uses O(1) database round-trip instead of O(N) individual fetches.

    Args:
        db: Database session.
        query_ids: Set of query IDs to fetch.

    Returns:
        Dict mapping query_id to IngestionQuery for found queries.

    """
    if not query_ids:
        return {}

    result: Result[tuple[IngestionQuery]] = await db.execute(
        select(IngestionQuery).where(IngestionQuery.id.in_(query_ids))
    )
    queries: Sequence[IngestionQuery] = result.scalars().all()
    return {query.id: query for query in queries}


async def find_or_create_query(
    db: AsyncSession,
    search_keywords: list[str],
    locations: list[dict[str, Any]],
) -> IngestionQuery:
    """Find or create a scrape query for the given keywords and locations.

    Args:
        db: Database session.
        search_keywords: Search keywords (will be normalized).
        locations: Locations (will be canonicalized).

    Returns:
        Existing or new IngestionQuery.

    """
    # Normalize the dedupe key
    normalized_keywords = normalize_keywords(search_keywords)
    canonical_locations = canonicalize_locations(locations)

    # Look for existing query with same keywords and locations
    # We need to compare as JSON since JSONB comparison needs exact correlation
    locations_json = canonical_locations

    result = await db.execute(
        select(IngestionQuery).where(
            IngestionQuery.search_keywords == normalized_keywords,
            IngestionQuery.locations == locations_json,
        )
    )
    query = result.scalar_one_or_none()

    if query:
        logger.debug("Found existing query", query_id=str(query.id))
        return query

    query = IngestionQuery(search_keywords=normalized_keywords, locations=canonical_locations)
    try:
        async with db.begin_nested():
            db.add(query)
            await db.flush()
    except IntegrityError:
        result = await db.execute(
            select(IngestionQuery).where(
                IngestionQuery.search_keywords == normalized_keywords,
                IngestionQuery.locations == canonical_locations,
            )
        )
        query = result.scalar_one()
        logger.debug("Concurrent canonical query won", query_id=str(query.id))
        return query

    logger.info("Created new scrape query", query_id=str(query.id), keywords=normalized_keywords)
    return query


async def create_or_update_contributor(
    db: AsyncSession,
    data: ContributorInput,
) -> QueryContributor:
    """Create or update a contributor record.

    Args:
        db: Database session.
        data: Contributor input data.

    Returns:
        Created or updated QueryContributor.

    """
    result = await db.execute(select(QueryContributor).where(QueryContributor.pref_id == data.pref_id))
    contributor = result.scalar_one_or_none()
    remote_pref = extract_remote_pref(data.locations)

    if contributor is not None:
        previous_query_id = contributor.query_id if contributor.query_id != data.query_id else None
        contributor.query_id = data.query_id
        contributor.user_id = data.user_id
        contributor.work_arrangements = data.work_arrangements
        contributor.remote_preference = remote_pref
        contributor.sources = data.sources
        contributor.frequency_tier = data.frequency_tier
        contributor.is_active = data.is_active
        contributor.updated_at = datetime.now(UTC)
        contributor.previous_query_id = previous_query_id
        logger.debug("Updated contributor", pref_id=str(data.pref_id), query_id=str(data.query_id))
    else:
        contributor = QueryContributor(
            query_id=data.query_id,
            pref_id=data.pref_id,
            user_id=data.user_id,
            work_arrangements=data.work_arrangements,
            remote_preference=remote_pref,
            sources=data.sources,
            frequency_tier=data.frequency_tier,
            is_active=data.is_active,
        )
        db.add(contributor)
        logger.info("Created contributor", pref_id=str(data.pref_id), query_id=str(data.query_id))

    await db.flush()
    return contributor


async def delete_contributor(
    db: AsyncSession,
    pref_id: UUID,
) -> tuple[UUID | None, bool]:
    """Delete a contributor and return its query_id.

    Args:
        db: Database session.
        pref_id: Profile ID to delete.

    Returns:
        Tuple of (query_id, is_last_contributor).
        query_id is None if contributor not found.

    """
    # Find the contributor
    result = await db.execute(select(QueryContributor).where(QueryContributor.pref_id == pref_id))
    contributor = result.scalar_one_or_none()

    if not contributor:
        return None, False

    query_id = contributor.query_id

    # Delete the contributor
    await db.execute(delete(QueryContributor).where(QueryContributor.pref_id == pref_id))

    # Check remaining contributors
    remaining = await db.scalar(
        select(func.count()).select_from(QueryContributor).where(QueryContributor.query_id == query_id)
    )

    is_last = remaining == 0

    logger.info(
        "Deleted contributor",
        pref_id=str(pref_id),
        query_id=str(query_id),
        is_last_contributor=is_last,
    )

    return query_id, is_last


async def delete_query(db: AsyncSession, query_id: UUID) -> bool:
    """Delete a query.

    Args:
        db: Database session.
        query_id: Query ID to delete.

    Returns:
        True if deleted, False if not found.

    """
    query = await db.get(IngestionQuery, query_id)
    if not query:
        return False

    await db.delete(query)
    logger.info("Deleted query", query_id=str(query_id))
    return True


async def update_contributor_frequency(
    db: AsyncSession,
    user_id: UUID,
    frequency_tier: str,
) -> list[UUID]:
    """Update frequency tier for all contributors of a user.

    Uses bulk UPDATE for O(1) database round-trip instead of O(N) ORM updates.

    Args:
        db: Database session.
        user_id: Account ID.
        frequency_tier: New frequency tier.

    Returns:
        List of affected query IDs.

    """
    now = datetime.now(UTC)

    result: Result[tuple[UUID]] = await db.execute(
        select(QueryContributor.query_id).where(QueryContributor.user_id == user_id)
    )
    affected_query_ids = list({row[0] for row in result.fetchall()})

    if not affected_query_ids:
        return []

    await db.execute(
        update(QueryContributor)
        .where(QueryContributor.user_id == user_id)
        .values(frequency_tier=frequency_tier, updated_at=now)
    )

    logger.info(
        "Updated contributor frequencies",
        user_id=str(user_id),
        frequency_tier=frequency_tier,
        affected_queries=len(affected_query_ids),
    )

    return affected_query_ids


async def set_user_inactive(db: AsyncSession, user_id: UUID) -> list[UUID]:
    """Set all contributors for a user as inactive.

    Uses bulk UPDATE for O(1) database round-trip instead of O(N) ORM updates.

    Args:
        db: Database session.
        user_id: Account ID.

    Returns:
        List of affected query IDs.

    """
    now = datetime.now(UTC)

    result: Result[tuple[UUID]] = await db.execute(
        select(QueryContributor.query_id).where(
            QueryContributor.user_id == user_id,
            QueryContributor.is_active.is_(True),
        )
    )
    affected_query_ids = list({row[0] for row in result.fetchall()})

    if not affected_query_ids:
        return []

    await db.execute(
        update(QueryContributor)
        .where(QueryContributor.user_id == user_id, QueryContributor.is_active.is_(True))
        .values(is_active=False, updated_at=now)
    )

    logger.info("Set user inactive", user_id=str(user_id), affected_queries=len(affected_query_ids))

    return affected_query_ids


async def delete_user_contributions(db: AsyncSession, user_id: UUID) -> set[UUID]:
    """Delete all contributions for a user and decrement affected query counts."""
    schema = get_settings().database.schema_name
    contributors = table(
        "query_contributors",
        column("query_id"),
        column("user_id"),
        schema=schema,
    )
    queries = table(
        "ingestion_queries",
        column("id"),
        column("total_contributor_count"),
        schema=schema,
    )

    result = await db.execute(select(contributors.c.query_id).where(contributors.c.user_id == user_id))
    affected_query_ids = {row[0] for row in result.fetchall()}
    if not affected_query_ids:
        return set()

    deleted = (
        delete(contributors).where(contributors.c.user_id == user_id).returning(contributors.c.query_id).cte("deleted")
    )
    removed = select(deleted.c.query_id, func.count().label("count")).group_by(deleted.c.query_id).cte("removed")
    statement = (
        update(queries)
        .where(queries.c.id == removed.c.query_id)
        .values(
            total_contributor_count=func.greatest(
                queries.c.total_contributor_count - removed.c.count,
                0,
            )
        )
    )
    delete_result = await db.execute(statement)
    deleted_count = cast(CursorResult[Any], delete_result).rowcount or 0

    await db.flush()
    logger.info("Deleted user contributions", user_id=str(user_id), count=deleted_count)
    return affected_query_ids


async def set_user_active(db: AsyncSession, user_id: UUID) -> list[UUID]:
    """Reactivate all contributors for a user.

    Uses bulk UPDATE for O(1) database round-trip instead of O(N) ORM updates.

    Args:
        db: Database session.
        user_id: Account ID.

    Returns:
        List of affected query IDs.

    """
    now = datetime.now(UTC)

    result = await db.execute(
        select(QueryContributor.query_id).where(
            QueryContributor.user_id == user_id,
            QueryContributor.is_active.is_(False),
        )
    )
    affected_query_ids = list({row[0] for row in result.fetchall()})

    if not affected_query_ids:
        return []

    await db.execute(
        update(QueryContributor)
        .where(QueryContributor.user_id == user_id, QueryContributor.is_active.is_(False))
        .values(is_active=True, updated_at=now)
    )

    logger.info("Reactivated user", user_id=str(user_id), affected_queries=len(affected_query_ids))

    return affected_query_ids
