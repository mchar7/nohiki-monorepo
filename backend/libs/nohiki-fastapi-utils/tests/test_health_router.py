"""Tests for health router utilities."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from nohiki_common_exceptions import HealthProbeResult, HealthStatus
from nohiki_fastapi_utils.health_router import (
    _check_readiness_gate,
    _determine_overall_status,
    build_probe_health_router,
    build_stateless_health_router,
)


class TestDetermineOverallStatus:
    """Tests for _determine_overall_status function."""

    def test_unhealthy_when_not_all_healthy(self) -> None:
        """Returns unhealthy when any probe is unhealthy."""
        assert _determine_overall_status(all_healthy=False, has_degraded=True) == "unhealthy"

    def test_unhealthy_when_not_all_healthy_no_degraded(self) -> None:
        """Returns unhealthy even without degraded when not all healthy."""
        assert _determine_overall_status(all_healthy=False, has_degraded=False) == "unhealthy"

    def test_degraded_when_all_healthy_but_has_degraded(self) -> None:
        """Returns degraded when all healthy but some degraded."""
        assert _determine_overall_status(all_healthy=True, has_degraded=True) == "degraded"

    def test_healthy_when_all_healthy_no_degraded(self) -> None:
        """Returns healthy when all healthy and no degraded."""
        assert _determine_overall_status(all_healthy=True, has_degraded=False) == "healthy"


class TestCheckReadinessGate:
    """Tests for _check_readiness_gate function."""

    def test_returns_none_when_gate_is_none(self) -> None:
        """Returns None when no gate is configured."""
        assert _check_readiness_gate(None, "test-service") is None

    def test_returns_503_when_gate_is_failed(self) -> None:
        """Returns 503 with startup_failed reason when gate.is_failed is True."""
        gate = MagicMock()
        gate.is_failed = True
        gate.is_ready = False

        result = _check_readiness_gate(gate, "test-service")
        assert result is not None
        assert result.status_code == 503
        assert result.body == b'{"status":"unhealthy","service":"test-service","reason":"startup_failed"}'

    def test_returns_503_when_gate_not_ready(self) -> None:
        """Returns 503 with models_loading reason when gate.is_ready is False."""
        gate = MagicMock()
        gate.is_failed = False
        gate.is_ready = False

        result = _check_readiness_gate(gate, "test-service")
        assert result is not None
        assert result.status_code == 503
        assert b'"reason":"models_loading"' in result.body

    def test_returns_none_when_gate_is_ready(self) -> None:
        """Returns None when gate is ready (not failed, is_ready=True)."""
        gate = MagicMock()
        gate.is_failed = False
        gate.is_ready = True

        assert _check_readiness_gate(gate, "test-service") is None


class TestBuildStatelessHealthRouter:
    """Tests for build_stateless_health_router function."""

    def test_healthz_returns_ok(self) -> None:
        """Stateless router /healthz returns 200 with status ok."""
        router = build_stateless_health_router("test-service")
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "test-service"

    def test_readyz_returns_ok(self) -> None:
        """Stateless router /readyz returns 200 with status ok."""
        router = build_stateless_health_router("test-service")
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/readyz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "test-service"


class TestBuildProbeHealthRouter:
    """Tests for build_probe_health_router function."""

    def test_healthz_returns_ok(self) -> None:
        """Probe router /healthz returns 200 with status ok."""
        router = build_probe_health_router("test-service", list)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "test-service"

    def test_readyz_healthy_with_no_probes(self) -> None:
        """Readiness probe returns 200/healthy when no probes are registered."""
        router = build_probe_health_router("test-service", list)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/readyz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "test-service"
        assert "timestamp" in data
        assert data["probes"] == []

    def test_readyz_healthy_with_passing_probe(self) -> None:
        """Readiness probe returns 200 when all probes pass."""

        class HealthyProbe:
            name = "db"

            async def check(self) -> HealthProbeResult:
                await asyncio.sleep(0)
                return HealthProbeResult(
                    name="db",
                    status=HealthStatus.HEALTHY,
                    message="connected",
                    latency_ms=1.0,
                )

        router = build_probe_health_router("test-service", lambda: [HealthyProbe()])
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/readyz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert len(data["probes"]) == 1
        assert data["probes"][0]["name"] == "db"

    def test_readyz_redacts_probe_details_while_debug_health_retains_them(self) -> None:
        """Readiness exposes dependency state, while details require the opt-in debug route."""

        class FailingProbe:
            name = "kafka"

            async def check(self) -> HealthProbeResult:
                await asyncio.sleep(0)
                return HealthProbeResult(
                    name="kafka",
                    status=HealthStatus.UNHEALTHY,
                    message="broker-password=super-secret",
                    latency_ms=5000.0,
                )

        router = build_probe_health_router(
            "test-service",
            lambda: [FailingProbe()],
            include_debug_endpoint=True,
        )
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        readiness_response = client.get("/readyz")
        debug_response = client.get("/health")

        assert readiness_response.status_code == 503
        assert readiness_response.json()["probes"] == [{"name": "kafka", "status": "unhealthy", "healthy": False}]
        assert "super-secret" not in readiness_response.text
        assert debug_response.status_code == 503
        assert debug_response.json()["probes"][0]["message"] == "broker-password=super-secret"

    def test_readyz_returns_200_when_degraded(self) -> None:
        """Readiness probe returns 200 with degraded status."""

        class DegradedProbe:
            name = "cache"

            async def check(self) -> HealthProbeResult:
                await asyncio.sleep(0)
                return HealthProbeResult(
                    name="cache",
                    status=HealthStatus.DEGRADED,
                    message="slow responses",
                    latency_ms=500.0,
                )

        router = build_probe_health_router("test-service", lambda: [DegradedProbe()])
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/readyz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"

    def test_no_debug_endpoint_by_default(self) -> None:
        """Debug /health endpoint is not included by default."""
        router = build_probe_health_router("test-service", list)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 404

    def test_includes_debug_endpoint_when_enabled(self) -> None:
        """Debug /health endpoint is included when include_debug_endpoint=True."""
        router = build_probe_health_router("test-service", list, include_debug_endpoint=True)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 200

    def test_readiness_gate_blocks_when_not_ready(self) -> None:
        """Readiness gate returns 503 before probes are executed."""
        gate = MagicMock()
        gate.is_failed = False
        gate.is_ready = False

        router = build_probe_health_router("test-service", list, readiness_gate=gate)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/readyz")
        assert response.status_code == 503
        data = response.json()
        assert data["reason"] == "models_loading"

    def test_readiness_gate_blocks_when_failed(self) -> None:
        """Readiness gate returns 503 with startup_failed when gate has failed."""
        gate = MagicMock()
        gate.is_failed = True
        gate.is_ready = False

        router = build_probe_health_router("test-service", list, readiness_gate=gate)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/readyz")
        assert response.status_code == 503
        data = response.json()
        assert data["reason"] == "startup_failed"

    def test_readiness_gate_allows_when_ready(self) -> None:
        """Readiness gate allows probe execution when gate is ready."""
        gate = MagicMock()
        gate.is_failed = False
        gate.is_ready = True

        router = build_probe_health_router("test-service", list, readiness_gate=gate)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_multiple_probes_mixed_results(self) -> None:
        """Readiness returns unhealthy when any probe in a mixed set fails."""

        class HealthyProbe:
            name = "db"

            async def check(self) -> HealthProbeResult:
                await asyncio.sleep(0)
                return HealthProbeResult(
                    name="db",
                    status=HealthStatus.HEALTHY,
                    message="ok",
                    latency_ms=1.0,
                )

        class FailingProbe:
            name = "kafka"

            async def check(self) -> HealthProbeResult:
                await asyncio.sleep(0)
                return HealthProbeResult(
                    name="kafka",
                    status=HealthStatus.UNHEALTHY,
                    message="down",
                    latency_ms=1.0,
                )

        router = build_probe_health_router(
            "test-service",
            lambda: [HealthyProbe(), FailingProbe()],
        )
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/readyz")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert len(data["probes"]) == 2
