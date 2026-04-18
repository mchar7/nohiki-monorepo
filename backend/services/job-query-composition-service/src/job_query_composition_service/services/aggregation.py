"""Aggregation logic for scrape queries."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from nohiki.common.v1 import JobBoardSource, WorkArrangement
from nohiki_observability import get_logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from job_query_composition_service.db.models import IngestionQuery, QueryContributor

logger = get_logger(__name__)

# Frequency tier mappings
TIER_FREQUENCIES: dict[str, timedelta] = {
    "hourly": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
}


def tier_to_frequency(tier: str) -> timedelta:
    """Convert frequency tier name to timedelta.

    Args:
        tier: Tier name (hourly, 6h, daily, weekly).

    Returns:
        Corresponding timedelta.

    """
    return TIER_FREQUENCIES.get(tier, timedelta(days=1))


def _compute_aggregates_from_contributors(
    contributors: list[QueryContributor],
) -> tuple[list[WorkArrangement], list[str], list[JobBoardSource], timedelta, int]:
    """Compute aggregates from a list of contributors.

    Args:
        contributors: List of contributors (will filter to active).

    Returns:
        Tuple of (work_arrangements, remote_preferences, sources, min_frequency, active_count).

    """
    active_contributors = [c for c in contributors if c.is_active]

    work_arrangements: set[WorkArrangement] = set()
    remote_preferences: set[str] = set()
    sources: set[JobBoardSource] = set()
    min_frequency = timedelta(days=7)

    for contributor in active_contributors:
        work_arrangements.update(contributor.work_arrangements or [])
        remote_preferences.add(contributor.remote_preference)
        sources.update(contributor.sources or [])
        contributor_frequency = tier_to_frequency(contributor.frequency_tier)
        min_frequency = min(min_frequency, contributor_frequency)

    return (
        sorted(work_arrangements, key=lambda x: x.value),
        sorted(remote_preferences),
        sorted(sources, key=lambda x: x.value),
        min_frequency,
        len(active_contributors),
    )


async def recompute_query_aggregates(
    db: AsyncSession,
    query_id: UUID,
) -> IngestionQuery | None:
    """Recompute all aggregates for a query from its contributors.

    Complexity: O(n) where n = number of contributors

    This is simpler than reference counting and will be replaced
    by ML-based clustering in a future iteration.

    Args:
        db: Database session.
        query_id: Query ID to recompute.

    Returns:
        Updated IngestionQuery or None if not found.

    """
    result = await db.execute(select(QueryContributor).where(QueryContributor.query_id == query_id))
    contributors = list(result.scalars().all())

    work_arr, remote_prefs, src_list, min_freq, active_count = _compute_aggregates_from_contributors(contributors)

    query = await db.get(IngestionQuery, query_id)
    if query:
        query.work_arrangements = work_arr
        query.remote_preferences = remote_prefs
        query.sources = src_list
        query.frequency = min_freq
        query.is_active = active_count > 0
        query.active_contributor_count = active_count
        query.total_contributor_count = len(contributors)
        query.last_recomputed_at = datetime.now(UTC)
        query.updated_at = datetime.now(UTC)

        logger.info(
            "Recomputed query aggregates",
            query_id=str(query_id),
            active_contributors=active_count,
            work_arrangements=len(work_arr),
            sources=len(src_list),
        )

    return query


async def recompute_query_aggregates_batch(
    db: AsyncSession,
    query_ids: set[UUID],
) -> dict[UUID, IngestionQuery]:
    """Recompute aggregates for multiple queries in a single batch.

    Complexity: O(1) database round-trips regardless of query count.

    Args:
        db: Database session.
        query_ids: Set of query IDs to recompute.

    Returns:
        Dict mapping query_id to updated IngestionQuery.

    """
    if not query_ids:
        return {}

    result = await db.execute(select(QueryContributor).where(QueryContributor.query_id.in_(query_ids)))
    all_contributors = list(result.scalars().all())

    contributors_by_query: defaultdict[UUID, list[QueryContributor]] = defaultdict(list)
    for contributor in all_contributors:
        contributors_by_query[contributor.query_id].append(contributor)

    queries_result = await db.execute(select(IngestionQuery).where(IngestionQuery.id.in_(query_ids)))
    queries = {q.id: q for q in queries_result.scalars().all()}

    now = datetime.now(UTC)
    updated: dict[UUID, IngestionQuery] = {}

    for query_id in query_ids:
        query = queries.get(query_id)
        if not query:
            continue

        contributors = contributors_by_query.get(query_id, [])
        work_arr, remote_prefs, src_list, min_freq, active_count = _compute_aggregates_from_contributors(contributors)

        query.work_arrangements = work_arr
        query.remote_preferences = remote_prefs
        query.sources = src_list
        query.frequency = min_freq
        query.is_active = active_count > 0
        query.active_contributor_count = active_count
        query.total_contributor_count = len(contributors)
        query.last_recomputed_at = now
        query.updated_at = now

        updated[query_id] = query

    if updated:
        logger.info("Batch recomputed query aggregates", query_count=len(updated))

    return updated
