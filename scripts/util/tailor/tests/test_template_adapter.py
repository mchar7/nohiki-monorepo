"""Tests for tailor.adapters.template_adapter -- TailorTemplateAdapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tailor.adapters.template_adapter import TailorTemplateAdapter, _is_image_format
from tailor.core.types import JsonDict, RenderOutputFormat
from tailor.exceptions import GotenbergError, RenderError
from tailor.models.outputs import RenderResult

_TEMPLATE_HTML = "<html><body>{{ name }}</body></html>"
_SAMPLE_DATA: JsonDict = {"name": "Alice"}


@pytest.fixture
def mock_tailor_settings(tmp_path: Path) -> MagicMock:
    """Return a plain MagicMock settings object with Gotenberg attributes configured.

    Overrides the conftest fixture to avoid spec=TailorSettings which does not
    expose attributes from LLMMixin and causes AttributeError during setup.
    """
    settings = MagicMock()
    settings.gotenberg_url = "http://localhost:3000"
    settings.gotenberg_timeout_s = 30
    settings.resolved_output_dir = tmp_path
    return settings


@pytest.fixture
def mock_gotenberg(mocker: MagicMock) -> MagicMock:
    """Patch GotenbergService in the template adapter module and return the mock instance."""
    mock_cls = mocker.patch("tailor.adapters.template_adapter.GotenbergService")
    mock_instance = MagicMock()
    mock_instance.health_check = AsyncMock(return_value=True)
    mock_cls.return_value = mock_instance
    return mock_instance


@pytest.fixture
def mock_generate_document(mocker: MagicMock) -> AsyncMock:
    """Patch generate_document in the template adapter module."""
    return mocker.patch(
        "tailor.adapters.template_adapter.generate_document",
        new_callable=AsyncMock,
    )


@pytest.fixture
def adapter(mock_tailor_settings: MagicMock, mock_gotenberg: MagicMock) -> TailorTemplateAdapter:
    """Return a TailorTemplateAdapter with patched GotenbergService."""
    # mock_gotenberg is declared as a dependency so GotenbergService is patched before instantiation
    _ = mock_gotenberg
    return TailorTemplateAdapter(mock_tailor_settings)


class TestIsImageFormat:
    """Tests for the _is_image_format TypeGuard function."""

    @pytest.mark.parametrize("fmt", ["png", "jpeg", "webp"])
    def test_image_formats_return_true(self, fmt: RenderOutputFormat) -> None:
        """Image format strings must return True."""
        assert _is_image_format(fmt) is True

    @pytest.mark.parametrize("fmt", ["pdf", "html", "text"])
    def test_non_image_formats_return_false(self, fmt: RenderOutputFormat) -> None:
        """Non-image format strings must return False."""
        assert _is_image_format(fmt) is False


class TestBuildRenderResult:
    """Tests for TailorTemplateAdapter._build_render_result."""

    @pytest.mark.parametrize(
        ("output_format", "expected_content_type"),
        [
            ("pdf", "application/pdf"),
            ("html", "text/html"),
            ("text", "text/plain"),
            ("png", "image/png"),
            ("webp", "image/webp"),
        ],
    )
    def test_content_type_mapping(
        self,
        adapter: TailorTemplateAdapter,
        output_format: RenderOutputFormat,
        expected_content_type: str,
    ) -> None:
        """Content-type header is correctly derived from the output format."""
        result = adapter._build_render_result("hello", output_format)
        assert result.content_type == expected_content_type

    def test_size_bytes_for_str_content(self, adapter: TailorTemplateAdapter) -> None:
        """size_bytes equals the UTF-8 encoded byte length for string content."""
        content = "caf\u00e9"  # 5 UTF-8 bytes
        result = adapter._build_render_result(content, "html")
        assert result.size_bytes == len(content.encode("utf-8"))

    def test_size_bytes_for_bytes_content(self, adapter: TailorTemplateAdapter) -> None:
        """size_bytes equals len() for bytes content."""
        content = b"\x25\x50\x44\x46\x00"  # 5 bytes
        result = adapter._build_render_result(content, "pdf")
        assert result.size_bytes == 5

    def test_tuple_input_uses_first_element(self, adapter: TailorTemplateAdapter) -> None:
        """When a tuple is passed, the first element is used as content."""
        result = adapter._build_render_result(("primary content", "secondary"), "html")
        assert result.content == "primary content"

    def test_returns_render_result_instance(self, adapter: TailorTemplateAdapter) -> None:
        """_build_render_result must return a RenderResult dataclass."""
        result = adapter._build_render_result("data", "pdf")
        assert isinstance(result, RenderResult)


class TestRender:
    """Tests for TailorTemplateAdapter.render success and error paths."""

    async def test_render_pdf_calls_generate_document_with_pdf_format(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """render('pdf') calls generate_document with output_format='pdf'."""
        mock_generate_document.return_value = b"%PDF"
        result = await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "pdf")
        mock_generate_document.assert_called_once()
        call_kwargs = mock_generate_document.call_args[1]
        assert call_kwargs["output_format"] == "pdf"
        assert result.content_type == "application/pdf"

    async def test_render_html_calls_generate_document_with_html_format(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """render('html') calls generate_document with output_format='html'."""
        mock_generate_document.return_value = "<html>rendered</html>"
        result = await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "html")
        call_kwargs = mock_generate_document.call_args[1]
        assert call_kwargs["output_format"] == "html"
        assert result.content_type == "text/html"

    async def test_render_text_calls_generate_document_with_text_format(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """render('text') calls generate_document with output_format='text'."""
        mock_generate_document.return_value = "plain text"
        result = await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "text")
        call_kwargs = mock_generate_document.call_args[1]
        assert call_kwargs["output_format"] == "text"
        assert result.content_type == "text/plain"

    async def test_render_png_calls_generate_document_with_image_format(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """render('png') calls generate_document with output_format='image' and ImageOptions(format='png')."""
        from doc_template_service.schemas.models import ImageOptions

        mock_generate_document.return_value = b"\x89PNG"
        await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "png")
        call_kwargs = mock_generate_document.call_args[1]
        assert call_kwargs["output_format"] == "image"
        assert call_kwargs["image_options"] == ImageOptions(format="png")

    async def test_render_jpeg_calls_generate_document_with_image_format(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """render('jpeg') calls generate_document with output_format='image' and ImageOptions(format='jpeg')."""
        from doc_template_service.schemas.models import ImageOptions

        mock_generate_document.return_value = b"\xff\xd8"
        await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "jpeg")
        call_kwargs = mock_generate_document.call_args[1]
        assert call_kwargs["output_format"] == "image"
        assert call_kwargs["image_options"] == ImageOptions(format="jpeg")

    async def test_render_webp_calls_generate_document_with_image_format(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """render('webp') calls generate_document with output_format='image' and ImageOptions(format='webp')."""
        from doc_template_service.schemas.models import ImageOptions

        mock_generate_document.return_value = b"RIFF"
        await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "webp")
        call_kwargs = mock_generate_document.call_args[1]
        assert call_kwargs["output_format"] == "image"
        assert call_kwargs["image_options"] == ImageOptions(format="webp")

    async def test_oserror_with_connection_raises_gotenberg_error(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """OSError with 'connection' in message raises GotenbergError."""
        mock_generate_document.side_effect = OSError("connection refused")
        with pytest.raises(GotenbergError):
            await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "pdf")

    async def test_oserror_with_gotenberg_raises_gotenberg_error(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """OSError with 'gotenberg' in message raises GotenbergError."""
        mock_generate_document.side_effect = OSError("gotenberg service unavailable")
        with pytest.raises(GotenbergError):
            await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "pdf")

    async def test_oserror_with_generic_message_raises_render_error(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """OSError with a generic message raises RenderError."""
        mock_generate_document.side_effect = OSError("disk full")
        with pytest.raises(RenderError):
            await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "pdf")

    async def test_value_error_raises_render_error(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """ValueError raises RenderError."""
        mock_generate_document.side_effect = ValueError("invalid template variable")
        with pytest.raises(RenderError):
            await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "pdf")

    async def test_render_error_output_format_attribute(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """RenderError.output_format is set to the requested format."""
        mock_generate_document.side_effect = ValueError("boom")
        with pytest.raises(RenderError) as exc_info:
            await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "html")
        assert exc_info.value.output_format == "html"

    async def test_doc_template_generation_error_raises_render_error(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """doc-template-service GenerationError is caught and re-raised as RenderError."""
        from doc_template_service.core.generator import GenerationError as DocGenError

        mock_generate_document.side_effect = DocGenError("template validation failed")
        with pytest.raises(RenderError):
            await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "pdf")

    async def test_render_passes_use_cache_false(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """Render always passes use_cache=False to avoid Redis dependency."""
        mock_generate_document.return_value = b"%PDF"
        await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "pdf")
        call_kwargs = mock_generate_document.call_args[1]
        assert call_kwargs["use_cache"] is False

    async def test_render_image_passes_use_cache_false(
        self, adapter: TailorTemplateAdapter, mock_generate_document: AsyncMock
    ) -> None:
        """Render for image formats also passes use_cache=False."""
        mock_generate_document.return_value = b"\x89PNG"
        await adapter.render(_TEMPLATE_HTML, _SAMPLE_DATA, "png")
        call_kwargs = mock_generate_document.call_args[1]
        assert call_kwargs["use_cache"] is False


class TestHealthCheck:
    """Tests for TailorTemplateAdapter.health_check."""

    async def test_returns_true_when_gotenberg_available(
        self, adapter: TailorTemplateAdapter, mock_gotenberg: MagicMock
    ) -> None:
        """health_check returns True when GotenbergService.health_check() returns True."""
        mock_gotenberg.health_check = AsyncMock(return_value=True)
        assert await adapter.health_check() is True

    async def test_returns_false_when_gotenberg_returns_false(
        self, adapter: TailorTemplateAdapter, mock_gotenberg: MagicMock
    ) -> None:
        """health_check returns False when GotenbergService.health_check() returns False."""
        mock_gotenberg.health_check = AsyncMock(return_value=False)
        assert await adapter.health_check() is False

    async def test_returns_false_on_oserror(self, adapter: TailorTemplateAdapter, mock_gotenberg: MagicMock) -> None:
        """health_check returns False (does not raise) when OSError is raised."""
        mock_gotenberg.health_check = AsyncMock(side_effect=OSError("connection refused"))
        result = await adapter.health_check()
        assert result is False


class TestEnsureGotenbergAvailable:
    """Tests for TailorTemplateAdapter.ensure_gotenberg_available."""

    async def test_no_exception_when_available(self, adapter: TailorTemplateAdapter, mock_gotenberg: MagicMock) -> None:
        """ensure_gotenberg_available returns None when Gotenberg is available."""
        mock_gotenberg.health_check = AsyncMock(return_value=True)
        result = await adapter.ensure_gotenberg_available()
        assert result is None

    async def test_raises_gotenberg_error_when_unavailable(
        self, adapter: TailorTemplateAdapter, mock_gotenberg: MagicMock
    ) -> None:
        """ensure_gotenberg_available raises GotenbergError when service is unavailable."""
        mock_gotenberg.health_check = AsyncMock(return_value=False)
        with pytest.raises(GotenbergError, match="not available"):
            await adapter.ensure_gotenberg_available()
