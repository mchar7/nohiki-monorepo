"""Correlation ID management for request tracing across services.

Thread-safe correlation ID handling using contextvars
and FastAPI middleware for automatic correlation ID injection.
"""

from contextvars import ContextVar
from typing import TYPE_CHECKING

from uuid_utils.compat import uuid7

if TYPE_CHECKING:
    from fastapi import Request, Response
    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

_FASTAPI_AVAILABLE = False
try:
    from fastapi import Request, Response
    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

    _FASTAPI_AVAILABLE = True
except ModuleNotFoundError:
    pass


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


if _FASTAPI_AVAILABLE:

    class CorrelationIdMiddleware(BaseHTTPMiddleware):
        """FastAPI middleware that extracts or generates correlation IDs for requests.

        This middleware:
        1. Extracts correlation ID from X-Correlation-ID header if present
        2. Generates a new UUID if no correlation ID is provided
        3. Sets the correlation ID in the context variable
        4. Adds the correlation ID to the response headers
        """

        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
            """Process the request and handle correlation ID."""
            correlation_id = request.headers.get(CORRELATION_ID_HEADER, "")
            if not _is_valid_correlation_id(correlation_id):
                correlation_id = str(uuid7())

            token = _correlation_id_ctx_var.set(correlation_id)
            try:
                response: Response = await call_next(request)
                response.headers[CORRELATION_ID_HEADER] = correlation_id
                return response
            finally:
                _correlation_id_ctx_var.reset(token)

else:

    class CorrelationIdMiddleware:
        """Raises helpful error if used without FastAPI extra."""

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            """Initialize middleware with helpful error message."""
            msg = "FastAPI not installed. Install nohiki-observability[fastapi] to use CorrelationIdMiddleware."
            raise ImportError(msg)
