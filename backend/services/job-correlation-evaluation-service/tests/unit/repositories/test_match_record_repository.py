"""Unit tests for MatchRecordRepository class."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from job_correlation_evaluation_service.repositories.match_record_repository import (
    MatchRecordRepository,
)
from job_correlation_evaluation_service.services.match_types import JobMatchResult
from nohiki_db_utils.testing import create_mock_session


class TestMatchRecordRepositoryInit:
    """Tests for MatchRecordRepository initialization."""

    def test_initializes_with_db_session(self) -> None:
        """Test that repository initializes with db session."""
        mock_db = create_mock_session()
        repo = MatchRecordRepository(mock_db)

        assert repo._db is mock_db


class TestMatchRecordRepositoryExists:
    """Tests for MatchRecordRepository.exists method."""

    @pytest.mark.asyncio
    async def test_exists_returns_true_when_found(self) -> None:
        """Test exists returns True when correlation found."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = uuid.uuid4()
        mock_db.execute.return_value = mock_result

        repo = MatchRecordRepository(mock_db)
        result = await repo.exists(str(uuid.uuid4()), str(uuid.uuid4()))

        assert result is True

    @pytest.mark.asyncio
    async def test_exists_returns_false_when_not_found(self) -> None:
        """Test exists returns False when correlation not found."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        repo = MatchRecordRepository(mock_db)
        result = await repo.exists(str(uuid.uuid4()), str(uuid.uuid4()))

        assert result is False


class TestMatchRecordRepositoryGetExistingListingIds:
    """Tests for MatchRecordRepository.get_existing_listing_ids method."""

    @pytest.mark.asyncio
    async def test_returns_empty_set_for_empty_input(self) -> None:
        """Test returns empty set when no listing IDs provided."""
        mock_db = create_mock_session()
        repo = MatchRecordRepository(mock_db)

        result = await repo.get_existing_listing_ids(str(uuid.uuid4()), [])

        assert result == set()
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_existing_ids(self) -> None:
        """Test returns set of existing listing IDs."""
        mock_db = create_mock_session()
        existing_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.all.return_value = [(existing_id,)]
        mock_db.execute.return_value = mock_result

        repo = MatchRecordRepository(mock_db)
        result = await repo.get_existing_listing_ids(
            str(uuid.uuid4()),
            [str(existing_id), str(uuid.uuid4())],
        )

        assert str(existing_id) in result


class TestMatchRecordRepositoryRecordMatch:
    """Tests for MatchRecordRepository.record_match method."""

    @pytest.fixture
    def mock_result(self) -> JobMatchResult:
        """Create mock job match result."""
        return JobMatchResult(
            pref_id=str(uuid.uuid4()),
            listing_id=str(uuid.uuid4()),
            listing_url="https://example.com/job",
            score=85,
            breakdown={"skill_match": 0.8},
            feature_schema_version="v5.0.0",
            feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
            role_relevance_raw=0.0,
            ranking_index=0.0,
            factors=(),
        )

    @pytest.mark.asyncio
    async def test_returns_true_when_inserted(self, mock_result: JobMatchResult) -> None:
        """Test returns True when row inserted."""
        mock_db = create_mock_session()
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = uuid.uuid4()
        mock_db.execute.return_value = mock_execute_result

        repo = MatchRecordRepository(mock_db)
        result = await repo.record_match(mock_result, str(uuid.uuid4()))

        assert result is True
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_conflict(self, mock_result: JobMatchResult) -> None:
        """Test returns False when row already exists (conflict)."""
        mock_db = create_mock_session()
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_execute_result

        repo = MatchRecordRepository(mock_db)
        result = await repo.record_match(mock_result, str(uuid.uuid4()))

        assert result is False


class TestMatchRecordRepositoryRecordMatchesBatch:
    """Tests for MatchRecordRepository.record_matches_batch method."""

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_list(self) -> None:
        """Test returns 0 when no results provided."""
        mock_db = create_mock_session()
        repo = MatchRecordRepository(mock_db)

        result = await repo.record_matches_batch([], str(uuid.uuid4()))

        assert result == 0
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_inserted_count(self) -> None:
        """Test returns count of inserted rows."""
        mock_db = create_mock_session()
        mock_execute_result = MagicMock()
        mock_execute_result.all.return_value = [(uuid.uuid4(),), (uuid.uuid4(),)]
        mock_db.execute.return_value = mock_execute_result

        results = [
            JobMatchResult(
                pref_id=str(uuid.uuid4()),
                listing_id=str(uuid.uuid4()),
                listing_url="https://example.com/job1",
                score=85,
                breakdown={},
                feature_schema_version="v5.0.0",
                feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
                role_relevance_raw=0.0,
                ranking_index=0.0,
                factors=(),
            ),
            JobMatchResult(
                pref_id=str(uuid.uuid4()),
                listing_id=str(uuid.uuid4()),
                listing_url="https://example.com/job2",
                score=90,
                breakdown={},
                feature_schema_version="v5.0.0",
                feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
                role_relevance_raw=0.0,
                ranking_index=0.0,
                factors=(),
            ),
        ]

        repo = MatchRecordRepository(mock_db)
        result = await repo.record_matches_batch(results, str(uuid.uuid4()))

        assert result == 2
        mock_db.commit.assert_awaited_once()


class TestMatchRecordRepositoryRecordProfileMatchesBatch:
    """Tests for MatchRecordRepository.record_profile_matches_batch method."""

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_list(self) -> None:
        """Test returns 0 when no (result, user_id) pairs provided."""
        mock_db = create_mock_session()
        repo = MatchRecordRepository(mock_db)

        result = await repo.record_profile_matches_batch([])

        assert result == 0
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_inserted_count_for_multiple_users(self) -> None:
        """Test batch-inserts results with distinct user IDs and returns count."""
        mock_db = create_mock_session()
        mock_execute_result = MagicMock()
        mock_execute_result.all.return_value = [(uuid.uuid4(),), (uuid.uuid4(),)]
        mock_db.execute.return_value = mock_execute_result

        results_with_users = [
            (
                JobMatchResult(
                    pref_id=str(uuid.uuid4()),
                    listing_id=str(uuid.uuid4()),
                    listing_url="https://example.com/job1",
                    score=80,
                    breakdown={},
                    feature_schema_version="v5.0.0",
                    feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
                    role_relevance_raw=0.0,
                    ranking_index=0.0,
                    factors=(),
                ),
                str(uuid.uuid4()),
            ),
            (
                JobMatchResult(
                    pref_id=str(uuid.uuid4()),
                    listing_id=str(uuid.uuid4()),
                    listing_url="https://example.com/job2",
                    score=90,
                    breakdown={},
                    feature_schema_version="v5.0.0",
                    feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
                    role_relevance_raw=0.0,
                    ranking_index=0.0,
                    factors=(),
                ),
                str(uuid.uuid4()),
            ),
        ]

        repo = MatchRecordRepository(mock_db)
        result = await repo.record_profile_matches_batch(results_with_users)

        assert result == 2
        mock_db.commit.assert_awaited_once()


class TestMatchRecordRepositoryGetActionableMatches:
    """Tests for MatchRecordRepository.get_actionable_matches method."""

    @pytest.mark.asyncio
    async def test_returns_list_of_correlations(self) -> None:
        """Test returns list of correlation records."""
        mock_db = create_mock_session()
        mock_correlations = [MagicMock(), MagicMock()]
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_correlations
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        repo = MatchRecordRepository(mock_db)
        result = await repo.get_actionable_matches(str(uuid.uuid4()))

        assert len(result) == 2


class TestMatchRecordRepositoryDismissForDeletedListing:
    """Tests for MatchRecordRepository.dismiss_for_deleted_listing method."""

    @pytest.mark.asyncio
    async def test_returns_dismissed_count(self) -> None:
        """Test returns count of dismissed correlations."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.all.return_value = [(uuid.uuid4(),), (uuid.uuid4(),), (uuid.uuid4(),)]
        mock_db.execute.return_value = mock_result

        repo = MatchRecordRepository(mock_db)
        result = await repo.dismiss_for_deleted_listing(uuid.uuid4())

        assert result == 3
        mock_db.commit.assert_awaited_once()


class TestMatchRecordRepositoryUpsertMatchesBatch:
    """Tests for MatchRecordRepository.upsert_matches_batch method."""

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_list(self) -> None:
        """Test returns 0 when no results provided."""
        mock_db = create_mock_session()
        repo = MatchRecordRepository(mock_db)

        result = await repo.upsert_matches_batch([], str(uuid.uuid4()))

        assert result == 0
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upserts_multiple_results(self) -> None:
        """Test upserts multiple results in batches."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.all.return_value = [(uuid.uuid4(),), (uuid.uuid4(),)]
        mock_db.execute.return_value = mock_result

        results = [
            JobMatchResult(
                pref_id=str(uuid.uuid4()),
                listing_id=str(uuid.uuid4()),
                listing_url="https://example.com/job1",
                score=85,
                breakdown={},
                feature_schema_version="v5.0.0",
                feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
                role_relevance_raw=0.0,
                ranking_index=0.0,
                factors=(),
            ),
            JobMatchResult(
                pref_id=str(uuid.uuid4()),
                listing_id=str(uuid.uuid4()),
                listing_url="https://example.com/job2",
                score=90,
                breakdown={},
                feature_schema_version="v5.0.0",
                feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
                role_relevance_raw=0.0,
                ranking_index=0.0,
                factors=(),
            ),
        ]

        repo = MatchRecordRepository(mock_db)
        result = await repo.upsert_matches_batch(results, str(uuid.uuid4()))

        assert result == 2
        mock_db.commit.assert_awaited_once()

    """Tests for _sanitize_breakdown function."""

    def test_handles_nested_dicts_with_nan(self) -> None:
        """Test _sanitize_breakdown handles nested dicts with NaN values."""
        from typing import cast

        from job_correlation_evaluation_service.repositories.match_record_repository import (
            _sanitize_breakdown,
        )

        breakdown = {
            "outer": {
                "inner_nan": float("nan"),
                "inner_inf": float("inf"),
                "inner_neg_inf": float("-inf"),
                "normal": 42.0,
            },
            "top_level_nan": float("nan"),
        }

        result = _sanitize_breakdown(breakdown)
        outer = cast(dict[str, object], result["outer"])

        assert result["top_level_nan"] is None
        assert outer["inner_nan"] is None
        assert outer["inner_inf"] is None
        assert outer["inner_neg_inf"] is None
        assert outer["normal"] == pytest.approx(42.0)

    def test_handles_empty_dict(self) -> None:
        """Test _sanitize_breakdown handles empty dict."""
        from job_correlation_evaluation_service.repositories.match_record_repository import (
            _sanitize_breakdown,
        )

        result = _sanitize_breakdown({})
        assert result == {}

    def test_handles_non_float_values(self) -> None:
        """Test _sanitize_breakdown preserves non-float values."""
        from job_correlation_evaluation_service.repositories.match_record_repository import (
            _sanitize_breakdown,
        )

        breakdown = {
            "string": "test",
            "int": 42,
            "bool": True,
            "list": [1, 2, 3],
        }

        result = _sanitize_breakdown(breakdown)

        assert result["string"] == "test"
        assert result["int"] == 42
        assert result["bool"] is True
        assert result["list"] == [1, 2, 3]


class TestBuildCorrelationRecord:
    """Tests for _build_correlation_record function."""

    def test_converts_feature_vector_tuple_to_list(self) -> None:
        """Test _build_correlation_record converts feature_vector tuple to list."""
        from job_correlation_evaluation_service.repositories.match_record_repository import (
            _build_correlation_record,
        )

        result = JobMatchResult(
            pref_id=str(uuid.uuid4()),
            listing_id=str(uuid.uuid4()),
            listing_url="https://example.com/job",
            score=85,
            breakdown={},
            feature_schema_version="v5.0.0",
            feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
            role_relevance_raw=0.0,
            ranking_index=0.0,
            factors=(),
        )
        user_id = uuid.uuid4()

        record = _build_correlation_record(result, user_id)

        assert "feature_vector" in record
        assert record["feature_vector"] == [0.1, 0.2, 0.3, 0.4, 0.5]
        assert isinstance(record["feature_vector"], list)

    def test_feature_vector_none_when_not_provided(self) -> None:
        """Test _build_correlation_record handles missing feature_vector."""
        from job_correlation_evaluation_service.repositories.match_record_repository import (
            _build_correlation_record,
        )

        result = JobMatchResult(
            pref_id=str(uuid.uuid4()),
            listing_id=str(uuid.uuid4()),
            listing_url="https://example.com/job",
            score=85,
            breakdown={},
            feature_schema_version="v5.0.0",
            role_relevance_raw=0.0,
            ranking_index=0.0,
            factors=(),
        )
        user_id = uuid.uuid4()

        record = _build_correlation_record(result, user_id)

        assert "feature_vector" in record
        assert record["feature_vector"] is None


class TestMatchRecordRepositoryForceBackfillUpsert:
    """Tests for atomic upsert identity reporting and score-field replacement."""

    @pytest.mark.asyncio
    async def test_upsert_returns_exact_affected_listing_ids_without_commit(self) -> None:
        """Matcher publishes only rows actually accepted by the batch upsert."""
        mock_db = create_mock_session()
        listing_ids = [uuid.uuid4(), uuid.uuid4()]
        from nohiki.common.v1 import CorrelationStatus

        persisted_ids = [uuid.uuid4(), uuid.uuid4()]
        mock_execute_result = MagicMock()
        mock_execute_result.all.return_value = [
            (listing_id, persisted_id, CorrelationStatus.EVALUATED)
            for listing_id, persisted_id in zip(listing_ids, persisted_ids, strict=True)
        ]
        mock_db.execute.return_value = mock_execute_result
        results = [
            JobMatchResult(
                pref_id=str(uuid.uuid4()),
                listing_id=str(listing_id),
                listing_url=f"https://example.test/{index}",
                score=90 - index,
                breakdown={"semantic": 0.9 - index / 10},
                feature_schema_version="v-next",
                role_relevance_raw=0.8,
                ranking_index=0.7,
                factors=(),
                feature_vector=(0.1, 0.2),
            )
            for index, listing_id in enumerate(listing_ids)
        ]

        repo = MatchRecordRepository(mock_db)
        affected = await repo.upsert_matches_with_listing_ids_no_commit(results, uuid.uuid4())

        assert affected == {
            str(listing_id): (persisted_id, CorrelationStatus.EVALUATED)
            for listing_id, persisted_id in zip(listing_ids, persisted_ids, strict=True)
        }
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upsert_updates_scoring_fields_only(self) -> None:
        """Upsert refreshes every scoring field but preserves user interaction state."""
        mock_db = create_mock_session()
        mock_execute_result = MagicMock()
        mock_execute_result.all.return_value = [(uuid.uuid4(),)]
        mock_db.execute.return_value = mock_execute_result
        result = JobMatchResult(
            pref_id=str(uuid.uuid4()),
            listing_id=str(uuid.uuid4()),
            listing_url="https://example.test/job",
            score=87,
            breakdown={"semantic": 0.87},
            feature_schema_version="v-next",
            role_relevance_raw=0.8,
            ranking_index=0.9,
            factors=(),
            feature_vector=(0.8, 0.9),
        )

        repo = MatchRecordRepository(mock_db)
        await repo._execute_batch_upsert(
            [
                {
                    "pref_id": uuid.UUID(result.pref_id),
                    "listing_id": uuid.UUID(result.listing_id),
                    "user_id": uuid.uuid4(),
                    "listing_url": result.listing_url,
                    "correlation_score": result.score,
                    "correlation_reasoning": result.breakdown,
                    "feature_vector": list(result.feature_vector or ()),
                    "feature_schema_version": result.feature_schema_version,
                    "evaluated_at": result.evaluated_at,
                }
            ]
        )

        from sqlalchemy.dialects.postgresql import dialect

        statement = mock_db.execute.await_args.args[0]
        update_sql = str(statement.compile(dialect=dialect())).split("DO UPDATE SET ", 1)[1]
        assert "correlation_score = excluded.correlation_score" in update_sql
        assert "correlation_reasoning = excluded.correlation_reasoning" in update_sql
        assert "evaluated_at = excluded.evaluated_at" in update_sql
        assert "feature_vector = excluded.feature_vector" in update_sql
        assert "feature_schema_version = excluded.feature_schema_version" in update_sql
        assert "correlation_status" not in update_sql
        assert "is_viewed" not in update_sql
        assert "is_applied" not in update_sql
        assert "is_dismissed" not in update_sql
        assert "user_feedback" not in update_sql
