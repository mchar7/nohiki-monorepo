"""Command handlers for doc-template-service - handles template CRUD commands via Kafka."""

from __future__ import annotations

import json
from uuid import UUID

from nohiki.doc.template.v1 import (
    TemplateCreateRequested,
    TemplateDeleteRequested,
    TemplateVersionAddRequested,
)
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger

from doc_template_service.core.auth_helpers import can_write_resource
from doc_template_service.core.config import get_settings
from doc_template_service.core.kafka import kafka_client
from doc_template_service.events.publishers import (
    publish_template_created_event,
    publish_template_deleted_event,
    publish_template_updated_event,
)
from doc_template_service.schemas.templates import TemplateCreateRequest
from doc_template_service.services.template_service import (
    TemplateDuplicateError,
    TemplateNotFoundError,
    TemplateVersionError,
    create_template,
    delete_template,
    get_template_model_by_id,
)

logger = get_logger(__name__)
settings = get_settings()
command_group_id = f"{settings.kafka_consumer_group}-commands"


@kafka_client.message_handler(Topics.DOC_TEMPLATE_CREATE_REQUESTED, TemplateCreateRequested, group_id=command_group_id)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_template_create_requested(message: TemplateCreateRequested, context: MessageContext) -> None:
    """Handle template create command - performs authoritative write."""
    request_id = message.request_id
    user_id = UUID(message.user_id)

    logger.info(
        "Processing template create command",
        request_id=request_id,
        user_id=str(user_id),
        name=message.name,
    )

    if not message.namespace:
        msg = f"namespace is required in TemplateCreateRequested for request_id={request_id}"
        raise ValueError(msg)

    content_schema = json.loads(message.content_schema_json) if message.content_schema_json else None
    db = context.require_db_session()
    outbox = context.require_outbox()

    create_request = TemplateCreateRequest(
        name=message.name,
        display_name=message.display_name,
        namespace=message.namespace,
        version="1.0.0",
        template_content=message.template_content,
        description=message.description or None,
        content_schema=content_schema,
    )

    try:
        template = await create_template(db, create_request, user_id, commit=False)

        await publish_template_created_event(db, outbox, template)

        logger.info(
            "Template create command completed",
            request_id=request_id,
            template_id=str(template.id),
            version=template.version,
        )
    except TemplateDuplicateError as e:
        logger.warning(
            "Template create command failed - duplicate",
            request_id=request_id,
            error=str(e),
        )
        return
    except TemplateVersionError as e:
        logger.warning(
            "Template create command failed - validation error",
            request_id=request_id,
            error=str(e),
        )
        return


@kafka_client.message_handler(
    Topics.DOC_TEMPLATE_VERSION_ADD_REQUESTED, TemplateVersionAddRequested, group_id=command_group_id
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_template_version_add_requested(message: TemplateVersionAddRequested, context: MessageContext) -> None:
    """Handle template version add command - creates new version of existing template."""
    request_id = message.request_id
    user_id = UUID(message.user_id)
    source_template_id = UUID(message.template_id)

    logger.info(
        "Processing template version add command",
        request_id=request_id,
        source_template_id=str(source_template_id),
        version=message.version,
    )

    content_schema = json.loads(message.content_schema_json) if message.content_schema_json else None
    db = context.require_db_session()
    outbox = context.require_outbox()

    source_template = await get_template_model_by_id(db, source_template_id)
    if source_template is None or not can_write_resource(
        source_template.access_scope,
        source_template.owner_id,
        user_id,
    ):
        logger.warning(
            "Template version add command failed - source not found",
            request_id=request_id,
            source_template_id=str(source_template_id),
        )
        raise TemplateNotFoundError(str(source_template_id))

    create_request = TemplateCreateRequest(
        name=source_template.name,
        display_name=source_template.display_name,
        namespace=source_template.namespace,
        version=message.version,
        template_content=message.template_content,
        description=message.description or None,
        content_schema=content_schema,
        access_scope=source_template.access_scope,
        audience=source_template.audience,
    )

    try:
        template = await create_template(db, create_request, user_id, commit=False)

        await publish_template_updated_event(db, outbox, template)

        logger.info(
            "Template version add command completed",
            request_id=request_id,
            template_id=str(template.id),
            version=template.version,
        )
    except (TemplateDuplicateError, TemplateVersionError) as e:
        logger.warning(
            "Template version add command failed",
            request_id=request_id,
            error=str(e),
        )
        raise


@kafka_client.message_handler(Topics.DOC_TEMPLATE_DELETE_REQUESTED, TemplateDeleteRequested, group_id=command_group_id)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_template_delete_requested(message: TemplateDeleteRequested, context: MessageContext) -> None:
    """Handle template delete command (idempotent)."""
    request_id = message.request_id
    user_id = UUID(message.user_id)
    template_id = UUID(message.template_id)

    logger.info(
        "Processing template delete command",
        request_id=request_id,
        template_id=str(template_id),
    )

    db = context.require_db_session()
    outbox = context.require_outbox()

    try:
        await delete_template(db, template_id, user_id, commit=False)

        await publish_template_deleted_event(db, outbox, template_id=str(template_id))

        logger.info(
            "Template delete command completed",
            request_id=request_id,
            template_id=str(template_id),
        )
    except TemplateNotFoundError:
        logger.warning(
            "Template delete command skipped - not found (idempotent)",
            request_id=request_id,
            template_id=str(template_id),
        )
