"""Fresh-baseline constraints for canonical search preferences."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]

_INSERT = text(
    """
    INSERT INTO user_pref_schema.search_prefs (
        user_id, pref_name, search_keywords, work_arrangements
    ) VALUES (
        :user_id,
        'Canonical profile',
        CAST(:search_keywords AS VARCHAR(100)[]),
        CAST(:work_arrangements AS user_pref_schema.work_arrangement_enum[])
    )
    """
)


@pytest.mark.parametrize(
    ("search_keywords", "work_arrangements"),
    [
        ([], ["REMOTE"]),
        (["python"], []),
    ],
)
async def test_required_search_arrays_reject_empty_values(
    async_engine: AsyncEngine,
    setup_database_schema: None,
    search_keywords: list[str],
    work_arrangements: list[str],
) -> None:
    """Rows that cannot form a canonical snapshot never enter the baseline schema."""
    _ = setup_database_schema
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        with pytest.raises(IntegrityError):
            await connection.execute(
                _INSERT,
                {
                    "user_id": uuid4(),
                    "search_keywords": search_keywords,
                    "work_arrangements": work_arrangements,
                },
            )
        await transaction.rollback()
