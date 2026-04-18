"""Unit tests for query_service module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import job_query_composition_service.services.query_service as query_service_module
import pytest
from job_query_composition_service.services.query_service import (
    ContributorInput,
    create_or_update_contributor,
    delete_contributor,
    delete_query,
    delete_user_contributions,
    find_or_create_query,
    get_queries_by_ids,
    get_query_by_id,
    set_user_active,
    set_user_inactive,
    update_contributor_frequency,
)
from nohiki.common.v1 import CountryCode, JobBoardSource, Location, LocationType, WorkArrangement
from nohiki_db_utils.testing import create_mock_session
from sqlalchemy.exc import IntegrityError


class TestGetQueryById:
    """Tests for get_query_by_id function."""

    @pytest.mark.asyncio
    async def test_returns_query_when_found(self) -> None:
        """Test that query is returned when found."""
        mock_db = create_mock_session()
        query_id = uuid4()
        mock_query = MagicMock()
        mock_db.get.return_value = mock_query

        result = await get_query_by_id(mock_db, query_id)

        assert result is mock_query
        mock_db.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        """Test that None is returned when query not found."""
        mock_db = create_mock_session()
        query_id = uuid4()
        mock_db.get.return_value = None

        result = await get_query_by_id(mock_db, query_id)

        assert result is None


class TestGetQueriesByIds:
    """Tests for get_queries_by_ids function."""

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_no_ids(self) -> None:
        """Test that empty dict is returned when no IDs provided."""
        mock_db = create_mock_session()

        result = await get_queries_by_ids(mock_db, set())

        assert result == {}
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_dict_of_queries_by_id(self) -> None:
        """Test that queries are returned as dict keyed by ID."""
        mock_db = create_mock_session()
        query_id1 = uuid4()
        query_id2 = uuid4()

        mock_query1 = MagicMock()
        mock_query1.id = query_id1
        mock_query2 = MagicMock()
        mock_query2.id = query_id2

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_query1, mock_query2]
        mock_db.execute.return_value = mock_result

        result = await get_queries_by_ids(mock_db, {query_id1, query_id2})

        assert len(result) == 2
        assert result[query_id1] is mock_query1
        assert result[query_id2] is mock_query2
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_only_found_queries(self) -> None:
        """Test that only found queries are returned (missing IDs excluded)."""
        mock_db = create_mock_session()
        query_id1 = uuid4()
        query_id2 = uuid4()
        missing_id = uuid4()

        mock_query1 = MagicMock()
        mock_query1.id = query_id1
        mock_query2 = MagicMock()
        mock_query2.id = query_id2

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_query1, mock_query2]
        mock_db.execute.return_value = mock_result

        result = await get_queries_by_ids(mock_db, {query_id1, query_id2, missing_id})

        assert len(result) == 2
        assert missing_id not in result


class TestFindOrCreateQuery:
    """Canonical query identity and concurrent creation contracts."""

    @pytest.mark.asyncio
    async def test_new_query_persists_one_canonical_key(self) -> None:
        db = create_mock_session()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)
        db.add = MagicMock()
        savepoint = MagicMock()
        savepoint.__aenter__ = AsyncMock(return_value=None)
        savepoint.__aexit__ = AsyncMock(return_value=False)
        db.begin_nested = MagicMock(return_value=savepoint)
        location = Location(
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            state_province=" CA ",
            city="San Francisco",
        ).to_dict()

        query = await find_or_create_query(
            db,
            search_keywords=[" Python ", "developer", "PYTHON"],
            locations=[location, location],
        )

        assert query.search_keywords == ["developer", "python"]
        assert query.locations == [
            {
                "country": "USA",
                "location_type": "PHYSICAL",
                "state_province": "ca",
                "city": "san francisco",
            }
        ]

    @pytest.mark.asyncio
    async def test_concurrent_canonical_insert_reselects_winner_without_outer_rollback(
        self,
    ) -> None:
        """A uniqueness race resolves to the winner without aborting the event transaction."""
        db = create_mock_session()
        initial = MagicMock()
        initial.scalar_one_or_none.return_value = None
        winner = MagicMock()
        winning_query = MagicMock()
        winner.scalar_one.return_value = winning_query
        db.execute = AsyncMock(side_effect=[initial, winner])
        db.add = MagicMock()
        db.flush = AsyncMock(side_effect=IntegrityError("insert canonical query", {}, RuntimeError("duplicate")))
        savepoint = MagicMock()
        savepoint.__aenter__ = AsyncMock(return_value=None)
        savepoint.__aexit__ = AsyncMock(return_value=False)
        db.begin_nested = MagicMock(return_value=savepoint)

        query = await find_or_create_query(
            db,
            search_keywords=["PYTHON", "python"],
            locations=[],
        )

        assert query is winning_query
        assert db.execute.await_count == 2
        db.rollback.assert_not_awaited()


class TestCreateOrUpdateContributor:
    """Contributor ownership is unique across canonical queries."""

    @pytest.mark.asyncio
    async def test_existing_preference_moves_instead_of_creating_duplicate(self) -> None:
        db = create_mock_session()
        old_query_id = uuid4()
        target_query_id = uuid4()
        contributor = MagicMock()
        contributor.query_id = old_query_id
        result = MagicMock()
        result.scalar_one_or_none.return_value = contributor
        db.execute.return_value = result
        db.add = MagicMock()
        data = ContributorInput(
            query_id=target_query_id,
            pref_id=uuid4(),
            user_id=uuid4(),
            work_arrangements=[WorkArrangement.HYBRID],
            locations=[],
            sources=[JobBoardSource.INDEED],
            frequency_tier="hourly",
            is_active=True,
        )

        moved = await create_or_update_contributor(db, data)

        assert moved is contributor
        assert contributor.query_id == target_query_id
        assert contributor.previous_query_id == old_query_id
        db.add.assert_not_called()
        db.flush.assert_awaited_once()


class TestDeleteContributor:
    """Tests for delete_contributor function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        """Test that None is returned when contributor not found."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        query_id, is_last = await delete_contributor(mock_db, uuid4())

        assert query_id is None
        assert is_last is False

    @pytest.mark.asyncio
    async def test_deletes_contributor_and_checks_remaining(self) -> None:
        """Test that contributor is deleted and remaining count is checked."""
        mock_db = create_mock_session()
        mock_contributor = MagicMock()
        mock_contributor.query_id = uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_contributor
        mock_db.execute.return_value = mock_result
        mock_db.scalar.return_value = 0

        query_id, is_last = await delete_contributor(mock_db, uuid4())

        assert query_id == mock_contributor.query_id
        assert is_last is True

    @pytest.mark.asyncio
    async def test_returns_not_last_when_others_remain(self) -> None:
        """Test that is_last is False when other contributors remain."""
        mock_db = create_mock_session()
        mock_contributor = MagicMock()
        mock_contributor.query_id = uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_contributor
        mock_db.execute.return_value = mock_result
        mock_db.scalar.return_value = 2

        query_id, is_last = await delete_contributor(mock_db, uuid4())

        assert query_id == mock_contributor.query_id
        assert is_last is False


class TestDeleteQuery:
    """Tests for delete_query function."""

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self) -> None:
        """Test that False is returned when query not found."""
        mock_db = create_mock_session()
        mock_db.get.return_value = None

        result = await delete_query(mock_db, uuid4())

        assert result is False

    @pytest.mark.asyncio
    async def test_deletes_query_and_returns_true(self) -> None:
        """Test that query is deleted and True is returned."""
        mock_db = create_mock_session()
        mock_query = MagicMock()
        mock_db.get.return_value = mock_query

        result = await delete_query(mock_db, uuid4())

        assert result is True
        mock_db.delete.assert_awaited_once_with(mock_query)


class TestUpdateContributorFrequency:
    """Tests for update_contributor_frequency function."""

    @pytest.mark.asyncio
    async def test_updates_frequency_for_all_contributors(self) -> None:
        """Test that frequency tier is updated for all user contributors via bulk UPDATE."""
        mock_db = create_mock_session()
        user_id = uuid4()
        query_id1 = uuid4()
        query_id2 = uuid4()

        mock_select_result = MagicMock()
        mock_select_result.fetchall.return_value = [(query_id1,), (query_id2,)]

        mock_update_result = MagicMock()

        mock_db.execute.side_effect = [mock_select_result, mock_update_result]

        result = await update_contributor_frequency(mock_db, user_id, "premium")

        assert len(result) == 2
        assert query_id1 in result
        assert query_id2 in result
        assert mock_db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_contributors(self) -> None:
        """Test that empty list is returned when no contributors."""
        mock_db = create_mock_session()
        user_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        result = await update_contributor_frequency(mock_db, user_id, "premium")

        assert result == []
        assert mock_db.execute.await_count == 1


class TestSetUserInactive:
    """Tests for set_user_inactive function."""

    @pytest.mark.asyncio
    async def test_sets_active_contributors_inactive(self) -> None:
        """Test that active contributors are set inactive via bulk UPDATE."""
        mock_db = create_mock_session()
        user_id = uuid4()
        query_id = uuid4()

        mock_select_result = MagicMock()
        mock_select_result.fetchall.return_value = [(query_id,)]

        mock_update_result = MagicMock()

        mock_db.execute.side_effect = [mock_select_result, mock_update_result]

        result = await set_user_inactive(mock_db, user_id)

        assert len(result) == 1
        assert query_id in result
        assert mock_db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_active_contributors(self) -> None:
        """Test that empty list is returned when no active contributors."""
        mock_db = create_mock_session()
        user_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        result = await set_user_inactive(mock_db, user_id)

        assert result == []
        assert mock_db.execute.await_count == 1


class TestDeleteUserContributions:
    """Tests for delete_user_contributions function."""

    @pytest.mark.asyncio
    async def test_deletes_all_user_contributions(self) -> None:
        """Test that all user contributions are deleted via bulk DELETE."""
        mock_db = create_mock_session()
        user_id = uuid4()
        query_id1 = uuid4()
        query_id2 = uuid4()

        mock_select_result = MagicMock()
        mock_select_result.fetchall.return_value = [(query_id1,), (query_id2,)]

        mock_delete_result = MagicMock()
        mock_delete_result.rowcount = 2

        mock_db.execute.side_effect = [mock_select_result, mock_delete_result]

        result = await delete_user_contributions(mock_db, user_id)

        assert len(result) == 2
        assert query_id1 in result
        assert query_id2 in result
        assert mock_db.execute.await_count == 2
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bulk_delete_uses_configured_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bulk account deletion targets the configured schema, not the model default."""
        settings = MagicMock()
        settings.database.schema_name = "tenant_override"
        monkeypatch.setattr(query_service_module, "get_settings", MagicMock(return_value=settings))

        mock_db = create_mock_session()
        user_id = uuid4()
        query_id = uuid4()
        mock_select_result = MagicMock()
        mock_select_result.fetchall.return_value = [(query_id,)]
        mock_delete_result = MagicMock()
        mock_delete_result.rowcount = 1
        mock_db.execute.side_effect = [mock_select_result, mock_delete_result]

        await delete_user_contributions(mock_db, user_id)

        statements = [str(call.args[0]) for call in mock_db.execute.await_args_list]
        assert "tenant_override.query_contributors" in statements[0]
        assert "tenant_override.query_contributors" in statements[1]
        assert "tenant_override.ingestion_queries" in statements[1]
        assert all("job_query_schema." not in statement for statement in statements)

    @pytest.mark.asyncio
    async def test_returns_empty_set_when_no_contributions(self) -> None:
        """Test that empty set is returned when no contributions."""
        mock_db = create_mock_session()
        user_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        result = await delete_user_contributions(mock_db, user_id)

        assert result == set()
        assert mock_db.execute.await_count == 1


class TestSetUserActive:
    """Tests for set_user_active function."""

    @pytest.mark.asyncio
    async def test_reactivates_inactive_contributors(self) -> None:
        """Test that inactive contributors are reactivated via bulk UPDATE."""
        mock_db = create_mock_session()
        user_id = uuid4()
        query_id = uuid4()

        mock_select_result = MagicMock()
        mock_select_result.fetchall.return_value = [(query_id,)]

        mock_update_result = MagicMock()

        mock_db.execute.side_effect = [mock_select_result, mock_update_result]

        result = await set_user_active(mock_db, user_id)

        assert len(result) == 1
        assert query_id in result
        assert mock_db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_inactive_contributors(self) -> None:
        """Test that empty list is returned when no inactive contributors."""
        mock_db = create_mock_session()
        user_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        result = await set_user_active(mock_db, user_id)

        assert result == []
        assert mock_db.execute.await_count == 1
