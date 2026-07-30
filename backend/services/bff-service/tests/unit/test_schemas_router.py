"""Tests for schemas router.

This module consolidates all schema router tests:
- Response model validation tests
- Handler tests for CRUD operations
- Internal helper function tests
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi import HTTPException
from nohiki_db_utils.testing import create_mock_session
from pydantic import BaseModel

from ._helpers import (
    make_scalar_all,
    make_schema_family_projection,
    make_schema_version_projection,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


# Inline model definitions to test without importing heavy deps


class SchemaVersionResponse(BaseModel):
    """Response for a single schema version."""

    id: str
    family_id: str
    version: int
    json_schema: dict[str, object]


class SchemaFamilyResponse(BaseModel):
    """Response for a single schema family."""

    id: str
    name: str
    description: str | None
    latest_version: SchemaVersionResponse | None


class SchemaFamilyListResponse(BaseModel):
    """Response for listing schema families."""

    families: list[SchemaFamilyResponse]
    total: int


# Response Model Tests


class TestResponseModels:
    """Tests for response models."""

    def test_schema_version_response(self) -> None:
        response = SchemaVersionResponse(
            id="test-id",
            family_id="family-id",
            version=1,
            json_schema={"type": "object"},
        )
        assert response.id == "test-id"
        assert response.version == 1
        assert response.json_schema == {"type": "object"}

    def test_schema_family_response(self) -> None:
        response = SchemaFamilyResponse(
            id="test-id",
            name="Test Schema",
            description="A test schema",
            latest_version=None,
        )
        assert response.name == "Test Schema"
        assert response.description == "A test schema"
        assert response.latest_version is None

    def test_schema_family_response_with_latest(self) -> None:
        latest = SchemaVersionResponse(
            id="v-id",
            family_id="f-id",
            version=2,
            json_schema={},
        )
        response = SchemaFamilyResponse(
            id="test-id",
            name="Test Schema",
            description=None,
            latest_version=latest,
        )
        assert response.latest_version is not None
        assert response.latest_version.version == 2

    def test_schema_family_list_response(self) -> None:
        response = SchemaFamilyListResponse(families=[], total=0)
        assert response.families == []
        assert response.total == 0

    def test_schema_family_list_response_with_families(self) -> None:
        family = SchemaFamilyResponse(
            id="test-id",
            name="Test",
            description=None,
            latest_version=None,
        )
        response = SchemaFamilyListResponse(families=[family], total=1)
        assert len(response.families) == 1
        assert response.total == 1


# Schema Handler Tests


class TestSchemaHandlers:
    """Tests for schema router handlers."""

    @pytest.mark.asyncio
    async def test_list_schema_families_returns_all_families(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.schemas import list_schema_families
        from nohiki_fastapi_utils import PaginationParams

        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        version_id = uuid.uuid4()
        mock_db = create_mock_session()
        pagination = PaginationParams(page=1, page_size=20)

        family = make_schema_family_projection(id=family_id, name="Test Schema")
        version = make_schema_version_projection(id=version_id, family_id=family_id)

        count_result = mocker.MagicMock()
        count_result.scalar.return_value = 1

        families_result = mocker.MagicMock()
        families_result.scalars.return_value = make_scalar_all([family])
        version_result = mocker.MagicMock()
        version_result.scalars.return_value.all.return_value = [version]
        mock_db.execute.side_effect = [count_result, families_result, version_result]

        result = await list_schema_families(user_id, mock_db, pagination)

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].name == "Test Schema"
        assert result.items[0].latest_version is not None

    @pytest.mark.asyncio
    async def test_get_schema_family_returns_single_family(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.schemas import get_schema_family

        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        mock_db = create_mock_session()

        family = make_schema_family_projection(id=family_id, name="Resume Schema")
        version = make_schema_version_projection(family_id=family_id, version=2)

        family_result = mocker.MagicMock()
        family_result.scalar_one_or_none.return_value = family
        version_result = mocker.MagicMock()
        version_result.scalars.return_value.all.return_value = [version]
        mock_db.execute.side_effect = [family_result, version_result]

        result = await get_schema_family(family_id, user_id, mock_db)

        assert result.id == str(family_id)
        assert result.name == "Resume Schema"
        assert result.latest_version is not None
        assert result.latest_version.version == 2

    @pytest.mark.asyncio
    async def test_get_schema_family_raises_404_when_not_found(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.schemas import get_schema_family

        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        mock_db = create_mock_session()

        mock_result = mocker.MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await get_schema_family(family_id, user_id, mock_db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_schema_versions_returns_all_versions(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.schemas import list_schema_versions

        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        mock_db = create_mock_session()

        v1 = make_schema_version_projection(family_id=family_id, version=1)
        v2 = make_schema_version_projection(family_id=family_id, version=2)

        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value = make_scalar_all([v2, v1])
        mock_db.execute.return_value = mock_result

        result = await list_schema_versions(family_id, user_id, mock_db)

        assert len(result) == 2
        assert result[0].version == 2
        assert result[1].version == 1

    @pytest.mark.asyncio
    async def test_get_schema_version_returns_specific_version(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.schemas import get_schema_version

        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        version_num = 3
        mock_db = create_mock_session()

        version = make_schema_version_projection(
            family_id=family_id,
            version=version_num,
            schema_content={"type": "object", "properties": {"name": {"type": "string"}}},
        )
        mock_result = mocker.MagicMock()
        mock_result.scalar_one_or_none.return_value = version
        mock_db.execute.return_value = mock_result

        result = await get_schema_version(family_id, version_num, user_id, mock_db)

        assert result.family_id == str(family_id)
        assert result.version == version_num
        assert "properties" in result.json_schema

    @pytest.mark.asyncio
    async def test_get_schema_version_raises_404_when_not_found(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.schemas import get_schema_version

        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        mock_db = create_mock_session()

        mock_result = mocker.MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await get_schema_version(family_id, 99, user_id, mock_db)

        assert exc_info.value.status_code == 404

    def test_version_to_response_converts_projection(self) -> None:
        from bff_service.api.routers.schemas import _version_to_response
        from bff_service.db.models import SchemaVersionProjection

        version_id = uuid.uuid4()
        family_id = uuid.uuid4()
        version = SchemaVersionProjection(
            id=version_id,
            family_id=family_id,
            version=5,
            schema_content={"title": "Test"},
        )

        response = _version_to_response(version)

        assert response.id == str(version_id)
        assert response.family_id == str(family_id)
        assert response.version == 5
        assert response.json_schema == {"title": "Test"}

    @pytest.mark.asyncio
    async def test_get_latest_version_returns_highest_version(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.schemas import _get_latest_version

        family_id = uuid.uuid4()
        mock_db = create_mock_session()

        latest = make_schema_version_projection(family_id=family_id, version=10)
        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value.all.return_value = [latest]
        mock_db.execute.return_value = mock_result

        result = await _get_latest_version(mock_db, family_id)

        assert result is not None
        assert result.version == 10

    @pytest.mark.asyncio
    async def test_get_latest_version_returns_none_when_no_versions(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.schemas import _get_latest_version

        family_id = uuid.uuid4()
        mock_db = create_mock_session()

        mock_result = mocker.MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await _get_latest_version(mock_db, family_id)

        assert result is None
