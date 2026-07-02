"""Tests for skills router."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from nohiki_db_utils.testing import create_mock_session

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.asyncio
async def test_search_skills_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful skill search."""
    mock_skills = [
        {
            "id": str(uuid.uuid4()),
            "name": "Python",
            "display_name": "Python",
            "description": "A language",
            "category": "Programming",
        },
        {
            "id": str(uuid.uuid4()),
            "name": "PostgreSQL",
            "display_name": "PostgreSQL",
            "description": "A database",
            "category": "Database",
        },
    ]

    mock_search = AsyncMock(return_value=mock_skills)
    monkeypatch.setattr("bff_service.api.routers.skills.search_skills_cached", mock_search)

    from bff_service.api.routers.skills import search_skills

    mock_db = create_mock_session()
    result = await search_skills(uuid.uuid4(), "py", mock_db, limit=10, category=None)

    assert result.total == 2
    assert result.query == "py"
    assert len(result.skills) == 2
    mock_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_skills_with_category(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test skill search with category filter."""
    mock_skills = [
        {
            "id": str(uuid.uuid4()),
            "name": "Python",
            "display_name": "Python",
            "description": "A language",
            "category": "Programming",
        },
    ]

    mock_search = AsyncMock(return_value=mock_skills)
    monkeypatch.setattr("bff_service.api.routers.skills.search_skills_cached", mock_search)

    from bff_service.api.routers.skills import search_skills

    mock_db = create_mock_session()
    result = await search_skills(uuid.uuid4(), "py", mock_db, limit=10, category="Programming")

    assert result.total == 1
    mock_search.assert_awaited_once_with("py", 10, "Programming", mock_db)


@pytest.mark.asyncio
async def test_get_skills_by_ids_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test batch skill lookup."""
    skill_id = str(uuid.uuid4())
    mock_skills = [
        {
            "id": skill_id,
            "name": "Python",
            "display_name": "Python",
            "description": "A language",
            "category": "Programming",
        },
    ]

    mock_get = AsyncMock(return_value=mock_skills)
    monkeypatch.setattr("bff_service.api.routers.skills.get_skills_by_ids_cached", mock_get)

    from bff_service.api.routers.skills import SkillBatchRequest, get_skills_by_ids

    mock_db = create_mock_session()
    request = SkillBatchRequest(skill_ids=[skill_id])
    result = await get_skills_by_ids(uuid.uuid4(), request, mock_db)

    assert len(result.skills) == 1
    assert result.skills[0].name == "Python"


@pytest.mark.asyncio
async def test_get_skills_by_ids_empty() -> None:
    """Test batch skill lookup with empty skill_ids returns empty list."""
    from bff_service.api.routers.skills import SkillBatchRequest, get_skills_by_ids

    mock_db = create_mock_session()
    request = SkillBatchRequest(skill_ids=[])
    result = await get_skills_by_ids(uuid.uuid4(), request, mock_db)

    assert result.skills == []


@pytest.mark.asyncio
async def test_get_skill_by_id_success(mocker: MockerFixture) -> None:
    """Test getting a single skill by ID."""
    skill_id = uuid.uuid4()
    mock_skill = SimpleNamespace(
        id=skill_id,
        normalized_text="Python",
        display_name="Python Programming",
        description="A popular programming language",
        category="Programming",
    )

    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_skill
    mock_db = create_mock_session()
    mock_db.execute.return_value = mock_result

    from bff_service.api.routers.skills import get_skill

    result = await get_skill(uuid.uuid4(), skill_id, mock_db)

    assert result.id == str(skill_id)
    assert result.name == "Python"
    assert result.display_name == "Python Programming"
    assert result.description == "A popular programming language"
    assert result.category == "Programming"


@pytest.mark.asyncio
async def test_get_skill_by_id_not_found(mocker: MockerFixture) -> None:
    """Test getting a non-existent skill returns 404."""
    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = create_mock_session()
    mock_db.execute.return_value = mock_result

    from bff_service.api.routers.skills import get_skill

    with pytest.raises(HTTPException) as exc_info:
        await get_skill(uuid.uuid4(), uuid.uuid4(), mock_db)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Skill not found"


@pytest.mark.asyncio
async def test_list_skill_categories(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test listing skill categories."""
    mock_categories = ["Programming", "Database", "DevOps"]

    mock_get = AsyncMock(return_value=mock_categories)
    monkeypatch.setattr("bff_service.api.routers.skills.get_skill_categories_cached", mock_get)

    from bff_service.api.routers.skills import list_skill_categories

    mock_db = create_mock_session()
    result = await list_skill_categories(uuid.uuid4(), mock_db)

    assert result == ["Programming", "Database", "DevOps"]
    mock_get.assert_awaited_once_with(mock_db)


def test_skill_search_result_model() -> None:
    """Test SkillSearchResult model structure."""
    from bff_service.api.routers.skills import SkillSearchResult

    result = SkillSearchResult(
        id=str(uuid.uuid4()),
        name="Python",
        display_name="Python Programming",
        description="A language",
        category="Programming",
    )

    assert result.name == "Python"
    assert result.display_name == "Python Programming"


def test_skill_search_response_model() -> None:
    """Test SkillSearchResponse model structure."""
    from bff_service.api.routers.skills import SkillSearchResponse, SkillSearchResult

    skill = SkillSearchResult(
        id=str(uuid.uuid4()),
        name="Python",
        display_name="Python Programming",
    )
    response = SkillSearchResponse(skills=[skill], total=1, query="py")

    assert response.total == 1
    assert response.query == "py"
    assert len(response.skills) == 1


def test_skill_batch_request_model() -> None:
    """Test SkillBatchRequest model validation."""
    from bff_service.api.routers.skills import SkillBatchRequest

    request = SkillBatchRequest(skill_ids=["id1", "id2"])
    assert request.skill_ids == ["id1", "id2"]


def test_skill_batch_response_model() -> None:
    """Test SkillBatchResponse model structure."""
    from bff_service.api.routers.skills import SkillBatchResponse, SkillSearchResult

    skill = SkillSearchResult(id=str(uuid.uuid4()), name="Python")
    response = SkillBatchResponse(skills=[skill])

    assert len(response.skills) == 1
    assert response.skills[0].name == "Python"
