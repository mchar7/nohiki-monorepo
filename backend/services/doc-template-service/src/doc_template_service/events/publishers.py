"""Event publishing functions for template lifecycle events via outbox pattern.

ECST Design: Events carry full DocumentTemplateSnapshot so consumers can build projections
without querying back to doc-template-service.

Single-table design: Each DocumentTemplate IS a complete version, no separate version table.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nohiki.common.v1 import AccessScope
from nohiki.doc.template.v1 import (
    DocumentTemplateSnapshot,
    DocumentTemplateVersionSnapshot,
    TemplateCreated,
    TemplateDeleted,
    TemplateUpdated,
)
from nohiki_db_utils import OutboxEventParams, create_event_metadata
from nohiki_kafka_client import Topics
from nohiki_observability import get_logger

from doc_template_service.core.config import get_settings

if TYPE_CHECKING:
    from nohiki_db_utils import OutboxWriter
    from sqlalchemy.ext.asyncio import AsyncSession

    from doc_template_service.db.models import DocumentTemplate

logger = get_logger(__name__)

AGGREGATE_TYPE = "template"
settings = get_settings()


def build_template_snapshot(template: DocumentTemplate) -> DocumentTemplateSnapshot:
    """Build ECST DocumentTemplateSnapshot from domain model.

    Single-table design: DocumentTemplate contains all version data directly.
    """
    content_schema_json = json.dumps(template.content_schema) if template.content_schema else ""

    version_snapshot = DocumentTemplateVersionSnapshot(
        version_id=str(template.id),
        version=template.version,
        template_content=template.template_content,
        content_schema_json=content_schema_json,
        description=template.description or "",
    )

    return DocumentTemplateSnapshot(
        id=str(template.id),
        namespace=template.namespace,
        name=template.name,
        display_name=template.display_name,
        access_scope=AccessScope[template.access_scope.name],
        audience=template.audience,
        owner_id=str(template.owner_id) if template.owner_id else "",
        latest_version=template.version,
        description=template.description or "",
        version_snapshot=version_snapshot,
    )


async def publish_template_created_event(
    db: AsyncSession,
    outbox: OutboxWriter,
    template: DocumentTemplate,
) -> None:
    """Publish template created event with full ECST snapshot."""
    snapshot = build_template_snapshot(template)

    event = TemplateCreated(
        metadata=create_event_metadata(settings.service_name),
        template_id=str(template.id),
        template_snapshot=snapshot,
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=str(template.id),
            event_type=Topics.DOC_TEMPLATE_CREATED,
        ),
        event=event,
    )
    logger.info(
        "Published template created event (ECST)",
        template_id=str(template.id),
        name=template.name,
        version=template.version,
    )


async def publish_template_updated_event(
    db: AsyncSession,
    outbox: OutboxWriter,
    template: DocumentTemplate,
) -> None:
    """Publish template updated event with full ECST snapshot."""
    snapshot = build_template_snapshot(template)

    event = TemplateUpdated(
        metadata=create_event_metadata(settings.service_name),
        template_id=str(template.id),
        template_snapshot=snapshot,
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=str(template.id),
            event_type=Topics.DOC_TEMPLATE_UPDATED,
        ),
        event=event,
    )
    logger.info(
        "Published template updated event (ECST)",
        template_id=str(template.id),
        version=template.version,
    )


async def publish_template_deleted_event(
    db: AsyncSession,
    outbox: OutboxWriter,
    template_id: str,
) -> None:
    """Publish template deleted event."""
    event = TemplateDeleted(
        metadata=create_event_metadata(settings.service_name),
        template_id=template_id,
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=template_id,
            event_type=Topics.DOC_TEMPLATE_DELETED,
        ),
        event=event,
    )
    logger.info("Published template deleted event", template_id=template_id)
