"""Nohiki Observability Module.

Standardized observability capabilities for all Nohiki microservices,
including structured logging, distributed tracing, metrics collection, and correlation tracking.

Example usage:
    from nohiki_observability import Observability, get_logger

    # Initialize from settings (recommended)
    obs = Observability.from_settings(settings)
    obs.init()

    # Get a logger
    logger = get_logger(__name__)

    # For FastAPI apps
    obs.init_fastapi(app)

    # Or use the builder for custom configuration
    obs = (
        Observability.builder()
        .service("my-service", "1.0.0")
        .otel_endpoint("http://collector:4317")
        .environment("production")
        .build()
    )
    obs.init()
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from ._protobuf_init import init_protobuf

# OTLP exporters require generated protobuf descriptors to be registered before their first lazy import.
init_protobuf()

if TYPE_CHECKING:
    from .access_log import HTTPAccessLogMiddleware as HTTPAccessLogMiddleware
    from .builder import ObservabilityBuilder as ObservabilityBuilder
    from .config import ObservabilityOptions as ObservabilityOptions
    from .config import OtelConfig as OtelConfig
    from .correlation import CORRELATION_ID_HEADER as CORRELATION_ID_HEADER
    from .correlation import CorrelationIdMiddleware as CorrelationIdMiddleware
    from .correlation import get_correlation_id as get_correlation_id
    from .correlation import set_correlation_id as set_correlation_id
    from .health import OTelHealthProbe as OTelHealthProbe
    from .logger import Logger as Logger
    from .logger import get_logger as get_logger
    from .observability import Observability as Observability
    from .prometheus import build_metrics_router as build_metrics_router
    from .protocols import ObservabilityConfig as ObservabilityConfig
    from .protocols import ObservabilitySettingsProvider as ObservabilitySettingsProvider

__all__ = [
    "CORRELATION_ID_HEADER",
    "CorrelationIdMiddleware",
    "HTTPAccessLogMiddleware",
    "Logger",
    "OTelHealthProbe",
    "Observability",
    "ObservabilityBuilder",
    "ObservabilityConfig",
    "ObservabilityOptions",
    "ObservabilitySettingsProvider",
    "OtelConfig",
    "build_metrics_router",
    "get_correlation_id",
    "get_logger",
    "set_correlation_id",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "CORRELATION_ID_HEADER": ("nohiki_observability.correlation", "CORRELATION_ID_HEADER"),
    "CorrelationIdMiddleware": ("nohiki_observability.correlation", "CorrelationIdMiddleware"),
    "HTTPAccessLogMiddleware": ("nohiki_observability.access_log", "HTTPAccessLogMiddleware"),
    "Logger": ("nohiki_observability.logger", "Logger"),
    "OTelHealthProbe": ("nohiki_observability.health", "OTelHealthProbe"),
    "Observability": ("nohiki_observability.observability", "Observability"),
    "ObservabilityBuilder": ("nohiki_observability.builder", "ObservabilityBuilder"),
    "ObservabilityConfig": ("nohiki_observability.protocols", "ObservabilityConfig"),
    "ObservabilityOptions": ("nohiki_observability.config", "ObservabilityOptions"),
    "ObservabilitySettingsProvider": ("nohiki_observability.protocols", "ObservabilitySettingsProvider"),
    "OtelConfig": ("nohiki_observability.config", "OtelConfig"),
    "build_metrics_router": ("nohiki_observability.prometheus", "build_metrics_router"),
    "get_correlation_id": ("nohiki_observability.correlation", "get_correlation_id"),
    "get_logger": ("nohiki_observability.logger", "get_logger"),
    "set_correlation_id": ("nohiki_observability.correlation", "set_correlation_id"),
}


def __getattr__(name: str) -> object:
    """Lazy-import observability components on first use (PEP 562)."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
