"""Tests for aggregation functions."""

from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from job_query_composition_service.services.aggregation import (
    _compute_aggregates_from_contributors,
    recompute_query_aggregates_batch,
    tier_to_frequency,
)
from nohiki.common.v1 import JobBoardSource, WorkArrangement
from nohiki_db_utils.testing import create_mock_session


class TestTierToFrequency:
    """Tests for tier_to_frequency function."""

    def test_hourly_tier(self) -> None:
        assert tier_to_frequency("hourly") == timedelta(hours=1)

    def test_daily_tier(self) -> None:
        assert tier_to_frequency("daily") == timedelta(days=1)

    def test_weekly_tier(self) -> None:
        assert tier_to_frequency("weekly") == timedelta(days=7)

    def test_six_hour_tier(self) -> None:
        assert tier_to_frequency("6h") == timedelta(hours=6)


class TestRecomputeQueryAggregates:
    """Tests for recompute_query_aggregates function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_query_not_found(self) -> None:
        from job_query_composition_service.services.aggregation import recompute_query_aggregates

        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        mock_db.get.return_value = None

        result = await recompute_query_aggregates(mock_db, uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_aggregates_active_contributors(self) -> None:
        from job_query_composition_service.services.aggregation import recompute_query_aggregates

        mock_db = create_mock_session()

        # Create mock contributors
        contributor1 = MagicMock()
        contributor1.is_active = True
        contributor1.work_arrangements = [WorkArrangement.REMOTE, WorkArrangement.HYBRID]
        contributor1.remote_preference = "remote"
        contributor1.sources = [JobBoardSource.LINKEDIN]
        contributor1.frequency_tier = "daily"

        contributor2 = MagicMock()
        contributor2.is_active = True
        contributor2.work_arrangements = [WorkArrangement.ON_SITE]
        contributor2.remote_preference = "hybrid"
        contributor2.sources = [JobBoardSource.INDEED]
        contributor2.frequency_tier = "hourly"

        contributor3 = MagicMock()
        contributor3.is_active = False  # Inactive
        contributor3.work_arrangements = [WorkArrangement.ON_SITE]
        contributor3.remote_preference = "onsite"
        contributor3.sources = [JobBoardSource.GLASSDOOR]
        contributor3.frequency_tier = "weekly"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [contributor1, contributor2, contributor3]
        mock_db.execute.return_value = mock_result

        mock_query = MagicMock()
        mock_db.get.return_value = mock_query

        result = await recompute_query_aggregates(mock_db, uuid4())

        assert result == mock_query
        # Check aggregates were set correctly
        assert set(mock_query.work_arrangements) == {
            WorkArrangement.REMOTE,
            WorkArrangement.HYBRID,
            WorkArrangement.ON_SITE,
        }
        assert set(mock_query.remote_preferences) == {"hybrid", "remote"}
        assert set(mock_query.sources) == {JobBoardSource.INDEED, JobBoardSource.LINKEDIN}
        assert mock_query.frequency == timedelta(hours=1)  # Most frequent
        assert mock_query.is_active is True
        assert mock_query.active_contributor_count == 2
        assert mock_query.total_contributor_count == 3


class TestComputeAggregatesFromContributors:
    """Tests for _compute_aggregates_from_contributors helper function."""

    def test_filters_inactive_contributors(self) -> None:
        active = MagicMock()
        active.is_active = True
        active.work_arrangements = [WorkArrangement.REMOTE]
        active.remote_preference = "remote"
        active.sources = [JobBoardSource.LINKEDIN]
        active.frequency_tier = "daily"

        inactive = MagicMock()
        inactive.is_active = False
        inactive.work_arrangements = [WorkArrangement.ON_SITE]
        inactive.remote_preference = "onsite"
        inactive.sources = [JobBoardSource.INDEED]
        inactive.frequency_tier = "hourly"

        work_arr, remote_prefs, sources, min_freq, active_count = _compute_aggregates_from_contributors(
            [active, inactive]
        )

        assert work_arr == [WorkArrangement.REMOTE]
        assert remote_prefs == ["remote"]
        assert sources == [JobBoardSource.LINKEDIN]
        assert min_freq == timedelta(days=1)
        assert active_count == 1

    def test_merges_multiple_active_contributors(self) -> None:
        c1 = MagicMock()
        c1.is_active = True
        c1.work_arrangements = [WorkArrangement.REMOTE, WorkArrangement.HYBRID]
        c1.remote_preference = "remote"
        c1.sources = [JobBoardSource.LINKEDIN]
        c1.frequency_tier = "daily"

        c2 = MagicMock()
        c2.is_active = True
        c2.work_arrangements = [WorkArrangement.ON_SITE]
        c2.remote_preference = "onsite"
        c2.sources = [JobBoardSource.INDEED, JobBoardSource.LINKEDIN]
        c2.frequency_tier = "hourly"

        work_arr, remote_prefs, sources, min_freq, active_count = _compute_aggregates_from_contributors([c1, c2])

        assert set(work_arr) == {WorkArrangement.HYBRID, WorkArrangement.ON_SITE, WorkArrangement.REMOTE}
        assert set(remote_prefs) == {"onsite", "remote"}
        assert set(sources) == {JobBoardSource.INDEED, JobBoardSource.LINKEDIN}
        assert min_freq == timedelta(hours=1)
        assert active_count == 2

    def test_handles_none_work_arrangements(self) -> None:
        c1 = MagicMock()
        c1.is_active = True
        c1.work_arrangements = None
        c1.remote_preference = "remote"
        c1.sources = [JobBoardSource.LINKEDIN]
        c1.frequency_tier = "daily"

        work_arr, remote_prefs, sources, _, active_count = _compute_aggregates_from_contributors([c1])

        assert work_arr == []
        assert remote_prefs == ["remote"]
        assert sources == [JobBoardSource.LINKEDIN]
        assert active_count == 1


class TestRecomputeQueryAggregatesBatch:
    """Tests for recompute_query_aggregates_batch function."""

    @pytest.mark.asyncio
    async def test_returns_empty_dict_for_empty_input(self) -> None:
        mock_db = create_mock_session()
        result = await recompute_query_aggregates_batch(mock_db, set())
        assert result == {}
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_processes_multiple_queries(self) -> None:
        query_id1 = uuid4()
        query_id2 = uuid4()

        c1 = MagicMock()
        c1.query_id = query_id1
        c1.is_active = True
        c1.work_arrangements = [WorkArrangement.REMOTE]
        c1.remote_preference = "remote"
        c1.sources = [JobBoardSource.LINKEDIN]
        c1.frequency_tier = "daily"

        c2 = MagicMock()
        c2.query_id = query_id2
        c2.is_active = True
        c2.work_arrangements = [WorkArrangement.ON_SITE]
        c2.remote_preference = "onsite"
        c2.sources = [JobBoardSource.INDEED]
        c2.frequency_tier = "hourly"

        mock_db = create_mock_session()

        contributors_result = MagicMock()
        contributors_result.scalars.return_value.all.return_value = [c1, c2]

        query1 = MagicMock()
        query1.id = query_id1
        query2 = MagicMock()
        query2.id = query_id2

        queries_result = MagicMock()
        queries_result.scalars.return_value.all.return_value = [query1, query2]

        mock_db.execute.side_effect = [contributors_result, queries_result]

        result = await recompute_query_aggregates_batch(mock_db, {query_id1, query_id2})

        assert len(result) == 2
        assert query_id1 in result
        assert query_id2 in result
        assert result[query_id1].work_arrangements == [WorkArrangement.REMOTE]
        assert result[query_id2].work_arrangements == [WorkArrangement.ON_SITE]

    @pytest.mark.asyncio
    async def test_skips_missing_queries(self) -> None:
        query_id1 = uuid4()
        query_id2 = uuid4()

        c1 = MagicMock()
        c1.query_id = query_id1
        c1.is_active = True
        c1.work_arrangements = [WorkArrangement.REMOTE]
        c1.remote_preference = "remote"
        c1.sources = [JobBoardSource.LINKEDIN]
        c1.frequency_tier = "daily"

        mock_db = create_mock_session()

        contributors_result = MagicMock()
        contributors_result.scalars.return_value.all.return_value = [c1]

        query1 = MagicMock()
        query1.id = query_id1

        queries_result = MagicMock()
        queries_result.scalars.return_value.all.return_value = [query1]

        mock_db.execute.side_effect = [contributors_result, queries_result]

        result = await recompute_query_aggregates_batch(mock_db, {query_id1, query_id2})

        assert len(result) == 1
        assert query_id1 in result
        assert query_id2 not in result
