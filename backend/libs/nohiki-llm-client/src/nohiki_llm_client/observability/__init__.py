"""Observability module for nohiki-llm-client.

Contains health probes, metrics, tracing, and instrumentation.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .health import LLMHealthProbe as LLMHealthProbe
    from .health import ensure_llm_ready as ensure_llm_ready
    from .instrumentation import create_instrumented_model as create_instrumented_model
    from .metrics import LLMMetrics as LLMMetrics
    from .metrics import RequestMetricsParams as RequestMetricsParams
    from .metrics import get_llm_metrics as get_llm_metrics
    from .phoenix import create_grpc_exporter as create_grpc_exporter
    from .phoenix import create_openinference_processor as create_openinference_processor
    from .phoenix import create_phoenix_resource as create_phoenix_resource
    from .tracing import llm_span_context as llm_span_context
    from .tracing import prompt_template_context as prompt_template_context
    from .tracing import set_llm_span_feedback as set_llm_span_feedback

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

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "LLMHealthProbe": ("nohiki_llm_client.observability.health", "LLMHealthProbe"),
    "ensure_llm_ready": ("nohiki_llm_client.observability.health", "ensure_llm_ready"),
    "create_instrumented_model": (
        "nohiki_llm_client.observability.instrumentation",
        "create_instrumented_model",
    ),
    "LLMMetrics": ("nohiki_llm_client.observability.metrics", "LLMMetrics"),
    "RequestMetricsParams": ("nohiki_llm_client.observability.metrics", "RequestMetricsParams"),
    "get_llm_metrics": ("nohiki_llm_client.observability.metrics", "get_llm_metrics"),
    "create_grpc_exporter": ("nohiki_llm_client.observability.phoenix", "create_grpc_exporter"),
    "create_openinference_processor": (
        "nohiki_llm_client.observability.phoenix",
        "create_openinference_processor",
    ),
    "create_phoenix_resource": ("nohiki_llm_client.observability.phoenix", "create_phoenix_resource"),
    "llm_span_context": ("nohiki_llm_client.observability.tracing", "llm_span_context"),
    "prompt_template_context": ("nohiki_llm_client.observability.tracing", "prompt_template_context"),
    "set_llm_span_feedback": ("nohiki_llm_client.observability.tracing", "set_llm_span_feedback"),
}


def __getattr__(name: str) -> object:
    """Lazy-import observability components (PEP 562)."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
