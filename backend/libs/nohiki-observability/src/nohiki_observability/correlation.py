"""Correlation ID management for request tracing across services.

Thread-safe correlation ID handling using contextvars
and FastAPI middleware for automatic correlation ID injection.
"""

from __future__ import annotations

import importlib
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._correlation_middleware import CorrelationIdMiddleware

__all__ = [
    "CORRELATION_ID_HEADER",
    "CorrelationIdMiddleware",
    "get_correlation_id",
    "set_correlation_id",
]

# Standard header name for correlation ID
CORRELATION_ID_HEADER = "X-Correlation-ID"

# Thread-safe context variable for correlation ID storage
_correlation_id_ctx_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_MAX_CORRELATION_ID_LENGTH = 128


def _is_valid_correlation_id(value: str) -> bool:
    """Accept bounded printable ASCII IDs safe for logs and response headers."""
    return 0 < len(value) <= _MAX_CORRELATION_ID_LENGTH and value.isascii() and value.isprintable()


def get_correlation_id() -> str | None:
    """Get the current correlation ID from the context.

    Returns:
        The correlation ID if set, None otherwise.

    """
    return _correlation_id_ctx_var.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID in the current context.

    This is typically called by the middleware, but can be used
    to manually set the correlation ID in non-HTTP contexts
    (e.g., Kafka message handlers).

    Args:
        correlation_id: The correlation ID to set.

    """
    _correlation_id_ctx_var.set(correlation_id)


_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "CorrelationIdMiddleware": ("nohiki_observability._correlation_middleware", "CorrelationIdMiddleware"),
}


def __getattr__(name: str) -> object:
    """Lazy-import FastAPI middleware on first use (PEP 562)."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
