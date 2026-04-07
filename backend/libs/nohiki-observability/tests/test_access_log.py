"""Tests for HTTP access log middleware."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from nohiki_observability.access_log import _SILENT_PATHS, HTTPAccessLogMiddleware


@pytest.fixture
def app() -> FastAPI:
    """Create a test FastAPI app with access log middleware."""
    app = FastAPI()
    app.add_middleware(HTTPAccessLogMiddleware)

    @app.get("/api/test")
    async def test_endpoint() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "healthy"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        return {"status": "ready"}

    @app.get("/metrics")
    async def metrics_endpoint() -> str:
        return "metrics"

    return app


class TestHTTPAccessLogMiddleware:
    """Tests for HTTPAccessLogMiddleware."""

    @pytest.mark.asyncio
    async def test_logs_request_details(self, app: FastAPI) -> None:
        """Test middleware logs method, path, status_code, and duration_ms."""
        with patch("nohiki_observability.access_log.logger") as mock_logger:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/test")

            assert response.status_code == 200
            mock_logger.info.assert_called_once()
            call_kwargs = mock_logger.info.call_args
            assert call_kwargs[0][0] == "HTTP request"
            assert call_kwargs[1]["method"] == "GET"
            assert call_kwargs[1]["path"] == "/api/test"
            assert call_kwargs[1]["status_code"] == 200
            assert isinstance(call_kwargs[1]["duration_ms"], (float, int))
            assert call_kwargs[1]["duration_ms"] >= 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", sorted(_SILENT_PATHS))
    async def test_excludes_silent_paths(self, app: FastAPI, path: str) -> None:
        """Test middleware does not log health/metrics endpoints."""
        with patch("nohiki_observability.access_log.logger") as mock_logger:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                await client.get(path)

            mock_logger.info.assert_not_called()

    @pytest.mark.asyncio
    async def test_duration_is_non_negative(self, app: FastAPI) -> None:
        """Test duration_ms is a non-negative number."""
        with patch("nohiki_observability.access_log.logger") as mock_logger:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                await client.get("/api/test")

            duration = mock_logger.info.call_args[1]["duration_ms"]
            assert duration >= 0

    @pytest.mark.asyncio
    async def test_logs_post_method(self, app: FastAPI) -> None:
        """Test middleware correctly logs POST requests."""

        @app.post("/api/submit")
        async def submit() -> dict[str, str]:
            return {"submitted": "true"}

        with patch("nohiki_observability.access_log.logger") as mock_logger:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                await client.post("/api/submit")

            assert mock_logger.info.call_args[1]["method"] == "POST"

    @pytest.mark.asyncio
    async def test_logs_different_status_codes(self, app: FastAPI) -> None:
        """Test middleware logs non-200 status codes."""

        @app.get("/api/not-found")
        async def not_found() -> dict[str, str]:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Not found")

        with patch("nohiki_observability.access_log.logger") as mock_logger:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/not-found")

            assert response.status_code == 404
            mock_logger.info.assert_called_once()
            assert mock_logger.info.call_args[1]["status_code"] == 404

    @pytest.mark.asyncio
    async def test_logs_and_propagates_unhandled_exceptions(self, app: FastAPI) -> None:
        """Unhandled failures emit a metadata-only 500 access log and still propagate."""
        error_message = "database password leaked"

        @app.get("/api/failure")
        async def failure() -> None:
            raise RuntimeError(error_message)

        with patch("nohiki_observability.access_log.logger") as mock_logger:
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                with pytest.raises(RuntimeError, match=error_message):
                    await client.get("/api/failure")

        mock_logger.info.assert_not_called()
        mock_logger.error.assert_called_once()
        call_args, call_kwargs = mock_logger.error.call_args
        assert call_args == ("HTTP request",)
        assert call_kwargs.keys() == {"method", "path", "status_code", "duration_ms"}
        assert call_kwargs["method"] == "GET"
        assert call_kwargs["path"] == "/api/failure"
        assert call_kwargs["status_code"] == 500
        assert call_kwargs["duration_ms"] >= 0
