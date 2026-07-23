"""Tests for observability health probe."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from nohiki_observability.health import OTelHealthProbe


class TestOTelHealthProbeInit:
    """Tests for OTelHealthProbe initialization."""

    def test_init_with_endpoint(self) -> None:
        """Probe stores endpoint and timeout."""
        probe = OTelHealthProbe("http://collector:4317", timeout_seconds=5.0)
        assert probe._otel_endpoint == "http://collector:4317"
        assert abs(probe._timeout_seconds - 5.0) < 1e-9

    def test_init_with_none_endpoint(self) -> None:
        """Probe accepts None endpoint (disabled mode)."""
        probe = OTelHealthProbe(None)
        assert probe._otel_endpoint is None
        assert abs(probe._timeout_seconds - 2.0) < 1e-9

    def test_name_property(self) -> None:
        """Probe name is correct."""
        probe = OTelHealthProbe("http://collector:4317")
        assert probe.name == "otel_collector"


class TestOTelHealthProbeCheck:
    """Tests for OTelHealthProbe.check method."""

    @pytest.mark.asyncio
    async def test_check_disabled_returns_healthy(self) -> None:
        """Returns healthy when endpoint not configured."""
        probe = OTelHealthProbe(None)
        result = await probe.check()

        assert result.status.value == "healthy"
        assert "not configured" in result.message
        assert result.details["configured"] is False

    @pytest.mark.asyncio
    async def test_check_success_returns_healthy(self) -> None:
        """Returns healthy when collector is reachable."""
        probe = OTelHealthProbe("http://collector:4317")

        mock_writer = AsyncMock()
        mock_writer.close = lambda: None
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(AsyncMock(), mock_writer)):
            result = await probe.check()

        assert result.status.value == "healthy"
        assert "reachable" in result.message
        assert result.details["endpoint"] == "http://collector:4317"

    @pytest.mark.asyncio
    async def test_check_timeout_returns_degraded(self) -> None:
        """Returns degraded on connection timeout."""
        probe = OTelHealthProbe("http://collector:4317", timeout_seconds=0.1)

        with patch("asyncio.open_connection", side_effect=TimeoutError):
            result = await probe.check()

        assert result.status.value == "degraded"
        assert "timeout" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_connection_refused_returns_degraded(self) -> None:
        """Returns degraded on connection refused."""
        probe = OTelHealthProbe("http://collector:4317")

        with patch(
            "asyncio.open_connection",
            side_effect=ConnectionRefusedError("Connection refused"),
        ):
            result = await probe.check()

        assert result.status.value == "degraded"
        assert "unreachable" in result.message.lower()
        assert result.details["error_type"] == "ConnectionRefusedError"

    @pytest.mark.asyncio
    async def test_check_generic_exception_returns_degraded(self) -> None:
        """Returns degraded on generic exception."""
        probe = OTelHealthProbe("http://collector:4317")

        with patch("asyncio.open_connection", side_effect=OSError("Network error")):
            result = await probe.check()

        assert result.status.value == "degraded"
        assert "unreachable" in result.message.lower()
        assert "Network error" in str(result.details["error"])

    @pytest.mark.asyncio
    async def test_check_value_error_returns_degraded(self) -> None:
        """Returns degraded on invalid endpoint configuration."""
        probe = OTelHealthProbe("http://collector:4317")

        with patch.object(OTelHealthProbe, "_parse_endpoint", side_effect=ValueError("bad port")):
            result = await probe.check()

        assert result.status.value == "degraded"
        assert "Invalid OTEL endpoint" in result.message
        assert result.details["error_type"] == "ValueError"


class TestOTelHealthProbeParseEndpoint:
    """Tests for _parse_endpoint method."""

    def test_parse_http_endpoint_with_port(self) -> None:
        """Parses http endpoint with port."""
        probe = OTelHealthProbe("http://collector:4317")
        host, port = probe._parse_endpoint()
        assert host == "collector"
        assert port == 4317

    def test_parse_https_endpoint_with_port(self) -> None:
        """Parses https endpoint with port."""
        probe = OTelHealthProbe("https://otel.example.com:443")
        host, port = probe._parse_endpoint()
        assert host == "otel.example.com"
        assert port == 443

    def test_parse_endpoint_without_port(self) -> None:
        """Uses default port 4317 when not specified."""
        probe = OTelHealthProbe("http://collector")
        host, port = probe._parse_endpoint()
        assert host == "collector"
        assert port == 4317

    def test_parse_plain_host_with_port(self) -> None:
        """Parses plain host:port without scheme."""
        probe = OTelHealthProbe("localhost:9090")
        host, port = probe._parse_endpoint()
        assert host == "localhost"
        assert port == 9090

    def test_parse_empty_endpoint(self) -> None:
        """Handles empty endpoint gracefully."""
        probe = OTelHealthProbe(None)
        host, port = probe._parse_endpoint()
        assert host == ""
        assert port == 4317
