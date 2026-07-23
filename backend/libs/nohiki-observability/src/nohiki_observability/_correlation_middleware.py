"""FastAPI correlation middleware loaded only for HTTP users."""

from __future__ import annotations

from typing import TYPE_CHECKING

from uuid_utils.compat import uuid7

from .correlation import CORRELATION_ID_HEADER, _correlation_id_ctx_var, _is_valid_correlation_id

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


if _FASTAPI_AVAILABLE:

    class CorrelationIdMiddleware(BaseHTTPMiddleware):
        """Extract or generate correlation IDs for FastAPI requests."""

        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
            """Set a request-scoped correlation ID and add it to the response."""
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
        """Raise a helpful error when the FastAPI extra is unavailable."""

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            """Initialize middleware with a helpful dependency error."""
            msg = "FastAPI not installed. Install nohiki-observability[fastapi] to use CorrelationIdMiddleware."
            raise ImportError(msg)
