"""Doc template domain projection handlers."""

import json
from datetime import UTC, datetime
from uuid import UUID

from nohiki.common.v1 import AccessScope, ProcessingStatus
from nohiki.doc.template.v1 import (
    DocumentRenderCompleted,
    TemplateCreated,
    TemplateDeleted,
    TemplateUpdated,
)
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bff_service.core.kafka import kafka_client
from bff_service.db.models import DocumentGenerationStatus, TemplateProjection
from bff_service.events.projections._constants import projection_priority_group_id
from bff_service.events.projections._helpers import mark_command_completed
from bff_service.sse import get_sse_bridge
from bff_service.sse.events import SSE_EVENT_DOCUMENT_STATUS, DocumentStatusPayload

logger = get_logger(__name__)


async def _upsert_template_from_snapshot(session: AsyncSession, msg: TemplateCreated | TemplateUpdated) -> bool:
    """Upsert template projection from ECST snapshot."""
    now = datetime.now(UTC)
    template_id = UUID(msg.template_id)

    snapshot = msg.template_snapshot
    if not snapshot:
        logger.warning("No template_snapshot in event", template_id=msg.template_id)
        return False

    version_snapshot = getattr(snapshot, "version_snapshot", None)
    if not version_snapshot:
        logger.warning("No version_snapshot in event", template_id=msg.template_id)
        return False

    if (
        not snapshot.namespace
        or not snapshot.name
        or not version_snapshot.version
        or not version_snapshot.template_content
    ):
        logger.warning("Template snapshot is incomplete", template_id=msg.template_id)
        return False
    content_schema: dict[str, object] | None = None
    if version_snapshot.content_schema_json:
        parsed = json.loads(version_snapshot.content_schema_json)
        if not isinstance(parsed, dict):
            logger.warning("Template content schema is not an object", template_id=msg.template_id)
            return False
        content_schema = parsed

    access_scope = snapshot.access_scope or AccessScope.PUBLIC
    owner_id = UUID(snapshot.owner_id) if snapshot.owner_id else None
    display_name = snapshot.display_name
    audience = snapshot.audience

    stmt = (
        insert(TemplateProjection)
        .values(
            id=template_id,
            version_id=UUID(version_snapshot.version_id) if version_snapshot.version_id else None,
            namespace=snapshot.namespace or "default",
            name=snapshot.name,
            display_name=display_name,
            version=version_snapshot.version,
            template_content=version_snapshot.template_content,
            content_schema=content_schema,
            description=snapshot.description or None,
            access_scope=access_scope,
            owner_id=owner_id,
            audience=audience,
            is_active=True,
            created_at=now,
        )
        .on_conflict_do_update(
            index_elements=["id"],
            set_={
                "version_id": UUID(version_snapshot.version_id) if version_snapshot.version_id else None,
                "namespace": snapshot.namespace or "default",
                "name": snapshot.name,
                "display_name": display_name,
                "version": version_snapshot.version,
                "template_content": version_snapshot.template_content,
                "content_schema": content_schema,
                "description": snapshot.description or None,
                "access_scope": access_scope,
                "owner_id": owner_id,
                "audience": audience,
                "is_active": True,
            },
        )
    )
    result = await session.execute(stmt)
    rowcount = getattr(result, "rowcount", None)
    # SQLAlchemy reports affected rows for PostgreSQL upserts. Test doubles and
    # dialects without rowcount still indicate success by completing execute.
    return not isinstance(rowcount, int) or rowcount > 0


@kafka_client.message_handler(
    Topics.DOC_TEMPLATE_CREATED,
    TemplateCreated,
    group_id=projection_priority_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_template_created(message: TemplateCreated, context: MessageContext) -> None:
    """Handle template created event - upsert template projection."""
    session = context.require_db_session()
    if await _upsert_template_from_snapshot(session, message):
        await mark_command_completed(
            session,
            message.metadata.correlation_id if message.metadata else None,
        )
        logger.info("Template projection created (ECST)", template_id=message.template_id)


@kafka_client.message_handler(
    Topics.DOC_TEMPLATE_UPDATED,
    TemplateUpdated,
    group_id=projection_priority_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_template_updated(message: TemplateUpdated, context: MessageContext) -> None:
    """Handle template updated event - upsert template projection."""
    session = context.require_db_session()
    if await _upsert_template_from_snapshot(session, message):
        await mark_command_completed(
            session,
            message.metadata.correlation_id if message.metadata else None,
        )
        logger.info("Template projection updated (ECST)", template_id=message.template_id)


@kafka_client.message_handler(
    Topics.DOC_TEMPLATE_DELETED,
    TemplateDeleted,
    group_id=projection_priority_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_template_deleted(message: TemplateDeleted, context: MessageContext) -> None:
    """Handle template deleted event - remove template projection."""
    template_id = UUID(message.template_id)
    session = context.require_db_session()
    await session.execute(delete(TemplateProjection).where(TemplateProjection.id == template_id))
    await mark_command_completed(
        session,
        message.metadata.correlation_id if message.metadata else None,
    )
    logger.info("Template projection deleted", template_id=message.template_id)


@kafka_client.message_handler(
    Topics.DOC_TEMPLATE_RENDER_COMPLETED,
    DocumentRenderCompleted,
    group_id=projection_priority_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session(auto_commit=False)
async def handle_render_completed(message: DocumentRenderCompleted, context: MessageContext) -> None:
    """Handle render completed event - update document generation status with S3 storage info."""
    correlation_id = message.metadata.correlation_id if message.metadata else None
    if not correlation_id:
        logger.warning("RenderCompleted missing correlation_id, skipping status update")
        return

    request_id = UUID(correlation_id)
    now = datetime.now(UTC)

    status = "completed" if message.result and message.result.status == ProcessingStatus.COMPLETED else "failed"
    error_msg = message.result.error.error_message if message.result and message.result.error else None

    session = context.require_db_session()
    stmt = (
        update(DocumentGenerationStatus)
        .where(
            DocumentGenerationStatus.request_id == request_id,
            DocumentGenerationStatus.status.not_in(("completed", "failed")),
        )
        .values(
            status=status,
            storage_key=message.storage_key if status == "completed" else None,
            file_size=message.file_size if status == "completed" else None,
            content_hash=message.content_hash if status == "completed" else None,
            error_message=error_msg,
            completed_at=now,
        )
    )
    await session.execute(stmt)
    await session.commit()

    canonical_result = await session.execute(
        select(DocumentGenerationStatus).where(
            DocumentGenerationStatus.request_id == request_id,
            DocumentGenerationStatus.status.in_(("completed", "failed")),
        )
    )
    canonical = canonical_result.scalar_one_or_none()
    if canonical is None:
        logger.warning(
            "Terminal document status missing after render completion",
            request_id=str(request_id),
        )
        return

    logger.info(
        "Document generation status persisted",
        request_id=str(request_id),
        status=canonical.status,
        storage_key=canonical.storage_key,
    )
    payload = DocumentStatusPayload(
        type=SSE_EVENT_DOCUMENT_STATUS,
        request_id=str(canonical.request_id),
        status=canonical.status,
        storage_key=canonical.storage_key,
        error_message=canonical.error_message,
        file_size=canonical.file_size,
        content_hash=canonical.content_hash,
    )
    await get_sse_bridge().publish(canonical.user_id, payload)
