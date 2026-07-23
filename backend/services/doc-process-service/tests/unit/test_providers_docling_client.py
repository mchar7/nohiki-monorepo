"""Tests for doc_process_service.providers.docling.client module."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from doc_process_service.core.config import DoclingSettings, VLMSettings
from doc_process_service.models.domain import ProcessingOptions
from doc_process_service.providers.docling.client import DoclingClient, DoclingClientConfig


@pytest.fixture
def docling_settings() -> DoclingSettings:
    """Create Docling provider settings for testing."""
    return DoclingSettings(
        base_url="http://localhost:5001",
        timeout_seconds=300,
        max_retries=3,
    )


@pytest.fixture
def vlm_settings() -> VLMSettings:
    """Create VLM settings for testing."""
    return VLMSettings(
        enabled=False,
        model="test-model",
        timeout_seconds=60,
        max_tokens=1000,
        temperature=0.1,
        thinking_budget=512,
    )


@pytest.fixture
def docling_client(docling_settings: DoclingSettings, vlm_settings: VLMSettings) -> DoclingClient:
    """Create DoclingClient for testing."""
    return DoclingClient.from_settings(docling_settings, vlm_settings)


class TestDoclingClient:
    """Tests for DoclingClient class."""

    def test_init(self, docling_client: DoclingClient) -> None:
        """Test DoclingClient initialization."""
        assert docling_client._config is not None
        assert docling_client._config.base_url == "http://localhost:5001"

    def test_is_available_true(self, docling_client: DoclingClient) -> None:
        """Test is_available returns True when health check succeeds."""
        with patch("httpx.Client.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            docling_client.reset_availability()
            assert docling_client.is_available() is True

    def test_is_available_false(self, docling_client: DoclingClient) -> None:
        """Test is_available returns False when health check fails."""
        with patch("httpx.Client.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=503)
            docling_client.reset_availability()
            assert docling_client.is_available() is False

    def test_is_available_exception(self, docling_client: DoclingClient) -> None:
        """Test is_available returns False on exception."""
        with patch("httpx.Client.get") as mock_get:
            mock_get.side_effect = httpx.RequestError("Connection error")
            docling_client.reset_availability()
            assert docling_client.is_available() is False

    def test_is_available_cached(self, docling_client: DoclingClient) -> None:
        """Test availability is cached."""
        with patch("httpx.Client.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            docling_client.reset_availability()
            assert docling_client.is_available() is True
            assert docling_client.is_available() is True
            assert mock_get.call_count == 1

    def test_name_property(self, docling_client: DoclingClient) -> None:
        """Test name property returns correct value."""
        assert docling_client.name == "docling"

    def test_process_unavailable(self, docling_client: DoclingClient) -> None:
        """Test process returns error when unavailable."""
        with patch.object(DoclingClient, "is_available", return_value=False):
            result = docling_client.process(b"content", "id", ProcessingOptions())
            assert not result.success
            assert result.error is not None
            assert "unavailable" in result.error

    def test_detect_mime_type_pdf(self, docling_client: DoclingClient) -> None:
        """Test MIME type detection for PDF."""
        content = b"%PDF-1.4"
        assert docling_client._detect_mime_type(content) == "application/pdf"

    def test_detect_mime_type_image(self, docling_client: DoclingClient) -> None:
        """Test MIME type detection for images."""
        assert docling_client._detect_mime_type(b"\x89PNG") == "image/png"
        assert docling_client._detect_mime_type(b"\xff\xd8\xff") == "image/jpeg"

    def test_detect_mime_type_default(self, docling_client: DoclingClient) -> None:
        """Test MIME type detection defaults to PDF for unknown content."""
        assert docling_client._detect_mime_type(b"unknown") == "application/pdf"

    @patch("httpx.Client.post")
    def test_submit_task_success(self, mock_post: MagicMock, docling_client: DoclingClient) -> None:
        """Test successful task submission."""
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.json.return_value = {"task_id": "task_123"}

        task_id = docling_client._submit_task(httpx.Client(), b"content", "application/pdf")
        assert task_id == "task_123"

        submitted_files = mock_post.call_args.kwargs["files"]
        format_entries = [value for name, value in submitted_files if name == "to_formats"]
        assert format_entries == [
            (None, "md", None),
            (None, "html", None),
            (None, "json", None),
        ]

    @patch("httpx.Client.post")
    def test_submit_task_no_id(self, mock_post: MagicMock, docling_client: DoclingClient) -> None:
        """Test submission failure when no task_id returned."""
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.json.return_value = {}

        with pytest.raises(ValueError, match="No task_id"):
            docling_client._submit_task(httpx.Client(), b"content", "application/pdf")

    def test_extract_json_content(self, docling_client: DoclingClient) -> None:
        """Test extracting json_content from API response."""
        doc1 = {"json_content": {"foo": "bar"}}
        assert docling_client._extract_json_content(doc1) == {"foo": "bar"}

        doc2 = {"json_content": {"baz": "qux"}}
        assert docling_client._extract_json_content(doc2) == {"baz": "qux"}

        assert docling_client._extract_json_content(None) is None

    @patch("httpx.Client.get")
    def test_try_fetch_result_404(self, mock_get: MagicMock, docling_client: DoclingClient) -> None:
        """Test result fetch returns None on 404."""
        mock_get.return_value = MagicMock(status_code=404)
        assert docling_client._try_fetch_result(httpx.Client(), "task_123") is None

    @patch("httpx.Client.get")
    def test_poll_once_success(self, mock_get: MagicMock, docling_client: DoclingClient) -> None:
        """Test single poll attempt returning success."""
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {"task_status": "success"}

        with patch.object(DoclingClient, "_fetch_result", return_value={"doc": 1}):
            result = docling_client._poll_once(httpx.Client(), "url", "task_123", {}, float("inf"))
            assert result == {"doc": 1}

    @patch("httpx.Client.get")
    def test_poll_once_failure(self, mock_get: MagicMock, docling_client: DoclingClient) -> None:
        """Test single poll attempt returning failure."""
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {"task_status": "failure", "error_message": "crash"}

        with pytest.raises(ValueError, match="Task failed: crash"):
            docling_client._poll_once(httpx.Client(), "url", "task_123", {}, float("inf"))

    @pytest.mark.usefixtures("_mock_sleep")
    @patch("httpx.Client.get")
    def test_poll_for_result_timeout(self, mock_get: MagicMock, docling_client: DoclingClient) -> None:
        """Test timeout after max poll attempts."""
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {"task_status": "pending"}

        original_config = docling_client._config
        new_config = DoclingClientConfig(
            base_url=original_config.base_url,
            timeout=original_config.timeout,
            api_key=original_config.api_key,
            pipeline=original_config.pipeline,
            pdf_backend=original_config.pdf_backend,
            ocr_engine=original_config.ocr_engine,
            table_mode=original_config.table_mode,
            do_ocr=original_config.do_ocr,
            force_ocr=original_config.force_ocr,
            do_table_structure=original_config.do_table_structure,
            include_images=original_config.include_images,
            do_picture_description=original_config.do_picture_description,
            picture_description_custom_config=original_config.picture_description_custom_config,
            poll_interval=original_config.poll_interval,
            max_poll_attempts=2,
        )

        with (
            patch.object(docling_client, "_config", new_config),
            pytest.raises(TimeoutError, match="Timeout waiting"),
        ):
            docling_client._poll_for_result(httpx.Client(), "task_123")

        assert mock_get.call_count == 2

    def test_detect_mime_type_svg(self, docling_client: DoclingClient) -> None:
        """Test MIME type detection for SVG."""
        assert docling_client._detect_mime_type(b"<svg") == "image/svg+xml"
        assert docling_client._detect_mime_type(b"<?xml") == "image/svg+xml"

    def test_detect_mime_type_gif(self, docling_client: DoclingClient) -> None:
        """Test MIME type detection for GIF."""
        assert docling_client._detect_mime_type(b"GIF8") == "image/gif"

    def test_detect_mime_type_webp(self, docling_client: DoclingClient) -> None:
        """Test MIME type detection for WebP."""
        assert docling_client._detect_mime_type(b"RIFF") == "image/webp"

    def test_build_headers_with_api_key(self) -> None:
        """Test headers include X-Api-Key when API key is set."""
        config = DoclingClientConfig(
            base_url="http://localhost:5001",
            timeout=300,
            api_key="test-key",
            pipeline="standard",
            pdf_backend="docling_parse",
            ocr_engine="rapidocr",
            table_mode="accurate",
            do_ocr=True,
            force_ocr=False,
            do_table_structure=True,
            include_images=True,
            do_picture_description=False,
            picture_description_custom_config=None,
            poll_interval=1.0,
            max_poll_attempts=300,
        )
        client = DoclingClient(config)
        headers = client._build_headers()

        assert headers["X-Api-Key"] == "test-key"
        assert headers["Accept"] == "application/json"

    def test_config_with_picture_description(self) -> None:
        """Test config properly stores picture_description custom config."""
        config = DoclingClientConfig(
            base_url="http://localhost:5001",
            timeout=300,
            api_key=None,
            pipeline="vlm",
            pdf_backend="docling_parse",
            ocr_engine="rapidocr",
            table_mode="accurate",
            do_ocr=True,
            force_ocr=False,
            do_table_structure=True,
            include_images=True,
            do_picture_description=True,
            picture_description_custom_config=(
                '{"model_spec": {"name": "test", "default_repo_id": "test",'
                ' "prompt": "Describe", "response_format": "markdown"},'
                ' "engine_options": {"engine_type": "api_ollama", "url": "http://test",'
                ' "headers": {}, "params": {"model": "test"}, "timeout": 30, "concurrency": 1},'
                ' "prompt": "Describe"}'
            ),
            poll_interval=1.0,
            max_poll_attempts=300,
        )
        client = DoclingClient(config)

        assert client._config.do_picture_description is True
        assert client._config.picture_description_custom_config is not None

    @pytest.mark.usefixtures("_mock_sleep")
    @patch("httpx.Client.get")
    def test_poll_once_unknown_status(self, mock_get: MagicMock, docling_client: DoclingClient) -> None:
        """Test poll_once returns None for unknown status."""
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {"task_status": "unknown_status"}

        result = docling_client._poll_once(httpx.Client(), "url", "task_123", {}, float("inf"))
        assert result is None

    @pytest.mark.usefixtures("_mock_sleep")
    @patch("httpx.Client.get")
    def test_poll_once_404_with_result(
        self,
        mock_get: MagicMock,
        docling_client: DoclingClient,
    ) -> None:
        """Test poll_once handles 404 by trying to fetch result."""
        mock_get.return_value = MagicMock(status_code=404)

        with patch(
            "doc_process_service.providers.docling.client.DoclingClient._try_fetch_result",
            return_value={"doc": 1},
        ):
            result = docling_client._poll_once(httpx.Client(), "url", "task_123", {}, float("inf"))
            assert result == {"doc": 1}

    @patch("httpx.Client.get")
    def test_poll_404_respects_deadline(
        self,
        mock_get: MagicMock,
        docling_client: DoclingClient,
    ) -> None:
        """Test that server and local waits use only the remaining deadline."""
        mock_get.return_value = MagicMock(status_code=404)

        with (
            patch.object(DoclingClient, "_try_fetch_result", return_value=None),
            patch(
                "doc_process_service.providers.docling.client.time.monotonic",
                side_effect=[10.0, 10.03],
            ),
            patch("doc_process_service.providers.docling.client.time.sleep") as mock_sleep,
        ):
            result = docling_client._poll_once(httpx.Client(), "url", "task_123", {}, 10.05)

        assert result is None
        assert mock_get.call_args.kwargs["params"]["wait"] == pytest.approx(0.05)
        assert mock_sleep.call_args.args[0] == pytest.approx(0.02)

    @patch("httpx.Client.get")
    def test_try_fetch_result_success(self, mock_get: MagicMock, docling_client: DoclingClient) -> None:
        """Test successful result fetch."""
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {"document": {"content": "test"}}

        result = docling_client._try_fetch_result(httpx.Client(), "task_123")
        assert result == {"document": {"content": "test"}}

    @patch("httpx.Client.get")
    def test_try_fetch_result_http_error_404(self, mock_get: MagicMock, docling_client: DoclingClient) -> None:
        """Test result fetch returns None on HTTPStatusError 404."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.side_effect = httpx.HTTPStatusError("Not found", request=MagicMock(), response=mock_response)

        result = docling_client._try_fetch_result(httpx.Client(), "task_123")
        assert result is None

    @patch("httpx.Client.get")
    def test_fetch_result_success(self, mock_get: MagicMock, docling_client: DoclingClient) -> None:
        """Test _fetch_result returns result data."""
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {"document": {"content": "test"}}

        result = docling_client._fetch_result(httpx.Client(), "task_123")
        assert result == {"document": {"content": "test"}}

    def test_extract_json_content_list_of_documents(self, docling_client: DoclingClient) -> None:
        """Test extracting json_content from list of documents."""
        document = {"json_content": {"key": "value"}}
        assert docling_client._extract_json_content(document) == {"key": "value"}

    def test_extract_json_content_no_json_content(self, docling_client: DoclingClient) -> None:
        """Test extracting returns None when no json_content."""
        document = {"other_key": "value"}
        assert docling_client._extract_json_content(document) is None

    def test_extract_json_content_invalid_json_content_type(self, docling_client: DoclingClient) -> None:
        """Test returns None when json_content is not a dict."""
        document = {"json_content": "not a dict"}
        assert docling_client._extract_json_content(document) is None

    def test_extract_document(self, docling_client: DoclingClient) -> None:
        """Test extracting current document payload from result response."""
        single = {"document": {"json_content": {"foo": "bar"}}}
        many = {"documents": [{"json_content": {"baz": "qux"}}]}

        assert docling_client._extract_document(single) == {"json_content": {"foo": "bar"}}
        assert docling_client._extract_document(many) == {"json_content": {"baz": "qux"}}
        assert docling_client._extract_document({}) is None

    def test_parse_result_prefers_current_document_fields(self, docling_client: DoclingClient) -> None:
        """Test result parsing prefers current md/html document fields."""
        result = {
            "status": "success",
            "document": {
                "md_content": "# Parsed markdown",
                "html_content": "<p>Parsed html</p>",
                "json_content": {
                    "body": {"children": []},
                    "tables": [{"id": "t1"}, {"id": "t2"}],
                    "pictures": {"p1": {}, "p2": {}, "p3": {}},
                },
            },
        }

        parsed = docling_client._parse_result(result, "content-1", ProcessingOptions())

        assert parsed.content_id == "content-1"
        assert parsed.markdown == "# Parsed markdown"
        assert parsed.html == "<p>Parsed html</p>"
        assert parsed.table_count == 2
        assert parsed.image_count == 3

    def test_parse_result_rejects_non_success_status(self, docling_client: DoclingClient) -> None:
        """Test result parsing rejects failed result payloads."""
        result = {
            "status": "failure",
            "errors": ["converter crashed"],
            "document": {},
        }

        with pytest.raises(ValueError, match="Docling result was not successful: converter crashed"):
            docling_client._parse_result(result, "content-2", ProcessingOptions())
