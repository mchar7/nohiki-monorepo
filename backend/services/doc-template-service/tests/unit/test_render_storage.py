"""Tests for render_storage service."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from doc_template_service.services.render_storage import (
    RENDERED_DOCS_PREFIX,
    StoredRenderResult,
    _build_storage_key,
    _compute_content_hash,
    _content_type_to_extension,
    store_rendered_document,
)


class TestComputeContentHash:
    """Tests for _compute_content_hash function."""

    def test_computes_sha256_hash(self) -> None:
        """Test that function computes SHA-256 hash correctly."""
        content = b"test content"
        result = _compute_content_hash(content)

        # SHA-256 hash is always 64 hex characters
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_empty_content_hash(self) -> None:
        """Test hash computation for empty content."""
        result = _compute_content_hash(b"")

        # SHA-256 of empty string is well-known
        assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_different_content_produces_different_hash(self) -> None:
        """Test that different content produces different hashes."""
        hash1 = _compute_content_hash(b"content1")
        hash2 = _compute_content_hash(b"content2")

        assert hash1 != hash2


class TestContentTypeToExtension:
    """Tests for _content_type_to_extension function."""

    def test_pdf_extension(self) -> None:
        """Test PDF content type mapping."""
        assert _content_type_to_extension("application/pdf") == "pdf"

    def test_png_extension(self) -> None:
        """Test PNG content type mapping."""
        assert _content_type_to_extension("image/png") == "png"

    def test_jpeg_extension(self) -> None:
        """Test JPEG content type mapping."""
        assert _content_type_to_extension("image/jpeg") == "jpg"

    def test_html_extension(self) -> None:
        """Test HTML content type mapping."""
        assert _content_type_to_extension("text/html") == "html"

    def test_plain_text_extension(self) -> None:
        """Test plain text content type mapping."""
        assert _content_type_to_extension("text/plain") == "txt"

    def test_unknown_content_type_defaults_to_bin(self) -> None:
        """Test that unknown content type defaults to bin extension."""
        assert _content_type_to_extension("application/unknown") == "bin"
        assert _content_type_to_extension("something/else") == "bin"


class TestBuildStorageKey:
    """Tests for _build_storage_key function."""

    def test_builds_correct_key_format(self) -> None:
        """Test that storage key follows expected format."""
        correlation_id = "corr-123"
        template_id = "template-456"
        content_type = "application/pdf"

        result = _build_storage_key(correlation_id, template_id, content_type)

        assert result == f"{RENDERED_DOCS_PREFIX}/corr-123/template-456.pdf"

    def test_key_with_png_content_type(self) -> None:
        """Test storage key with PNG content type."""
        result = _build_storage_key("corr", "tmpl", "image/png")

        assert result == f"{RENDERED_DOCS_PREFIX}/corr/tmpl.png"

    def test_key_with_unknown_content_type(self) -> None:
        """Test storage key with unknown content type uses bin extension."""
        result = _build_storage_key("corr", "tmpl", "application/octet-stream")

        assert result == f"{RENDERED_DOCS_PREFIX}/corr/tmpl.bin"


class TestStoredRenderResult:
    """Tests for StoredRenderResult dataclass."""

    def test_dataclass_creation(self) -> None:
        """Test that dataclass can be created with required fields."""
        result = StoredRenderResult(
            storage_key="rendered/test/doc.pdf",
            file_size=1024,
            content_hash="abc123def456",
        )

        assert result.storage_key == "rendered/test/doc.pdf"
        assert result.file_size == 1024
        assert result.content_hash == "abc123def456"

    def test_dataclass_is_frozen(self) -> None:
        """Test that dataclass is immutable (frozen)."""
        import dataclasses

        assert dataclasses.is_dataclass(StoredRenderResult)
        params = getattr(StoredRenderResult, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestStoreRenderedDocument:
    """Tests for store_rendered_document function."""

    @pytest.mark.asyncio
    async def test_uploads_to_s3_and_returns_result(self) -> None:
        """Test successful upload to S3 returns correct result."""
        content = b"PDF content here"
        correlation_id = "corr-123"
        template_id = "template-456"
        content_type = "application/pdf"

        mock_s3_client = AsyncMock()
        mock_s3_client.put_object = AsyncMock()

        result = await store_rendered_document(
            content=content,
            correlation_id=correlation_id,
            template_id=template_id,
            content_type=content_type,
            s3_client=mock_s3_client,
        )

        # Verify result
        assert isinstance(result, StoredRenderResult)
        assert result.storage_key == f"{RENDERED_DOCS_PREFIX}/{correlation_id}/{template_id}.pdf"
        assert result.file_size == len(content)
        assert len(result.content_hash) == 64

        # Verify S3 client was called correctly
        mock_s3_client.put_object.assert_called_once()
        call_kwargs = mock_s3_client.put_object.call_args.kwargs
        assert call_kwargs["key"] == result.storage_key
        assert call_kwargs["data"] == content
        assert call_kwargs["content_type"] == content_type
        assert "correlation-id" in call_kwargs["metadata"]
        assert "template-id" in call_kwargs["metadata"]
        assert "content-hash" in call_kwargs["metadata"]

    @pytest.mark.asyncio
    async def test_uses_singleton_client_when_not_provided(self) -> None:
        """Test that function uses singleton S3 client when not provided."""
        content = b"test content"

        with patch("doc_template_service.services.render_storage._get_s3_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.put_object = AsyncMock()
            mock_get_client.return_value = mock_client

            await store_rendered_document(
                content=content,
                correlation_id="corr",
                template_id="tmpl",
                content_type="text/plain",
            )

            mock_get_client.assert_called_once()
            mock_client.put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_computes_correct_content_hash(self) -> None:
        """Test that content hash is computed correctly."""
        content = b"specific content for hash test"
        expected_hash = _compute_content_hash(content)

        mock_s3_client = AsyncMock()
        mock_s3_client.put_object = AsyncMock()

        result = await store_rendered_document(
            content=content,
            correlation_id="corr",
            template_id="tmpl",
            content_type="text/plain",
            s3_client=mock_s3_client,
        )

        assert result.content_hash == expected_hash

    @pytest.mark.asyncio
    async def test_logs_upload_info(self) -> None:
        """Test that upload information is logged."""
        content = b"test content"

        mock_s3_client = AsyncMock()
        mock_s3_client.put_object = AsyncMock()

        with patch("doc_template_service.services.render_storage.logger") as mock_logger:
            await store_rendered_document(
                content=content,
                correlation_id="corr-123",
                template_id="tmpl-456",
                content_type="application/pdf",
                s3_client=mock_s3_client,
            )

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert "Stored rendered document" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_handles_different_content_types(self) -> None:
        """Test handling of various content types."""
        mock_s3_client = AsyncMock()
        mock_s3_client.put_object = AsyncMock()

        content_types = [
            ("application/pdf", "pdf"),
            ("image/png", "png"),
            ("image/jpeg", "jpg"),
            ("text/html", "html"),
            ("text/plain", "txt"),
        ]

        for content_type, expected_ext in content_types:
            result = await store_rendered_document(
                content=b"test",
                correlation_id="corr",
                template_id="tmpl",
                content_type=content_type,
                s3_client=mock_s3_client,
            )

            assert result.storage_key.endswith(f".{expected_ext}")
