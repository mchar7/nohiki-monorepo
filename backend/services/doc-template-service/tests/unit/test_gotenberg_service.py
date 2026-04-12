"""Tests for Gotenberg service integration."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from doc_template_service.services.gotenberg import (
    GotenbergError,
    GotenbergService,
    ScreenshotOptions,
    get_gotenberg_service,
)


class TestGotenbergService:
    """Tests for GotenbergService class."""

    def test_init_with_defaults(self) -> None:
        """Test initialization with default values."""
        service = GotenbergService()
        assert service.base_url.endswith("/") is False
        assert service.convert_endpoint.endswith("/forms/chromium/convert/html")
        assert service.screenshot_endpoint.endswith("/forms/chromium/screenshot/html")

    def test_init_with_custom_values(self) -> None:
        """Test initialization with custom values."""
        service = GotenbergService(base_url="http://custom:3000/", timeout=30)
        assert service.base_url == "http://custom:3000"
        assert service.timeout == 30

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "html",
        [
            '<html><head><meta http-equiv="refresh" content="0; url=https://example.com"></head></html>',
            "<html><head><META HTTP-EQUIV='ReFrEsH' CONTENT='0;URL=http://example.com'></head></html>",
            "<html><head><meta   content = '0; url=file:///etc/passwd'   http-equiv = refresh ></head></html>",
            '<html><head><meta http-equiv = " refresh " content = "0; url=data:text/html,test"></head></html>',
            "<html><head><meta http-equiv='REFRESH' content='0; javascript:alert(1)'></head></html>",
        ],
    )
    @pytest.mark.parametrize("renderer", ["pdf", "screenshot"])
    async def test_meta_refresh_is_rejected_before_renderer(self, html: str, renderer: str) -> None:
        """Meta refresh must never reach Chromium, regardless of spelling or target scheme."""
        service = GotenbergService()

        render = (
            service.convert_html_to_pdf(html)
            if renderer == "pdf"
            else service.screenshot_html(html, ScreenshotOptions(image_format="png"))
        )
        with (
            patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client,
            pytest.raises(GotenbergError, match=r"(?i)meta refresh"),
        ):
            await render

        mock_client.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "metadata",
        [
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
        ],
    )
    async def test_non_navigating_metadata_reaches_renderer(self, metadata: str) -> None:
        """Ordinary document metadata must remain valid."""
        service = GotenbergService()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.content = b"%PDF-1.4 mock content"
        mock_response.raise_for_status.return_value = None

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await service.convert_html_to_pdf(f"<html><head>{metadata}</head><body>Test</body></html>")

        assert result == b"%PDF-1.4 mock content"
        mock_post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_convert_html_to_pdf_success(self) -> None:
        """Test successful HTML to PDF conversion."""
        service = GotenbergService()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.content = b"%PDF-1.4 mock content"
        mock_response.raise_for_status.return_value = None

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            result = await service.convert_html_to_pdf("<html><body>Test</body></html>")

            assert result == b"%PDF-1.4 mock content"

    @pytest.mark.asyncio
    async def test_convert_html_to_pdf_http_error(self) -> None:
        """Test HTML to PDF conversion with HTTP error."""
        service = GotenbergService()
        request = httpx.Request("POST", "http://testserver/forms/chromium/convert/html")
        response = httpx.Response(status_code=500, request=request, text="Internal Server Error")
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError("Error", request=request, response=response)
        mock_response.text = "Internal Server Error"

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            with pytest.raises(GotenbergError, match="Gotenberg returned status 500"):
                await service.convert_html_to_pdf("<html><body>Test</body></html>")

    @pytest.mark.asyncio
    async def test_convert_html_to_pdf_timeout(self) -> None:
        """Test HTML to PDF conversion with timeout."""
        service = GotenbergService(timeout=1)

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.TimeoutException("Timeout")
            )

            with pytest.raises(GotenbergError, match="timed out"):
                await service.convert_html_to_pdf("<html><body>Test</body></html>")

    @pytest.mark.asyncio
    async def test_convert_html_to_pdf_request_error(self) -> None:
        """Test HTML to PDF conversion with request error."""
        service = GotenbergService()

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.RequestError("Connection failed")
            )

            with pytest.raises(GotenbergError, match="Failed to connect to Gotenberg"):
                await service.convert_html_to_pdf("<html><body>Test</body></html>")

    @pytest.mark.asyncio
    async def test_convert_html_to_pdf_with_page_size(self) -> None:
        """Test HTML to PDF conversion with a custom page size."""
        service = GotenbergService()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.content = b"%PDF-1.4 mock content"
        mock_response.raise_for_status.return_value = None

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await service.convert_html_to_pdf(
                "<html><body>Test</body></html>",
                page_size="A4",
            )
            assert result == b"%PDF-1.4 mock content"

            call_kwargs = mock_post.call_args.kwargs
            assert "files" in call_kwargs
            assert "paperWidth" in call_kwargs["files"]
            assert "paperHeight" in call_kwargs["files"]

    @pytest.mark.asyncio
    async def test_screenshot_html_success(self) -> None:
        """Test successful HTML to screenshot conversion."""
        service = GotenbergService()
        options = ScreenshotOptions(image_format="png", width=800, height=600)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.content = b"\x89PNG mock content"
        mock_response.raise_for_status.return_value = None

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            result = await service.screenshot_html("<html><body>Test</body></html>", options)

            assert result == b"\x89PNG mock content"

    @pytest.mark.asyncio
    async def test_screenshot_html_jpeg_with_quality(self) -> None:
        """Test screenshot with JPEG format includes quality parameter."""
        service = GotenbergService()
        options = ScreenshotOptions(image_format="jpeg", width=800, height=600, quality=85)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.content = b"\xff\xd8\xff mock jpeg"
        mock_response.raise_for_status.return_value = None

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await service.screenshot_html("<html><body>Test</body></html>", options)

            # Verify quality was included in data
            call_kwargs = mock_post.call_args.kwargs
            assert "files" in call_kwargs
            assert "quality" in call_kwargs["files"]
            assert call_kwargs["files"]["quality"] == (None, "85", "text/plain")

    @pytest.mark.asyncio
    async def test_screenshot_html_http_error(self) -> None:
        """Test screenshot with HTTP error."""
        service = GotenbergService()
        options = ScreenshotOptions(image_format="png")
        request = httpx.Request("POST", "http://testserver/forms/chromium/screenshot/html")
        response = httpx.Response(status_code=500, request=request, text="Internal Server Error")
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError("Error", request=request, response=response)

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            with pytest.raises(GotenbergError, match="Gotenberg returned status 500"):
                await service.screenshot_html("<html><body>Test</body></html>", options)

    @pytest.mark.asyncio
    async def test_screenshot_html_timeout(self) -> None:
        """Test screenshot with timeout."""
        service = GotenbergService(timeout=1)
        options = ScreenshotOptions(image_format="png")

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.TimeoutException("Timeout")
            )

            with pytest.raises(GotenbergError, match="timed out"):
                await service.screenshot_html("<html><body>Test</body></html>", options)

    @pytest.mark.asyncio
    async def test_screenshot_html_request_error(self) -> None:
        """Test screenshot with request error."""
        service = GotenbergService()
        options = ScreenshotOptions(image_format="png")

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.RequestError("Connection failed")
            )

            with pytest.raises(GotenbergError, match="Failed to connect to Gotenberg"):
                await service.screenshot_html("<html><body>Test</body></html>", options)

    @pytest.mark.asyncio
    async def test_convert_html_to_pdf_stream_success(self) -> None:
        """Test successful HTML to PDF streaming."""
        service = GotenbergService()

        async def aiter_bytes(*, chunk_size: int = 8192) -> AsyncIterator[bytes]:
            _ = chunk_size
            yield b"one"
            yield b"two"

        stream_response = MagicMock(spec=httpx.Response)
        stream_response.raise_for_status = MagicMock()
        stream_response.aiter_bytes = aiter_bytes

        @asynccontextmanager
        async def mock_stream(*_args: object, **_kwargs: object) -> AsyncIterator[httpx.Response]:
            yield stream_response

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.stream = mock_stream
            mock_client.return_value.__aenter__.return_value = mock_instance

            stream_iter = service.convert_html_to_pdf_stream("<html></html>")
            chunk1 = await anext(stream_iter)
            chunk2 = await anext(stream_iter)
            with pytest.raises(StopAsyncIteration):
                await anext(stream_iter)

            assert [chunk1, chunk2] == [b"one", b"two"]

    @pytest.mark.asyncio
    async def test_screenshot_html_stream_success(self) -> None:
        """Test successful HTML screenshot streaming."""
        service = GotenbergService()

        async def aiter_bytes(*, chunk_size: int = 8192) -> AsyncIterator[bytes]:
            _ = chunk_size
            yield b"img1"
            yield b"img2"

        stream_response = MagicMock(spec=httpx.Response)
        stream_response.raise_for_status = MagicMock()
        stream_response.aiter_bytes = aiter_bytes

        @asynccontextmanager
        async def mock_stream(*_args: object, **_kwargs: object) -> AsyncIterator[httpx.Response]:
            yield stream_response

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.stream = mock_stream
            mock_client.return_value.__aenter__.return_value = mock_instance

            options = ScreenshotOptions(image_format="png")
            stream_iter = service.screenshot_html_stream("<html></html>", options)
            chunk1 = await anext(stream_iter)
            chunk2 = await anext(stream_iter)
            with pytest.raises(StopAsyncIteration):
                await anext(stream_iter)

            assert [chunk1, chunk2] == [b"img1", b"img2"]

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        """Test successful health check."""
        service = GotenbergService()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

            result = await service.health_check()

            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self) -> None:
        """Test health check failure."""
        service = GotenbergService()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 503

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

            result = await service.health_check()

            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_exception(self) -> None:
        """Test health check with exception returns False."""
        service = GotenbergService()

        with patch("doc_template_service.services.gotenberg.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.RequestError("Connection failed")
            )

            result = await service.health_check()

            assert result is False


class TestGotenbergError:
    """Tests for GotenbergError exception."""

    def test_error_with_message_only(self) -> None:
        """Test error with message only."""
        error = GotenbergError("Test error")
        assert error.message == "Test error"
        assert error.status_code is None
        assert error.response_text is None
        assert str(error) == "Test error"

    def test_error_with_all_fields(self) -> None:
        """Test error with all fields."""
        error = GotenbergError("Test error", status_code=500, response_text="Server error")
        assert error.message == "Test error"
        assert error.status_code == 500
        assert error.response_text == "Server error"


class TestScreenshotOptions:
    """Tests for ScreenshotOptions named tuple."""

    def test_default_values(self) -> None:
        """Test default values for screenshot options."""
        options = ScreenshotOptions(image_format="png")
        assert options.image_format == "png"
        assert options.width == 800
        assert options.height == 600
        assert options.clip is False
        assert options.quality == 100
        assert options.omit_background is False
        assert options.optimize_for_speed is False

    def test_custom_values(self) -> None:
        """Test custom values for screenshot options."""
        options = ScreenshotOptions(
            image_format="jpeg",
            width=1920,
            height=1080,
            clip=True,
            quality=85,
            omit_background=True,
            optimize_for_speed=True,
        )
        assert options.image_format == "jpeg"
        assert options.width == 1920
        assert options.height == 1080
        assert options.clip is True
        assert options.quality == 85
        assert options.omit_background is True
        assert options.optimize_for_speed is True


class TestGetGotenbergService:
    """Tests for get_gotenberg_service factory function."""

    def test_returns_gotenberg_service(self) -> None:
        """Test that factory returns GotenbergService instance."""
        service = get_gotenberg_service()
        assert isinstance(service, GotenbergService)
