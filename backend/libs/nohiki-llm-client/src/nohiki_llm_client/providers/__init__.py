"""Providers module for nohiki-llm-client.

Contains provider-specific model creation, profiles, and transformers.
"""

from __future__ import annotations

from .caching import CachingConfig, CachingOpenRouterModel
from .factory import (
    create_caching_openrouter,
    create_full_model_chain,
    create_model,
    create_settings_from_model,
    resolve_chain,
)
from .llamacpp import LlamaCppProvider
from .openrouter import RobustOpenRouterModel
from .profiles import (
    INLINED_REFS_OPENROUTER_PROFILE,
    OLLAMA_PROFILE,
    OpenRouterModelQuirks,
    select_openrouter_quirks,
)
from .transformers import InlinedRefsJsonSchemaTransformer, OllamaJsonSchemaTransformer

__all__ = [
    "INLINED_REFS_OPENROUTER_PROFILE",
    "OLLAMA_PROFILE",
    "CachingConfig",
    "CachingOpenRouterModel",
    "InlinedRefsJsonSchemaTransformer",
    "LlamaCppProvider",
    "OllamaJsonSchemaTransformer",
    "OpenRouterModelQuirks",
    "RobustOpenRouterModel",
    "create_caching_openrouter",
    "create_full_model_chain",
    "create_model",
    "create_settings_from_model",
    "resolve_chain",
    "select_openrouter_quirks",
]
