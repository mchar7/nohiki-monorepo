"""Client module for nohiki-llm-client."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .concurrency import (
        apply_concurrency_limit as apply_concurrency_limit,
    )
    from .concurrency import (
        get_or_create_provider_limiter as get_or_create_provider_limiter,
    )
    from .concurrency import (
        reset_provider_limiters as reset_provider_limiters,
    )
    from .core import (
        CachePoint as CachePoint,
    )
    from .core import (
        DynamicAgentConfig as DynamicAgentConfig,
    )
    from .core import (
        LLMClient as LLMClient,
    )
    from .core import (
        LLMResult as LLMResult,
    )
    from .core import (
        ModelSettings as ModelSettings,
    )
    from .core import (
        StructuredAgentConfig as StructuredAgentConfig,
    )
    from .core import (
        SystemPromptFn as SystemPromptFn,
    )

__all__ = [
    "CachePoint",
    "DynamicAgentConfig",
    "LLMClient",
    "LLMResult",
    "ModelSettings",
    "StructuredAgentConfig",
    "SystemPromptFn",
    "apply_concurrency_limit",
    "get_or_create_provider_limiter",
    "reset_provider_limiters",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "apply_concurrency_limit": ("nohiki_llm_client.client.concurrency", "apply_concurrency_limit"),
    "get_or_create_provider_limiter": ("nohiki_llm_client.client.concurrency", "get_or_create_provider_limiter"),
    "reset_provider_limiters": ("nohiki_llm_client.client.concurrency", "reset_provider_limiters"),
    "CachePoint": ("nohiki_llm_client.client.core", "CachePoint"),
    "DynamicAgentConfig": ("nohiki_llm_client.client.core", "DynamicAgentConfig"),
    "LLMClient": ("nohiki_llm_client.client.core", "LLMClient"),
    "LLMResult": ("nohiki_llm_client.client.core", "LLMResult"),
    "ModelSettings": ("nohiki_llm_client.client.core", "ModelSettings"),
    "StructuredAgentConfig": ("nohiki_llm_client.client.core", "StructuredAgentConfig"),
    "SystemPromptFn": ("nohiki_llm_client.client.core", "SystemPromptFn"),
}


def __getattr__(name: str) -> object:
    """Lazy-import client components (PEP 562)."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
