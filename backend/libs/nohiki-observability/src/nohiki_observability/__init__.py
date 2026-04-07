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

from typing import TYPE_CHECKING

from ._protobuf_init import init_protobuf
from .access_log import HTTPAccessLogMiddleware
from .builder import ObservabilityBuilder
from .config import ObservabilityOptions, OtelConfig
from .correlation import (
    CORRELATION_ID_HEADER,
    CorrelationIdMiddleware,
    get_correlation_id,
    set_correlation_id,
)
from .health import OTelHealthProbe
from .logger import Logger
from .observability import Observability, get_logger
from .protocols import ObservabilityConfig, ObservabilitySettingsProvider

init_protobuf()

if TYPE_CHECKING:
    from .prometheus import build_metrics_router as build_metrics_router

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


def __getattr__(name: str) -> object:
    """Lazy import for optional FastAPI-dependent symbols."""
    if name == "build_metrics_router":
        from .prometheus import build_metrics_router  # noqa: PLC0415

        return build_metrics_router
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
