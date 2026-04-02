"""Async pagination helper for SQLAlchemy queries.

Eliminates duplicated offset/limit/count boilerplate across BFF list
endpoints by providing a single ``paginate_query`` function that accepts
a base query and pagination parameters, executes the count + page fetch,
and returns items with total count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql import Select


@dataclass(frozen=True, slots=True)
class PaginationResult[T]:
    """Result of a paginated query containing items and total count.

    Attributes:
        items: The items for the current page.
        total: Total number of items matching the query (before pagination).

    """

    items: Sequence[T]
    total: int


async def paginate_query[T](
    db: AsyncSession,
    query: Select[tuple[T]],
    *,
    offset: int,
    limit: int,
) -> PaginationResult[T]:
    """Execute a paginated query with count.

    Runs a COUNT subquery and the paginated SELECT in sequence,
    returning both the page items and the total matching count.

    Args:
        db: Async SQLAlchemy session.
        query: Base SELECT query (before offset/limit).
        offset: Number of rows to skip.
        limit: Maximum number of rows to return.

    Returns:
        PaginationResult with items and total count.

    """
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    page_query = query.offset(offset).limit(limit)
    page_result = await db.execute(page_query)
    items = page_result.scalars().all()

    return PaginationResult(items=items, total=total)
