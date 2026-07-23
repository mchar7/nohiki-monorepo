"""Package initialization and lazy import contracts."""

from __future__ import annotations

import importlib
import sys


def test_http_dependencies_are_lazy() -> None:
    """Root import avoids FastAPI until an HTTP-only export is resolved."""
    prefixes = ("fastapi", "nohiki_observability")
    saved = {name: module for name, module in sys.modules.items() if name.startswith(prefixes)}
    try:
        for name in saved:
            sys.modules.pop(name, None)

        observability = importlib.import_module("nohiki_observability")

        assert "fastapi" not in sys.modules
        assert "nohiki_observability.access_log" not in sys.modules
        assert "nohiki_observability.prometheus" not in sys.modules
        assert "nohiki_observability._correlation_middleware" not in sys.modules
        assert "nohiki_observability.observability" not in sys.modules

        access_log_middleware = observability.HTTPAccessLogMiddleware
        correlation_middleware = observability.CorrelationIdMiddleware

        build_metrics_router = observability.build_metrics_router

        assert access_log_middleware.__name__ == "HTTPAccessLogMiddleware"
        assert correlation_middleware.__name__ == "CorrelationIdMiddleware"
        assert callable(build_metrics_router)
        assert "nohiki_observability.access_log" in sys.modules
        assert "nohiki_observability._correlation_middleware" in sys.modules
        assert "nohiki_observability.prometheus" in sys.modules
        assert "fastapi" in sys.modules
    finally:
        for name in list(sys.modules):
            if name.startswith(prefixes):
                del sys.modules[name]
        sys.modules.update(saved)
