"""Document-related Pydantic schemas for the template processor API."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    """Request for document generation."""

    template_version_id: UUID = Field(..., description="Template version ID to use for generation")
    data: dict[str, Any] = Field(..., description="Data to render in the template")
    output_format: str = Field(default="pdf", description="Output format (pdf, html, png, etc.)")
    schema_id: UUID | None = Field(default=None, description="Schema ID for data validation")
    include_text_alternative: bool = Field(default=False, description="Include text alternative of generated content")


class GenerateResponse(BaseModel):
    """Response for document generation."""

    content: bytes = Field(..., description="Generated document content")
    text_alt: str | None = Field(None, description="Text alternative of the generated content")
    template_version_id: UUID = Field(..., description="Template version ID used")
    template_name: str = Field(..., description="Name of the template used")
    template_version: str = Field(..., description="Version of the template used")


class ValidationRequest(BaseModel):
    """Request for data validation."""

    data: dict[str, Any] = Field(..., description="Data to validate")
    schema_id: UUID | None = Field(None, description="Schema ID to validate against")


class ValidationResponse(BaseModel):
    """Response for data validation."""

    is_valid: bool = Field(..., description="Whether the data is valid")
    errors: list[str] = Field(default_factory=list, description="Validation errors")
    warnings: list[str] = Field(default_factory=list, description="Validation warnings")
