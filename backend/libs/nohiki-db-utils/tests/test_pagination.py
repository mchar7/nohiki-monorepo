"""Tests for async pagination helper."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_db_utils.pagination import PaginationResult, paginate_query
from nohiki_db_utils.testing import create_mock_session

_MODULE = "nohiki_db_utils.pagination"


@dataclass
class FakeRow:
    """Minimal row for testing."""

    id: int
    name: str


def _mock_session(
    *,
    count: int,
    items: Sequence[FakeRow],
) -> AsyncMock:
    """Build an AsyncSession mock that returns count then items."""
    session = create_mock_session()

    count_result = MagicMock()
    count_result.scalar.return_value = count

    page_result = MagicMock()
    page_result.scalars.return_value.all.return_value = list(items)

    session.execute = AsyncMock(side_effect=[count_result, page_result])
    return session


class TestPaginationResult:
    """Tests for PaginationResult dataclass."""

    def test_frozen(self) -> None:
        """PaginationResult is immutable."""
        import dataclasses

        assert dataclasses.is_dataclass(PaginationResult)
        params = getattr(PaginationResult, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_slots(self) -> None:
        """PaginationResult uses slots for memory efficiency."""
        result = PaginationResult(items=[], total=0)
        assert hasattr(result, "__slots__")

    def test_stores_items_and_total(self) -> None:
        """PaginationResult stores items and total correctly."""
        items = [FakeRow(id=1, name="a"), FakeRow(id=2, name="b")]
        result = PaginationResult(items=items, total=42)
        assert list(result.items) == items
        assert result.total == 42


class TestPaginateQuery:
    """Tests for paginate_query async helper."""

    @pytest.mark.asyncio
    async def test_returns_items_and_total(self) -> None:
        """paginate_query returns items from page query and total from count."""
        items = [FakeRow(id=1, name="first"), FakeRow(id=2, name="second")]
        db = _mock_session(count=50, items=items)
        query = MagicMock()

        with patch(f"{_MODULE}.select") as mock_select:
            mock_select.return_value.select_from.return_value = MagicMock()
            result = await paginate_query(db, query, offset=0, limit=20)

        assert result.total == 50
        assert list(result.items) == items

    @pytest.mark.asyncio
    async def test_applies_offset_and_limit(self) -> None:
        """paginate_query chains .offset() and .limit() on the query."""
        db = _mock_session(count=100, items=[])
        query = MagicMock()

        with patch(f"{_MODULE}.select") as mock_select:
            mock_select.return_value.select_from.return_value = MagicMock()
            await paginate_query(db, query, offset=40, limit=20)

        query.offset.assert_called_once_with(40)
        query.offset.return_value.limit.assert_called_once_with(20)

    @pytest.mark.asyncio
    async def test_executes_two_queries(self) -> None:
        """paginate_query executes count query then page query."""
        db = _mock_session(count=10, items=[])
        query = MagicMock()

        with patch(f"{_MODULE}.select") as mock_select:
            mock_select.return_value.select_from.return_value = MagicMock()
            await paginate_query(db, query, offset=0, limit=10)

        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_builds_count_from_subquery(self) -> None:
        """paginate_query calls .subquery() on the base query for counting."""
        db = _mock_session(count=10, items=[])
        query = MagicMock()

        with patch(f"{_MODULE}.select") as mock_select:
            mock_select.return_value.select_from.return_value = MagicMock()
            await paginate_query(db, query, offset=0, limit=10)

        query.subquery.assert_called_once()

    @pytest.mark.asyncio
    async def test_zero_count_returns_empty(self) -> None:
        """paginate_query handles zero total gracefully."""
        db = _mock_session(count=0, items=[])
        query = MagicMock()

        with patch(f"{_MODULE}.select") as mock_select:
            mock_select.return_value.select_from.return_value = MagicMock()
            result = await paginate_query(db, query, offset=0, limit=20)

        assert result.total == 0
        assert list(result.items) == []

    @pytest.mark.asyncio
    async def test_null_count_treated_as_zero(self) -> None:
        """paginate_query treats NULL scalar result as 0."""
        db = _mock_session(count=0, items=[])
        # Override count to return None
        count_result = MagicMock()
        count_result.scalar.return_value = None
        page_result = MagicMock()
        page_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[count_result, page_result])
        query = MagicMock()

        with patch(f"{_MODULE}.select") as mock_select:
            mock_select.return_value.select_from.return_value = MagicMock()
            result = await paginate_query(db, query, offset=0, limit=20)

        assert result.total == 0

    @pytest.mark.asyncio
    async def test_large_offset_returns_empty_items(self) -> None:
        """paginate_query with offset beyond total returns empty items."""
        db = _mock_session(count=5, items=[])
        query = MagicMock()

        with patch(f"{_MODULE}.select") as mock_select:
            mock_select.return_value.select_from.return_value = MagicMock()
            result = await paginate_query(db, query, offset=100, limit=20)

        assert result.total == 5
        assert list(result.items) == []

    @pytest.mark.asyncio
    async def test_single_item(self) -> None:
        """paginate_query works with a single item."""
        items = [FakeRow(id=1, name="only")]
        db = _mock_session(count=1, items=items)
        query = MagicMock()

        with patch(f"{_MODULE}.select") as mock_select:
            mock_select.return_value.select_from.return_value = MagicMock()
            result = await paginate_query(db, query, offset=0, limit=20)

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].name == "only"
