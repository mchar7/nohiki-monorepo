"""Render request handler for doc-template-service - handles document rendering via Kafka."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from nohiki.common.v1 import (
    ErrorInfo,
    OperationOutcome,
    ProcessingStatus,
    RenderOutputFormat,
)
from nohiki.doc.template.v1 import (
    DocumentRenderCompleted,
    DocumentRenderRequested,
)
from nohiki_common_exceptions import ValidationError
from nohiki_db_utils import OutboxEventParams
from nohiki_kafka_client import MessageContext, Topics, create_event_metadata
from nohiki_observability import get_logger
from sqlalchemy.exc import SQLAlchemyError

from doc_template_service.core.config import get_settings
from doc_template_service.core.generator import GenerationError, TextAlternativeMode, generate_document
from doc_template_service.core.kafka import kafka_client
from doc_template_service.services import store_rendered_document
from doc_template_service.services.template_service import get_template_model_by_id

if TYPE_CHECKING:
    from nohiki_db_utils import OutboxWriter
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)
settings = get_settings()

type GeneratorFormat = Literal["html", "pdf", "image", "text"]
_SHA256_HEX_LENGTH = 64
_INVALID_COMPLETED_ARTIFACTS = "completed render callback requires valid artifact metadata"


@dataclass(frozen=True, slots=True)
class RenderCompletedParams:
    """Parameters for publishing RenderCompleted event."""

    correlation_id: str
    template_id: str
    template_name: str
    template_version: str
    storage_key: str
    content_type: str
    file_size: int
    content_hash: str
    text_alternative: str


@dataclass(frozen=True, slots=True)
class RenderFailedParams:
    """Parameters for publishing a failed RenderCompleted event."""

    correlation_id: str
    template_id: str
    template_version: str
    error_message: str


_OUTPUT_FORMAT_MAP: dict[RenderOutputFormat, GeneratorFormat] = {
    RenderOutputFormat.PDF: "pdf",
    RenderOutputFormat.IMAGE: "image",
    RenderOutputFormat.TEXT: "text",
}

_CONTENT_TYPE_MAP: dict[RenderOutputFormat, str] = {
    RenderOutputFormat.PDF: "application/pdf",
    RenderOutputFormat.IMAGE: "image/png",
    RenderOutputFormat.TEXT: "text/plain",
}


def _render_output_format_to_generator_format(fmt: RenderOutputFormat) -> GeneratorFormat:
    """Convert proto RenderOutputFormat enum to generator format string."""
    return _OUTPUT_FORMAT_MAP.get(fmt, "html")


def _render_output_format_to_content_type(fmt: RenderOutputFormat) -> str:
    """Convert proto RenderOutputFormat enum to MIME content type."""
    return _CONTENT_TYPE_MAP.get(fmt, "text/html")


def _process_render_result(
    result: bytes | str | tuple[str, str],
    output_format: GeneratorFormat,
) -> tuple[bytes, str]:
    """Process render result into content bytes and text alternative."""
    if output_format == "html" and isinstance(result, tuple):
        rendered_content, text_alternative = result
        return rendered_content.encode(), text_alternative

    if isinstance(result, bytes):
        return result, ""

    return str(result).encode(), ""


def _validate_render_request(message: DocumentRenderRequested) -> tuple[str, str, str]:
    """Validate render request and extract required fields."""
    if message.metadata is None:
        raise ValidationError(field_name="metadata", constraint="metadata is required in RenderRequested event")

    correlation_id = message.metadata.correlation_id
    if not correlation_id:
        raise ValidationError(
            field_name="metadata.correlation_id",
            constraint="correlation_id is required in RenderRequested event metadata",
        )

    template_id = message.template_id
    template_version = message.template_version
    if not template_id:
        raise ValidationError(field_name="template_id", constraint="template_id is required in RenderRequested event")

    if not message.template_content:
        raise ValidationError(
            field_name="template_content",
            constraint=f"template_content is required for template_id={template_id}",
        )
    if len(message.template_content.encode("utf-8")) > 100 * 1024:
        raise ValidationError(field_name="template_content", constraint="template_content exceeds 102400 bytes")

    if not template_version:
        raise ValidationError(
            field_name="template_version",
            constraint=f"template_version is required for template_id={template_id}",
        )

    return correlation_id, template_id, template_version


async def _render_and_store(
    message: DocumentRenderRequested,
    correlation_id: str,
    template_id: str,
) -> tuple[str, str, int, str, str]:
    """Render document and store in S3."""
    output_format = _render_output_format_to_generator_format(message.output_format)
    content_type = _render_output_format_to_content_type(message.output_format)

    text_alt_mode = TextAlternativeMode.ENABLED if message.include_text_alt else TextAlternativeMode.DISABLED
    template_data = message.data.to_dict() if message.data else {}
    if len(json.dumps(template_data, separators=(",", ":")).encode("utf-8")) > 1024 * 1024:
        raise ValidationError(field_name="data", constraint="render data exceeds 1048576 bytes")
    # _validate_render_request rejects empty/None template_content before this
    # function is reached; ty cannot follow that across calls so re-establish
    # the invariant locally to keep generate_document's str contract.
    template_content = message.template_content
    if template_content is None:
        raise ValidationError(
            field_name="template_content",
            constraint=f"template_content is required for template_id={template_id}",
        )
    result = await generate_document(
        template=template_content,
        data=template_data,
        output_format=output_format,
        text_alternative=text_alt_mode,
    )

    rendered_content, text_alternative = _process_render_result(result, output_format)
    if len(rendered_content) > 25 * 1024 * 1024:
        error_message = "Document generation failed: rendered output exceeds 26214400 bytes"
        raise GenerationError(error_message)

    storage_result = await store_rendered_document(
        content=rendered_content,
        correlation_id=correlation_id,
        template_id=template_id,
        content_type=content_type,
    )

    return (
        storage_result.storage_key,
        content_type,
        storage_result.file_size,
        storage_result.content_hash,
        text_alternative,
    )


async def _publish_render_completed(
    db: AsyncSession,
    outbox: OutboxWriter,
    params: RenderCompletedParams,
) -> None:
    """Publish RenderCompleted event via outbox pattern for guaranteed delivery."""
    if (
        not params.storage_key
        or not params.content_type
        or params.file_size <= 0
        or len(params.content_hash) != _SHA256_HEX_LENGTH
    ):
        raise ValueError(_INVALID_COMPLETED_ARTIFACTS)
    response_event = DocumentRenderCompleted(
        metadata=create_event_metadata(settings.service_name, params.correlation_id),
        template_id=params.template_id,
        template_name=params.template_name,
        template_version=params.template_version,
        storage_key=params.storage_key,
        content_type=params.content_type,
        text_alternative=params.text_alternative,
        result=OperationOutcome(
            status=ProcessingStatus.COMPLETED,
        ),
        file_size=params.file_size,
        content_hash=params.content_hash,
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type="render",
            aggregate_id=params.correlation_id,
            event_type=Topics.DOC_TEMPLATE_RENDER_COMPLETED,
            correlation_id=params.correlation_id,
        ),
        event=response_event,
    )


async def _publish_render_failed(
    db: AsyncSession,
    outbox: OutboxWriter,
    params: RenderFailedParams,
) -> None:
    """Publish a schema-valid RenderCompleted event with FAILED status."""
    response_event = DocumentRenderCompleted(
        metadata=create_event_metadata(settings.service_name, params.correlation_id),
        template_id=params.template_id,
        template_name="",
        template_version=params.template_version,
        storage_key="",
        content_type="",
        text_alternative=None,
        result=OperationOutcome(
            status=ProcessingStatus.FAILED,
            error=ErrorInfo(
                error_code="RENDER_FAILED",
                error_message=params.error_message,
                retryable=False,
            ),
        ),
        file_size=0,
        content_hash="",
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type="render",
            aggregate_id=params.correlation_id,
            event_type=Topics.DOC_TEMPLATE_RENDER_COMPLETED,
            correlation_id=params.correlation_id,
        ),
        event=response_event,
    )


async def _record_template_usage(db: AsyncSession, template_id: str) -> None:
    """Record a usage event on the template after successful render.

    Best-effort: if the template is not found (e.g. deleted between event
    publish and render) or a DB error occurs, we log and move on: the
    render itself already succeeded.

    Uses a savepoint so failures don't corrupt the caller's transaction.
    """
    try:
        parsed_id = UUID(template_id)
    except ValueError:
        logger.debug("Skipping usage tracking - invalid template_id", template_id=template_id)
        return

    try:
        async with db.begin_nested():
            if template := await get_template_model_by_id(db, parsed_id):
                template.record_usage()
                logger.debug("Recorded template usage", template_id=template_id)
            else:
                logger.debug("Skipping usage tracking - template not found", template_id=template_id)
    except OSError, SQLAlchemyError:
        logger.warning("Failed to record template usage", template_id=template_id, exc_info=True)


@kafka_client.message_handler(
    Topics.DOC_TEMPLATE_RENDER_REQUESTED,
    DocumentRenderRequested,
    group_id=f"{settings.kafka_consumer_group}-commands",
    preserve_partition_order=False,
)
@kafka_client.with_db_session(schema=settings.database.schema_name, auto_commit=False)
async def handle_template_render_requested(
    message: DocumentRenderRequested,
    context: MessageContext,
) -> None:
    """Handle template render request event (ECST pattern)."""
    db = context.require_db_session()
    outbox = context.require_outbox()

    try:
        correlation_id, template_id, template_version = _validate_render_request(message)
    except ValidationError as e:
        correlation_id = (message.metadata.correlation_id if message.metadata else None) or context.correlation_id
        template_id = message.template_id
        template_version = message.template_version or ""
        if not correlation_id or not template_id:
            logger.exception(
                "Invalid render request cannot produce correlated terminal failure",
                error=str(e),
                correlation_id=correlation_id,
                template_id=template_id,
            )
            raise
        logger.warning(
            "Invalid render request - publishing terminal failure",
            error=str(e),
            correlation_id=correlation_id,
            template_id=template_id,
        )
        await _publish_render_failed(
            db,
            outbox,
            RenderFailedParams(correlation_id, template_id, template_version, str(e)),
        )
        await db.commit()
        return

    logger.info(
        "Processing template render request",
        template_id=template_id,
        template_version=template_version,
        correlation_id=correlation_id,
        output_format=message.output_format,
    )

    try:
        storage_key, content_type, file_size, content_hash, text_alternative = await _render_and_store(
            message=message,
            correlation_id=correlation_id,
            template_id=template_id,
        )
    except (GenerationError, ValidationError) as e:
        logger.warning(
            "Template rendering failed - terminal validation or generation error",
            template_id=template_id,
            correlation_id=correlation_id,
            error=str(e),
        )
        await _publish_render_failed(
            db, outbox, RenderFailedParams(correlation_id, template_id, template_version, str(e))
        )
        await db.commit()
        return
    except Exception:
        logger.exception(
            "Template rendering failed - retryable infrastructure error",
            template_id=template_id,
            correlation_id=correlation_id,
        )
        raise

    await _record_template_usage(db, template_id)

    template_name = message.template_name or template_id

    await _publish_render_completed(
        db,
        outbox,
        RenderCompletedParams(
            correlation_id=correlation_id,
            template_id=template_id,
            template_name=template_name,
            template_version=template_version,
            storage_key=storage_key,
            content_type=content_type,
            file_size=file_size,
            content_hash=content_hash,
            text_alternative=text_alternative,
        ),
    )
    await db.commit()

    logger.info(
        "Template rendering completed",
        template_id=template_id,
        template_name=template_name,
        template_version=template_version,
        correlation_id=correlation_id,
        storage_key=storage_key,
        file_size=file_size,
    )
