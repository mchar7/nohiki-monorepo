"""Template families API routes - CQRS pattern with projections and command events."""

from __future__ import annotations

import re
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from nohiki.common.v1 import AccessScope, EventMetadata
from nohiki.doc.template.v1 import (
    TemplateAudience,
    TemplateCreateRequested,
    TemplateDeleteRequested,
    TemplateVersionAddRequested,
)
from nohiki_db_utils import paginate_query
from nohiki_domain_utils import BetterprotoEnumAdapter
from nohiki_fastapi_utils import PaginatedResponse, PaginationParams
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_observability import get_logger
from pydantic import AfterValidator, BaseModel, Field, field_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from uuid_utils.compat import uuid7

from bff_service.api.deps.auth import get_current_user_id_from_cookie
from bff_service.api.schemas import CommandAcceptedResponse
from bff_service.core.db import get_async_db
from bff_service.core.kafka import kafka_client
from bff_service.db.models import CommandRequest, TemplateProjection

logger = get_logger(__name__)

router = APIRouter()


# Template Validation Models


SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(-((0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(\.(0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$"
)
NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
TEMPLATE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,126}$")
_TEMPLATE_CONTENT_MAX_BYTES = 102400


def _validate_template_content_size(value: str) -> str:
    """Reject template content above the UTF-8 byte limit."""
    if len(value.encode("utf-8")) > _TEMPLATE_CONTENT_MAX_BYTES:
        message = f"template content exceeds {_TEMPLATE_CONTENT_MAX_BYTES} bytes"
        raise ValueError(message)
    return value


_TemplateContent = Annotated[str, AfterValidator(_validate_template_content_size)]


class TemplateValidationIssue(BaseModel):
    """A single validation issue found in a template."""

    path: str = Field(description="Location of the issue (e.g., 'line 5')")
    keyword: str = Field(description="Issue type identifier")
    message: str = Field(description="Human-readable description of the issue")


class TemplateValidationRequest(BaseModel):
    """Request to validate template content."""

    template: _TemplateContent = Field(description="Template HTML/Jinja2 content to validate")


class TemplateValidationResponse(BaseModel):
    """Response containing validation results."""

    valid: bool = Field(description="Whether the template passed validation")
    issues: list[TemplateValidationIssue] = Field(
        default_factory=list,
        description="List of validation issues found",
    )


class TemplateResponse(BaseModel):
    """Response for a template version in single-table design.

    In single-table design, each row represents a template version.
    The "family" is identified by (namespace, name) combination.
    """

    id: str = Field(description="Template version identifier")
    namespace: str = Field(description="Template namespace (e.g., 'resume', 'cover_letter')")
    name: str = Field(description="Template name within namespace")
    display_name: str = Field(description="User-facing template name")
    version: str = Field(description="Semantic version string (e.g., '1.0.0')")
    template_content: str = Field(description="Jinja2 HTML template content")
    content_schema: dict[str, Any] | None = Field(default=None, description="JSON schema for template variables")
    description: str | None = Field(default=None, max_length=1000)
    access_scope: Annotated[AccessScope, BetterprotoEnumAdapter()] = Field(
        description="Access control: PUBLIC, PRIVATE, or SYSTEM"
    )
    owner_id: str | None = Field(default=None, description="Owner user ID for PRIVATE templates")
    is_active: bool = Field(default=True, description="Whether this version is active")

    @field_validator("version")
    @classmethod
    def validate_semver(cls, v: str) -> str:
        """Validate semantic version format."""
        if not SEMVER_PATTERN.match(v):
            msg = f"Invalid semver format: {v}. Expected X.Y.Z[-prerelease][+build]"
            raise ValueError(msg)
        return v

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        """Validate namespace format."""
        if not NAMESPACE_PATTERN.match(v):
            msg = f"Invalid namespace: {v}. Must be lowercase alphanumeric with underscores/hyphens"
            raise ValueError(msg)
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate template name format."""
        if not TEMPLATE_NAME_PATTERN.match(v):
            msg = f"Invalid name: {v}. Must be lowercase alphanumeric with underscores/hyphens"
            raise ValueError(msg)
        return v


class TemplateFamilyResponse(BaseModel):
    """Response for a template family with its latest version."""

    id: str
    namespace: str
    name: str
    display_name: str
    description: str | None = None
    latest_version: TemplateResponse | None = None


def _version_to_response(template: TemplateProjection) -> TemplateResponse:
    """Convert a template projection to response."""
    return TemplateResponse(
        id=str(template.id),
        namespace=template.namespace,
        name=template.name,
        display_name=template.display_name,
        version=template.version,
        template_content=template.template_content,
        content_schema=template.content_schema,
        description=template.description,
        access_scope=template.access_scope,
        owner_id=str(template.owner_id) if template.owner_id else None,
        is_active=template.is_active,
    )


def template_visibility_filter(user_id: UUID | None) -> ColumnElement[bool]:
    """Restrict reads to document templates allowed by their access scope."""
    document_template = TemplateProjection.audience == TemplateAudience.DOCUMENT
    shared_scope = TemplateProjection.access_scope.in_((AccessScope.PUBLIC, AccessScope.SYSTEM))
    if user_id is None:
        return and_(TemplateProjection.is_active.is_(True), document_template, shared_scope)
    return and_(
        TemplateProjection.is_active.is_(True),
        document_template,
        or_(
            shared_scope,
            and_(
                TemplateProjection.access_scope == AccessScope.PRIVATE,
                TemplateProjection.owner_id == user_id,
            ),
        ),
    )


async def _get_latest_version(
    db: AsyncSession,
    namespace: str,
    name: str,
    user_id: UUID | None = None,
) -> TemplateResponse | None:
    """Get the latest visible version for a template family."""
    stmt = (
        select(TemplateProjection)
        .where(
            TemplateProjection.namespace == namespace,
            TemplateProjection.name == name,
            template_visibility_filter(user_id),
        )
        .order_by(TemplateProjection.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    template = result.scalar_one_or_none()
    return _version_to_response(template) if template else None


@router.get("")
async def list_template_families(
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    pagination: Annotated[PaginationParams, Query()],
) -> PaginatedResponse[TemplateFamilyResponse]:
    """List template families with their latest versions."""
    logger.debug("Listing template families")

    # DISTINCT ON gives one row per (namespace, name), picking the latest
    query = (
        select(TemplateProjection)
        .distinct(TemplateProjection.namespace, TemplateProjection.name)
        .where(template_visibility_filter(user_id))
        .order_by(
            TemplateProjection.namespace,
            TemplateProjection.name,
            TemplateProjection.created_at.desc(),
        )
    )
    result = await paginate_query(db, query, offset=pagination.offset, limit=pagination.page_size)

    return PaginatedResponse[TemplateFamilyResponse].create(
        items=[
            TemplateFamilyResponse(
                id=str(t.id),
                namespace=t.namespace,
                name=t.name,
                display_name=t.display_name,
                description=t.description,
                latest_version=_version_to_response(t),
            )
            for t in result.items
        ],
        total=result.total,
        params=pagination,
    )


@router.get("/families/{namespace}/{name}", response_model=TemplateFamilyResponse)
async def get_template_family(
    namespace: str,
    name: str,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> TemplateFamilyResponse:
    """Get a specific template family by namespace and name."""
    logger.debug("Getting template family", namespace=namespace, name=name)

    latest = await _get_latest_version(db, namespace, name, user_id)
    if not latest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template family not found")

    return TemplateFamilyResponse(
        id=latest.id,
        namespace=namespace,
        name=name,
        display_name=latest.display_name,
        description=latest.description,
        latest_version=latest,
    )


async def _get_template_by_id(
    db: AsyncSession,
    template_id: UUID,
    user_id: UUID,
) -> TemplateProjection | None:
    """Fetch a visible template by ID from the database."""
    stmt = select(TemplateProjection).where(
        TemplateProjection.id == template_id,
        template_visibility_filter(user_id),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template_by_id(
    template_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> TemplateResponse:
    """Get a specific template by ID."""
    template = await _get_template_by_id(db, template_id, user_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return _version_to_response(template)


@router.get("/by-name/{namespace}/{name}/versions", response_model=list[TemplateResponse])
async def list_template_versions(
    namespace: str,
    name: str,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> list[TemplateResponse]:
    """List all versions of a template by namespace and name."""
    logger.debug("Listing template versions", namespace=namespace, name=name)

    stmt = (
        select(TemplateProjection)
        .where(
            TemplateProjection.namespace == namespace,
            TemplateProjection.name == name,
            template_visibility_filter(user_id),
        )
        .order_by(TemplateProjection.created_at.desc())
    )
    result = await db.execute(stmt)
    templates = result.scalars().all()

    return [_version_to_response(template) for template in templates]


@router.get("/by-name/{namespace}/{name}/{version}", response_model=TemplateResponse)
async def get_template_by_name_version(
    namespace: str,
    name: str,
    version: str,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> TemplateResponse:
    """Get a specific template by namespace, name, and version."""
    logger.debug("Getting template by name/version", namespace=namespace, name=name, version=version)

    stmt = select(TemplateProjection).where(
        TemplateProjection.namespace == namespace,
        TemplateProjection.name == name,
        TemplateProjection.version == version,
        template_visibility_filter(user_id),
    )
    result = await db.execute(stmt)
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    return _version_to_response(template)


# Template Validation

# Jinja2 block patterns
_JINJA_BLOCK_OPEN = re.compile(r"\{%\s*(if|for|block|macro|call|filter)\b")
_JINJA_BLOCK_CLOSE = re.compile(r"\{%\s*end(if|for|block|macro|call|filter)\s*%\}")
_JINJA_EXPR_OPEN = re.compile(r"\{\{")
_JINJA_EXPR_CLOSE = re.compile(r"\}\}")


def _count_pattern_matches(text: str, pattern: re.Pattern[str]) -> int:
    """Count matches of a regex pattern in text."""
    return len(pattern.findall(text))


def _validate_jinja_blocks(template: str) -> list[TemplateValidationIssue]:
    """Validate that all Jinja2 block tags are properly closed."""
    issues: list[TemplateValidationIssue] = []
    open_count = _count_pattern_matches(template, _JINJA_BLOCK_OPEN)
    close_count = _count_pattern_matches(template, _JINJA_BLOCK_CLOSE)

    if open_count != close_count:
        issues.append(
            TemplateValidationIssue(
                path="$",
                keyword="jinja_block_miscorrelation",
                message=f"Mismatched Jinja2 blocks: {open_count} opened, {close_count} closed",
            )
        )
    return issues


def _validate_jinja_expressions_per_line(template: str) -> list[TemplateValidationIssue]:
    """Validate that Jinja2 expressions are properly closed on each line."""
    issues: list[TemplateValidationIssue] = []
    lines = template.split("\n")

    for line_num, line in enumerate(lines, start=1):
        open_count = _count_pattern_matches(line, _JINJA_EXPR_OPEN)
        close_count = _count_pattern_matches(line, _JINJA_EXPR_CLOSE)
        if open_count != close_count:
            issues.append(
                TemplateValidationIssue(
                    path=f"line {line_num}",
                    keyword="jinja_expression_miscorrelation",
                    message=f"Unclosed Jinja2 expression on line {line_num}",
                )
            )
    return issues


def _validate_html_structure(template: str) -> list[TemplateValidationIssue]:
    """Validate basic HTML structure."""
    issues: list[TemplateValidationIssue] = []
    template_lower = template.lower()

    if "<!doctype" not in template_lower:
        issues.append(
            TemplateValidationIssue(
                path="$",
                keyword="missing_doctype",
                message="Missing <!DOCTYPE html> declaration",
            )
        )

    if "<html" not in template_lower:
        issues.append(
            TemplateValidationIssue(
                path="$",
                keyword="missing_html_tag",
                message="Missing <html> tag",
            )
        )

    if "<head" not in template_lower:
        issues.append(
            TemplateValidationIssue(
                path="$",
                keyword="missing_head_tag",
                message="Missing <head> tag",
            )
        )

    if "<body" not in template_lower:
        issues.append(
            TemplateValidationIssue(
                path="$",
                keyword="missing_body_tag",
                message="Missing <body> tag",
            )
        )

    return issues


def validate_template_content(template: str) -> TemplateValidationResponse:
    """Validate template content for Jinja2 and HTML issues."""
    issues: list[TemplateValidationIssue] = []

    issues.extend(_validate_jinja_blocks(template))
    issues.extend(_validate_jinja_expressions_per_line(template))
    issues.extend(_validate_html_structure(template))

    return TemplateValidationResponse(valid=len(issues) == 0, issues=issues)


@router.post("/validate", response_model=TemplateValidationResponse)
async def validate_template(
    request: TemplateValidationRequest,
    _user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
) -> TemplateValidationResponse:
    """Validate template content for syntax errors and structural issues.

    Performs the following checks:
    - Jinja2 block tag matching (if/endif, for/endfor, etc.)
    - Jinja2 expression syntax ({{ }})
    - Basic HTML structure (doctype, html, head, body tags)
    """
    logger.debug("Validating template", template_length=len(request.template))
    return validate_template_content(request.template)


# Template Write Operations (ECST Command Events)


class TemplateCreateRequest(BaseModel):
    """Request to create a new template family."""

    name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=255)
    namespace: str = Field(default="default", max_length=50)
    template_content: _TemplateContent = Field(..., min_length=10)
    description: str | None = Field(default=None, max_length=1000)
    schema_compatibility: list[str] | None = Field(default=None, max_length=20)


class TemplateVersionAddRequest(BaseModel):
    """Request to add a new version to a template family."""

    version: str = Field(..., pattern=SEMVER_PATTERN)
    template_content: _TemplateContent = Field(..., min_length=10)
    description: str | None = Field(default=None, max_length=1000)
    schema_compatibility: list[str] | None = Field(default=None, max_length=20)


def _create_cmd_metadata(request_id: UUID | None = None) -> EventMetadata:
    """Create standard ECST event metadata for BFF commands."""
    return create_event_metadata("bff-service", str(request_id) if request_id else None)


class CommandRequestParams(BaseModel):
    """Parameters for tracking a command request."""

    request_id: UUID
    user_id: UUID
    command_type: str
    entity_type: str
    entity_id: UUID | None = None


async def _track_command_request(db: AsyncSession, params: CommandRequestParams) -> None:
    """Track a command request for async status polling."""
    command = CommandRequest(
        request_id=params.request_id,
        user_id=params.user_id,
        command_type=params.command_type,
        status="pending",
    )
    db.add(command)
    await db.commit()


@router.post("", response_model=CommandAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_template_family(
    request: TemplateCreateRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> CommandAcceptedResponse:
    """Create a new template family.

    Publishes TemplateCreateRequested command event to Kafka.
    Returns 202 Accepted with request_id for async tracking.
    """
    validation = validate_template_content(request.template_content)
    if not validation.valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": "Invalid template content", "issues": [i.model_dump() for i in validation.issues]},
        )

    request_id = uuid7()
    metadata = _create_cmd_metadata(request_id)

    event = TemplateCreateRequested(
        metadata=metadata,
        request_id=str(request_id),
        user_id=str(user_id),
        name=request.name,
        display_name=request.display_name,
        namespace=request.namespace,
        template_content=request.template_content,
        description=request.description,
        visibility=AccessScope.PRIVATE,
    )

    params = CommandRequestParams(
        request_id=request_id,
        user_id=user_id,
        command_type="template_create",
        entity_type="template_family",
    )
    await _track_command_request(db, params)
    await kafka_client.publish(topic=Topics.DOC_TEMPLATE_CREATE_REQUESTED, message=event, key=str(request_id))

    logger.info("Template create command published", request_id=str(request_id), name=request.name)
    return CommandAcceptedResponse(request_id=str(request_id))


@router.post("/{family_id}/versions", response_model=CommandAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def add_template_version(
    family_id: UUID,
    request: TemplateVersionAddRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> CommandAcceptedResponse:
    """Add a new version to an existing template family.

    Publishes TemplateVersionAddRequested command event to Kafka.
    Returns 202 Accepted with request_id for async tracking.
    """
    validation = validate_template_content(request.template_content)
    if not validation.valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": "Invalid template content", "issues": [i.model_dump() for i in validation.issues]},
        )

    request_id = uuid7()
    metadata = _create_cmd_metadata(request_id)

    event = TemplateVersionAddRequested(
        metadata=metadata,
        request_id=str(request_id),
        user_id=str(user_id),
        template_id=str(family_id),
        version=request.version,
        template_content=request.template_content,
        description=request.description,
    )

    params = CommandRequestParams(
        request_id=request_id,
        user_id=user_id,
        command_type="template_version_add",
        entity_type="template_version",
        entity_id=family_id,
    )
    await _track_command_request(db, params)
    await kafka_client.publish(topic=Topics.DOC_TEMPLATE_VERSION_ADD_REQUESTED, message=event, key=str(request_id))

    logger.info("Template version add command published", request_id=str(request_id), family_id=str(family_id))
    return CommandAcceptedResponse(request_id=str(request_id))


@router.delete("/{family_id}", response_model=CommandAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def delete_template_family(
    family_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> CommandAcceptedResponse:
    """Delete a template family and all its versions.

    Publishes TemplateDeleteRequested command event to Kafka.
    Returns 202 Accepted with request_id for async tracking.
    """
    request_id = uuid7()
    metadata = _create_cmd_metadata(request_id)

    event = TemplateDeleteRequested(
        metadata=metadata,
        request_id=str(request_id),
        user_id=str(user_id),
        template_id=str(family_id),
    )

    params = CommandRequestParams(
        request_id=request_id,
        user_id=user_id,
        command_type="template_delete",
        entity_type="template_family",
        entity_id=family_id,
    )
    await _track_command_request(db, params)
    await kafka_client.publish(topic=Topics.DOC_TEMPLATE_DELETE_REQUESTED, message=event, key=str(request_id))

    logger.info("Template delete command published", request_id=str(request_id), family_id=str(family_id))
    return CommandAcceptedResponse(request_id=str(request_id))
