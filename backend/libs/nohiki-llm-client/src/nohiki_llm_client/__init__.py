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

from .client import (
    CachePoint,
    DynamicAgentConfig,
    LLMClient,
    LLMResult,
    ModelSettings,
    StructuredAgentConfig,
    SystemPromptFn,
    get_or_create_provider_limiter,
    reset_provider_limiters,
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
from .evals import (
    EvaluationResult,
    FieldMatchEvaluator,
    ListLengthEvaluator,
    LLMEvaluator,
    create_extraction_dataset,
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
from .observability import (
    LLMHealthProbe,
    LLMMetrics,
    RequestMetricsParams,
    create_instrumented_model,
    ensure_llm_ready,
    get_llm_metrics,
    llm_span_context,
    prompt_template_context,
    set_llm_span_feedback,
)
from .pricing import calc_llm_cost
from .providers import create_settings_from_model, resolve_chain

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
