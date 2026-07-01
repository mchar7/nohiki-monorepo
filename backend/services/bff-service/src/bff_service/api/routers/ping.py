"""System endpoints for BFF service."""

from fastapi import APIRouter

router = APIRouter(tags=["system", "ping"])


@router.get("/api/ping", summary="Ping")
def ping() -> dict[str, str]:
    """Return ok status for frontend connectivity checks."""
    return {"status": "ok"}
