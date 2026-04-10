"""Command handlers for doc-content-service - handles content generation requests via Kafka."""

from __future__ import annotations

from uuid import UUID

from nohiki.common.v1 import RenderOutputFormat
from nohiki.doc.content.v1 import ContentGenerationRequested, TriggerType
from nohiki_common_exceptions import ValidationError
from nohiki_kafka_client import MessageContext, Topics
from nohiki_llm_client import LLMClient
from nohiki_observability import get_logger
from nohiki_s3_client import S3Client

from doc_content_service.core.config import get_settings
from doc_content_service.core.kafka import kafka_client
from doc_content_service.services.content_service import (
    ContentGenerationParams,
    process_content_generation,
)

logger = get_logger(__name__)
settings = get_settings()
primary_group_id = settings.kafka.consumer_group
_s3_client = S3Client(settings.s3)
_llm_client = LLMClient(settings.llm, chain="doc_tailoring")


async def close_llm_client() -> None:
    """Close the process-owned document model transports."""
    await _llm_client.close()


def _required_uuid(value: str, field_name: str) -> UUID:
    """Parse a required UUID field into its trusted service-boundary form."""
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError) as e:
        raise ValidationError(field_name=field_name, constraint="must be a valid UUID") from e


def _build_generation_params(
    message: ContentGenerationRequested,
) -> ContentGenerationParams:
    """Validate the command boundary and build generation parameters."""
    if message.trigger_type not in (TriggerType.AUTOMATIC, TriggerType.MANUAL):
        raise ValidationError(
            field_name="trigger_type",
            constraint="must be AUTOMATIC or MANUAL",
        )
    if message.output_format not in (
        RenderOutputFormat.HTML,
        RenderOutputFormat.PDF,
        RenderOutputFormat.IMAGE,
        RenderOutputFormat.TEXT,
    ):
        raise ValidationError(
            field_name="output_format",
            constraint="must be a supported non-UNSPECIFIED output format",
        )

    request_id = _required_uuid(message.request_id, "request_id")
    user_id = _required_uuid(message.pref_snapshot.user_id, "pref_snapshot.user_id")
    _required_uuid(message.template_id, "template_id")
    _required_uuid(message.job_correlation_id, "job_correlation_id")
    correlation_id = message.metadata.correlation_id or str(request_id)

    return ContentGenerationParams(
        request_id=request_id,
        user_id=user_id,
        context=message.context,
        pref_snapshot=message.pref_snapshot,
        correlation_id=correlation_id,
        output_format=message.output_format,
        template_id=message.template_id,
        template_name=message.template_name,
        job_correlation_id=message.job_correlation_id,
    )


@kafka_client.message_handler(
    Topics.DOC_CONTENT_GENERATION_REQUESTED,
    ContentGenerationRequested,
    group_id=primary_group_id,
)
async def handle_content_generation_requested(message: ContentGenerationRequested, _context: MessageContext) -> None:
    """Handle content generation requested events using ECST (stateless)."""
    params = _build_generation_params(message)
    request_id = str(params.request_id)
    ctx = params.context

    user_id = str(params.user_id)
    correlation_id = params.correlation_id

    logger.info(
        "Received content generation request (ECST)",
        request_id=request_id,
        user_id=user_id,
        listing_id=ctx.listing.id if ctx.listing else None,
        template_version_id=ctx.template_version.version_id if ctx.template_version else None,
        example_attachments_count=len(ctx.example_uploads),
        context_attachments_count=len(ctx.context_uploads),
        trigger_type=message.trigger_type,
        correlation_id=correlation_id,
        job_correlation_id=message.job_correlation_id,
    )

    await process_content_generation(params=params, s3_client=_s3_client, llm_client=_llm_client)

    logger.info(
        "Content generation request processing initiated (ECST)",
        request_id=request_id,
        listing_id=ctx.listing.id if ctx.listing else None,
    )
