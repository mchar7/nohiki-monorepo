"""Tests for template_service.py."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from doc_template_service.db.models import DocumentTemplate
from doc_template_service.schemas.templates import (
    TemplateCreateRequest,
    TemplateListQuery,
)
from doc_template_service.services.template_service import (
    SystemScopeNotAllowedError,
    TemplateDuplicateError,
    TemplateNotFoundError,
    _template_to_response,
    create_template,
    delete_all_template_versions,
    delete_template,
    generate_etag,
    get_latest_template,
    get_template_by_id,
    get_template_by_name_version,
    get_template_model_by_id,
    list_template_versions,
    list_templates,
    template_exists,
    template_version_exists,
)
from nohiki.common.v1 import AccessScope
from nohiki.doc.template.v1 import TemplateAudience
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def mock_db() -> MagicMock:
    """Mock SQLAlchemy AsyncSession."""
    return MagicMock(spec=AsyncSession)


@pytest.fixture
def mock_cache() -> MagicMock:
    """Mock RedisCache instance."""
    mock = MagicMock()
    # Mocking methods as AsyncMock to handle await calls from decorators
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=None)
    mock.delete = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def sample_template() -> DocumentTemplate:
    """Create a sample DocumentTemplate for testing."""
    return DocumentTemplate(
        id=uuid.uuid4(),
        namespace="test",
        name="test-template",
        display_name="Test Template",
        version="1.0.0",
        template_content="<html>{{ content }}</html>",
        content_schema={"type": "object"},
        description="Test template",
        access_scope=AccessScope.PUBLIC,
        audience=TemplateAudience.DOCUMENT,
        owner_id=None,
        created_at=datetime.now(UTC),
    )


class TestTemplateService:
    """Unit tests for TemplateService functions."""

    def test_generate_etag(self, sample_template: DocumentTemplate) -> None:
        """Test ETag generation."""
        etag = generate_etag(sample_template)
        assert isinstance(etag, str)
        assert len(etag) == 64  # SHA-256 hash length

    @pytest.mark.asyncio
    async def test_get_template_by_id_caching_behavior(
        self, mock_db: MagicMock, mock_cache: MagicMock, sample_template: DocumentTemplate
    ) -> None:
        """Test getting template by ID uses cache correctly."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = mock_result

        # Patch the cache used by the decorator
        with (
            patch("doc_template_service.services.template_service.cache", mock_cache),
            patch("doc_template_service.services.template_service.can_access_resource", return_value=True),
        ):
            # 1. First call: Cache miss, should call DB and then set cache
            response1 = await get_template_by_id(mock_db, sample_template.id, uuid.uuid4())

            assert response1.id == sample_template.id
            assert mock_db.execute.call_count == 1
            mock_cache.get.assert_called_once()
            mock_cache.set.assert_called_once()

            # Reset mocks for next step
            mock_db.execute.reset_mock()
            mock_cache.get.reset_mock()
            mock_cache.set.reset_mock()

            # 2. Second call: Cache hit, should NOT call DB
            cached_val = _template_to_response(sample_template)
            mock_cache.get.return_value = cached_val

            response2 = await get_template_by_id(mock_db, sample_template.id, uuid.uuid4())

            assert response2.id == sample_template.id
            assert mock_db.execute.call_count == 0  # CRITICAL: No DB call
            mock_cache.get.assert_called_once()
            assert mock_cache.set.call_count == 0  # No need to set if hit

    @pytest.mark.asyncio
    async def test_get_template_by_id_unauthorized(self, mock_db: MagicMock, sample_template: DocumentTemplate) -> None:
        """Test getting template by ID raises error if unauthorized."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = mock_result

        with (
            patch("doc_template_service.services.template_service.can_access_resource", return_value=False),
            pytest.raises(TemplateNotFoundError),
        ):
            await get_template_by_id(mock_db, sample_template.id, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_template_by_id_not_found(self, mock_db: MagicMock) -> None:
        """Test getting template by ID raises error if not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(TemplateNotFoundError):
            await get_template_by_id(mock_db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_template_by_name_version_caching_behavior(
        self, mock_db: MagicMock, mock_cache: MagicMock, sample_template: DocumentTemplate
    ) -> None:
        """Test getting template by name/version uses cache correctly."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = mock_result

        with (
            patch("doc_template_service.services.template_service.cache", mock_cache),
            patch("doc_template_service.services.template_service.can_access_resource", return_value=True),
        ):
            # Cache miss
            await get_template_by_name_version(
                mock_db, sample_template.namespace, sample_template.name, sample_template.version, uuid.uuid4()
            )
            assert mock_db.execute.call_count == 1
            mock_cache.get.assert_called_once()
            mock_cache.set.assert_called_once()

            mock_db.execute.reset_mock()
            mock_cache.get.reset_mock()

            # Cache hit
            mock_cache.get.return_value = _template_to_response(sample_template)

            await get_template_by_name_version(
                mock_db, sample_template.namespace, sample_template.name, sample_template.version, uuid.uuid4()
            )
            assert mock_db.execute.call_count == 0
            mock_cache.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_template_by_name_version_unauthorized(
        self, mock_db: MagicMock, sample_template: DocumentTemplate
    ) -> None:
        """Test getting template by name/version raises error if unauthorized."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = mock_result

        with (
            patch("doc_template_service.services.template_service.can_access_resource", return_value=False),
            pytest.raises(TemplateNotFoundError),
        ):
            await get_template_by_name_version(
                mock_db, sample_template.namespace, sample_template.name, sample_template.version, uuid.uuid4()
            )

    @pytest.mark.asyncio
    async def test_get_latest_template_success(self, mock_db: MagicMock, sample_template: DocumentTemplate) -> None:
        """Test getting the latest template successfully."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = mock_result

        response = await get_latest_template(mock_db, sample_template.namespace, sample_template.name, uuid.uuid4())

        assert response.name == sample_template.name

    @pytest.mark.asyncio
    async def test_get_latest_template_not_found(self, mock_db: MagicMock) -> None:
        """Test getting latest template raises error if none found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(TemplateNotFoundError):
            await get_latest_template(mock_db, "nonexistent", "template", uuid.uuid4())

    @pytest.mark.asyncio
    async def test_list_templates(self, mock_db: MagicMock, sample_template: DocumentTemplate) -> None:
        """Test listing templates with filters."""
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [sample_template]

        mock_db.execute.side_effect = [mock_count_result, mock_list_result]

        filters = TemplateListQuery(page=1, page_size=10)
        response = await list_templates(mock_db, filters, uuid.uuid4())

        assert response.total == 1
        assert len(response.templates) == 1
        assert response.templates[0].id == sample_template.id

    @pytest.mark.asyncio
    async def test_list_templates_latest_only(self, mock_db: MagicMock, sample_template: DocumentTemplate) -> None:
        """Test listing templates with latest_only=True."""
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [sample_template]

        mock_db.execute.side_effect = [mock_count_result, mock_list_result]

        filters = TemplateListQuery(page=1, page_size=10, latest_only=True)
        response = await list_templates(mock_db, filters, uuid.uuid4())

        assert response.total == 1
        assert len(response.templates) == 1

    @pytest.mark.asyncio
    async def test_list_template_versions_success(self, mock_db: MagicMock, sample_template: DocumentTemplate) -> None:
        """Test listing all versions of a template."""
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [sample_template]
        mock_db.execute.return_value = mock_list_result

        response = await list_template_versions(mock_db, sample_template.namespace, sample_template.name, uuid.uuid4())

        assert response.total == 1
        assert response.versions[0].version == sample_template.version

    @pytest.mark.asyncio
    async def test_list_template_versions_not_found(self, mock_db: MagicMock) -> None:
        """Test listing versions raises error if none found."""
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_list_result

        with pytest.raises(TemplateNotFoundError):
            await list_template_versions(mock_db, "nonexistent", "template", uuid.uuid4())

    @pytest.mark.asyncio
    async def test_create_template_success(self, mock_db: MagicMock) -> None:
        """Test creating a new template successfully."""
        user_id = uuid.uuid4()
        request = TemplateCreateRequest(
            namespace="test",
            name="new-template",
            display_name="New Template",
            version="1.0.0",
            template_content="content",
            access_scope=AccessScope.PUBLIC,
        )

        with (
            patch("doc_template_service.services.template_service.validate_semantic_version"),
            patch("doc_template_service.services.template_service._prime_template_cache"),
        ):
            template = await create_template(mock_db, request, user_id)

            assert template.name == "new-template"
            assert template.version == "1.0.0"
            mock_db.add.assert_called_once()
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_template_system_scope_unauthorized(self, mock_db: MagicMock) -> None:
        """Test only seeder can create SYSTEM-scoped templates."""
        request = TemplateCreateRequest(
            namespace="test",
            name="sys-template",
            display_name="Sys Template",
            version="1.0.0",
            template_content="content",
            access_scope=AccessScope.SYSTEM,
        )

        with (
            patch("doc_template_service.services.template_service.validate_semantic_version"),
            pytest.raises(SystemScopeNotAllowedError),
        ):
            await create_template(mock_db, request, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_create_template_duplicate(self, mock_db: MagicMock) -> None:
        """Test creating a duplicate template raises TemplateDuplicateError."""
        from sqlalchemy.exc import IntegrityError

        request = TemplateCreateRequest(
            namespace="test",
            name="dup-template",
            display_name="Dup Template",
            version="1.0.0",
            template_content="content",
            access_scope=AccessScope.PUBLIC,
        )

        mock_db.commit.side_effect = IntegrityError("uq_template_name_version_owner", params={}, orig=Exception())

        with (
            patch("doc_template_service.services.template_service.validate_semantic_version"),
            pytest.raises(TemplateDuplicateError),
        ):
            await create_template(mock_db, request, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_delete_template_success(self, mock_db: MagicMock, sample_template: DocumentTemplate) -> None:
        """Test deleting a template successfully."""
        user_id = uuid.uuid4()
        sample_template.owner_id = user_id
        sample_template.access_scope = AccessScope.PRIVATE

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = mock_result

        with (
            patch("doc_template_service.services.template_service.can_access_resource", return_value=True),
            patch("doc_template_service.services.template_service._invalidate_template_cache"),
        ):
            await delete_template(mock_db, sample_template.id, user_id)

            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_template_invalidates_cache(
        self, mock_db: MagicMock, mock_cache: MagicMock, sample_template: DocumentTemplate
    ) -> None:
        """Test deleting a template invalidates all related cache entries."""
        user_id = uuid.uuid4()
        sample_template.owner_id = user_id
        sample_template.access_scope = AccessScope.PRIVATE

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = mock_result

        with (
            patch("doc_template_service.services.template_service.cache", mock_cache),
            patch("doc_template_service.services.template_service.can_access_resource", return_value=True),
        ):
            await delete_template(mock_db, sample_template.id, user_id)

            # Should invalidate by ID, by name/version, and latest
            assert mock_cache.delete.call_count == 3

            # Check if all keys were deleted
            deleted_keys = [call.args[0] for call in mock_cache.delete.call_args_list]
            assert f"template_by_id:{sample_template.id}" in deleted_keys
            assert (
                f"template_by_name_version:{sample_template.namespace}:{sample_template.name}:{sample_template.version}"
                in deleted_keys
            )
            assert f"template_latest:{sample_template.namespace}:{sample_template.name}" in deleted_keys

    @pytest.mark.asyncio
    async def test_delete_template_not_found(self, mock_db: MagicMock) -> None:
        """Test deleting non-existent template raises error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(TemplateNotFoundError):
            await delete_template(mock_db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_delete_template_wrong_owner(self, mock_db: MagicMock, sample_template: DocumentTemplate) -> None:
        """Test deleting template owned by someone else raises error."""
        sample_template.owner_id = uuid.uuid4()
        sample_template.access_scope = AccessScope.PRIVATE

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = mock_result

        with (
            patch("doc_template_service.services.template_service.can_access_resource", return_value=True),
            pytest.raises(TemplateNotFoundError),
        ):
            await delete_template(mock_db, sample_template.id, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_delete_all_template_versions_success(
        self, mock_db: MagicMock, sample_template: DocumentTemplate
    ) -> None:
        """Test deleting all versions successfully."""
        user_id = uuid.uuid4()
        sample_template.owner_id = user_id

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [sample_template]
        mock_db.execute.return_value = mock_list_result

        with patch("doc_template_service.services.template_service._invalidate_template_cache"):
            count = await delete_all_template_versions(mock_db, "test", "test-template", user_id)
            assert count == 1
            assert mock_db.commit.call_count == 1

    @pytest.mark.asyncio
    async def test_template_exists(self, mock_db: MagicMock) -> None:
        """Test template_exists utility."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = uuid.uuid4()
        mock_db.execute.return_value = mock_result

        exists = await template_exists(mock_db, uuid.uuid4())
        assert exists is True

    @pytest.mark.asyncio
    async def test_template_version_exists(self, mock_db: MagicMock) -> None:
        """Test template_version_exists utility."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = uuid.uuid4()
        mock_db.execute.return_value = mock_result

        exists = await template_version_exists(mock_db, "test", "name", "1.0.0")
        assert exists is True

    @pytest.mark.asyncio
    async def test_get_template_model_by_id(self, mock_db: MagicMock, sample_template: DocumentTemplate) -> None:
        """Test getting raw model by ID."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_template
        mock_db.execute.return_value = mock_result

        model = await get_template_model_by_id(mock_db, sample_template.id)
        assert model == sample_template


def test_template_create_rejects_invalid_content_schema() -> None:
    """Invalid JSON Schema cannot enter storage through a create request."""
    with pytest.raises(ValueError, match="content_schema is not a valid JSON Schema"):
        TemplateCreateRequest(
            namespace="test",
            name="invalid-schema",
            display_name="Invalid Schema",
            template_content="<html></html>",
            content_schema={"type": "nonsense"},
        )


def test_template_create_rejects_non_local_schema_reference() -> None:
    """A stored schema cannot reference a resource outside its own document."""
    with pytest.raises(ValueError, match=r"content_schema contains a non-local \$ref"):
        TemplateCreateRequest(
            namespace="test",
            name="remote-schema",
            display_name="Remote Schema",
            template_content="<html></html>",
            content_schema={"properties": {"summary": {"$ref": "https://schemas.example.invalid/summary.json"}}},
        )


def test_template_create_accepts_local_schema_reference() -> None:
    """References to definitions in the same schema remain supported."""
    request = TemplateCreateRequest(
        namespace="test",
        name="local-schema",
        display_name="Local Schema",
        template_content="<html></html>",
        content_schema={
            "$defs": {"summary": {"type": "string"}},
            "properties": {"summary": {"$ref": "#/$defs/summary"}},
        },
    )

    assert request.content_schema is not None
