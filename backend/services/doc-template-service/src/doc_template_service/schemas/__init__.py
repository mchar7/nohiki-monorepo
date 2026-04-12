"""Pydantic schemas for doc-template-service API."""

from .templates import (
    TemplateCreateRequest,
    TemplateListQuery,
    TemplateListResponse,
    TemplateResponse,
    TemplateVersionsResponse,
)

__all__ = [
    "TemplateCreateRequest",
    "TemplateListQuery",
    "TemplateListResponse",
    "TemplateResponse",
    "TemplateVersionsResponse",
]
