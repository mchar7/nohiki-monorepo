"""Documents API routes - async document generation with ECST events."""

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from nohiki.common.v1 import AccessScope, RenderOutputFormat, UploadReference
from nohiki.doc.content.v1 import (
    ContentGenerationContext,
    ContentGenerationRequested,
    TriggerType,
)
from nohiki.doc.template.v1 import (
    DocumentRenderRequested,
    DocumentTemplateVersionSnapshot,
)
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_db_utils import get_async_sessionmaker, paginate_query
from nohiki_fastapi_utils import JWTClaims, PaginatedResponse, PaginationParams
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_observability import get_logger
from nohiki_proto_google.protobuf import Struct
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from starlette.background import BackgroundTask
from uuid_utils.compat import uuid7

from bff_service.api.deps.auth import (
    get_current_user_claims,
    get_current_user_id_from_cookie,
    get_verified_user_claims,
)
from bff_service.api.routers.templates import template_visibility_filter
from bff_service.core.config import get_settings
from bff_service.core.db import get_async_db
from bff_service.core.kafka import kafka_client
from bff_service.db.models import (
    DocumentGenerationStatus,
    JobCorrelationProjection,
    JobListingProjection,
    TemplateProjection,
)
from bff_service.sse import get_shutdown_event, get_sse_bridge
from bff_service.sse.stream import SSEStreamContext, sse_event_generator

logger = get_logger(__name__)

router = APIRouter()
document_events_router = APIRouter()


class GenerateDocumentRequest(BaseModel):
    """Request to generate a document."""

    template_version_id: UUID
    data: dict[str, object]
    output_format: str = Field(default="pdf", pattern="^(pdf|html|png)$")


class GenerateTailoredDocumentRequest(BaseModel):
    """Request tailored content generation for an owned job match."""

    job_correlation_id: UUID
    template_id: UUID
    output_format: str = Field(default="pdf", pattern="^(pdf|html|png)$")


class GenerateDocumentResponse(BaseModel):
    """Response for document generation initiation."""

    request_id: str
    status: str = "accepted"


class DocumentStatusResponse(BaseModel):
    """Response for document generation status."""

    request_id: str
    status: str  # pending, processing, completed, failed
    download_url: str | None = None
    error: str | None = None
    template_name: str | None = None
    output_format: str = "pdf"
    created_at: datetime | None = None


def _output_format_to_proto(fmt: str) -> RenderOutputFormat:
    """Convert string format to proto enum."""
    if fmt == "pdf":
        return RenderOutputFormat.PDF
    if fmt == "png":
        return RenderOutputFormat.IMAGE
    return RenderOutputFormat.HTML


_MAX_DATA_PAIRS = 100
_MAX_DATA_KEY_LEN = 64
_MAX_DATA_VALUE_SERIALIZED = 50000
_MAX_SCHEMA_ERRORS = 10
_MAX_SCHEMA_ERROR_MESSAGE_LEN = 500
_MAX_TOTAL_UPLOADS = 20


def _schema_error_detail(error: object, path: Sequence[object]) -> dict[str, object]:
    message = str(getattr(error, "message", "Invalid template data"))
    return {
        "loc": ["body", "data", *path],
        "msg": message[:_MAX_SCHEMA_ERROR_MESSAGE_LEN],
        "type": f"json_schema.{getattr(error, 'validator', 'validation')}",
    }


def _validate_content_schema(data: dict[str, object], schema: Mapping[str, object] | None) -> None:
    """Reject render data that does not satisfy the selected template schema."""
    if not schema:
        return

    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
    except SchemaError:
        logger.exception("Stored template has an invalid content schema")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Template schema is invalid",
        ) from None

    details: list[dict[str, object]] = []
    errors = sorted(
        validator.iter_errors(data),
        key=lambda error: (tuple(map(str, error.absolute_path)), error.message),
    )
    for error in errors:
        path = list(error.absolute_path)
        if error.validator == "required" and isinstance(error.validator_value, list):
            missing = (name for name in error.validator_value if name not in error.instance)
            for name in missing:
                details.append(_schema_error_detail(error, [*path, name]))
                if len(details) == _MAX_SCHEMA_ERRORS:
                    break
        else:
            details.append(_schema_error_detail(error, path))
        if len(details) == _MAX_SCHEMA_ERRORS:
            break

    if details:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=details)


def _validate_data_field(data: dict[str, object]) -> dict[str, object]:
    """Validate template data against original proto constraints.

    Enforces max_pairs, keys.max_len, and values serialized size at
    the API boundary.
    """
    if len(data) > _MAX_DATA_PAIRS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Too many data fields (max {_MAX_DATA_PAIRS})",
        )
    for key, value in data.items():
        if len(key) > _MAX_DATA_KEY_LEN:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Data key too long (max {_MAX_DATA_KEY_LEN} chars): {key[:32]}...",
            )
        if len(json.dumps(value)) > _MAX_DATA_VALUE_SERIALIZED:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Data value too large for key: {key[:32]}...",
            )
    return data


def _snapshot_conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _validate_uploads(uploads: list[UploadReference], user_id: UUID) -> None:
    if any(not upload.storage_key or upload.user_id != str(user_id) for upload in uploads):
        detail = "Preference upload snapshot is incomplete or stale"
        raise _snapshot_conflict(detail)


def _validate_upload_aggregate(
    example_uploads: Sequence[UploadReference],
    context_uploads: Sequence[UploadReference],
) -> None:
    if len(example_uploads) + len(context_uploads) > _MAX_TOTAL_UPLOADS:
        detail = f"Generation context exceeds the {_MAX_TOTAL_UPLOADS}-upload limit"
        raise _snapshot_conflict(detail)


def _merge_context_uploads(
    pref_uploads: list[UploadReference],
    correlation_uploads: list[UploadReference],
) -> list[UploadReference]:
    merged: dict[str, UploadReference] = {}
    for upload in (*pref_uploads, *correlation_uploads):
        merged.setdefault(upload.storage_key, upload)
    return list(merged.values())


@router.post(
    "/generate",
    response_model=GenerateDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_document(
    data: GenerateDocumentRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> GenerateDocumentResponse:
    """Initiate async document generation.

    Publishes RenderRequested command event to doc-template-service.
    Returns 202 Accepted with request_id. Use /documents/{request_id}/status
    or /documents/{request_id}/events (SSE) to track progress.
    """
    validated_data = _validate_data_field(data.data)
    request_id = uuid7()
    template_version_id = data.template_version_id

    # Fetch only active templates visible to the current user.
    stmt = select(TemplateProjection).where(
        TemplateProjection.id == template_version_id,
        template_visibility_filter(user_id),
    )
    result = await db.execute(stmt)
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    _validate_content_schema(validated_data, template.content_schema)
    template_name = template.name

    # Create document generation status record
    doc_status = DocumentGenerationStatus(
        request_id=request_id,
        user_id=user_id,
        template_version_id=template_version_id,
        output_format=data.output_format,
        status="pending",
    )
    db.add(doc_status)
    await db.commit()

    # ECST: Include template content in event (no DB lookup by consumer)
    metadata = create_event_metadata("bff-service", str(request_id))

    event = DocumentRenderRequested(
        metadata=metadata,
        template_id=str(template.id),
        template_version=template.version,
        template_name=template_name,
        data=Struct.from_dict(validated_data),
        output_format=_output_format_to_proto(data.output_format),
        template_content=template.template_content,
    )

    await kafka_client.publish(
        topic=Topics.DOC_TEMPLATE_RENDER_REQUESTED,
        message=event,
        key=str(request_id),
    )

    logger.info(
        "Document generation requested",
        user_id=str(user_id),
        request_id=str(request_id),
        template_version_id=data.template_version_id,
        output_format=data.output_format,
    )
    return GenerateDocumentResponse(request_id=str(request_id))


@router.post(
    "/generate-tailored",
    response_model=GenerateDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_tailored_document(
    data: GenerateTailoredDocumentRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> GenerateDocumentResponse:
    """Generate tailored content and then render it through Kafka ECST."""
    correlation_result = await db.execute(
        select(JobCorrelationProjection).where(
            JobCorrelationProjection.id == data.job_correlation_id,
            JobCorrelationProjection.user_id == user_id,
        )
    )
    correlation = correlation_result.scalar_one_or_none()
    if correlation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job correlation not found")

    listing_result = await db.execute(
        select(JobListingProjection).where(JobListingProjection.id == correlation.listing_id)
    )
    listing_projection = listing_result.scalar_one_or_none()
    if listing_projection is None:
        detail = "Listing projection is unavailable"
        raise _snapshot_conflict(detail)

    template_result = await db.execute(
        select(TemplateProjection).where(
            TemplateProjection.id == data.template_id,
            TemplateProjection.is_active.is_(True),
            or_(
                TemplateProjection.access_scope.in_((AccessScope.PUBLIC, AccessScope.SYSTEM)),
                TemplateProjection.owner_id == user_id,
            ),
        )
    )
    template = template_result.scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    if correlation.pref_snapshot is None or listing_projection.snapshot is None:
        detail = "Required generation snapshot is unavailable"
        raise _snapshot_conflict(detail)
    try:
        pref_snapshot = SearchPrefSnapshot.from_dict(correlation.pref_snapshot)
        listing_snapshot = ListingSnapshot.from_dict(listing_projection.snapshot)
        correlation_uploads = [UploadReference.from_dict(item) for item in correlation.pref_uploads or []]
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        detail = "Required generation snapshot is invalid"
        raise _snapshot_conflict(detail) from exc

    if (
        not pref_snapshot.is_active
        or pref_snapshot.id != str(correlation.pref_id)
        or pref_snapshot.user_id != str(user_id)
        or listing_snapshot.id != str(correlation.listing_id)
    ):
        detail = "Required generation snapshot is incomplete or stale"
        raise _snapshot_conflict(detail)
    if template.version_id is None or not template.template_content or not template.content_schema:
        detail = "Template version snapshot is incomplete"
        raise _snapshot_conflict(detail)

    _validate_uploads(
        [
            *pref_snapshot.example_uploads,
            *pref_snapshot.context_uploads,
            *correlation_uploads,
        ],
        user_id,
    )
    example_uploads = pref_snapshot.example_uploads
    context_uploads = _merge_context_uploads(pref_snapshot.context_uploads, correlation_uploads)
    _validate_upload_aggregate(example_uploads, context_uploads)
    template_version = DocumentTemplateVersionSnapshot(
        version_id=str(template.version_id),
        version=template.version,
        template_content=template.template_content,
        description=template.description,
        content_schema_json=json.dumps(template.content_schema),
    )
    generation_context = ContentGenerationContext(
        listing=listing_snapshot,
        template_version=template_version,
        example_uploads=example_uploads,
        context_uploads=context_uploads,
        user_preferences=Struct.from_dict(dict(pref_snapshot.tailoring_preferences)),
    )

    request_id = uuid7()
    db.add(
        DocumentGenerationStatus(
            request_id=request_id,
            user_id=user_id,
            template_version_id=template.version_id,
            job_correlation_id=correlation.id,
            pref_id=correlation.pref_id,
            listing_id=correlation.listing_id,
            output_format=data.output_format,
            status="pending",
        )
    )
    await db.commit()

    event = ContentGenerationRequested(
        metadata=create_event_metadata("bff-service", str(request_id)),
        request_id=str(request_id),
        trigger_type=TriggerType.MANUAL,
        context=generation_context,
        pref_snapshot=pref_snapshot,
        output_format=_output_format_to_proto(data.output_format),
        template_id=str(template.id),
        template_name=template.name,
        job_correlation_id=str(correlation.id),
    )
    await kafka_client.publish(
        topic=Topics.DOC_CONTENT_GENERATION_REQUESTED,
        message=event,
        key=str(request_id),
    )
    logger.info(
        "Tailored document generation requested",
        user_id=str(user_id),
        request_id=str(request_id),
        job_correlation_id=str(correlation.id),
        template_id=str(template.id),
        output_format=data.output_format,
    )
    return GenerateDocumentResponse(request_id=str(request_id))


@router.get("/{request_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    request_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> DocumentStatusResponse:
    """Get the status of a document generation request.

    Joins with template_projections to surface the template name alongside
    output_format and created_at from the document_generation_status row.
    """
    logger.debug("Getting document status", request_id=str(request_id))

    stmt = (
        select(DocumentGenerationStatus, TemplateProjection.name.label("template_name"))
        .outerjoin(
            TemplateProjection,
            DocumentGenerationStatus.template_version_id == TemplateProjection.id,
        )
        .where(
            DocumentGenerationStatus.request_id == request_id,
            DocumentGenerationStatus.user_id == user_id,
        )
    )
    result = await db.execute(stmt)
    row = result.one_or_none()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document request {request_id} not found",
        )

    doc_status, template_name = row

    return DocumentStatusResponse(
        request_id=str(doc_status.request_id),
        status=doc_status.status,
        download_url=doc_status.storage_key,
        error=doc_status.error_message,
        template_name=template_name,
        output_format=doc_status.output_format,
        created_at=doc_status.created_at,
    )


@document_events_router.get("/{request_id}/events", response_class=EventSourceResponse)
async def stream_document_events(
    request_id: UUID,
    verified_claims: Annotated[JWTClaims, Depends(get_verified_user_claims)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    """Stream durable status events for one authenticated user's request."""
    settings = get_settings()
    if settings.database is None:
        msg = "DATABASE must be configured for database operations"
        raise RuntimeError(msg)

    session_factory = get_async_sessionmaker(settings.database)
    async with session_factory() as db:
        principal = await get_current_user_claims(verified_claims, db)
        user_id = UUID(principal.sub)
        result = await db.execute(
            select(DocumentGenerationStatus.request_id).where(
                DocumentGenerationStatus.request_id == request_id,
                DocumentGenerationStatus.user_id == user_id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document request {request_id} not found",
            )

    if last_event_id is not None and re.fullmatch(r"\d+-\d+", last_event_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Last-Event-ID must be a Redis Stream ID",
        )

    bridge = get_sse_bridge()
    shutdown_event = get_shutdown_event()
    lease = await bridge.acquire_stream_slot(
        user_id,
        limit=settings.sse.max_concurrent_streams_per_user,
        ttl_seconds=(settings.sse.max_stream_duration_seconds + settings.sse.heartbeat_interval_seconds),
    )
    if lease is None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many concurrent document event streams",
        )

    generator = sse_event_generator(
        user_id=user_id,
        principal=principal,
        context=SSEStreamContext(
            session_factory=session_factory,
            bridge=bridge,
            settings=settings.sse,
            shutdown_event=shutdown_event,
        ),
        request_id=request_id,
        last_event_id=last_event_id,
    )

    return EventSourceResponse(
        generator,
        ping=settings.sse.heartbeat_interval_seconds,
        ping_message_factory=lambda: ServerSentEvent(comment="ping"),
        background=BackgroundTask(bridge.release_stream_slot, lease),
    )


@router.get("")
async def list_documents(
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    pagination: Annotated[PaginationParams, Query()],
) -> PaginatedResponse[DocumentStatusResponse]:
    """List recent document generation requests for the current user.

    Template names are resolved via a single batch query to avoid N+1 lookups.
    """
    logger.debug("Listing documents", page=pagination.page, page_size=pagination.page_size)

    query = (
        select(DocumentGenerationStatus)
        .where(DocumentGenerationStatus.user_id == user_id)
        .order_by(DocumentGenerationStatus.created_at.desc())
    )
    paginated = await paginate_query(db, query, offset=pagination.offset, limit=pagination.page_size)

    # Batch-resolve template names to avoid N+1 (one extra query for the whole page).
    template_ids = {doc.template_version_id for doc in paginated.items}
    template_name_map: dict[UUID, str] = {}
    if template_ids:
        tpl_stmt = select(TemplateProjection.id, TemplateProjection.name).where(
            TemplateProjection.id.in_(template_ids),
        )
        tpl_result = await db.execute(tpl_stmt)
        template_name_map = {row[0]: row[1] for row in tpl_result.all()}

    return PaginatedResponse[DocumentStatusResponse].create(
        items=[
            DocumentStatusResponse(
                request_id=str(doc.request_id),
                status=doc.status,
                download_url=doc.storage_key,
                error=doc.error_message,
                template_name=template_name_map.get(doc.template_version_id),
                output_format=doc.output_format,
                created_at=doc.created_at,
            )
            for doc in paginated.items
        ],
        total=paginated.total,
        params=pagination,
    )


# Mount the request-scoped event route with the rest of the documents API.
