"""Tests for pagination, sorting, and paginated response utilities."""

import pytest
from nohiki_fastapi_utils.pagination import (
    PaginatedResponse,
    PaginationParams,
    SortParams,
)
from pydantic import BaseModel, ValidationError


class ItemResponse(BaseModel):
    """Minimal item model for testing generic PaginatedResponse."""

    id: int
    name: str


class TestPaginationParams:
    """Tests for PaginationParams."""

    def test_defaults(self) -> None:
        params = PaginationParams()
        assert params.page == 1
        assert params.page_size == 20

    def test_offset_calculations(self) -> None:
        assert PaginationParams(page=1, page_size=20).offset == 0
        assert PaginationParams(page=2, page_size=20).offset == 20
        assert PaginationParams(page=5, page_size=10).offset == 40

    def test_validation_rejects_invalid(self) -> None:
        with pytest.raises(ValidationError):
            PaginationParams(page=0)
        with pytest.raises(ValidationError):
            PaginationParams(page=-1)
        with pytest.raises(ValidationError):
            PaginationParams(page_size=0)
        with pytest.raises(ValidationError):
            PaginationParams(page_size=101)
        with pytest.raises(ValidationError):
            PaginationParams(page=10_001)

    def test_boundary_values_accepted(self) -> None:
        assert PaginationParams(page_size=100).page_size == 100
        assert PaginationParams(page=10_000).page == 10_000


class TestSortParams:
    """Tests for SortParams."""

    def test_defaults(self) -> None:
        params = SortParams()
        assert params.sort_by is None
        assert params.sort_dir == "desc"
        assert params.is_ascending is False

    def test_ascending(self) -> None:
        assert SortParams(sort_dir="asc").is_ascending is True

    def test_invalid_sort_dir_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SortParams(sort_dir="invalid")

    def test_sort_by_max_length_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SortParams(sort_by="a" * 65)


class TestPaginatedResponse:
    """Tests for PaginatedResponse."""

    def test_create_single_page(self) -> None:
        params = PaginationParams(page=1, page_size=20)
        items = [ItemResponse(id=i, name=f"item-{i}") for i in range(5)]
        resp = PaginatedResponse[ItemResponse].create(items=items, total=5, params=params)

        assert len(resp.items) == 5
        assert resp.total == 5
        assert resp.total_pages == 1
        assert resp.has_next is False
        assert resp.has_prev is False

    def test_create_first_of_multiple(self) -> None:
        params = PaginationParams(page=1, page_size=10)
        items = [ItemResponse(id=i, name=f"item-{i}") for i in range(10)]
        resp = PaginatedResponse[ItemResponse].create(items=items, total=25, params=params)

        assert resp.total_pages == 3
        assert resp.has_next is True
        assert resp.has_prev is False

    def test_create_middle_page(self) -> None:
        params = PaginationParams(page=2, page_size=10)
        items = [ItemResponse(id=i, name=f"item-{i}") for i in range(10)]
        resp = PaginatedResponse[ItemResponse].create(items=items, total=25, params=params)

        assert resp.has_next is True
        assert resp.has_prev is True

    def test_create_last_page(self) -> None:
        params = PaginationParams(page=3, page_size=10)
        items = [ItemResponse(id=i, name=f"item-{i}") for i in range(5)]
        resp = PaginatedResponse[ItemResponse].create(items=items, total=25, params=params)

        assert resp.has_next is False
        assert resp.has_prev is True

    def test_create_zero_total(self) -> None:
        params = PaginationParams(page=1, page_size=20)
        resp = PaginatedResponse[ItemResponse].create(items=[], total=0, params=params)

        assert resp.total == 0
        assert resp.total_pages == 1
        assert resp.has_next is False

    def test_create_exact_boundary(self) -> None:
        params = PaginationParams(page=1, page_size=10)
        items = [ItemResponse(id=i, name=f"item-{i}") for i in range(10)]
        resp = PaginatedResponse[ItemResponse].create(items=items, total=10, params=params)

        assert resp.total_pages == 1
        assert resp.has_next is False

    def test_empty(self) -> None:
        params = PaginationParams(page=1, page_size=20)
        resp = PaginatedResponse[ItemResponse].empty(params=params)

        assert resp.items == []
        assert resp.total == 0
        assert resp.total_pages == 0
        assert resp.has_next is False
        assert resp.has_prev is False

    def test_serialization_roundtrip(self) -> None:
        params = PaginationParams(page=2, page_size=10)
        items = [ItemResponse(id=1, name="test")]
        resp = PaginatedResponse[ItemResponse].create(items=items, total=15, params=params)

        data = resp.model_dump()
        assert data["items"] == [{"id": 1, "name": "test"}]
        assert data["page"] == 2
        assert data["total"] == 15
