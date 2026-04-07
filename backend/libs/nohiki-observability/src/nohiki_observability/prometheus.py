"""Prometheus metrics endpoint for FastAPI services."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


def build_metrics_router() -> APIRouter:
    """Build router exposing /metrics endpoint for Prometheus scraping.

    This endpoint serves metrics from the default Prometheus registry,
    which includes all OTEL metrics exported via the Prometheus exporter.

    Usage:
        from nohiki_observability import build_metrics_router

        app = FastAPI()
        app.include_router(build_metrics_router())

    Returns:
        FastAPI router with /metrics endpoint.

    """
    router = APIRouter(tags=["observability"])

    @router.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        """Prometheus metrics endpoint."""
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    return router
