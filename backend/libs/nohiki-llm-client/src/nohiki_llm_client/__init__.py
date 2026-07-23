"""Shared LLM client for Nohiki services.

Provides PydanticAI-based structured output generation with integrated
metrics, retry logic, and observability. Uses ``provider:model`` strings
as the canonical model identifier format.

Example (Fixed Schema)::

    from nohiki_llm_client import LLMClient, LLMResult, StructuredAgentConfig

    client = LLMClient(settings.llm)
    agent = client.create_agent(StructuredAgentConfig(
        deps_type=MyContext,
        output_type=MyOutput,
        system_prompt="You are a helpful assistant.",
    ))
    result = await client.run(agent, "Generate", deps=ctx)

Example (Dynamic Schema)::

    from nohiki_llm_client import LLMClient, DynamicAgentConfig

    agent = client.create_dynamic_schema_agent(DynamicAgentConfig(
        deps_type=MyContext,
        json_schema=schema,
        schema_name="TailoredResume",
    ))
    result = await client.run(agent, "Generate", deps=ctx)
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import (
        CachePoint as CachePoint,
    )
    from .client import (
        DynamicAgentConfig as DynamicAgentConfig,
    )
    from .client import (
        LLMClient as LLMClient,
    )
    from .client import (
        LLMResult as LLMResult,
    )
    from .client import (
        ModelSettings as ModelSettings,
    )
    from .client import (
        StructuredAgentConfig as StructuredAgentConfig,
    )
    from .client import (
        SystemPromptFn as SystemPromptFn,
    )
    from .client import (
        get_or_create_provider_limiter as get_or_create_provider_limiter,
    )
    from .client import (
        reset_provider_limiters as reset_provider_limiters,
    )
    from .evals import (
        EvaluationResult as EvaluationResult,
    )
    from .evals import (
        FieldMatchEvaluator as FieldMatchEvaluator,
    )
    from .evals import (
        ListLengthEvaluator as ListLengthEvaluator,
    )
    from .evals import (
        LLMEvaluator as LLMEvaluator,
    )
    from .evals import (
        create_extraction_dataset as create_extraction_dataset,
    )
    from .observability import (
        LLMHealthProbe as LLMHealthProbe,
    )
    from .observability import (
        LLMMetrics as LLMMetrics,
    )
    from .observability import (
        RequestMetricsParams as RequestMetricsParams,
    )
    from .observability import (
        create_instrumented_model as create_instrumented_model,
    )
    from .observability import (
        ensure_llm_ready as ensure_llm_ready,
    )
    from .observability import (
        get_llm_metrics as get_llm_metrics,
    )
    from .observability import (
        llm_span_context as llm_span_context,
    )
    from .observability import (
        prompt_template_context as prompt_template_context,
    )
    from .observability import (
        set_llm_span_feedback as set_llm_span_feedback,
    )
    from .pricing import calc_llm_cost as calc_llm_cost
    from .providers import (
        create_settings_from_model as create_settings_from_model,
    )
    from .providers import (
        resolve_chain as resolve_chain,
    )
from .config import (
    DEFAULT_OLLAMA_NUM_CTX,
    ApiKeyRegistry,
    CacheTTL,
    LLMCachingSettings,
    LLMInstrumentationSettings,
    LLMMixin,
    LLMModelConfig,
    LLMProviderSettings,
    LLMSettings,
    OllamaSettings,
    ReasoningEffort,
)
from .exceptions import (
    LLMApplicationRateLimitError,
    LLMAuthenticationError,
    LLMCircuitOpenError,
    LLMContextTooLongError,
    LLMError,
    LLMInvalidSchemaError,
    LLMProviderResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMTransientError,
    LLMValidationError,
)

__all__ = [
    "DEFAULT_OLLAMA_NUM_CTX",
    "ApiKeyRegistry",
    "CachePoint",
    "CacheTTL",
    "DynamicAgentConfig",
    "EvaluationResult",
    "FieldMatchEvaluator",
    "LLMApplicationRateLimitError",
    "LLMAuthenticationError",
    "LLMCachingSettings",
    "LLMCircuitOpenError",
    "LLMClient",
    "LLMContextTooLongError",
    "LLMError",
    "LLMEvaluator",
    "LLMHealthProbe",
    "LLMInstrumentationSettings",
    "LLMInvalidSchemaError",
    "LLMMetrics",
    "LLMMixin",
    "LLMModelConfig",
    "LLMProviderResponseError",
    "LLMProviderSettings",
    "LLMRateLimitError",
    "LLMResult",
    "LLMSettings",
    "LLMTimeoutError",
    "LLMTransientError",
    "LLMValidationError",
    "ListLengthEvaluator",
    "ModelSettings",
    "OllamaSettings",
    "ReasoningEffort",
    "RequestMetricsParams",
    "StructuredAgentConfig",
    "SystemPromptFn",
    "calc_llm_cost",
    "create_extraction_dataset",
    "create_instrumented_model",
    "create_settings_from_model",
    "ensure_llm_ready",
    "get_llm_metrics",
    "get_or_create_provider_limiter",
    "llm_span_context",
    "prompt_template_context",
    "reset_provider_limiters",
    "resolve_chain",
    "set_llm_span_feedback",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "CachePoint": ("nohiki_llm_client.client", "CachePoint"),
    "DynamicAgentConfig": ("nohiki_llm_client.client", "DynamicAgentConfig"),
    "LLMClient": ("nohiki_llm_client.client", "LLMClient"),
    "LLMResult": ("nohiki_llm_client.client", "LLMResult"),
    "ModelSettings": ("nohiki_llm_client.client", "ModelSettings"),
    "StructuredAgentConfig": ("nohiki_llm_client.client", "StructuredAgentConfig"),
    "SystemPromptFn": ("nohiki_llm_client.client", "SystemPromptFn"),
    "get_or_create_provider_limiter": ("nohiki_llm_client.client", "get_or_create_provider_limiter"),
    "reset_provider_limiters": ("nohiki_llm_client.client", "reset_provider_limiters"),
    "EvaluationResult": ("nohiki_llm_client.evals", "EvaluationResult"),
    "FieldMatchEvaluator": ("nohiki_llm_client.evals", "FieldMatchEvaluator"),
    "ListLengthEvaluator": ("nohiki_llm_client.evals", "ListLengthEvaluator"),
    "LLMEvaluator": ("nohiki_llm_client.evals", "LLMEvaluator"),
    "create_extraction_dataset": ("nohiki_llm_client.evals", "create_extraction_dataset"),
    "LLMHealthProbe": ("nohiki_llm_client.observability", "LLMHealthProbe"),
    "LLMMetrics": ("nohiki_llm_client.observability", "LLMMetrics"),
    "RequestMetricsParams": ("nohiki_llm_client.observability", "RequestMetricsParams"),
    "create_instrumented_model": ("nohiki_llm_client.observability", "create_instrumented_model"),
    "ensure_llm_ready": ("nohiki_llm_client.observability", "ensure_llm_ready"),
    "get_llm_metrics": ("nohiki_llm_client.observability", "get_llm_metrics"),
    "llm_span_context": ("nohiki_llm_client.observability", "llm_span_context"),
    "prompt_template_context": ("nohiki_llm_client.observability", "prompt_template_context"),
    "set_llm_span_feedback": ("nohiki_llm_client.observability", "set_llm_span_feedback"),
    "calc_llm_cost": ("nohiki_llm_client.pricing", "calc_llm_cost"),
    "create_settings_from_model": ("nohiki_llm_client.providers", "create_settings_from_model"),
    "resolve_chain": ("nohiki_llm_client.providers", "resolve_chain"),
}


def __getattr__(name: str) -> object:
    """Lazy-import runtime LLM components (PEP 562)."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
