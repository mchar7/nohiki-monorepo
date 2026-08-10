"""Constants for nohiki-llm-client."""

from __future__ import annotations

from typing import Final, Literal

# HTTP status codes
HTTP_OK: Final[int] = 200
HTTP_UNAUTHORIZED: Final[int] = 401

# Health probe defaults
DEFAULT_HEALTH_TIMEOUT_SECONDS: Final[float] = 10.0
DEFAULT_STARTUP_TIMEOUT_SECONDS: Final[float] = 30.0
DEFAULT_RETRY_INTERVAL_SECONDS: Final[float] = 5.0
HEALTH_PROBE_NAME: Final[str] = "llm"

# Retry configuration
MAX_RETRY_ATTEMPTS: Final[int] = 3
RETRY_MULTIPLIER: Final[float] = 1.0
RETRY_MIN_WAIT_SECONDS: Final[float] = 2.0
RETRY_MAX_WAIT_SECONDS: Final[float] = 30.0

# Model string format
LLM_MODEL_SEPARATOR: Final[str] = ":"

type ReasoningEffort = Literal["disabled", "low", "medium", "high"]

# Default model settings
DEFAULT_APP_TITLE: Final[str] = "Nohiki"
DEFAULT_MAX_TOOL_RETRIES: Final[int] = 3
DEFAULT_TIMEOUT_SECONDS: Final[float] = 120.0
DEFAULT_TEMPERATURE: Final[float] = 0.0
DEFAULT_REASONING_EFFORT: Final[ReasoningEffort] = "high"

# Ollama defaults (calculated for production workloads)
# num_ctx calculation: 1118 input + 4096 output + 8192 thinking = 13406 → 16384
DEFAULT_OLLAMA_BASE_URL: Final[str] = "http://localhost:11434/v1"
DEFAULT_OLLAMA_NUM_CTX: Final[int] = 16384
DEFAULT_OLLAMA_TOP_K: Final[int] = 40
DEFAULT_OLLAMA_REPEAT_PENALTY: Final[float] = 1.1
OLLAMA_MIN_CONTEXT: Final[int] = 512
OLLAMA_MAX_CONTEXT: Final[int] = 131072

# Anthropic model prefixes that support adaptive thinking (type="adaptive") and
# the anthropic_effort parameter. Temperature must be 1.0 when active.
ANTHROPIC_ADAPTIVE_THINKING_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "claude-sonnet-4-6",
        "claude-opus-4-6",
    }
)

# Anthropic model prefixes that support classic extended thinking (type="enabled",
# budget_tokens=N) but NOT adaptive thinking. Temperature must be 1.0 when active.
ANTHROPIC_EXTENDED_THINKING_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "claude-haiku-4-5",
    }
)

# budget_tokens mapped from ReasoningEffort for extended thinking (enabled) mode.
ANTHROPIC_EXTENDED_THINKING_BUDGET: Final[dict[str, int]] = {
    "low": 2_000,
    "medium": 8_000,
    "high": 16_000,
}

# Provider identifiers
PROVIDER_OPENROUTER: Final[str] = "openrouter"
PROVIDER_OPENAI: Final[str] = "openai"
PROVIDER_OLLAMA: Final[str] = "ollama"
PROVIDER_ANTHROPIC: Final[str] = "anthropic"
PROVIDER_LLAMACPP: Final[str] = "llamacpp"
PROVIDER_GOOGLE_VERTEX: Final[str] = "google-vertex"
KEYLESS_PROVIDERS: Final[frozenset[str]] = frozenset({PROVIDER_OLLAMA, PROVIDER_LLAMACPP})
API_KEY_OPTIONAL_PROVIDERS: Final[frozenset[str]] = frozenset({PROVIDER_GOOGLE_VERTEX})

# Phoenix/OpenTelemetry settings
PHOENIX_SERVICE_NAMESPACE: Final[str] = "nohiki"
PHOENIX_DEFAULT_SERVICE_NAME: Final[str] = "nohiki-llm"

# Provider settings bounds
PROVIDER_MAX_TOKENS: Final[int] = 128_000
PROVIDER_REQUEST_TIMEOUT_MAX: Final[float] = 600.0
PROVIDER_TOOL_RETRIES_MAX: Final[int] = 10

# HTTP-level retry for LLM provider connections
HTTP_RETRY_ATTEMPTS: Final[int] = 5
HTTP_RETRY_MIN_WAIT_SECONDS: Final[float] = 1.0
HTTP_RETRY_MAX_WAIT_SECONDS: Final[float] = 60.0
HTTP_RETRY_MAX_TOTAL_WAIT_SECONDS: Final[float] = 300.0
HTTP_STATUS_RATE_LIMIT: Final[int] = 429
HTTP_RETRYABLE_STATUS_CODES: Final[frozenset[int]] = frozenset({HTTP_STATUS_RATE_LIMIT, 502, 503, 504})

# Span export configuration for per-model instrumentation (smaller values suit per-request tracing)
INSTRUMENTATION_SPAN_QUEUE_MAX_SIZE: Final[int] = 512
INSTRUMENTATION_SPAN_EXPORT_BATCH_SIZE: Final[int] = 32
INSTRUMENTATION_SPAN_EXPORT_DELAY_MS: Final[int] = 500

# PydanticAI OpenRouter message prefix when the provider returns a response that fails
# ChatCompletion validation (all null fields): indicates model not found or permanent
# provider routing failure. NOT retryable.
OPENROUTER_INVALID_RESPONSE_PREFIX: Final[str] = "Invalid response from openrouter chat completions endpoint"

# Error messages
ERROR_NO_API_KEY: Final[str] = "LLM API key not configured"

# OTEL metrics meter name
OTEL_METER_NAME: Final[str] = "nohiki.llm"

# Metrics names (OTEL semantic conventions with nohiki_ prefix)
METRIC_LLM_REQUESTS_TOTAL: Final[str] = "nohiki_llm_requests_total"
METRIC_LLM_REQUEST_DURATION: Final[str] = "nohiki_llm_request_duration_seconds"
METRIC_LLM_PROMPT_TOKENS: Final[str] = "nohiki_llm_prompt_tokens_total"
METRIC_LLM_COMPLETION_TOKENS: Final[str] = "nohiki_llm_completion_tokens_total"
METRIC_LLM_ERRORS: Final[str] = "nohiki_llm_errors_total"
METRIC_LLM_COST: Final[str] = "nohiki_llm_cost_microdollars_total"
METRIC_LLM_CACHE_HITS: Final[str] = "nohiki_llm_cache_hits_total"
METRIC_LLM_CACHE_READ_TOKENS: Final[str] = "nohiki_llm_cache_read_tokens_total"
METRIC_LLM_CACHE_WRITE_TOKENS: Final[str] = "nohiki_llm_cache_write_tokens_total"
