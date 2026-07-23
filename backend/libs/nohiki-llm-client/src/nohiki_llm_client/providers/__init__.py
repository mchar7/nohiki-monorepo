"""Providers module for nohiki-llm-client.

Contains provider-specific model creation, profiles, and transformers.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .caching import CachingConfig as CachingConfig
    from .caching import CachingOpenRouterModel as CachingOpenRouterModel
    from .factory import create_caching_openrouter as create_caching_openrouter
    from .factory import create_full_model_chain as create_full_model_chain
    from .factory import create_model as create_model
    from .factory import create_settings_from_model as create_settings_from_model
    from .factory import resolve_chain as resolve_chain
    from .llamacpp import LlamaCppProvider as LlamaCppProvider
    from .openrouter import RobustOpenRouterModel as RobustOpenRouterModel
    from .profiles import INLINED_REFS_OPENROUTER_PROFILE as INLINED_REFS_OPENROUTER_PROFILE
    from .profiles import OLLAMA_PROFILE as OLLAMA_PROFILE
    from .profiles import OpenRouterModelQuirks as OpenRouterModelQuirks
    from .profiles import select_openrouter_quirks as select_openrouter_quirks
    from .transformers import InlinedRefsJsonSchemaTransformer as InlinedRefsJsonSchemaTransformer
    from .transformers import OllamaJsonSchemaTransformer as OllamaJsonSchemaTransformer

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

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "CachingConfig": ("nohiki_llm_client.providers.caching", "CachingConfig"),
    "CachingOpenRouterModel": ("nohiki_llm_client.providers.caching", "CachingOpenRouterModel"),
    "create_caching_openrouter": ("nohiki_llm_client.providers.factory", "create_caching_openrouter"),
    "create_full_model_chain": ("nohiki_llm_client.providers.factory", "create_full_model_chain"),
    "create_model": ("nohiki_llm_client.providers.factory", "create_model"),
    "create_settings_from_model": ("nohiki_llm_client.providers.factory", "create_settings_from_model"),
    "resolve_chain": ("nohiki_llm_client.providers.factory", "resolve_chain"),
    "LlamaCppProvider": ("nohiki_llm_client.providers.llamacpp", "LlamaCppProvider"),
    "RobustOpenRouterModel": ("nohiki_llm_client.providers.openrouter", "RobustOpenRouterModel"),
    "INLINED_REFS_OPENROUTER_PROFILE": (
        "nohiki_llm_client.providers.profiles",
        "INLINED_REFS_OPENROUTER_PROFILE",
    ),
    "OLLAMA_PROFILE": ("nohiki_llm_client.providers.profiles", "OLLAMA_PROFILE"),
    "OpenRouterModelQuirks": ("nohiki_llm_client.providers.profiles", "OpenRouterModelQuirks"),
    "select_openrouter_quirks": ("nohiki_llm_client.providers.profiles", "select_openrouter_quirks"),
    "InlinedRefsJsonSchemaTransformer": (
        "nohiki_llm_client.providers.transformers",
        "InlinedRefsJsonSchemaTransformer",
    ),
    "OllamaJsonSchemaTransformer": (
        "nohiki_llm_client.providers.transformers",
        "OllamaJsonSchemaTransformer",
    ),
}


def __getattr__(name: str) -> object:
    """Lazy-import provider components (PEP 562)."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
