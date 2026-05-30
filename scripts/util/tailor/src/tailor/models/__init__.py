"""Data models for tailor CLI."""

from __future__ import annotations

from tailor.models.inputs import ContextFile, JobFile, TailorInput
from tailor.models.outputs import GenerationResult, RenderResult, TailorOutput
from tailor.models.templates import SchemaInfo, TemplateInfo

__all__ = [
    "ContextFile",
    "GenerationResult",
    "JobFile",
    "RenderResult",
    "SchemaInfo",
    "TailorInput",
    "TailorOutput",
    "TemplateInfo",
]
