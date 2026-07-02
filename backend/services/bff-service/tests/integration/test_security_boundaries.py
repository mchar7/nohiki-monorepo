"""PostgreSQL-backed security boundaries for BFF read and document command APIs."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest
import sqlalchemy as sa
from bff_service.api.routers.attachments import get_attachment
from bff_service.api.routers.documents import GenerateDocumentRequest, generate_document, get_document_status
from bff_service.api.routers.templates import (
    get_template_by_id,
    list_template_families,
    list_template_versions,
)
from bff_service.db.models import AttachmentProjection, DocumentGenerationStatus, TemplateProjection
from bff_service.db.models.base import SCHEMA_NAME
from fastapi import HTTPException
from nohiki.common.v1 import AccessScope
from nohiki.doc.template.v1 import TemplateAudience
from nohiki_fastapi_utils import PaginationParams
from sqlalchemy.ext.asyncio import async_sessionmaker

if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]


def _create_projection_tables(connection: Connection) -> None:
    """Create the exact tables exercised by the security integration tests."""
    tables = (
        cast("sa.Table", TemplateProjection.__table__),
        cast("sa.Table", DocumentGenerationStatus.__table__),
        cast("sa.Table", AttachmentProjection.__table__),
    )
    for table in tables:
        table.create(connection)


@pytest.fixture
async def security_session(async_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Create only the projection tables exercised by these boundaries."""
    async with async_engine.begin() as connection:
        await connection.execute(sa.text(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE"))
        await connection.execute(sa.text(f"CREATE SCHEMA {SCHEMA_NAME}"))
        await connection.run_sync(_create_projection_tables)

    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


def _template(
    *,
    template_id: uuid.UUID,
    namespace: str,
    name: str,
    display_name: str,
    version: str,
    scope: AccessScope,
    audience: TemplateAudience = TemplateAudience.DOCUMENT,
    owner_id: uuid.UUID | None = None,
    active: bool = True,
    created_second: int = 0,
) -> TemplateProjection:
    return TemplateProjection(
        id=template_id,
        namespace=namespace,
        name=name,
        display_name=display_name,
        version=version,
        template_content="<!doctype html><html><body>{{ name }}</body></html>",
        content_schema=None,
        description=None,
        access_scope=scope,
        audience=audience,
        owner_id=owner_id,
        is_active=active,
        created_at=datetime(2026, 1, 1, 0, 0, created_second, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_template_reads_enforce_owner_scope_and_active_visibility(
    security_session: AsyncSession,
) -> None:
    """Callers see DOCUMENT templates allowed by scope, never INTERNAL or inactive rows."""
    caller = uuid.uuid4()
    other_user = uuid.uuid4()
    public_id = uuid.uuid4()
    system_id = uuid.uuid4()
    internal_id = uuid.uuid4()
    own_private_id = uuid.uuid4()
    other_private_id = uuid.uuid4()
    inactive_id = uuid.uuid4()
    security_session.add_all(
        [
            _template(
                template_id=public_id,
                namespace="shared",
                name="resume",
                display_name="Professional Résumé",
                version="1.0.0",
                scope=AccessScope.PUBLIC,
            ),
            _template(
                template_id=system_id,
                namespace="shared",
                name="resume",
                display_name="Executive Résumé",
                version="2.0.0",
                scope=AccessScope.SYSTEM,
                created_second=1,
            ),
            _template(
                template_id=internal_id,
                namespace="messaging-service",
                name="job_notification",
                display_name="Job notification",
                version="1.0.0",
                scope=AccessScope.SYSTEM,
                audience=TemplateAudience.INTERNAL,
            ),
            _template(
                template_id=own_private_id,
                namespace="mine",
                name="cover-letter",
                display_name="My Cover Letter",
                version="1.0.0",
                scope=AccessScope.PRIVATE,
                owner_id=caller,
            ),
            _template(
                template_id=other_private_id,
                namespace="private",
                name="secret",
                display_name="Secret Template",
                version="1.0.0",
                scope=AccessScope.PRIVATE,
                owner_id=other_user,
            ),
            _template(
                template_id=inactive_id,
                namespace="retired",
                name="old",
                display_name="Retired Template",
                version="1.0.0",
                scope=AccessScope.PUBLIC,
                active=False,
            ),
        ]
    )
    await security_session.commit()

    families = await list_template_families(caller, security_session, PaginationParams(page=1, page_size=20))
    versions = await list_template_versions("shared", "resume", caller, security_session)
    own = await get_template_by_id(own_private_id, caller, security_session)

    assert {(family.namespace, family.name) for family in families.items} == {
        ("mine", "cover-letter"),
        ("shared", "resume"),
    }
    assert {family.display_name for family in families.items} == {"Executive Résumé", "My Cover Letter"}
    assert [version.id for version in versions] == [str(system_id), str(public_id)]
    assert [version.display_name for version in versions] == ["Executive Résumé", "Professional Résumé"]
    assert own.id == str(own_private_id)
    assert own.display_name == "My Cover Letter"
    for hidden_id in (internal_id, other_private_id, inactive_id):
        with pytest.raises(HTTPException) as exc_info:
            await get_template_by_id(hidden_id, caller, security_session)
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_private_template_cannot_create_cross_user_document(
    security_session: AsyncSession,
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A private template owned by another user returns 404 and creates no orphan status/event."""
    caller = uuid.uuid4()
    template = _template(
        template_id=uuid.uuid4(),
        namespace="private",
        name="secret",
        display_name="Secret Template",
        version="1.0.0",
        scope=AccessScope.PRIVATE,
        owner_id=uuid.uuid4(),
    )
    security_session.add(template)
    await security_session.commit()
    publish = mocker.AsyncMock()
    monkeypatch.setattr(
        "bff_service.api.routers.documents.kafka_client",
        mocker.MagicMock(publish=publish),
    )

    with pytest.raises(HTTPException) as exc_info:
        await generate_document(
            GenerateDocumentRequest(template_version_id=template.id, data={"name": "Alice"}),
            caller,
            security_session,
        )

    count = await security_session.scalar(sa.select(sa.func.count()).select_from(DocumentGenerationStatus))
    assert exc_info.value.status_code == 404
    assert count == 0
    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_document_and_upload_reads_hide_other_users_resources(
    security_session: AsyncSession,
    mocker: MockerFixture,
) -> None:
    """Known document and upload UUIDs remain indistinguishable from nonexistent cross-user resources."""
    owner = uuid.uuid4()
    caller = uuid.uuid4()
    request_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    security_session.add_all(
        [
            DocumentGenerationStatus(
                request_id=request_id,
                user_id=owner,
                template_version_id=uuid.uuid4(),
                output_format="pdf",
                status="completed",
                created_at=datetime.now(UTC),
            ),
            AttachmentProjection(
                id=upload_id,
                user_id=owner,
                filename="private.pdf",
                content_type="application/pdf",
                file_size=128,
                storage_key=f"user-uploads/{owner}/{upload_id}/private.pdf",
                created_at=datetime.now(UTC),
            ),
        ]
    )
    await security_session.commit()

    with pytest.raises(HTTPException) as document_error:
        await get_document_status(request_id, caller, security_session)
    with pytest.raises(HTTPException) as upload_error:
        await get_attachment(upload_id, caller, security_session, mocker.AsyncMock())

    assert document_error.value.status_code == 404
    assert upload_error.value.status_code == 404
