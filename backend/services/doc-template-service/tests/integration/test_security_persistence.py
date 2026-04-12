"""Persistence regressions for template visibility and atomic event delivery."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from doc_template_service.core.auth_helpers import SYSTEM_SERVICE_UUID
from doc_template_service.db.models import SCHEMA_NAME, DocumentTemplate
from doc_template_service.events.publishers import publish_template_created_event
from doc_template_service.schemas.templates import TemplateCreateRequest, TemplateListQuery
from doc_template_service.services.template_service import create_template, list_templates
from nohiki.common.v1 import AccessScope
from nohiki.doc.template.v1 import TemplateAudience
from nohiki_db_utils import OutboxWriter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]


def _template(name: str, scope: AccessScope, owner_id: UUID | None = None) -> DocumentTemplate:
    return DocumentTemplate(
        namespace="security",
        name=name,
        display_name=name.replace("-", " ").title(),
        version="1.0.0",
        template_content="<html>{{ value }}</html>",
        content_schema={"type": "object"},
        access_scope=scope,
        audience=TemplateAudience.DOCUMENT,
        owner_id=owner_id,
    )


@pytest.mark.asyncio
async def test_duplicate_null_owner_is_rejected_by_migrated_database(async_session: AsyncSession) -> None:
    async_session.add(_template("public-template", AccessScope.PUBLIC))
    await async_session.commit()

    async_session.add(_template("public-template", AccessScope.PUBLIC))
    with pytest.raises(IntegrityError):
        await async_session.flush()


@pytest.mark.asyncio
async def test_transaction_rollback_persists_neither_template_nor_outbox_event(async_session: AsyncSession) -> None:
    request = TemplateCreateRequest(
        namespace="security",
        name="rolled-back",
        display_name="Rolled Back",
        version="1.0.0",
        template_content="<html>{{ value }}</html>",
        content_schema={"type": "object"},
        access_scope=AccessScope.PUBLIC,
        audience=TemplateAudience.DOCUMENT,
    )
    template = await create_template(async_session, request, uuid4(), commit=False)
    await publish_template_created_event(
        async_session,
        OutboxWriter(schema=SCHEMA_NAME),
        template,
    )

    await async_session.rollback()

    template_count = await async_session.scalar(sa.select(sa.func.count()).select_from(DocumentTemplate))
    outbox_count = await async_session.scalar(sa.text(f"SELECT count(*) FROM {SCHEMA_NAME}.outbox"))
    assert (template_count, outbox_count) == (0, 0)


@pytest.mark.asyncio
async def test_private_and_system_templates_are_visible_only_to_their_principals(async_session: AsyncSession) -> None:
    owner = uuid4()
    other_owner = uuid4()
    async_session.add_all(
        [
            _template("public", AccessScope.PUBLIC),
            _template("mine", AccessScope.PRIVATE, owner),
            _template("other-private", AccessScope.PRIVATE, other_owner),
            _template("system", AccessScope.SYSTEM),
        ]
    )
    await async_session.commit()
    query = TemplateListQuery(page=1, page_size=10, latest_only=False)

    owner_result = await list_templates(async_session, query, owner)
    system_result = await list_templates(async_session, query, SYSTEM_SERVICE_UUID)

    assert {template.name for template in owner_result.templates} == {"public", "mine"}
    assert {template.name for template in system_result.templates} == {"public", "system"}
