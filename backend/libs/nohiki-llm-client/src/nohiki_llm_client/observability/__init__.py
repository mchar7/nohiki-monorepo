"""Observability module for nohiki-llm-client.

Contains health probes, metrics, tracing, and instrumentation.
"""

from __future__ import annotations

from .health import LLMHealthProbe, ensure_llm_ready
from .instrumentation import create_instrumented_model
from .metrics import LLMMetrics, RequestMetricsParams, get_llm_metrics
from .phoenix import (
    create_grpc_exporter,
    create_openinference_processor,
    create_phoenix_resource,
)
from .tracing import llm_span_context, prompt_template_context, set_llm_span_feedback

__all__ = [
    "LLMHealthProbe",
    "LLMMetrics",
    "RequestMetricsParams",
    "create_grpc_exporter",
    "create_instrumented_model",
    "create_openinference_processor",
    "create_phoenix_resource",
    "ensure_llm_ready",
    "get_llm_metrics",
    "llm_span_context",
    "prompt_template_context",
    "set_llm_span_feedback",
]
