"""Tests for Prometheus metrics endpoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from nohiki_observability import build_metrics_router


class TestBuildMetricsRouter:
    """Tests for build_metrics_router function."""

    def test_router_has_metrics_endpoint(self) -> None:
        """Router should have /metrics endpoint."""
        router = build_metrics_router()
        routes = [route.path for route in router.routes if isinstance(route, APIRoute)]
        assert "/metrics" in routes

    def test_metrics_endpoint_returns_200(self) -> None:
        """Metrics endpoint should return HTTP 200."""
        app = FastAPI()
        app.include_router(build_metrics_router())
        client = TestClient(app)

        response = client.get("/metrics")

        assert response.status_code == 200

    def test_metrics_endpoint_returns_prometheus_format(self) -> None:
        """Metrics endpoint should return Prometheus format content type."""
        app = FastAPI()
        app.include_router(build_metrics_router())
        client = TestClient(app)

        response = client.get("/metrics")

        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]

    def test_metrics_endpoint_contains_prometheus_metrics(self) -> None:
        """Metrics endpoint should contain Prometheus metrics data."""
        app = FastAPI()
        app.include_router(build_metrics_router())
        client = TestClient(app)

        response = client.get("/metrics")

        assert response.status_code == 200
        content = response.text
        assert "python_" in content or "process_" in content or "# HELP" in content

    def test_metrics_endpoint_not_in_openapi_schema(self) -> None:
        """Metrics endpoint should not appear in OpenAPI schema."""
        app = FastAPI()
        app.include_router(build_metrics_router())
        client = TestClient(app)

        response = client.get("/openapi.json")
        schema = response.json()

        assert "/metrics" not in schema.get("paths", {})

    def test_router_has_observability_tag(self) -> None:
        """Router should have observability tag."""
        router = build_metrics_router()
        assert router.tags == ["observability"]

    def test_multiple_router_instances_work(self) -> None:
        """Multiple router instances should work independently."""
        router1 = build_metrics_router()
        router2 = build_metrics_router()

        assert router1 is not router2

        app = FastAPI()
        app.include_router(router1)
        client = TestClient(app)

        response = client.get("/metrics")
        assert response.status_code == 200


class TestExports:
    """Tests for module exports."""

    def test_build_metrics_router_exported(self) -> None:
        """build_metrics_router should be exported from package."""
        from nohiki_observability import build_metrics_router as imported_func

        assert callable(imported_func)

    def test_observability_class_exported(self) -> None:
        """Observability class should still be exported."""
        from nohiki_observability import Observability

        assert Observability is not None

    def test_get_logger_exported(self) -> None:
        """get_logger should still be exported."""
        from nohiki_observability import get_logger

        assert callable(get_logger)

    def test_correlation_functions_exported(self) -> None:
        """Correlation functions should still be exported."""
        from nohiki_observability import (
            CorrelationIdMiddleware,
            get_correlation_id,
            set_correlation_id,
        )

        assert CorrelationIdMiddleware is not None
        assert callable(get_correlation_id)
        assert callable(set_correlation_id)

    def test_otel_health_probe_exported(self) -> None:
        """OTelHealthProbe should still be exported."""
        from nohiki_observability import OTelHealthProbe

        assert OTelHealthProbe is not None

    def test_all_exports_in_dunder_all(self) -> None:
        """All exported items should be in __all__."""
        import nohiki_observability

        expected_exports = [
            "CORRELATION_ID_HEADER",
            "CorrelationIdMiddleware",
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

        for export in expected_exports:
            assert export in nohiki_observability.__all__, f"{export} should be in __all__"


class TestIntegration:
    """Integration tests for prometheus module with FastAPI."""

    def test_metrics_router_with_other_routes(self) -> None:
        """Metrics router should work alongside other routes."""
        app = FastAPI()
        app.include_router(build_metrics_router())

        @app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app)

        health_response = client.get("/health")
        assert health_response.status_code == 200
        assert health_response.json() == {"status": "ok"}

        metrics_response = client.get("/metrics")
        assert metrics_response.status_code == 200
        assert "text/plain" in metrics_response.headers["content-type"]

    def test_metrics_content_is_valid_prometheus_format(self) -> None:
        """Metrics content should be valid Prometheus exposition format."""
        app = FastAPI()
        app.include_router(build_metrics_router())
        client = TestClient(app)

        response = client.get("/metrics")
        content = response.text

        lines = content.strip().split("\n")
        for line in lines:
            if line.startswith("#"):
                assert line.startswith(("# HELP", "# TYPE")), f"Comment line should be HELP or TYPE: {line}"
