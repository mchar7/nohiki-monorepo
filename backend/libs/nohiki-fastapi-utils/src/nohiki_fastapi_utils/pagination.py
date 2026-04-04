"""Standardized pagination, sorting, and filtering for FastAPI list endpoints.

Provides reusable FastAPI dependency models for consistent pagination
across all BFF list endpoints, eliminating duplicated offset/limit
calculations and inconsistent parameter naming.

Usage::

    from nohiki_fastapi_utils.pagination import (
        PaginatedResponse,
        PaginationParams,
        SortParams,
    )

    @router.get("/items")
    async def list_items(
        pagination: Annotated[PaginationParams, Query()],
        sort: Annotated[SortParams, Query()],
    ) -> PaginatedResponse[ItemResponse]:
        ...
        return PaginatedResponse.create(
            items=items,
            total=total,
            params=pagination,
        )

"""

from typing import Self

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """Standard pagination parameters for list endpoints.

    Injected via ``Annotated[PaginationParams, Query()]`` as a FastAPI
    dependency. Computes ``offset`` from page-based parameters.
    """

    page: int = Field(default=1, ge=1, le=10_000, description="Page number (1-indexed)")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")

    @property
    def offset(self) -> int:
        """Compute SQL OFFSET from page-based parameters."""
        return (self.page - 1) * self.page_size


class SortParams(BaseModel):
    """Standard sort parameters for list endpoints.

    ``sort_by`` accepts a column name; validation of allowed columns
    is the responsibility of the endpoint handler.
    """

    sort_by: str | None = Field(default=None, max_length=64, description="Column to sort by")
    sort_dir: str = Field(default="desc", pattern=r"^(asc|desc)$", description="Sort direction")

    @property
    def is_ascending(self) -> bool:
        """Whether sort direction is ascending."""
        return self.sort_dir == "asc"


class PaginatedResponse[T](BaseModel):
    """Generic paginated response envelope.

    Wraps a list of items with pagination metadata. Use the ``create``
    classmethod to construct from query results.
    """

    items: list[T]
    total: int = Field(ge=0, description="Total number of items matching the query")
    page: int = Field(ge=1, description="Current page number")
    page_size: int = Field(ge=1, description="Items per page")
    total_pages: int = Field(ge=0, description="Total number of pages")
    has_next: bool = Field(description="Whether a next page exists")
    has_prev: bool = Field(description="Whether a previous page exists")

    @classmethod
    def create(
        cls,
        *,
        items: list[T],
        total: int,
        params: PaginationParams,
    ) -> Self:
        """Construct a paginated response from items and pagination state.

        Args:
            items: The items for the current page.
            total: Total number of items matching the query (before pagination).
            params: The pagination parameters used for the query.

        Returns:
            Fully populated paginated response with computed metadata.

        """
        total_pages = max(1, -(-total // params.page_size))
        return cls(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            total_pages=total_pages,
            has_next=params.page < total_pages,
            has_prev=params.page > 1,
        )

    @classmethod
    def empty(cls, *, params: PaginationParams) -> Self:
        """Construct an empty paginated response.

        Args:
            params: The pagination parameters used for the query.

        Returns:
            Paginated response with zero items.

        """
        return cls(
            items=[],
            total=0,
            page=params.page,
            page_size=params.page_size,
            total_pages=0,
            has_next=False,
            has_prev=False,
        )
