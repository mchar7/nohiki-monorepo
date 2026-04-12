"""Core models for doc-template-service schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ALLOWED_IMAGE_FORMATS: frozenset[str] = frozenset({"png", "jpeg", "webp"})
ALLOWED_OUTPUT_FORMATS: frozenset[str] = frozenset({"pdf", "html", "png", "jpeg", "webp"})

MIN_DIMENSION = 1
MAX_DIMENSION = 4096
MIN_QUALITY = 1
MAX_QUALITY = 100


class ValidationIssue(BaseModel):
    """Represents a single validation issue."""

    path: str = Field(..., description="JSON path to the error location")
    keyword: str = Field(..., description="Validation keyword that failed")
    message: str = Field(..., description="Human-readable error message")


class ValidationReport(BaseModel):
    """Report containing validation results."""

    valid: bool = Field(..., description="Whether validation passed")
    issues: list[ValidationIssue] = Field(default_factory=list, description="List of validation issues")
    summary: dict[str, int] | None = Field(None, description="Summary counts by issue type")


class ImageOptions(BaseModel):
    """Options for image output format."""

    format: Literal["png", "jpeg", "webp"] = Field(..., description="Image format")
    width: int = Field(default=800, ge=1, le=4096, description="Image width in pixels")
    height: int = Field(default=600, ge=1, le=4096, description="Image height in pixels")
    quality: int = Field(default=90, ge=1, le=100, description="Image quality (1-100)")

    @field_validator("format", mode="before")
    @classmethod
    def validate_format(cls, v: str) -> str:
        """Validate image format."""
        if v not in ALLOWED_IMAGE_FORMATS:
            msg = f"Format must be one of: {', '.join(sorted(ALLOWED_IMAGE_FORMATS))}"
            raise ValueError(msg)
        return v

    @field_validator("width", "height", mode="before")
    @classmethod
    def validate_dimensions(cls, v: int) -> int:
        """Validate image dimensions."""
        if not MIN_DIMENSION <= v <= MAX_DIMENSION:
            msg = "Dimensions must be between 1 and 4096"
            raise ValueError(msg)
        return v

    @field_validator("quality", mode="before")
    @classmethod
    def validate_quality(cls, v: int) -> int:
        """Validate image quality."""
        if not MIN_QUALITY <= v <= MAX_QUALITY:
            msg = "Quality must be between 1 and 100"
            raise ValueError(msg)
        return v


class GenerateRequest(BaseModel):
    """Request to generate a document."""

    template: str = Field(..., description="Jinja2 template content")
    data: dict[str, Any] = Field(..., description="Data to render into template")
    output_format: Literal["pdf", "html", "png", "jpeg", "webp"] = Field(default="pdf", description="Output format")
    schema_id: str | None = Field(None, description="Optional schema ID for validation")
    schema_version: int | None = Field(None, description="Optional schema version")
    image_options: ImageOptions | None = Field(None, description="Options for image output")

    @field_validator("output_format", mode="before")
    @classmethod
    def validate_output_format(cls, v: str) -> str:
        """Validate output format."""
        if v not in ALLOWED_OUTPUT_FORMATS:
            msg = f"Output format must be one of: {', '.join(sorted(ALLOWED_OUTPUT_FORMATS))}"
            raise ValueError(msg)
        return v
