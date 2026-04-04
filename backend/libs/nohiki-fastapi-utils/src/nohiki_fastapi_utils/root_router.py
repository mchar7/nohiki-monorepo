"""Root router factory for Nohiki services."""

from typing import Any

from fastapi import APIRouter


def build_root_router(service_name: str, version: str) -> APIRouter:
    """Build a standardized root router for a Nohiki service.

    Args:
        service_name: Name of the service (e.g., "doc-layout-service")
        version: Version of the service (e.g., "0.1.0")

    Returns:
        APIRouter with root endpoint configured

    """
    router = APIRouter()

    @router.get("/", tags=["system"], summary="Root")
    async def root() -> dict[str, Any]:
        """Root endpoint returning service information."""
        return {
            "service": service_name,
            "version": version,
            "status": "running",
        }

    return router
