"""Tests for nohiki-fastapi-utils package initialization."""

from __future__ import annotations

from nohiki_fastapi_utils import (
    CORRELATION_ID_HEADER,
    CorrelationIdMiddleware,
    CSRFMiddleware,
    ReadinessGateProtocol,
    build_probe_health_router,
    build_root_router,
    build_stateless_health_router,
    get_correlation_id,
    set_correlation_id,
    setup_error_handlers,
    validate_csrf,
)


class TestPackageExports:
    """Tests for package exports."""

    def test_correlation_id_header_exported(self) -> None:
        """Test CORRELATION_ID_HEADER is exported."""
        assert CORRELATION_ID_HEADER is not None
        assert isinstance(CORRELATION_ID_HEADER, str)

    def test_csrf_middleware_exported(self) -> None:
        """Test CSRFMiddleware is exported."""
        assert CSRFMiddleware is not None

    def test_correlation_id_middleware_exported(self) -> None:
        """Test CorrelationIdMiddleware is exported."""
        assert CorrelationIdMiddleware is not None

    def test_readiness_gate_protocol_exported(self) -> None:
        """Test ReadinessGateProtocol is exported."""
        assert ReadinessGateProtocol is not None

    def test_build_probe_health_router_exported(self) -> None:
        """Test build_probe_health_router is exported."""
        assert build_probe_health_router is not None
        assert callable(build_probe_health_router)

    def test_build_root_router_exported(self) -> None:
        """Test build_root_router is exported."""
        assert build_root_router is not None
        assert callable(build_root_router)

    def test_build_stateless_health_router_exported(self) -> None:
        """Test build_stateless_health_router is exported."""
        assert build_stateless_health_router is not None
        assert callable(build_stateless_health_router)

    def test_get_correlation_id_exported(self) -> None:
        """Test get_correlation_id is exported."""
        assert get_correlation_id is not None
        assert callable(get_correlation_id)

    def test_set_correlation_id_exported(self) -> None:
        """Test set_correlation_id is exported."""
        assert set_correlation_id is not None
        assert callable(set_correlation_id)

    def test_setup_error_handlers_exported(self) -> None:
        """Test setup_error_handlers is exported."""
        assert setup_error_handlers is not None
        assert callable(setup_error_handlers)

    def test_validate_csrf_exported(self) -> None:
        """Test validate_csrf is exported."""
        assert validate_csrf is not None
        assert callable(validate_csrf)
