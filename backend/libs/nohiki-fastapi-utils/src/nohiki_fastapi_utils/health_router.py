"""Kubernetes-compliant health check router for FastAPI applications."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from .startup_validation import run_health_probes

if TYPE_CHECKING:
    from collections.abc import Callable

    from nohiki_common_exceptions import HealthProbe

LIVENESS_PATH = "/healthz"
READINESS_PATH = "/readyz"


def _determine_overall_status(*, all_healthy: bool, has_degraded: bool) -> str:
    """Determine overall health status from probe results."""
    if not all_healthy:
        return "unhealthy"
    if has_degraded:
        return "degraded"
    return "healthy"


@runtime_checkable
class ReadinessGateProtocol(Protocol):
    """Protocol for services with async startup (e.g. ML model download).

    When provided to the health router, /readyz returns 503 while
    ``is_ready`` is False, allowing Docker/K8s to distinguish
    "starting" from "unhealthy".
    """

    @property
    def is_ready(self) -> bool:
        """Whether the service has completed startup."""
        ...

    @property
    def is_failed(self) -> bool:
        """Whether startup has permanently failed."""
        ...


def _check_readiness_gate(
    gate: ReadinessGateProtocol | None,
    service_name: str,
) -> JSONResponse | None:
    """Return a 503 response if the readiness gate is not yet open."""
    if gate is None:
        return None
    if gate.is_failed:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "service": service_name, "reason": "startup_failed"},
        )
    if not gate.is_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "starting", "service": service_name, "reason": "models_loading"},
        )
    return None


def build_probe_health_router(
    service_name: str,
    get_probes: Callable[[], list[HealthProbe]],
    *,
    readiness_gate: ReadinessGateProtocol | None = None,
    include_debug_endpoint: bool = False,
) -> APIRouter:
    """Build a Kubernetes-compliant health check router using domain-owned health probes.

    Each library owns its health probe logic (e.g., KafkaHealthProbe, DatabaseHealthProbe).
    Services declare which probes they need, and this router aggregates results.

    Standard K8s Endpoints:
    - /healthz: Liveness probe (minimal checks, restart container if fails)
    - /readyz: Readiness probe (runs all registered probes)

    Optional:
    - /health: Debug/monitoring endpoint with full probe details

    Args:
        service_name: Name of the service.
        get_probes: Callable that returns list of HealthProbe instances.
                   Called on each request to allow dynamic probe lists.
        readiness_gate: Optional gate for async startup (e.g., ML model loading).
                       When provided, /readyz returns 503 until the gate is ready.
        include_debug_endpoint: Include /health endpoint for debugging.

    Returns:
        FastAPI router with Kubernetes-compliant health check endpoints.

    Example:
        from nohiki_db_utils import DatabaseHealthProbe, get_async_engine
        from nohiki_kafka_client import KafkaHealthProbe, KafkaCapability

        def get_probes() -> list[HealthProbe]:
            return [
                DatabaseHealthProbe(get_async_engine(settings.database)),
                KafkaHealthProbe(
                    settings.kafka.bootstrap_servers,
                    capabilities={KafkaCapability.BROKER_CONNECTIVITY, KafkaCapability.CONSUMER_READY},
                ),
            ]

        router = build_probe_health_router("my-service", get_probes)
        app.include_router(router)

    """
    router = APIRouter()

    def liveness_probe() -> dict[str, str]:
        """Liveness probe: verify service process is running."""
        return {"status": "ok", "service": service_name}

    async def probe_health_response(*, include_details: bool) -> JSONResponse:
        """Run registered probes and build a health response."""
        probes: list[HealthProbe] = get_probes()
        results = await run_health_probes(probes)

        all_healthy = all(r.is_healthy() for r in results)
        has_degraded = any(r.status.value == "degraded" for r in results)
        overall_status = _determine_overall_status(all_healthy=all_healthy, has_degraded=has_degraded)
        probe_data = (
            [result.to_dict() for result in results]
            if include_details
            else [
                {"name": result.name, "status": result.status.value, "healthy": result.is_healthy()}
                for result in results
            ]
        )
        response_content = {
            "status": overall_status,
            "service": service_name,
            "timestamp": datetime.now(UTC).isoformat(),
            "probes": probe_data,
        }

        response_status = status.HTTP_503_SERVICE_UNAVAILABLE if overall_status == "unhealthy" else status.HTTP_200_OK
        return JSONResponse(status_code=response_status, content=response_content)

    async def readiness_probe() -> JSONResponse:
        """Readiness probe: run probes without exposing dependency details."""
        if (gate_response := _check_readiness_gate(readiness_gate, service_name)) is not None:
            return gate_response
        return await probe_health_response(include_details=False)

    async def debug_health_probe() -> JSONResponse:
        """Debug health probe with full dependency details."""
        if (gate_response := _check_readiness_gate(readiness_gate, service_name)) is not None:
            return gate_response
        return await probe_health_response(include_details=True)

    router.add_api_route(
        LIVENESS_PATH,
        liveness_probe,
        methods=["GET"],
        summary="Liveness probe",
        description="K8s liveness probe - restart container if fails",
        tags=["health"],
    )

    router.add_api_route(
        READINESS_PATH,
        readiness_probe,
        methods=["GET"],
        summary="Readiness probe",
        description="K8s readiness probe - runs all registered health probes",
        tags=["health"],
    )

    if include_debug_endpoint:
        router.add_api_route(
            "/health",
            debug_health_probe,
            methods=["GET"],
            summary="Debug health check",
            description="health overview for debugging/monitoring",
            tags=["debug"],
        )

    return router


def build_stateless_health_router(service_name: str) -> APIRouter:
    """Build health router for stateless services (no external dependencies).

    For stateless services, liveness and readiness are effectively the same.
    """
    router = APIRouter()

    def stateless_health() -> dict[str, str]:
        """Health check for stateless services."""
        return {"status": "ok", "service": service_name}

    router.add_api_route(LIVENESS_PATH, stateless_health, methods=["GET"], tags=["health"])
    router.add_api_route(READINESS_PATH, stateless_health, methods=["GET"], tags=["health"])

    return router
