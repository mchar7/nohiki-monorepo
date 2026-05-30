"""Adapters for integrating with Nohiki modules."""

from __future__ import annotations

from tailor.adapters.file_adapter import TailorFileAdapter
from tailor.adapters.llm_adapter import TailorLLMAdapter
from tailor.adapters.template_adapter import TailorTemplateAdapter

__all__ = [
    "TailorFileAdapter",
    "TailorLLMAdapter",
    "TailorTemplateAdapter",
]
