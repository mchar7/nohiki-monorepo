import os

# Set testing environment BEFORE any imports that might trigger Settings loading
os.environ["TESTING"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["BFF_DATABASE__DSN"] = "postgresql://test:test@localhost:5432/test"
os.environ["BFF_DATABASE__SCHEMA_NAME"] = "bff_schema"
os.environ["BFF_KAFKA__DSN"] = "kafka://localhost:29092"
os.environ["BFF_REDIS__DSN"] = "redis://localhost:6379/0"
os.environ["BFF_S3__ENDPOINT"] = "http://localhost:9000"
os.environ["BFF_S3__ACCESS_KEY"] = "test"
os.environ["BFF_S3__SECRET_KEY"] = "test"
os.environ["BFF_S3__BUCKET"] = "test"

import logging
import sys
from collections.abc import Generator
from types import ModuleType
from typing import Self

import pytest


class _CorrelationIdMiddleware:
    """Stub for CorrelationIdMiddleware."""

    def __init__(self, app: object, header_name: str = "X-Correlation-ID") -> None:
        """Initialize middleware stub."""
        self.app = app
        self.header_name = header_name


class _StubLogger:
    """Structured-logger stub that accepts **kwargs without raising."""

    def __init__(self, name: str) -> None:
        """Initialize with underlying stdlib logger."""
        self._logger = logging.getLogger(name)

    def debug(self, msg: str, **_kwargs: object) -> None:
        """Log debug message, discarding structured fields."""
        self._logger.debug(msg)

    def info(self, msg: str, **_kwargs: object) -> None:
        """Log info message, discarding structured fields."""
        self._logger.info(msg)

    def warning(self, msg: str, **_kwargs: object) -> None:
        """Log warning message, discarding structured fields."""
        self._logger.warning(msg)

    def error(self, msg: str, **_kwargs: object) -> None:
        """Log error message, discarding structured fields."""
        self._logger.error(msg)

    def exception(self, msg: str, **_kwargs: object) -> None:
        """Log exception with traceback, discarding structured fields."""
        self._logger.exception(msg)

    def critical(self, msg: str, **_kwargs: object) -> None:
        """Log critical message, discarding structured fields."""
        self._logger.critical(msg)

    def bind(self, **_kwargs: object) -> _StubLogger:
        """Return self; context binding is a no-op in tests."""
        return self


def _get_stub_logger(name: str) -> _StubLogger:
    """Return a _StubLogger for the given module name."""
    return _StubLogger(name)


class _ObservabilityStub:
    """Stub for nohiki_observability in tests."""

    @classmethod
    def from_settings(cls, _settings: object) -> Self:
        """Create stub from settings."""
        return cls()

    def init(self) -> None:
        """Initialize stub (no-op)."""

    def get_logger(self, name: str) -> _StubLogger:
        """Return structured-logger stub."""
        return _StubLogger(name)

    def init_fastapi(self, _app: object) -> None:
        """Initialize FastAPI stub (no-op)."""

    def shutdown(self) -> None:
        """Shutdown stub (no-op)."""


def _build_metrics_router() -> object:
    """Stub for build_metrics_router."""
    from fastapi import APIRouter

    return APIRouter()


def _get_correlation_id() -> str:
    """Stub for get_correlation_id function."""
    return "test-correlation-id"


def _set_correlation_id(_value: str) -> None:
    """Stub for set_correlation_id function."""


class _ObservabilityModule(ModuleType):
    """Module stub for nohiki_observability."""

    get_logger = staticmethod(_get_stub_logger)
    observability_class = _ObservabilityStub

    CORRELATION_ID_HEADER = "X-Correlation-ID"
    TRACE_ID_HEADER = "X-Trace-ID"
    Observability = _ObservabilityStub  # NOSONAR  # must match name in library
    CorrelationIdMiddleware = _CorrelationIdMiddleware  # NOSONAR  # must match name in library
    build_metrics_router = staticmethod(_build_metrics_router)
    get_correlation_id = staticmethod(_get_correlation_id)
    set_correlation_id = staticmethod(_set_correlation_id)


_OBSERVABILITY_MODULE = _ObservabilityModule("nohiki_observability")


@pytest.fixture(autouse=True)
def _reset_global_test_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Restore the observability module and settings cache after each test."""
    monkeypatch.setitem(sys.modules, "nohiki_observability", _OBSERVABILITY_MODULE)

    from bff_service.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
