"""Structured HTTP access log middleware.

Logs every HTTP request/response as a structured JSON event via structlog.
Replaces the silenced uvicorn.access logger with per-request visibility
that includes correlation ID, method, path, status code, and duration.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from .logger import get_logger

if TYPE_CHECKING:
    from fastapi import Request, Response
    from starlette.middleware.base import RequestResponseEndpoint

logger = get_logger(__name__)

# Paths excluded from access logging to reduce noise
_SILENT_PATHS: frozenset[str] = frozenset({"/healthz", "/readyz", "/metrics"})


class HTTPAccessLogMiddleware(BaseHTTPMiddleware):
    """Log each HTTP request as a structured event.

    Captures method, path, status code, and response time. Health/metrics
    endpoints are excluded to avoid log noise from orchestrator probes.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process request, measure duration, emit structured log."""
        path = request.url.path
        if path in _SILENT_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.error(  # noqa: TRY400  # access logs deliberately omit exception details
                "HTTP request",
                method=request.method,
                path=path,
                status_code=500,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            raise

        logger.info(
            "HTTP request",
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return response
