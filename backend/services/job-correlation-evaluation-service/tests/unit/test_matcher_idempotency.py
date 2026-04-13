"""Idempotency tests for job-correlation-evaluation-service match recording.

Verifies that MatchRecordRepository uses ON CONFLICT DO NOTHING/UPDATE
for idempotent match recording, and that duplicate records are handled
gracefully without raising exceptions.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_correlation_evaluation_service.repositories.match_record_repository import (
    MatchRecordRepository,
)
from nohiki.common.v1 import CorrelationStatus
from nohiki_db_utils.testing import create_mock_session


def _make_match_result(
    pref_id: str | None = None,
    listing_id: str | None = None,
    score: float = 0.85,
) -> MagicMock:
    """Create a mock JobMatchResult with string UUIDs matching real interface."""
    result = MagicMock()
    result.correlation_id = uuid.uuid4()
    result.pref_id = pref_id or str(uuid.uuid4())
    result.listing_id = listing_id or str(uuid.uuid4())
    result.listing_url = "https://example.com/job/1"
    result.score = score
    result.breakdown = {"semantic": 0.8, "keyword": 0.9}
    result.status = CorrelationStatus.EVALUATED
    result.evaluated_at = datetime.now(UTC)
    result.feature_vector = (0.5, 0.6, 0.7)
    result.feature_schema_version = "v-next"
    return result


class TestRecordMatchIdempotency:
    """Verify record_match uses ON CONFLICT DO NOTHING."""

    @pytest.mark.asyncio
    async def test_record_match_returns_true_on_insert(self) -> None:
        """First insert returns True (new record)."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = uuid.uuid4()
        mock_db.execute.return_value = mock_result

        repo = MatchRecordRepository(mock_db)
        result = _make_match_result()
        user_id = str(uuid.uuid4())

        inserted = await repo.record_match(result, user_id)

        assert inserted is True
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_match_returns_false_on_duplicate(self) -> None:
        """Duplicate insert returns False (ON CONFLICT DO NOTHING)."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        repo = MatchRecordRepository(mock_db)
        result = _make_match_result()
        user_id = str(uuid.uuid4())

        inserted = await repo.record_match(result, user_id)

        assert inserted is False

    @pytest.mark.asyncio
    async def test_record_match_twice_same_key_no_exception(self) -> None:
        """Calling record_match twice with same pref_id+listing_id must not raise."""
        mock_db = create_mock_session()
        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = uuid.uuid4()
        second_result = MagicMock()
        second_result.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [first_result, second_result]

        repo = MatchRecordRepository(mock_db)
        pref_id = str(uuid.uuid4())
        listing_id = str(uuid.uuid4())
        match = _make_match_result(pref_id=pref_id, listing_id=listing_id)
        user_id = str(uuid.uuid4())

        first = await repo.record_match(match, user_id)
        second = await repo.record_match(match, user_id)

        assert first is True
        assert second is False


class TestListingDelivery:
    """Defend terminal publication and replay idempotency."""

    @pytest.mark.asyncio
    async def test_duplicate_delivery_publishes_one_terminal_event(self) -> None:
        """A replay observes the committed pair and emits no duplicate event."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        profile = MagicMock(id=str(uuid.uuid4()), user_id=str(uuid.uuid4()))
        job = MagicMock(
            id=uuid.uuid4(),
            listing_url="https://example.test/job",
            skills_embedding=[0.1],
        )
        match = _make_match_result(pref_id=profile.id, listing_id=str(job.id), score=82)
        existing_pref_ids: set[str] = set()
        match_repo = MagicMock()

        async def read_existing(_listing_id: str, _pref_ids: list[str]) -> set[str]:
            return set(existing_pref_ids)

        async def persist_once(_result: MagicMock, _user_id: uuid.UUID) -> bool:
            existing_pref_ids.add(profile.id)
            return True

        match_repo.get_existing_pref_ids = AsyncMock(side_effect=read_existing)
        match_repo.record_match_no_commit = AsyncMock(side_effect=persist_once)
        profile_repo = MagicMock()
        profile_repo.get_active_profiles = AsyncMock(return_value=[profile])
        db = create_mock_session()
        ml_service = MagicMock(is_initialized=True)

        with (
            patch(
                "job_correlation_evaluation_service.services.matcher_service.ProfileProjectionRepository",
                return_value=profile_repo,
            ),
            patch(
                "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository",
                return_value=match_repo,
            ),
            patch.object(JobMatcherService, "_score_single", return_value=match) as score_single,
            patch(
                "job_correlation_evaluation_service.services.matcher_service.publish_correlation_evaluated",
                new=AsyncMock(),
            ) as publish,
        ):
            service = JobMatcherService(ml_scoring_service=ml_service)
            first = await service.match_job_to_profiles(db, job, "first-delivery")
            replay = await service.match_job_to_profiles(db, job, "replay-delivery")

        assert (first, replay) == (1, 0)
        score_single.assert_called_once()
        match_repo.record_match_no_commit.assert_awaited_once()
        publish.assert_awaited_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
    async def test_terminal_publication_failure_aborts_commit(self, failure_type: type[BaseException]) -> None:
        """Publisher errors escape for Kafka retry/DLQ policy; no partial commit occurs."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
            _PersistContext,
        )

        db = create_mock_session()
        repo = MagicMock()
        repo.record_match_no_commit = AsyncMock(return_value=True)
        profile = MagicMock(user_id=str(uuid.uuid4()))
        result = _make_match_result()
        job = MagicMock(listing_url=result.listing_url)
        context = _PersistContext(job=job, job_id_str=result.listing_id, correlation_id="trace")

        with (
            patch(
                "job_correlation_evaluation_service.services.matcher_service.publish_correlation_evaluated",
                new=AsyncMock(side_effect=failure_type("publish interrupted")),
            ),
            pytest.raises(failure_type, match="publish interrupted"),
        ):
            await JobMatcherService._persist_scored_matches(db, repo, [(profile, result)], context, force_rescore=False)

        db.commit.assert_not_awaited()


class TestForceRescoreVersion:
    """Defend stale embedding metadata replacement without identity churn."""

    @pytest.mark.asyncio
    async def test_upsert_replaces_embedding_version_but_not_terminal_state(
        self,
    ) -> None:
        from sqlalchemy.dialects.postgresql import dialect

        db = create_mock_session()
        query_result = MagicMock()
        db.execute.return_value = query_result
        result = _make_match_result(score=91)
        query_result.one.return_value = (result.correlation_id, result.status)

        await MatchRecordRepository(db).upsert_match_no_commit(result, uuid.uuid4())

        statement = db.execute.await_args.args[0]
        update_sql = str(statement.compile(dialect=dialect())).split("DO UPDATE SET ", 1)[1]
        assignments = {part.split(" = ", 1)[0] for part in update_sql.split(", ")}
        assert {
            "feature_vector",
            "feature_schema_version",
            "correlation_score",
        } <= assignments
        assert {
            "id",
            "correlation_status",
            "is_viewed",
            "is_applied",
            "is_dismissed",
            "user_feedback",
        }.isdisjoint(assignments)
        db.commit.assert_not_awaited()


class TestBatchInsertIdempotency:
    """Verify batch insert uses ON CONFLICT DO NOTHING."""

    @pytest.mark.asyncio
    async def test_batch_insert_empty_list(self) -> None:
        """Empty batch returns 0 without DB calls."""
        mock_db = create_mock_session()
        repo = MatchRecordRepository(mock_db)

        count = await repo.record_matches_batch([], str(uuid.uuid4()))

        assert count == 0
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_batch_insert_returns_count(self) -> None:
        """Batch insert returns count of actually inserted rows."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.all.return_value = [MagicMock(), MagicMock()]
        mock_db.execute.return_value = mock_result

        repo = MatchRecordRepository(mock_db)
        results = [_make_match_result() for _ in range(2)]

        count = await repo.record_matches_batch(results, str(uuid.uuid4()))

        assert count == 2


class TestBatchUpsertIdempotency:
    """Verify batch upsert uses ON CONFLICT DO UPDATE."""

    @pytest.mark.asyncio
    async def test_upsert_empty_list(self) -> None:
        """Empty upsert returns 0 without DB calls."""
        mock_db = create_mock_session()
        repo = MatchRecordRepository(mock_db)

        count = await repo.upsert_matches_batch([], str(uuid.uuid4()))

        assert count == 0
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_scores(self) -> None:
        """Upsert with same keys updates scores instead of failing."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.all.return_value = [MagicMock(), MagicMock()]
        mock_db.execute.return_value = mock_result

        repo = MatchRecordRepository(mock_db)
        pref_id = str(uuid.uuid4())
        listing_id = str(uuid.uuid4())
        results = [
            _make_match_result(pref_id=pref_id, listing_id=listing_id, score=0.7),
            _make_match_result(score=0.9),
        ]

        count = await repo.upsert_matches_batch(results, str(uuid.uuid4()))

        assert count == 2
        mock_db.commit.assert_awaited_once()
