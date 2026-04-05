"""LLM metrics - owned by nohiki-llm-client."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram

from nohiki_llm_client.config.constants import (
    METRIC_LLM_CACHE_HITS,
    METRIC_LLM_CACHE_READ_TOKENS,
    METRIC_LLM_CACHE_WRITE_TOKENS,
    METRIC_LLM_COMPLETION_TOKENS,
    METRIC_LLM_COST,
    METRIC_LLM_ERRORS,
    METRIC_LLM_PROMPT_TOKENS,
    METRIC_LLM_REQUEST_DURATION,
    METRIC_LLM_REQUESTS_TOTAL,
    OTEL_METER_NAME,
)


@dataclass(frozen=True, slots=True)
class RequestMetricsParams:
    """Parameters for recording LLM request metrics."""

    model: str
    provider: str
    duration_seconds: float
    success: bool = True
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    use_case: str | None = None
    error_type: str | None = None
    cost_microdollars: int | None = None


class LLMMetrics:
    """LLM request metrics using OpenTelemetry."""

    __slots__ = (
        "_meter",
        "cache_hits",
        "cache_read_tokens",
        "cache_write_tokens",
        "completion_tokens",
        "cost_microdollars",
        "errors",
        "latency",
        "prompt_tokens",
        "requests",
    )

    def __init__(self) -> None:
        """Initialize LLM metrics with OpenTelemetry meter."""
        self._meter = metrics.get_meter(OTEL_METER_NAME)

        self.requests: Counter = self._meter.create_counter(
            METRIC_LLM_REQUESTS_TOTAL,
            description="Total LLM API requests",
            unit="1",
        )
        self.latency: Histogram = self._meter.create_histogram(
            METRIC_LLM_REQUEST_DURATION,
            description="LLM request latency",
            unit="s",
        )
        self.prompt_tokens: Counter = self._meter.create_counter(
            METRIC_LLM_PROMPT_TOKENS,
            description="Total prompt tokens used",
            unit="1",
        )
        self.completion_tokens: Counter = self._meter.create_counter(
            METRIC_LLM_COMPLETION_TOKENS,
            description="Total completion tokens generated",
            unit="1",
        )
        self.errors: Counter = self._meter.create_counter(
            METRIC_LLM_ERRORS,
            description="LLM request errors",
            unit="1",
        )
        self.cost_microdollars: Counter = self._meter.create_counter(
            METRIC_LLM_COST,
            description="Estimated cost in micro-dollars (1/1,000,000 USD)",
            unit="1",
        )
        self.cache_hits: Counter = self._meter.create_counter(
            METRIC_LLM_CACHE_HITS,
            description="Prompt cache hits",
            unit="1",
        )
        self.cache_read_tokens: Counter = self._meter.create_counter(
            METRIC_LLM_CACHE_READ_TOKENS,
            description="Tokens served from provider cache (reduced cost)",
            unit="1",
        )
        self.cache_write_tokens: Counter = self._meter.create_counter(
            METRIC_LLM_CACHE_WRITE_TOKENS,
            description="Tokens written to provider cache",
            unit="1",
        )

    def record_request(
        self,
        params: RequestMetricsParams,
    ) -> None:
        """Record an LLM request with cache metrics."""
        attrs: dict[str, str] = {
            "model": params.model,
            "provider": params.provider,
            "status": "success" if params.success else "error",
        }
        if params.use_case:
            attrs["use_case"] = params.use_case
        if params.error_type:
            attrs["error_type"] = params.error_type

        self.requests.add(1, attrs)
        self.latency.record(params.duration_seconds, attrs)

        if params.prompt_tokens > 0:
            self.prompt_tokens.add(params.prompt_tokens, attrs)
        if params.completion_tokens > 0:
            self.completion_tokens.add(params.completion_tokens, attrs)
        if params.cache_read_tokens > 0:
            self.cache_hits.add(1, attrs)
            self.cache_read_tokens.add(params.cache_read_tokens, attrs)
        if params.cache_write_tokens > 0:
            self.cache_write_tokens.add(params.cache_write_tokens, attrs)
        if params.cost_microdollars is not None:
            self.cost_microdollars.add(params.cost_microdollars, attrs)

        if not params.success:
            self.errors.add(1, attrs)


@lru_cache(maxsize=1)
def get_llm_metrics() -> LLMMetrics:
    """Get singleton LLMMetrics instance."""
    return LLMMetrics()
