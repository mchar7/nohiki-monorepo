"""Tests for document generation module."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from doc_template_service.core.generator import (
    GenerationError,
    TextAlternativeMode,
    _validate_inputs_with_result,
    compute_hash,
    convert_html_to_text,
    generate_document,
    generate_document_streamed,
    get_cache_key,
    sanitize_text,
)
from doc_template_service.schemas.models import ValidationIssue, ValidationReport


class TestSanitizeText:
    """Tests for sanitize_text function."""

    def test_empty_text_returns_empty(self) -> None:
        """Test that empty text returns empty string."""
        assert sanitize_text("") == ""

    def test_removes_metadata_comments(self) -> None:
        """Test that TMPL_META comments are removed."""
        text = '<html><!-- TMPL_META {"name": "test"} --><body>Content</body></html>'
        result = sanitize_text(text)
        assert "TMPL_META" not in result
        assert "<body>Content</body>" in result

    def test_removes_null_characters(self) -> None:
        """Test that null characters are removed."""
        text = "Hello\x00World"
        result = sanitize_text(text)
        assert result == "HelloWorld"

    def test_preserves_normal_content(self) -> None:
        """Test that normal content is preserved."""
        text = "<html><body>Normal content</body></html>"
        result = sanitize_text(text)
        assert result == text


class TestConvertHtmlToText:
    """Tests for convert_html_to_text function."""

    def test_converts_simple_html(self) -> None:
        """Test conversion of simple HTML to text."""
        html = "<html><body><h1>Title</h1><p>Paragraph</p></body></html>"
        result = convert_html_to_text(html)
        assert "Title" in result
        assert "Paragraph" in result

    def test_handles_links(self) -> None:
        """Test that links are preserved in text output."""
        html = '<a href="https://example.com">Link</a>'
        result = convert_html_to_text(html)
        assert "Link" in result
        # html2text preserves links by default
        assert "example.com" in result


class TestComputeHash:
    """Tests for compute_hash function."""

    def test_none_returns_empty_string(self) -> None:
        """Test that None input returns empty string."""
        assert compute_hash(None) == ""

    def test_string_returns_hash(self) -> None:
        """Test that string input returns SHA-256 hash."""
        result = compute_hash("test")
        assert len(result) == 64  # SHA-256 hex length
        assert result.isalnum()

    def test_dict_returns_hash(self) -> None:
        """Test that dict input returns SHA-256 hash."""
        result = compute_hash({"key": "value"})
        assert len(result) == 64

    def test_same_input_same_hash(self) -> None:
        """Test that same input produces same hash."""
        assert compute_hash("test") == compute_hash("test")
        assert compute_hash({"a": 1}) == compute_hash({"a": 1})

    def test_different_input_different_hash(self) -> None:
        """Test that different input produces different hash."""
        assert compute_hash("test1") != compute_hash("test2")


class TestGetCacheKey:
    """Tests for get_cache_key function."""

    def test_generates_key_with_all_components(self) -> None:
        """Test that cache key includes all components."""
        key = get_cache_key(
            template="<html>{{ name }}</html>",
            schema={"type": "object"},
            data={"name": "test"},
        )
        assert "template:" in key
        assert "schema:" in key
        assert "data:" in key

    def test_generates_key_with_none_values(self) -> None:
        """Test that cache key handles None values."""
        key = get_cache_key(template=None, schema=None, data=None)
        assert "template:" in key
        assert "schema:" in key
        assert "data:" in key


class TestGenerationError:
    """Tests for GenerationError exception."""

    def test_error_with_message_only(self) -> None:
        """Test error with message only."""
        error = GenerationError("Test error")
        assert str(error) == "Test error"
        assert error.validation_report is None
        assert error.original_error is None

    def test_error_with_validation_report(self) -> None:
        """Test error with validation report."""
        report = ValidationReport(valid=False, issues=[])
        error = GenerationError("Validation failed", validation_report=report)
        assert error.validation_report == report

    def test_error_with_original_error(self) -> None:
        """Test error with original error."""
        original = ValueError("Original error")
        error = GenerationError("Wrapped error", original_error=original)
        assert error.original_error == original


class TestGenerateDocument:
    """Tests for generate_document function."""

    @pytest.mark.asyncio
    async def test_generate_html_document(self) -> None:
        """Test generating HTML document."""
        template = "<html><body>{{ name }}</body></html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation._validate_inputs_with_result",
                new_callable=AsyncMock,
                return_value=(ValidationReport(valid=True, issues=[]), None),
            ),
            patch(
                "doc_template_service.core.generator.generation.render_template",
                new_callable=AsyncMock,
                return_value="<html><body>Test</body></html>",
            ),
        ):
            result = await generate_document(template, data, output_format="html")

            assert result == "<html><body>Test</body></html>"

    @pytest.mark.asyncio
    async def test_generate_html_with_text_alternative(self) -> None:
        """Test generating HTML document with text alternative."""
        template = "<html><body>{{ name }}</body></html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation._validate_inputs_with_result",
                new_callable=AsyncMock,
                return_value=(ValidationReport(valid=True, issues=[]), None),
            ),
            patch(
                "doc_template_service.core.generator.generation.render_template",
                new_callable=AsyncMock,
                return_value="<html><body>Test</body></html>",
            ),
        ):
            result = await generate_document(
                template, data, output_format="html", text_alternative=TextAlternativeMode.ENABLED
            )

            assert isinstance(result, tuple)
            html_content, text_alt = result
            assert "<html>" in html_content
            assert "Test" in text_alt

    @pytest.mark.asyncio
    async def test_generate_text_document(self) -> None:
        """Test generating text document."""
        template = "<html><body>{{ name }}</body></html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation._validate_inputs_with_result",
                new_callable=AsyncMock,
                return_value=(ValidationReport(valid=True, issues=[]), None),
            ),
            patch(
                "doc_template_service.core.generator.generation.render_template",
                new_callable=AsyncMock,
                return_value="<html><body>Test</body></html>",
            ),
        ):
            result = await generate_document(template, data, output_format="text")

            assert isinstance(result, str)
            assert "Test" in result

    @pytest.mark.asyncio
    async def test_generate_pdf_document(self) -> None:
        """Test generating PDF document."""
        template = "<html><body>{{ name }}</body></html>"
        data = {"name": "Test"}

        mock_gotenberg = AsyncMock()
        mock_gotenberg.convert_html_to_pdf.return_value = b"%PDF-1.4 mock"

        with (
            patch(
                "doc_template_service.core.generator.generation._validate_inputs_with_result",
                new_callable=AsyncMock,
                return_value=(ValidationReport(valid=True, issues=[]), None),
            ),
            patch(
                "doc_template_service.core.generator.generation.render_template",
                new_callable=AsyncMock,
                return_value="<html><body>Test</body></html>",
            ),
            patch(
                "doc_template_service.core.generator.output_formats.get_gotenberg_service",
                return_value=mock_gotenberg,
            ),
        ):
            result = await generate_document(template, data, output_format="pdf")

            assert result == b"%PDF-1.4 mock"

    @pytest.mark.asyncio
    async def test_generate_image_without_options_uses_defaults(self) -> None:
        """Test that generating image without explicit options uses PNG defaults."""
        template = "<html><body>{{ name }}</body></html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation._validate_inputs_with_result",
                new_callable=AsyncMock,
                return_value=(ValidationReport(valid=True, issues=[]), None),
            ),
            patch(
                "doc_template_service.core.generator.generation.render_template",
                new_callable=AsyncMock,
                return_value="<html><body>Test</body></html>",
            ),
            patch(
                "doc_template_service.core.generator.output_formats.generate_image_content",
                new_callable=AsyncMock,
                return_value=b"PNG default image",
            ) as mock_generate_image,
        ):
            result = await generate_document(template, data, output_format="image")
            assert result == b"PNG default image"
            # Verify default PNG options were used
            call_args = mock_generate_image.call_args
            assert call_args[0][1].format == "png"

    @pytest.mark.asyncio
    async def test_validation_failure_raises_error(self) -> None:
        """Test that validation failure raises GenerationError."""
        template = "<html><body>{{ name }}</body></html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation._validate_inputs_with_result",
                new_callable=AsyncMock,
                return_value=(
                    ValidationReport(
                        valid=False,
                        issues=[ValidationIssue(path="$", keyword="error", message="Validation failed")],
                    ),
                    None,
                ),
            ),
            pytest.raises(GenerationError, match="Document generation failed"),
        ):
            await generate_document(template, data)

    @pytest.mark.asyncio
    async def test_template_rendering_error_raises_generation_error(self) -> None:
        """Test that template rendering error raises GenerationError."""
        template = "<html><body>{{ name }}</body></html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation._validate_inputs_with_result",
                new_callable=AsyncMock,
                return_value=(ValidationReport(valid=True, issues=[]), None),
            ),
            patch(
                "doc_template_service.core.generator.generation.render_template",
                new_callable=AsyncMock,
                side_effect=ValueError("Template error"),
            ),
            pytest.raises(GenerationError, match="template error"),
        ):
            await generate_document(template, data)


class TestGenerateDocumentStreamed:
    """Tests for generate_document_streamed function."""

    @pytest.mark.asyncio
    async def test_stream_html_document(self) -> None:
        """Test streaming HTML document."""
        template = "<html><body>{{ name }}</body></html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation._validate_inputs",
                new_callable=AsyncMock,
                return_value=ValidationReport(valid=True, issues=[]),
            ),
            patch(
                "doc_template_service.core.generator.generation.render_template",
                new_callable=AsyncMock,
                return_value="<html><body>Test</body></html>",
            ),
        ):
            chunks = [chunk async for chunk in generate_document_streamed(template, data, output_format="html")]

            content = b"".join(chunks)
            assert b"<html>" in content

    @pytest.mark.asyncio
    async def test_stream_text_document(self) -> None:
        """Test streaming text document."""
        template = "<html><body>{{ name }}</body></html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation._validate_inputs",
                new_callable=AsyncMock,
                return_value=ValidationReport(valid=True, issues=[]),
            ),
            patch(
                "doc_template_service.core.generator.generation.render_template",
                new_callable=AsyncMock,
                return_value="<html><body>Test</body></html>",
            ),
        ):
            chunks = [chunk async for chunk in generate_document_streamed(template, data, output_format="text")]

            content = b"".join(chunks)
            assert b"Test" in content

    @pytest.mark.asyncio
    async def test_stream_image_without_options_raises_error(self) -> None:
        """Test that streaming image without options raises error."""
        template = "<html><body>{{ name }}</body></html>"
        data = {"name": "Test"}

        with pytest.raises(GenerationError, match="Image options are required"):
            _ = [chunk async for chunk in generate_document_streamed(template, data, output_format="image")]


class TestTextAlternativeMode:
    """Tests for TextAlternativeMode enum."""

    def test_disabled_value(self) -> None:
        """Test DISABLED enum value."""
        assert TextAlternativeMode.DISABLED.value == "disabled"

    def test_enabled_value(self) -> None:
        """Test ENABLED enum value."""
        assert TextAlternativeMode.ENABLED.value == "enabled"


class TestCachedValidationReport:
    """Tests for cached validation report functions."""

    @pytest.mark.asyncio
    async def testget_cached_validation_report_returns_none_when_not_cached(self) -> None:
        """Test that None is returned when no cached report exists."""
        from doc_template_service.core.generator.cache import get_cached_validation_report

        with patch("doc_template_service.core.generator.cache._cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value=None)

            result = await get_cached_validation_report("test-key")

            assert result is None

    @pytest.mark.asyncio
    async def testget_cached_validation_report_returns_report_when_cached(self) -> None:
        """Test that cached report is returned when available."""
        from doc_template_service.core.generator.cache import get_cached_validation_report

        with patch("doc_template_service.core.generator.cache._cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value={"valid": True, "issues": []})

            result = await get_cached_validation_report("test-key")

            assert result is not None
            assert result.valid is True

    @pytest.mark.asyncio
    async def testget_cached_validation_report_returns_none_for_invalid_data(self) -> None:
        """Test that None is returned for non-dict cached data."""
        from doc_template_service.core.generator.cache import get_cached_validation_report

        with patch("doc_template_service.core.generator.cache._cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value="invalid")

            result = await get_cached_validation_report("test-key")

            assert result is None

    @pytest.mark.asyncio
    async def testset_cached_validation_report(self) -> None:
        """Test setting cached validation report."""
        from doc_template_service.core.generator.cache import set_cached_validation_report

        report = ValidationReport(valid=True, issues=[])

        with patch("doc_template_service.core.generator.cache._cache") as mock_cache:
            mock_cache.set = AsyncMock()

            await set_cached_validation_report("test-key", report)

            mock_cache.set.assert_called_once()


class TestCacheHashCaching:
    """Tests for cache.py hash caching behavior."""

    def test_compute_hash_dict_cache_hit(self) -> None:
        """Test that dict hash caching returns cached value on second call."""
        from doc_template_service.core.generator.cache import compute_hash

        test_dict = {"key": "value", "nested": {"a": 1}}
        hash1 = compute_hash(test_dict)
        hash2 = compute_hash(test_dict)

        assert hash1 == hash2
        assert len(hash1) == 64

    def test_compute_hash_different_dicts_different_hashes(self) -> None:
        """Test that different dicts produce different hashes."""
        from doc_template_service.core.generator.cache import compute_hash

        dict1 = {"a": 1}
        dict2 = {"a": 2}
        assert compute_hash(dict1) != compute_hash(dict2)


class TestCacheValidationReport:
    """Tests for cache.py validation report caching."""

    @pytest.mark.asyncio
    async def test_get_cached_report_with_issues(self) -> None:
        """Test retrieving cached report with issues."""
        from doc_template_service.core.generator.cache import get_cached_validation_report

        cached_data = {
            "valid": False,
            "issues": [
                {"path": "$.name", "keyword": "required", "message": "Name is required"},
            ],
        }

        with patch("doc_template_service.core.generator.cache._cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value=cached_data)

            result = await get_cached_validation_report("test-key")

            assert result is not None
            assert result.valid is False
            assert len(result.issues) == 1
            assert result.issues[0].path == "$.name"

    @pytest.mark.asyncio
    async def test_set_cached_report_with_issues(self) -> None:
        """Test setting cached report with issues."""
        from doc_template_service.core.generator.cache import set_cached_validation_report

        report = ValidationReport(
            valid=False,
            issues=[
                ValidationIssue(path="$.name", keyword="required", message="Name is required"),
            ],
        )

        with patch("doc_template_service.core.generator.cache._cache") as mock_cache:
            mock_cache.set = AsyncMock()

            await set_cached_validation_report("test-key", report)

            mock_cache.set.assert_called_once()
            call_args = mock_cache.set.call_args
            assert "validation:test-key" in call_args[0]


class TestStreamingFunctions:
    """Tests for streaming helper functions."""

    @pytest.mark.asyncio
    async def test_stream_pdf_chunks_full_path(self) -> None:
        """Test streaming PDF chunks with proper gotenberg mock."""
        from doc_template_service.core.generator.streaming import stream_pdf_chunks

        with patch("doc_template_service.core.generator.streaming.get_gotenberg_service") as mock_get_service:
            mock_service = AsyncMock()
            mock_service.convert_html_to_pdf = AsyncMock(return_value=b"PDF content here")
            mock_get_service.return_value = mock_service

            chunks = [chunk async for chunk in stream_pdf_chunks("<html></html>")]

            assert len(chunks) > 0
            assert b"".join(chunks) == b"PDF content here"
            mock_service.convert_html_to_pdf.assert_called_once_with("<html></html>")

    @pytest.mark.asyncio
    async def test_stream_image_chunks_full_path(self) -> None:
        """Test streaming image chunks with proper gotenberg mock."""
        from doc_template_service.core.generator.streaming import stream_image_chunks
        from doc_template_service.schemas.models import ImageOptions

        with patch("doc_template_service.core.generator.streaming.get_gotenberg_service") as mock_get_service:
            mock_service = AsyncMock()
            mock_service.screenshot_html = AsyncMock(return_value=b"PNG image content")
            mock_get_service.return_value = mock_service

            options = ImageOptions(format="png", width=800, height=600)
            chunks = [chunk async for chunk in stream_image_chunks("<html></html>", options)]

            assert len(chunks) > 0
            assert b"".join(chunks) == b"PNG image content"

    @pytest.mark.asyncio
    async def test_generate_image_content_full_path(self) -> None:
        """Test generate_image_content with gotenberg mock."""
        from doc_template_service.core.generator.streaming import generate_image_content
        from doc_template_service.schemas.models import ImageOptions

        with patch("doc_template_service.core.generator.streaming.get_gotenberg_service") as mock_get_service:
            mock_service = AsyncMock()
            mock_service.screenshot_html = AsyncMock(return_value=b"PNG screenshot")
            mock_get_service.return_value = mock_service

            options = ImageOptions(format="png", width=1024, height=768, quality=95)
            result = await generate_image_content("<html><body>Test</body></html>", options)

            assert result == b"PNG screenshot"
            mock_service.screenshot_html.assert_called_once()

    @pytest.mark.asyncio
    async def teststream_pdf_chunks(self) -> None:
        """Test streaming PDF chunks."""
        from doc_template_service.core.generator.streaming import stream_pdf_chunks

        with patch("doc_template_service.core.generator.streaming.get_gotenberg_service") as mock_get_service:
            mock_service = AsyncMock()
            mock_service.convert_html_to_pdf = AsyncMock(return_value=b"PDF content here")
            mock_get_service.return_value = mock_service

            chunks = [chunk async for chunk in stream_pdf_chunks("<html></html>")]

            assert len(chunks) > 0
            assert b"".join(chunks) == b"PDF content here"

    @pytest.mark.asyncio
    async def teststream_html_chunks(self) -> None:
        """Test streaming HTML chunks."""
        from doc_template_service.core.generator import stream_html_chunks

        html = "<html><body>Test content</body></html>"
        chunks = [chunk async for chunk in stream_html_chunks(html)]

        assert len(chunks) > 0
        assert b"".join(chunks) == html.encode("utf-8")

    @pytest.mark.asyncio
    async def teststream_text_chunks(self) -> None:
        """Test streaming text chunks."""
        from doc_template_service.core.generator import stream_text_chunks

        html = "<html><body>Test content</body></html>"
        chunks = [chunk async for chunk in stream_text_chunks(html)]

        assert len(chunks) > 0
        content = b"".join(chunks).decode("utf-8")
        assert "Test content" in content

    @pytest.mark.asyncio
    async def teststream_image_chunks(self) -> None:
        """Test streaming image chunks."""
        from doc_template_service.core.generator.streaming import stream_image_chunks
        from doc_template_service.schemas.models import ImageOptions

        with patch(
            "doc_template_service.core.generator.output_formats.generate_image_content",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = b"PNG image data"

            options = ImageOptions(format="png", width=800, height=600)
            chunks = [chunk async for chunk in stream_image_chunks("<html></html>", options)]

            assert len(chunks) > 0
            assert b"".join(chunks) == b"PNG image data here"


class TestGenerateImageContent:
    """Tests for generate_image_content function."""

    @pytest.mark.asyncio
    async def testgenerate_image_content(self) -> None:
        """Test generating image content."""
        from doc_template_service.core.generator.streaming import generate_image_content
        from doc_template_service.schemas.models import ImageOptions

        with patch("doc_template_service.core.generator.streaming.get_gotenberg_service") as mock_get_service:
            mock_service = AsyncMock()
            mock_service.screenshot_html = AsyncMock(return_value=b"PNG data")
            mock_get_service.return_value = mock_service

            options = ImageOptions(format="png", width=800, height=600, quality=90)
            result = await generate_image_content("<html></html>", options)

            assert result == b"PNG data"
            mock_service.screenshot_html.assert_called_once()


class TestGenerateDocumentWithImageFormat:
    """Tests for generate_document with image format."""

    @pytest.mark.asyncio
    async def test_generate_image_document(self) -> None:
        """Test generating image document."""
        from doc_template_service.schemas.models import ImageOptions

        template = "<html><body>{{ name }}</body></html>"
        data = {"name": "Test"}
        image_options = ImageOptions(format="png", width=800, height=600)

        with (
            patch(
                "doc_template_service.core.generator.generation._validate_inputs_with_result",
                new_callable=AsyncMock,
                return_value=(ValidationReport(valid=True, issues=[]), None),
            ),
            patch(
                "doc_template_service.core.generator.generation.render_template",
                new_callable=AsyncMock,
                return_value="<html><body>Test</body></html>",
            ),
            patch(
                "doc_template_service.core.generator.output_formats.generate_image_content",
                new_callable=AsyncMock,
                return_value=b"PNG image data",
            ),
        ):
            result = await generate_document(template, data, output_format="image", image_options=image_options)

            assert result == b"PNG image data"

    @pytest.mark.asyncio
    async def test_generate_image_without_options_uses_defaults(self) -> None:
        """Test that generating image without explicit options uses PNG defaults."""
        template = "<html><body>{{ name }}</body></html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation._validate_inputs_with_result",
                new_callable=AsyncMock,
                return_value=(ValidationReport(valid=True, issues=[]), None),
            ),
            patch(
                "doc_template_service.core.generator.generation.render_template",
                new_callable=AsyncMock,
                return_value="<html><body>Test</body></html>",
            ),
            patch(
                "doc_template_service.core.generator.output_formats.generate_image_content",
                new_callable=AsyncMock,
                return_value=b"PNG default image",
            ) as mock_generate_image,
        ):
            result = await generate_document(template, data, output_format="image")
            assert result == b"PNG default image"
            # Verify default PNG options were used
            call_args = mock_generate_image.call_args
            assert call_args[0][1].format == "png"


class TestStreamOutputFormat:
    """Tests for stream_output_format function."""

    @pytest.mark.asyncio
    async def test_stream_pdf_format(self) -> None:
        """Test streaming PDF format."""
        from doc_template_service.core.generator import stream_output_format

        with patch("doc_template_service.core.generator.output_formats.stream_pdf_chunks") as mock_stream:

            async def mock_generator() -> AsyncGenerator[bytes]:
                yield b"PDF chunk"

            mock_stream.return_value = mock_generator()

            chunks = [chunk async for chunk in stream_output_format("<html></html>", "pdf", None)]

            assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_stream_image_format(self) -> None:
        """Test streaming image format."""
        from doc_template_service.core.generator import stream_output_format
        from doc_template_service.schemas.models import ImageOptions

        with patch("doc_template_service.core.generator.output_formats.stream_image_chunks") as mock_stream:

            async def mock_generator() -> AsyncGenerator[bytes]:
                yield b"Image chunk"

            mock_stream.return_value = mock_generator()

            options = ImageOptions(format="png", width=800, height=600)
            chunks = [chunk async for chunk in stream_output_format("<html></html>", "image", options)]

            assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_stream_image_without_options_raises_error(self) -> None:
        """Test that streaming image without options raises error."""
        from doc_template_service.core.generator import stream_output_format

        with pytest.raises(GenerationError, match="Image options are required"):
            _ = [chunk async for chunk in stream_output_format("<html></html>", "image", None)]


class TestValidateAndRender:
    """Tests for _validate_and_render function."""

    @pytest.mark.asyncio
    async def test_validation_failure_raises_error(self) -> None:
        """Test that validation failure raises GenerationError."""
        from doc_template_service.core.generator import _validate_and_render

        template = "<html>{{ name }}</html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation._validate_inputs",
                new_callable=AsyncMock,
                return_value=ValidationReport(
                    valid=False,
                    issues=[ValidationIssue(path="$", keyword="error", message="Test error")],
                ),
            ),
            pytest.raises(GenerationError, match="Document generation failed"),
        ):
            await _validate_and_render(template, data)

    @pytest.mark.asyncio
    async def test_render_failure_raises_error(self) -> None:
        """Test that render failure raises GenerationError."""
        from doc_template_service.core.generator import _validate_and_render

        template = "<html>{{ name }}</html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation._validate_inputs",
                new_callable=AsyncMock,
                return_value=ValidationReport(valid=True, issues=[]),
            ),
            patch(
                "doc_template_service.core.generator.generation.render_template",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Render failed"),
            ),
            pytest.raises(GenerationError, match="template error"),
        ):
            await _validate_and_render(template, data)


class TestValidateInputs:
    """Tests for _validate_inputs function."""

    @pytest.mark.asyncio
    async def test_uses_cached_validation_when_available(self) -> None:
        """Test that cached validation is used when available."""
        from doc_template_service.core.generator.generation import _validate_inputs

        template = "<html>{{ name }}</html>"
        data = {"name": "Test"}

        cached_report = ValidationReport(valid=True, issues=[])

        with (
            patch(
                "doc_template_service.core.generator.generation.get_cached_validation_report",
                new_callable=AsyncMock,
                return_value=cached_report,
            ),
        ):
            result = await _validate_inputs(template=template, data=data, use_cache=True)

            assert result.valid is True

    @pytest.mark.asyncio
    async def test_runs_validation_when_not_cached(self) -> None:
        """Test that validation runs when not cached."""
        template = "<html>{{ name }}</html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation.get_cached_validation_report",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "doc_template_service.core.generator.generation.validate_all_with_result",
                new_callable=AsyncMock,
                return_value=(ValidationReport(valid=True, issues=[]), "<html>Test</html>"),
            ),
            patch(
                "doc_template_service.core.generator.generation.set_cached_validation_report",
                new_callable=AsyncMock,
            ),
        ):
            report, html = await _validate_inputs_with_result(template=template, data=data, use_cache=True)

            assert report.valid is True
            assert html == "<html>Test</html>"

    @pytest.mark.asyncio
    async def test_timeout_error_raises_generation_error(self) -> None:
        """Test that TimeoutError raises GenerationError."""
        template = "<html>{{ name }}</html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation.get_cached_validation_report",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "doc_template_service.core.generator.generation.validate_all_with_result",
                new_callable=AsyncMock,
                side_effect=TimeoutError("Validation timed out"),
            ),
            pytest.raises(GenerationError, match="timed out"),
        ):
            await _validate_inputs_with_result(template=template, data=data, use_cache=False)

    @pytest.mark.asyncio
    async def test_unexpected_error_raises_generation_error(self) -> None:
        """Test that unexpected errors raise GenerationError."""
        template = "<html>{{ name }}</html>"
        data = {"name": "Test"}

        with (
            patch(
                "doc_template_service.core.generator.generation.get_cached_validation_report",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "doc_template_service.core.generator.generation.validate_all_with_result",
                new_callable=AsyncMock,
                side_effect=ValueError("Unexpected error"),
            ),
            pytest.raises(GenerationError, match="validation error"),
        ):
            await _validate_inputs_with_result(template=template, data=data, use_cache=False)
