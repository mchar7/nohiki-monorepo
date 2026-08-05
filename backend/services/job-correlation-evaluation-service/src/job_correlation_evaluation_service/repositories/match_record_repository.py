"""Repository for recording job match correlations."""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from nohiki.common.v1 import CorrelationStatus
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import InstrumentedAttribute

from job_correlation_evaluation_service.db.models import Correlation
from job_correlation_evaluation_service.services.match_types import JobMatchResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

BATCH_INSERT_SIZE = 25


def _chunked[T](items: Sequence[T], size: int) -> Iterator[list[T]]:
    """Yield successive chunks of `size` from `items`."""
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def _build_correlation_record(
    result: JobMatchResult,
    user_uuid: uuid.UUID,
) -> dict[str, object]:
    """Build a correlation record dict for database insertion."""
    return {
        "id": result.correlation_id,
        "pref_id": uuid.UUID(result.pref_id),
        "listing_id": uuid.UUID(result.listing_id),
        "user_id": user_uuid,
        "listing_url": result.listing_url,
        "correlation_score": result.score,
        "correlation_status": result.status,
        "evaluated_at": result.evaluated_at,
        "feature_vector": list(result.feature_vector) if result.feature_vector is not None else None,
        "feature_schema_version": result.feature_schema_version,
    }


class MatchRecordRepository:
    """Repository for recording match results in the database.

    Handles all database operations for job match correlations.
    Uses batch operations where possible for efficiency.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: Async SQLAlchemy session for database operations.

        """
        self._db = db
        self._last_inserted_listing_ids: set[str] = set()

    @property
    def last_inserted_listing_ids(self) -> set[str]:
        """Listing IDs inserted by the latest batch write."""
        return self._last_inserted_listing_ids

    async def exists(self, pref_id: str, listing_id: str) -> bool:
        """Check if a correlation already exists for a pref/listing pair.

        Args:
            pref_id: User preference ID.
            listing_id: Job listing ID.

        Returns:
            True if correlation exists, False otherwise.

        """
        stmt = (
            select(Correlation.id)
            .where(
                Correlation.pref_id == uuid.UUID(pref_id),
                Correlation.listing_id == uuid.UUID(listing_id),
            )
            .limit(1)
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_existing_listing_ids(
        self,
        pref_id: str,
        listing_ids: list[str],
    ) -> set[str]:
        """Get listing IDs that already have correlations for a pref.

        Args:
            pref_id: User preference ID.
            listing_ids: List of listing IDs to check.

        Returns:
            Set of listing IDs that already have correlations.

        """
        return await self._get_existing_ids(
            fixed_column=Correlation.pref_id,
            fixed_value=pref_id,
            batch_column=Correlation.listing_id,
            batch_ids=listing_ids,
        )

    async def get_existing_pref_ids(
        self,
        listing_id: str,
        pref_ids: list[str],
    ) -> set[str]:
        """Get pref IDs that already have correlations for a listing.

        Args:
            listing_id: Job listing ID.
            pref_ids: List of preference IDs to check.

        Returns:
            Set of pref IDs that already have correlations.

        """
        return await self._get_existing_ids(
            fixed_column=Correlation.listing_id,
            fixed_value=listing_id,
            batch_column=Correlation.pref_id,
            batch_ids=pref_ids,
        )

    async def _get_existing_ids(
        self,
        fixed_column: InstrumentedAttribute[uuid.UUID],
        fixed_value: str,
        batch_column: InstrumentedAttribute[uuid.UUID],
        batch_ids: list[str],
    ) -> set[str]:
        """Query for existing correlation IDs on a fixed+batch column pair."""
        if not batch_ids:
            return set()

        batch_uuids = [uuid.UUID(bid) for bid in batch_ids]
        stmt = select(batch_column).where(
            fixed_column == uuid.UUID(fixed_value),
            batch_column.in_(batch_uuids),
        )
        result = await self._db.execute(stmt)
        return {str(row[0]) for row in result.all()}

    async def record_match(self, result: JobMatchResult, user_id: str) -> bool:
        """Record a single match result.

        Uses INSERT ON CONFLICT DO NOTHING for idempotency.

        Args:
            result: Match result to record.
            user_id: User ID for the correlation.

        Returns:
            True if inserted, False if already existed.

        """
        record = _build_correlation_record(result, uuid.UUID(user_id))
        stmt = (
            insert(Correlation)
            .values(record)
            .on_conflict_do_nothing(index_elements=["pref_id", "listing_id"])
            .returning(Correlation.id)
        )
        res = await self._db.execute(stmt)
        await self._db.commit()
        return res.scalar_one_or_none() is not None

    async def record_match_no_commit(
        self,
        result: JobMatchResult,
        user_id: uuid.UUID,
    ) -> bool:
        """Insert a match without committing and report whether it was new.

        The caller owns the transaction so the correlation row and its transactional
        WAL event commit atomically. A replay that loses the uniqueness race returns
        ``False`` and must not emit a duplicate terminal event.
        """
        record = _build_correlation_record(result, user_id)
        stmt = (
            insert(Correlation)
            .values(record)
            .on_conflict_do_nothing(index_elements=["pref_id", "listing_id"])
            .returning(Correlation.id)
        )
        query_result = await self._db.execute(stmt)
        return query_result.scalar_one_or_none() is not None

    async def upsert_match_no_commit(
        self,
        result: JobMatchResult,
        user_id: uuid.UUID,
    ) -> tuple[uuid.UUID, CorrelationStatus]:
        """Upsert model output and return the durable correlation identity.

        Re-scoring refreshes only model-owned fields. The existing correlation
        identity, lifecycle status, and user interaction fields remain owned by
        their lifecycle handlers.
        """
        record = _build_correlation_record(result, user_id)
        stmt = insert(Correlation).values(record)
        stmt = stmt.on_conflict_do_update(
            index_elements=["pref_id", "listing_id"],
            set_={
                "correlation_score": stmt.excluded.correlation_score,
                "evaluated_at": stmt.excluded.evaluated_at,
                "feature_vector": stmt.excluded.feature_vector,
                "feature_schema_version": stmt.excluded.feature_schema_version,
                "updated_at": datetime.now(UTC),
            },
        ).returning(Correlation.id, Correlation.correlation_status)
        query_result = await self._db.execute(stmt)
        row = query_result.one()
        return uuid.UUID(str(row[0])), row[1]

    async def record_matches_batch(self, results: Sequence[JobMatchResult], user_id: str) -> int:
        """Record multiple match results using chunked inserts."""
        if not results:
            return 0

        user_uuid = uuid.UUID(user_id)
        total = 0
        for chunk in _chunked(results, BATCH_INSERT_SIZE):
            records = [_build_correlation_record(r, user_uuid) for r in chunk]
            total += await self._execute_batch_insert(records)

        await self._db.commit()
        return total

    async def record_matches_batch_no_commit(
        self,
        results: list[JobMatchResult],
        user_id: uuid.UUID,
    ) -> int:
        """Record multiple match results without committing.

        Use this when emitting a transactional WAL event in the same transaction.
        Caller is responsible for calling db.commit() after all operations.

        Args:
            results: Match results to record.
            user_id: User UUID for the correlations.

        Returns:
            Number of records inserted (for logging purposes).

        """
        self._last_inserted_listing_ids = await self.record_matches_with_listing_ids_no_commit(results, user_id)
        return len(self._last_inserted_listing_ids)

    async def record_matches_with_listing_ids_no_commit(
        self,
        results: list[JobMatchResult],
        user_id: uuid.UUID,
    ) -> set[str]:
        """Batch-insert matches and return only listing IDs actually inserted."""
        inserted: set[str] = set()
        for chunk in _chunked(results, BATCH_INSERT_SIZE):
            records = [_build_correlation_record(result, user_id) for result in chunk]
            stmt = (
                insert(Correlation)
                .values(records)
                .on_conflict_do_nothing(index_elements=["pref_id", "listing_id"])
                .returning(Correlation.listing_id)
            )
            query_result = await self._db.execute(stmt)
            inserted.update(str(row[0]) for row in query_result.all())

        return inserted

    async def upsert_matches_with_listing_ids_no_commit(
        self,
        results: Sequence[JobMatchResult],
        user_id: uuid.UUID,
    ) -> dict[str, tuple[uuid.UUID, CorrelationStatus]]:
        """Batch-upsert scores and return persisted identity/status per listing."""
        persisted: dict[str, tuple[uuid.UUID, CorrelationStatus]] = {}
        for chunk in _chunked(results, BATCH_INSERT_SIZE):
            records = [_build_correlation_record(result, user_id) for result in chunk]
            stmt = insert(Correlation).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["pref_id", "listing_id"],
                set_={
                    "correlation_score": stmt.excluded.correlation_score,
                    "evaluated_at": stmt.excluded.evaluated_at,
                    "feature_vector": stmt.excluded.feature_vector,
                    "feature_schema_version": stmt.excluded.feature_schema_version,
                    "updated_at": datetime.now(UTC),
                },
            ).returning(Correlation.listing_id, Correlation.id, Correlation.correlation_status)
            query_result = await self._db.execute(stmt)
            rows = query_result.all()
            persisted.update({str(row[0]): (uuid.UUID(str(row[1])), row[2]) for row in rows})
        return persisted

    async def _execute_batch_insert(self, records: list[dict[str, Any]]) -> int:
        """Execute a single batch insert and return count of inserted rows."""
        stmt = (
            insert(Correlation)
            .values(records)
            .on_conflict_do_nothing(index_elements=["pref_id", "listing_id"])
            .returning(Correlation.id)
        )
        result = await self._db.execute(stmt)
        return len(result.all())

    async def record_profile_matches_batch(
        self,
        results_with_users: list[tuple[JobMatchResult, str]],
    ) -> int:
        """Record matches for multiple profiles, each with their own user ID.

        Unlike ``record_matches_batch``, supports a distinct user ID per result.
        Uses ``ON CONFLICT DO NOTHING`` for idempotency.

        Args:
            results_with_users: Pairs of (match result, user_id string).

        Returns:
            Number of newly inserted correlation records.

        """
        if not results_with_users:
            return 0

        all_records = [_build_correlation_record(result, uuid.UUID(user_id)) for result, user_id in results_with_users]

        total = 0
        for chunk in _chunked(all_records, BATCH_INSERT_SIZE):
            total += await self._execute_batch_insert(chunk)

        await self._db.commit()
        return total

    async def upsert_matches_batch(self, results: Sequence[JobMatchResult], user_id: str) -> int:
        """Upsert match results - insert new or update existing scores.

        Used for backfill to re-score existing correlations with real embeddings.

        Args:
            results: Match results to upsert.
            user_id: User ID for new correlations.

        Returns:
            Number of correlations upserted.

        """
        if not results:
            return 0

        user_uuid = uuid.UUID(user_id)
        total = 0
        for chunk in _chunked(results, BATCH_INSERT_SIZE):
            records = [_build_correlation_record(r, user_uuid) for r in chunk]
            total += await self._execute_batch_upsert(records)

        await self._db.commit()
        return total

    async def _execute_batch_upsert(self, records: list[dict[str, Any]]) -> int:
        """Execute batch upsert - insert or update on conflict."""
        stmt = insert(Correlation).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["pref_id", "listing_id"],
            set_={
                "correlation_score": stmt.excluded.correlation_score,
                "evaluated_at": stmt.excluded.evaluated_at,
                "feature_vector": stmt.excluded.feature_vector,
                "feature_schema_version": stmt.excluded.feature_schema_version,
                "updated_at": datetime.now(UTC),
            },
        ).returning(Correlation.id)
        result = await self._db.execute(stmt)
        return len(result.all())

    async def get_actionable_matches(
        self,
        pref_id: str,
        limit: int = 50,
    ) -> list[Correlation]:
        """Get actionable matches for a preference.

        Args:
            pref_id: User preference ID.
            limit: Maximum number of matches to return.

        Returns:
            List of correlation records ordered by score descending.

        """
        stmt = (
            select(Correlation)
            .where(
                Correlation.pref_id == uuid.UUID(pref_id),
                Correlation.correlation_status == CorrelationStatus.EVALUATED,
            )
            .order_by(Correlation.correlation_score.desc().nulls_last())
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def dismiss_for_deleted_listing(self, listing_id: uuid.UUID) -> int:
        """Dismiss all correlations for a deleted listing.

        Used for eventual consistency when a listing is deleted.

        Args:
            listing_id: UUID of the deleted listing.

        Returns:
            Number of correlations dismissed.

        """
        stmt = (
            update(Correlation)
            .where(
                Correlation.listing_id == listing_id,
                Correlation.correlation_status.notin_(
                    [
                        CorrelationStatus.DISMISSED,
                        CorrelationStatus.APPLIED,
                    ]
                ),
            )
            .values(
                correlation_status=CorrelationStatus.DISMISSED,
                is_dismissed=True,
                updated_at=datetime.now(UTC),
            )
            .returning(Correlation.id)
        )
        result = await self._db.execute(stmt)
        await self._db.commit()
        return len(result.all())
