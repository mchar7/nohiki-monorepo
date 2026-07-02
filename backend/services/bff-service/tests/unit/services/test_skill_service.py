"""Tests for skill_service module."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_db_utils.testing import create_mock_session
from sqlalchemy.dialects import postgresql

from tests.unit.conftest import make_scalar_all

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.asyncio
async def test_search_skills_cached_success(mocker: MockerFixture) -> None:
    """Test successful cached skill search."""
    skill_id = uuid.uuid4()
    mock_skill = SimpleNamespace(
        id=skill_id,
        normalized_text="Python",
        display_name="Python Programming",
        description="A language",
        category="Programming",
        reuse_level="CROSS_SECTOR",
        job_count=100,
        profile_count=50,
    )

    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = make_scalar_all([mock_skill])
    mock_db = create_mock_session()
    mock_db.execute.return_value = mock_result

    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock()

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import search_skills_cached

        result = await search_skills_cached("py", 10, None, mock_db)

    assert len(result) == 1
    assert result[0].name == "Python"
    assert result[0].display_name == "Python Programming"


@pytest.mark.asyncio
async def test_search_sql_prioritizes_labels_over_incidental_fts(mocker: MockerFixture) -> None:
    """Exact, prefix, and later-token labels precede description-only FTS matches."""
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = make_scalar_all([])
    mock_db = create_mock_session()
    mock_db.execute.return_value = mock_result
    mock_cache = MagicMock(get=AsyncMock(return_value=None), set=AsyncMock())

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import search_skills_cached

        await search_skills_cached("com", 10, None, mock_db)

    statement = mock_db.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    values = list(compiled.params.values())

    assert "CASE WHEN" in sql
    assert "lower(coalesce(bff_schema.skill_projections.display_name" in sql
    assert "lower(bff_schema.skill_projections.normalized_text)" in sql
    assert " LIKE " in sql
    assert " ~ " in sql
    assert "search_vector @@ to_tsquery" in sql
    assert values.index(0) < values.index(1) < values.index(2) < values.index(3)
    assert "com%" in values
    assert r"(^|\W)com" in values
    assert "com:*" in values


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "escaped_prefix"),
    [("100%", r"100\%%"), ("data_set", r"data\_set%")],
)
async def test_search_sql_treats_like_wildcards_literally(
    query: str, escaped_prefix: str, mocker: MockerFixture
) -> None:
    """Percent and underscore inputs cannot broaden label-prefix matches."""
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = make_scalar_all([])
    mock_db = create_mock_session()
    mock_db.execute.return_value = mock_result
    mock_cache = MagicMock(get=AsyncMock(return_value=None), set=AsyncMock())

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import search_skills_cached

        await search_skills_cached(query, 10, None, mock_db)

    statement = mock_db.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    values = list(compiled.params.values())

    assert escaped_prefix in values
    assert sql.count("ESCAPE") >= 4


@pytest.mark.asyncio
async def test_search_sql_preserves_deterministic_ties_filter_and_bounds(mocker: MockerFixture) -> None:
    """Concise labels win ties before popularity and stable identity ordering."""
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = make_scalar_all([])
    mock_db = create_mock_session()
    mock_db.execute.return_value = mock_result
    mock_cache = MagicMock(get=AsyncMock(return_value=None), set=AsyncMock())

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import search_skills_cached

        await search_skills_cached("com", 6, "Business", mock_db)

    statement = mock_db.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    values = list(compiled.params.values())
    order_by = sql.rsplit("ORDER BY", maxsplit=1)[1]

    label_length = order_by.index("length(coalesce")
    popularity = order_by.index("job_count + bff_schema.skill_projections.profile_count DESC")
    canonical = order_by.index("bff_schema.skill_projections.normalized_text", popularity)
    stable_id = order_by.index("bff_schema.skill_projections.id", canonical)
    assert label_length < popularity < canonical < stable_id
    assert "bff_schema.skill_projections.category =" in sql
    assert "Business" in values
    assert 500 in values
    assert values[-1] == 6


@pytest.mark.asyncio
async def test_search_sql_applies_token_and_reuse_priors_within_lexical_tier(mocker: MockerFixture) -> None:
    """Single-token and reuse priors resolve ties without overriding lexical relevance."""
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = make_scalar_all([])
    mock_db = create_mock_session()
    mock_db.execute.return_value = mock_result
    mock_cache = MagicMock(get=AsyncMock(return_value=None), set=AsyncMock())

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import search_skills_cached

        # "communication" must beat multi-token "comply with regulations"
        # in their shared lexical tier, before their reuse priors are compared.
        await search_skills_cached("com", 10, None, mock_db)

    statement = mock_db.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    values = list(compiled.params.values())
    order_by = sql.rsplit("ORDER BY", maxsplit=1)[1]

    lexical_case = order_by.index("lower(coalesce")
    single_token_case = order_by.index("strpos(bff_schema.skill_projections.normalized_text")
    reuse_case = order_by.index("bff_schema.skill_projections.reuse_level =")
    label_length = order_by.index("length(coalesce")
    assert lexical_case < single_token_case < reuse_case < label_length
    space_position = values.index(" ")
    assert values[space_position + 1 : space_position + 4] == [0, 0, 1]

    reuse_values = ["transversal", "cross-sector", "sector-specific", "occupation-specific"]
    reuse_positions = [values.index(value) for value in reuse_values]
    assert reuse_positions == sorted(reuse_positions)
    for reuse_value, expected_tier in zip(reuse_values, range(4), strict=True):
        value_position = values.index(reuse_value)
        assert values[value_position + 1] == expected_tier
    assert values[values.index("occupation-specific") + 2] == 4


@pytest.mark.asyncio
async def test_search_skills_cached_with_category(mocker: MockerFixture) -> None:
    """Test cached skill search with category filter."""
    mock_skill = SimpleNamespace(
        id=uuid.uuid4(),
        normalized_text="Python",
        display_name="Python",
        description=None,
        category="Programming",
        reuse_level=None,
        job_count=10,
        profile_count=5,
    )

    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = make_scalar_all([mock_skill])
    mock_db = create_mock_session()
    mock_db.execute.return_value = mock_result

    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock()

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import search_skills_cached

        result = await search_skills_cached("py", 10, "Programming", mock_db)

    assert len(result) == 1


@pytest.mark.asyncio
async def test_search_skills_cached_from_cache() -> None:
    """Test that search returns cached results when available."""
    cached_result = [
        {"id": str(uuid.uuid4()), "name": "Cached", "display_name": "Cached", "description": None, "category": None}
    ]

    mock_db = create_mock_session()
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=cached_result)

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import search_skills_cached

        result = await search_skills_cached("py", 10, None, mock_db)

    assert result == cached_result
    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_skills_by_ids_cached_success(mocker: MockerFixture) -> None:
    """Test successful batch skill lookup by IDs."""
    skill_id = uuid.uuid4()
    mock_skill = SimpleNamespace(
        id=skill_id,
        normalized_text="Python",
        display_name="Python",
        description="A language",
        category="Programming",
        reuse_level="CROSS_SECTOR",
    )

    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = make_scalar_all([mock_skill])
    mock_db = create_mock_session()
    mock_db.execute.return_value = mock_result

    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock()

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import get_skills_by_ids_cached

        result = await get_skills_by_ids_cached("key", [str(skill_id)], mock_db)

    assert len(result) == 1
    assert result[0].id == str(skill_id)


@pytest.mark.asyncio
async def test_get_skills_by_ids_cached_empty_list() -> None:
    """Test batch lookup with empty list returns empty result."""
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock()

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import get_skills_by_ids_cached

        mock_db = create_mock_session()
        result = await get_skills_by_ids_cached("key", [], mock_db)

    assert result == []


@pytest.mark.asyncio
async def test_get_skills_by_ids_cached_invalid_uuid(mocker: MockerFixture) -> None:
    """Test batch lookup skips invalid UUIDs."""
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = make_scalar_all([])
    mock_db = create_mock_session()
    mock_db.execute.return_value = mock_result

    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock()

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import get_skills_by_ids_cached

        result = await get_skills_by_ids_cached("key", ["not-a-uuid", "also-invalid"], mock_db)

    assert result == []


@pytest.mark.asyncio
async def test_get_skills_by_ids_cached_mixed_ids(mocker: MockerFixture) -> None:
    """Test batch lookup with valid and invalid UUIDs."""
    valid_id = uuid.uuid4()
    mock_skill = SimpleNamespace(
        id=valid_id,
        normalized_text="Python",
        display_name="Python",
        description=None,
        category=None,
        reuse_level=None,
    )

    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = make_scalar_all([mock_skill])
    mock_db = create_mock_session()
    mock_db.execute.return_value = mock_result

    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock()

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import get_skills_by_ids_cached

        result = await get_skills_by_ids_cached("key", ["invalid-uuid", str(valid_id)], mock_db)

    assert len(result) == 1
    assert result[0].id == str(valid_id)


@pytest.mark.asyncio
async def test_get_skill_categories_cached(mocker: MockerFixture) -> None:
    """Test getting skill categories."""
    mock_db = create_mock_session()
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = make_scalar_all(["Programming", "Database", "DevOps"])
    mock_db.execute.return_value = mock_result

    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock()

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import get_skill_categories_cached

        result = await get_skill_categories_cached(mock_db)

    assert result == ["Programming", "Database", "DevOps"]


@pytest.mark.asyncio
async def test_get_skill_categories_cached_filters_none(mocker: MockerFixture) -> None:
    """Test that None categories are filtered out."""
    mock_db = create_mock_session()
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = make_scalar_all(["Programming", None, "Database"])
    mock_db.execute.return_value = mock_result

    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock()

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import get_skill_categories_cached

        result = await get_skill_categories_cached(mock_db)

    assert result == ["Programming", "Database"]


@pytest.mark.asyncio
async def test_get_skill_categories_from_cache() -> None:
    """Test that categories returns cached results when available."""
    cached_categories = ["CachedCategory1", "CachedCategory2"]

    mock_db = create_mock_session()
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=cached_categories)

    with patch("bff_service.services.skill_service._cache", mock_cache):
        from bff_service.services.skill_service import get_skill_categories_cached

        result = await get_skill_categories_cached(mock_db)

    assert result == cached_categories
    mock_db.execute.assert_not_awaited()
