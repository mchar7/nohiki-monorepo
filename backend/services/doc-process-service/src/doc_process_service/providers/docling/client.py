"""Docling Serve HTTP client for document processing."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from enum import Enum
from io import BytesIO
from typing import TYPE_CHECKING, Final
from zipfile import BadZipFile, ZipFile

import httpx
from nohiki.doc.process.v1 import ProcessedDocumentSnapshot

from doc_process_service.models.domain import ProcessingOptions, ProcessingResult
from doc_process_service.providers.docling.config import DoclingClientConfig

if TYPE_CHECKING:
    from doc_process_service.core.config import DoclingSettings, VLMSettings

logger = logging.getLogger(__name__)

_HTTP_OK: Final[int] = 200
_HTTP_NOT_FOUND: Final[int] = 404
_HTTP_TOO_MANY_REQUESTS: Final[int] = 429
_HTTP_SERVER_ERROR: Final[int] = 500

_MIME_SVG: Final[str] = "image/svg+xml"
_MIME_PDF: Final[str] = "application/pdf"
_MIME_DOCX: Final[str] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_MIME_SIGNATURES: Final[tuple[tuple[bytes, str], ...]] = (
    (b"<svg", _MIME_SVG),
    (b"<?xml", _MIME_SVG),
    (b"\x89PNG", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
    (b"RIFF", "image/webp"),
    (b"%PDF", _MIME_PDF),
)


class _TaskStatus(Enum):
    """Document processing task status values from docling-serve."""

    PENDING = "pending"
    QUEUED = "queued"
    STARTED = "started"
    SUCCESS = "success"
    FAILURE = "failure"


class DoclingClient:
    """HTTP client for docling-serve with task submission and polling."""

    __slots__ = ("_available", "_config")

    def __init__(self, config: DoclingClientConfig) -> None:
        """Initialize the DoclingClient.

        Args:
            config: Client configuration.

        """
        self._config = config
        self._available: bool | None = None

    @classmethod
    def from_settings(cls, docling: DoclingSettings, vlm: VLMSettings) -> DoclingClient:
        """Create client from settings.

        Args:
            docling: Docling provider settings.
            vlm: VLM settings.

        Returns:
            Configured DoclingClient instance.

        """
        config = DoclingClientConfig.from_settings(docling, vlm)
        return cls(config)

    @property
    def name(self) -> str:
        """Provider identifier."""
        return "docling"

    def is_available(self) -> bool:
        """Check readiness endpoint with cached result."""
        if self._available is not None:
            return self._available

        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self._config.base_url}/ready")
                if resp.status_code == _HTTP_OK:
                    self._available = True
                    return True
        except httpx.RequestError:
            pass

        return False

    def reset_availability(self) -> None:
        """Reset cached availability for circuit breaker recovery."""
        self._available = None

    def process(
        self,
        content: bytes,
        content_id: str,
        options: ProcessingOptions,
    ) -> ProcessingResult:
        """Process document via async API with polling.

        Args:
            content: Raw document bytes.
            content_id: Opaque content identifier.
            options: Processing configuration.

        Returns:
            ProcessingResult with extracted content or error details.

        """
        if not self.is_available():
            return ProcessingResult(error="Processing service unavailable", is_retryable=True)

        try:
            processed = self._process_document(content, content_id, options)
            return ProcessingResult(content=processed)
        except httpx.HTTPStatusError as e:
            logger.warning("Processing failed: %s", e)
            return ProcessingResult(
                error="Document processing failed",
                is_retryable=e.response.status_code == _HTTP_TOO_MANY_REQUESTS
                or e.response.status_code >= _HTTP_SERVER_ERROR,
            )
        except (httpx.RequestError, TimeoutError) as e:
            logger.warning("Processing failed: %s", e)
            return ProcessingResult(error="Document processing failed", is_retryable=True)
        except ValueError as e:
            logger.warning("Processing failed: %s", e)
            return ProcessingResult(error="Document processing failed")

    async def process_async(
        self,
        content: bytes,
        content_id: str,
        options: ProcessingOptions,
    ) -> ProcessingResult:
        """Process document asynchronously.

        Args:
            content: Raw document bytes.
            content_id: Opaque content identifier.
            options: Processing configuration.

        Returns:
            ProcessingResult with extracted content or error details.

        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.process, content, content_id, options)

    def _process_document(
        self,
        content: bytes,
        content_id: str,
        options: ProcessingOptions,
    ) -> ProcessedDocumentSnapshot:
        """Process document via async API with polling."""
        mime_type = self._detect_mime_type(content)

        with httpx.Client(timeout=self._config.timeout) as client:
            task_id = self._submit_task(client, content, mime_type)
            result = self._poll_for_result(client, task_id)
            return self._parse_result(result, content_id, options)

    def _submit_task(self, client: httpx.Client, content: bytes, mime_type: str) -> str:
        """Submit document for async processing."""
        filename = (
            "image"
            if mime_type.startswith("image/")
            else "document.docx"
            if mime_type == _MIME_DOCX
            else "document.pdf"
        )

        files: list[tuple[str, tuple[str | None, str | bytes, str | None]]] = [
            ("files", (filename, content, mime_type)),
            ("to_formats", (None, "md", None)),
            ("to_formats", (None, "html", None)),
            ("to_formats", (None, "json", None)),
            ("pipeline", (None, self._config.pipeline, None)),
            ("pdf_backend", (None, self._config.pdf_backend, None)),
            ("do_ocr", (None, str(self._config.do_ocr).lower(), None)),
            ("force_ocr", (None, str(self._config.force_ocr).lower(), None)),
            ("ocr_engine", (None, self._config.ocr_engine, None)),
            ("table_mode", (None, self._config.table_mode, None)),
            ("do_table_structure", (None, str(self._config.do_table_structure).lower(), None)),
            ("include_images", (None, str(self._config.include_images).lower(), None)),
            ("do_picture_description", (None, str(self._config.do_picture_description).lower(), None)),
        ]

        if self._config.do_picture_description and self._config.picture_description_custom_config:
            files.append(
                (
                    "picture_description_custom_config",
                    (None, self._config.picture_description_custom_config, None),
                )
            )

        response = client.post(
            f"{self._config.base_url}/v1/convert/file/async",
            files=files,
            headers=self._build_headers(),
        )
        response.raise_for_status()

        if task_id := response.json().get("task_id"):
            return task_id
        msg = "No task_id in response"
        raise ValueError(msg)

    def _poll_for_result(self, client: httpx.Client, task_id: str) -> dict:
        """Poll for task completion and fetch result."""
        headers = self._build_headers()
        poll_url = f"{self._config.base_url}/v1/status/poll/{task_id}"
        deadline = time.monotonic() + self._config.max_poll_attempts * self._config.poll_interval

        for _ in range(self._config.max_poll_attempts):
            if time.monotonic() >= deadline:
                break
            if result := self._poll_once(client, poll_url, task_id, headers, deadline):
                return result

        msg = f"Timeout waiting for task {task_id}"
        raise TimeoutError(msg)

    def _poll_once(
        self,
        client: httpx.Client,
        poll_url: str,
        task_id: str,
        headers: dict[str, str],
        deadline: float,
    ) -> dict | None:
        """Execute single poll attempt."""
        try:
            wait_seconds = min(self._config.poll_interval, max(0.0, deadline - time.monotonic()))
            response = client.get(poll_url, headers=headers, params={"wait": wait_seconds})
            return self._handle_poll_response(client, response, task_id, deadline)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == _HTTP_NOT_FOUND:
                return self._handle_404_during_poll(client, task_id, deadline)
            raise

    def _handle_poll_response(
        self,
        client: httpx.Client,
        response: httpx.Response,
        task_id: str,
        deadline: float,
    ) -> dict | None:
        """Handle poll response and return result if ready."""
        if response.status_code == _HTTP_NOT_FOUND:
            return self._handle_404_during_poll(client, task_id, deadline)

        response.raise_for_status()
        data = response.json()

        try:
            status = _TaskStatus(data.get("task_status", "pending"))
        except ValueError:
            return None

        if status == _TaskStatus.SUCCESS:
            return self._fetch_result(client, task_id)
        if status == _TaskStatus.FAILURE:
            error = data.get("error_message") or "Unknown error"
            msg = f"Task failed: {error}"
            raise ValueError(msg)
        # PENDING, QUEUED, STARTED
        return None

    def _handle_404_during_poll(self, client: httpx.Client, task_id: str, deadline: float) -> dict | None:
        """Handle 404 by checking if result is available directly."""
        if result := self._try_fetch_result(client, task_id):
            return result
        time.sleep(min(self._config.poll_interval, max(0.0, deadline - time.monotonic())))
        return None

    def _try_fetch_result(self, client: httpx.Client, task_id: str) -> dict | None:
        """Try to fetch result, returning None if not available."""
        result_url = f"{self._config.base_url}/v1/result/{task_id}"
        try:
            response = client.get(result_url, headers=self._build_headers())
            if response.status_code == _HTTP_NOT_FOUND:
                return None
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == _HTTP_NOT_FOUND:
                return None
            raise

    def _fetch_result(self, client: httpx.Client, task_id: str) -> dict:
        """Fetch the completed task result."""
        result_url = f"{self._config.base_url}/v1/result/{task_id}"
        response = client.get(result_url, headers=self._build_headers())
        response.raise_for_status()
        return response.json()

    def _parse_result(
        self,
        result: dict,
        content_id: str,
        options: ProcessingOptions,
    ) -> ProcessedDocumentSnapshot:
        """Parse docling-serve result into ProcessedDocumentSnapshot."""
        self._raise_for_result_status(result)
        document = self._extract_document(result)
        json_content = self._extract_json_content(document)
        if not json_content:
            msg = "No json_content in docling response"
            raise ValueError(msg)

        markdown = document.get("md_content", "") if document else ""
        html = document.get("html_content", "") if document else ""
        serialized = json.dumps(json_content)

        return ProcessedDocumentSnapshot(
            content_id=content_id,
            content_hash="",
            level=options.level,
            markdown=markdown,
            html=html,
            table_count=self._count_items(json_content, "tables"),
            image_count=self._count_items(json_content, "pictures"),
            serialized_document=serialized,
        )

    def _raise_for_result_status(self, result: dict) -> None:
        """Validate top-level Docling result status before parsing content."""
        status = result.get("status")
        if status in {None, "success", "partial_success"}:
            return

        errors = result.get("errors")
        error_detail = "; ".join(str(error) for error in errors) if isinstance(errors, list) and errors else str(status)
        msg = f"Docling result was not successful: {error_detail}"
        raise ValueError(msg)

    def _extract_document(self, result: dict) -> dict | None:
        """Extract the primary document payload from a result response."""
        documents = result.get("document", result.get("documents", []))
        if isinstance(documents, dict):
            return documents

        if not documents:
            return None

        doc = documents[0] if isinstance(documents, list) else documents
        return doc if isinstance(doc, dict) else None

    def _extract_json_content(self, document: dict | None) -> dict | None:
        """Extract json_content (DoclingDocument structure) from a document payload."""
        if not document:
            return None

        json_content = document.get("json_content")

        return json_content if isinstance(json_content, dict) else None

    def _count_items(self, json_content: dict, field: str) -> int:
        """Count extracted items from modern DoclingDocument collection fields."""
        value = json_content.get(field)
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return len(value)
        return 0

    def _build_headers(self) -> dict[str, str]:
        """Build request headers."""
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._config.api_key:
            headers["X-Api-Key"] = self._config.api_key
        return headers

    def _detect_mime_type(self, content: bytes) -> str:
        """Detect MIME type from content bytes using signature matching."""
        for signature, mime_type in _MIME_SIGNATURES:
            if content.startswith(signature):
                return mime_type
        if content.startswith(b"PK\x03\x04"):
            try:
                with ZipFile(BytesIO(content)) as archive:
                    archive.getinfo("word/document.xml")
            except BadZipFile, KeyError:
                pass
            else:
                return _MIME_DOCX
        return _MIME_PDF
