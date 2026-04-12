"""Template-related Pydantic schemas for the doc-template-service API.

Single-table design: Each template row IS a version. No separate family/version concepts.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from nohiki.common.v1 import AccessScope
from nohiki.doc.template.v1 import TemplateAudience
from pydantic import BaseModel, Field, field_validator

DESC_TEMPLATE_CONTENT = "Template content (Jinja2)"
DESC_SEMVER = "Semantic version string"
DESC_ITEMS_PER_PAGE = "Items per page"
DESC_CREATED_AT = "Creation timestamp"
DESC_CONTENT_SCHEMA = "JSON Schema for LLM-generated content output"
DESC_TEMPLATE_NAME = "Template name"
DESC_TEMPLATE_NAMESPACE = "Template namespace"
DESC_TEMPLATE_DESC = "Template description"
MAX_TEMPLATE_SIZE_BYTES = 100 * 1024
MAX_SCHEMA_SIZE_BYTES = 100 * 1024


class TemplateCreateRequest(BaseModel):
    """Request for creating a new template (version)."""

    name: str = Field(..., min_length=1, max_length=255, description=DESC_TEMPLATE_NAME)
    display_name: str = Field(..., min_length=1, max_length=255, description="User-visible template name")
    namespace: str = Field(default="default", min_length=1, max_length=100, description=DESC_TEMPLATE_NAMESPACE)
    version: str = Field(default="1.0.0", min_length=1, max_length=50, description=DESC_SEMVER)
    description: str | None = Field(None, description=DESC_TEMPLATE_DESC)
    template_content: str = Field(..., min_length=1, description=DESC_TEMPLATE_CONTENT)
    content_schema: dict[str, object] | None = Field(None, description=DESC_CONTENT_SCHEMA)
    access_scope: AccessScope = Field(default=AccessScope.PRIVATE, description="Access scope level")
    audience: TemplateAudience = Field(default=TemplateAudience.DOCUMENT, description="Template audience")

    @field_validator("template_content")
    @classmethod
    def validate_template_size(cls, value: str) -> str:
        """Reject templates above the UTF-8 byte limit."""
        if len(value.encode("utf-8")) > MAX_TEMPLATE_SIZE_BYTES:
            message = f"template_content exceeds {MAX_TEMPLATE_SIZE_BYTES} bytes"
            raise ValueError(message)
        return value

    @field_validator("content_schema")
    @classmethod
    def validate_schema_size(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        """Reject serialized schemas above the UTF-8 byte limit."""
        if value is not None and len(json.dumps(value, separators=(",", ":")).encode("utf-8")) > MAX_SCHEMA_SIZE_BYTES:
            message = f"content_schema exceeds {MAX_SCHEMA_SIZE_BYTES} bytes"
            raise ValueError(message)
        return value


class TemplateListQuery(BaseModel):
    """Query parameters for listing templates."""

    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description=DESC_ITEMS_PER_PAGE)
    search: str | None = Field(None, description="Search term for name/description")
    name: str | None = Field(None, description=f"Filter by {DESC_TEMPLATE_NAME.lower()}")
    namespace: str | None = Field(None, description="Filter by namespace")
    access_scope: AccessScope | None = Field(None, description="Filter by access scope")
    owner_id: UUID | None = Field(None, description="Filter by owner")
    latest_only: bool = Field(default=True, description="Return only latest version of each template")


class TemplateResponse(BaseModel):
    """Response model for a template."""

    id: UUID = Field(..., description="Template ID")
    namespace: str = Field(..., description=DESC_TEMPLATE_NAMESPACE)
    name: str = Field(..., description=DESC_TEMPLATE_NAME)
    display_name: str = Field(..., description="User-visible template name")
    version: str = Field(..., description=DESC_SEMVER)
    template_content: str = Field(..., description=DESC_TEMPLATE_CONTENT)
    content_schema: dict[str, object] | None = Field(None, description=DESC_CONTENT_SCHEMA)
    description: str | None = Field(None, description=DESC_TEMPLATE_DESC)
    access_scope: AccessScope = Field(..., description="Access scope level")
    audience: TemplateAudience = Field(..., description="Template audience")
    owner_id: UUID | None = Field(None, description="Owner user ID")
    created_at: datetime = Field(..., description=DESC_CREATED_AT)


class TemplateListResponse(BaseModel):
    """Response model for template listings."""

    templates: list[TemplateResponse] = Field(..., description="List of templates")
    total: int = Field(..., description="Total number of templates")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description=DESC_ITEMS_PER_PAGE)


class TemplateVersionsResponse(BaseModel):
    """Response model for listing all versions of a template."""

    namespace: str = Field(..., description=DESC_TEMPLATE_NAMESPACE)
    name: str = Field(..., description=DESC_TEMPLATE_NAME)
    versions: list[TemplateResponse] = Field(..., description="All versions of this template")
    total: int = Field(..., description="Total number of versions")
