"""Stateless document content generation service with direct PydanticAI LLM integration.

Processes content generation requests using ECST pattern - all context from event,
attachments from S3, LLM calls via PydanticAI, results published as events.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Never

from doc_content_service.core.config import get_settings
from doc_content_service.core.kafka import kafka_client
from doc_content_service.services.context import DocumentContentContext
from doc_content_service.services.prompt_builder import (
    build_system_prompt,
    build_user_prompt,
)
from doc_content_service.services.schema_preprocessing import preprocess_schema_for_llm
from nohiki.common.v1 import (
    ErrorInfo,
    OperationOutcome,
    ProcessingStatus,
    RenderOutputFormat,
)
from nohiki.doc.content.v1 import (
    ContentGenerationCompleted,
    ContentGenerationContext,
    ContentGenerationFailed,
)
from nohiki.doc.template.v1 import (
    DocumentRenderRequested,
    DocumentTemplateVersionSnapshot,
)
from nohiki.job.listing.v1 import ListingNotificationSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_common_exceptions import DataNotAvailableError, ValidationError
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_llm_client import DynamicAgentConfig, LLMClient
from nohiki_observability import get_logger
from nohiki_proto_google.protobuf import Struct
from nohiki_s3_client import (
    S3Client,
    S3ConnectionError,
    S3ObjectNotFoundError,
    S3ObjectTooLargeError,
)

if TYPE_CHECKING:
    from pydantic_ai import Agent

logger = get_logger(__name__)

settings = get_settings()

type _ContentAgent = Agent[DocumentContentContext, dict[str, Any]]
_agent_cache: dict[str, _ContentAgent] = {}
_STORAGE_KEY_PART_COUNT = 4
_PERCENT_ESCAPE_PATTERN = re.compile(r"%[0-9A-Fa-f]{2}")


@dataclass(frozen=True, slots=True)
class ContentGenerationParams:
    """Parameters for processing content generation from ECST event."""

    request_id: uuid.UUID
    user_id: uuid.UUID
    context: ContentGenerationContext
    pref_snapshot: SearchPrefSnapshot
    correlation_id: str
    output_format: RenderOutputFormat
    template_id: str
    template_name: str | None
    job_correlation_id: str


def _raise_invalid_context() -> Never:
    """Raise the shared missing generation context error."""
    raise ValidationError(
        field_name="context",
        constraint="listing and template_version are required",
    )


async def process_content_generation(
    params: ContentGenerationParams,
    s3_client: S3Client,
    llm_client: LLMClient,
) -> None:
    """Process content generation request using ECST dependencies (stateless)."""
    context = params.context

    logger.info(
        "Processing content generation",
        request_id=str(params.request_id),
        listing_id=context.listing.id if context.listing else None,
        template_version_id=context.template_version.version_id if context.template_version else None,
        job_correlation_id=params.job_correlation_id,
    )

    try:
        async with asyncio.timeout(settings.generation.timeout_seconds):
            if context.listing is None or context.template_version is None:
                _raise_invalid_context()
            attachment_storage_keys = _extract_storage_keys(context, params.user_id)
            attachments = await _fetch_attachments_from_s3(s3_client, attachment_storage_keys)

            raw_schema = _extract_content_schema(context.template_version)
            content_schema = preprocess_schema_for_llm(raw_schema)
            user_preferences = context.user_preferences.to_dict() if context.user_preferences else {}

            llm_context = DocumentContentContext(
                job_data=context.listing.to_dict(),
                schema_definition=content_schema,
                schema_name=context.template_version.version_id or "GeneratedDocument",
                schema_version=context.template_version.version or "1.0.0",
                attachments=attachments,
                user_preferences=user_preferences,
            )
            _validate_prompt_size(llm_context)
            result = await _run_content_generation_llm(
                llm_context,
                content_schema,
                llm_context.schema_name,
                llm_client,
            )

    except Exception as e:
        logger.exception("Content generation failed", request_id=str(params.request_id), error=str(e))
        await _publish_generation_failed(params, str(e))
        return

    await _publish_generation_completed(params, result)
    logger.info(
        "Content generation and render request completed",
        request_id=str(params.request_id),
    )


def _get_or_create_agent(
    llm_client: LLMClient,
    schema_definition: dict[str, Any],
    schema_name: str,
) -> _ContentAgent:
    """Get or create a cached content-generation agent for the given schema.

    Cache identity includes the canonical schema digest so an inconsistent or
    forged event cannot reuse an agent created for different output constraints.

    Args:
        llm_client: LLM client providing the underlying model.
        schema_definition: JSON schema dict describing the expected output.
        schema_name: Stable identifier for this schema (template version_id).

    Returns:
        Cached or newly created ``Agent`` instance.

    """
    schema_digest = hashlib.sha256(
        json.dumps(schema_definition, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cache_key = f"{schema_name}:{schema_digest}"
    if cache_key not in _agent_cache:
        if len(_agent_cache) >= settings.generation.max_cached_agents:
            del _agent_cache[next(iter(_agent_cache))]
        _agent_cache[cache_key] = llm_client.create_dynamic_schema_agent(
            DynamicAgentConfig(
                deps_type=DocumentContentContext,
                json_schema=schema_definition,
                schema_name=schema_name,
                schema_description=f"Generated document matching {schema_name} schema",
                system_prompt_fn=lambda ctx: build_system_prompt(ctx.deps),
            )
        )
    return _agent_cache[cache_key]


async def _run_content_generation_llm(
    ctx: DocumentContentContext,
    schema_definition: dict[str, Any],
    schema_name: str,
    llm_client: LLMClient,
) -> dict[str, Any]:
    """Run the LLM with dynamic JSON schema using PydanticAI."""
    agent = _get_or_create_agent(llm_client, schema_definition, schema_name)
    user_prompt = build_user_prompt(ctx)
    result = await llm_client.run(agent, user_prompt, deps=ctx)
    return result.output


async def _publish_generation_completed(
    params: ContentGenerationParams,
    generated_content: dict[str, Any],
) -> None:
    """Publish terminal content completion, then request document rendering."""
    ctx = params.context
    if ctx.listing is None or ctx.template_version is None:
        _raise_invalid_context()

    generated_content_json = json.dumps(generated_content, sort_keys=True, separators=(",", ":"))
    content_digest = hashlib.sha256(generated_content_json.encode("utf-8")).hexdigest()
    completion_metadata = create_event_metadata(settings.service_name, params.correlation_id)
    completion_metadata.event_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"nohiki:doc-content:{params.request_id}:completed:{content_digest}",
        )
    )
    render_metadata = create_event_metadata(settings.service_name, params.correlation_id)
    render_metadata.event_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"nohiki:doc-content:{params.request_id}:render-requested:{content_digest}",
        )
    )
    completion_event = ContentGenerationCompleted(
        metadata=completion_metadata,
        request_id=str(params.request_id),
        listing_id=ctx.listing.id,
        template_version_id=ctx.template_version.version_id,
        generated_content_json=generated_content_json,
        generation_metadata=Struct.from_dict({"job_correlation_id": params.job_correlation_id}),
        result=OperationOutcome(status=ProcessingStatus.COMPLETED),
        listing_snapshot=ListingNotificationSnapshot(
            id=ctx.listing.id,
            listing_url=ctx.listing.listing_url,
            title=ctx.listing.title,
            company_name=ctx.listing.company_name,
            location=ctx.listing.location,
            posted_at=ctx.listing.posted_at,
        ),
        pref_snapshot=params.pref_snapshot,
    )
    render_event = DocumentRenderRequested(
        metadata=render_metadata,
        template_id=params.template_id,
        template_version=ctx.template_version.version,
        template_name=params.template_name,
        data=Struct.from_dict(generated_content),
        output_format=params.output_format,
        template_content=ctx.template_version.template_content,
    )

    await kafka_client.publish(
        topic=Topics.DOC_CONTENT_GENERATION_COMPLETED,
        message=completion_event,
        key=str(params.request_id),
    )
    await kafka_client.publish(
        topic=Topics.DOC_TEMPLATE_RENDER_REQUESTED,
        message=render_event,
        key=str(params.request_id),
    )


async def _publish_generation_failed(params: ContentGenerationParams, error_message: str) -> None:
    """Publish ContentGenerationFailed event."""
    ctx = params.context
    metadata = create_event_metadata(settings.service_name, params.correlation_id)
    metadata.event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nohiki:doc-content:{params.request_id}:failed"))
    event = ContentGenerationFailed(
        metadata=metadata,
        request_id=str(params.request_id),
        listing_id=ctx.listing.id if ctx.listing else "",
        template_version_id=ctx.template_version.version_id if ctx.template_version else "",
        result=OperationOutcome(
            status=ProcessingStatus.FAILED,
            error=ErrorInfo(
                error_code="GENERATION_FAILED",
                error_message=error_message,
                retryable=False,
            ),
        ),
        pref_snapshot=params.pref_snapshot,
    )

    await kafka_client.publish(
        topic=Topics.DOC_CONTENT_GENERATION_FAILED,
        message=event,
        key=str(params.request_id),
    )


def _validate_prompt_size(context: DocumentContentContext) -> None:
    """Reject prompt inputs that exceed the configured LLM trust-boundary limit."""
    prompt_characters = len(build_system_prompt(context)) + len(build_user_prompt(context))
    if prompt_characters > settings.generation.max_prompt_characters:
        raise ValidationError(
            field_name="content_generation_context",
            constraint=f"prompt must not exceed {settings.generation.max_prompt_characters} characters",
        )


def _extract_content_schema(
    template_version: DocumentTemplateVersionSnapshot,
) -> dict[str, Any]:
    """Extract and parse content schema JSON from template version snapshot."""
    schema_json = template_version.content_schema_json
    if not schema_json:
        return {}

    if len(schema_json.encode("utf-8")) > settings.generation.max_schema_bytes:
        raise ValidationError(
            field_name="content_schema_json",
            constraint=f"must not exceed {settings.generation.max_schema_bytes} bytes",
        )

    try:
        schema = json.loads(schema_json)
    except json.JSONDecodeError as e:
        raise ValidationError(field_name="content_schema_json", constraint="must be valid JSON") from e

    if not isinstance(schema, dict):
        raise ValidationError(field_name="content_schema", constraint="must be a JSON object")

    return schema


def _extract_storage_keys(context: ContentGenerationContext, user_id: uuid.UUID) -> list[str]:
    """Extract canonical storage keys owned by the authenticated user."""
    storage_keys = [ref.storage_key for ref in context.example_uploads] + [
        ref.storage_key for ref in context.context_uploads
    ]
    if len(storage_keys) > settings.generation.max_attachments:
        raise ValidationError(
            field_name="attachments",
            constraint=f"must not contain more than {settings.generation.max_attachments} items",
        )

    owner_prefix = f"user-uploads/{user_id}/"
    for storage_key in storage_keys:
        parts = storage_key.split("/")
        upload_id = parts[2] if len(parts) == _STORAGE_KEY_PART_COUNT else ""
        try:
            canonical_upload_id = str(uuid.UUID(upload_id))
        except ValueError:
            canonical_upload_id = ""

        if (
            not storage_key.startswith(owner_prefix)
            or len(parts) != _STORAGE_KEY_PART_COUNT
            or any(not part or part in {".", ".."} for part in parts)
            or canonical_upload_id != upload_id
            or "\\" in storage_key
            or not storage_key.isprintable()
            or _PERCENT_ESCAPE_PATTERN.search(storage_key) is not None
        ):
            raise ValidationError(
                field_name="attachments",
                constraint=f"storage keys must use the canonical {owner_prefix}<upload-id>/<filename> layout",
            )

    return storage_keys


async def _fetch_single_attachment(s3_client: S3Client, storage_key: str) -> dict[str, str]:
    """Fetch a single attachment from S3."""
    try:
        content_bytes = await s3_client.get_object(storage_key, max_bytes=settings.generation.max_attachment_bytes)
    except S3ObjectTooLargeError as e:
        raise ValidationError(
            field_name="attachment",
            constraint=f"must not exceed {settings.generation.max_attachment_bytes} bytes",
        ) from e
    except S3ObjectNotFoundError as e:
        raise DataNotAvailableError(resource_type="Upload", resource_id=storage_key, source="s3") from e
    except S3ConnectionError as e:
        raise DataNotAvailableError(resource_type="Upload", resource_id=storage_key, source="s3") from e

    if len(content_bytes) > settings.generation.max_attachment_bytes:
        raise ValidationError(
            field_name="attachment",
            constraint=f"must not exceed {settings.generation.max_attachment_bytes} bytes",
        )

    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValidationError(field_name="attachment", constraint="must be UTF-8 text") from e

    name = storage_key.rsplit("/", 1)[-1]
    return {"name": name, "content": content}


async def _fetch_attachments_from_s3(
    s3_client: S3Client,
    storage_keys: list[str],
) -> list[dict[str, str]]:
    """Fetch attachment content from S3 using storage keys in parallel."""
    if not storage_keys:
        return []

    if len(storage_keys) == 1:
        return [await _fetch_single_attachment(s3_client, storage_keys[0])]

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(_fetch_single_attachment(s3_client, key)) for key in storage_keys]
    attachments = [task.result() for task in tasks]
    total_bytes = sum(len(attachment["content"].encode("utf-8")) for attachment in attachments)
    if total_bytes > settings.generation.max_total_attachment_bytes:
        raise ValidationError(
            field_name="attachments",
            constraint=f"must not exceed {settings.generation.max_total_attachment_bytes} bytes in total",
        )
    return attachments
