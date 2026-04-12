"""Gotenberg service integration.

An async HTTP client for interacting with Gotenberg service
to convert HTML content to PDF using the /forms/chromium/convert/html endpoint.

Uses circuit breaker pattern for resilience against transient failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import httpx
from fastapi import status
from httpx import AsyncClient
from nohiki_observability import get_logger
from nohiki_redis_utils import CircuitBreakerConfig, circuit_breaker

from doc_template_service.core.config import get_settings
from doc_template_service.core.html.js_detector import detect_javascript

logger = get_logger(__name__)
settings = get_settings()

# Constants
HEALTH_CHECK_TIMEOUT = 2.0
CHUNK_SIZE = 16384  # 16KB
INDEX_HTML_FILENAME = "index.html"
CONTENT_TYPE_HTML = "text/html"
MAX_RESPONSE_SIZE_BYTES = 25 * 1024 * 1024
_NETWORK_ISOLATION_CSP = (
    '<meta http-equiv="Content-Security-Policy" '
    "content=\"default-src 'none'; base-uri 'none'; form-action 'none'; "
    "img-src data:; font-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'\">"
)


def _apply_network_isolation_csp(html_content: str) -> str:
    """Prevent rendered templates from making network or local-file requests."""
    lower_html = html_content.lower()
    head_start = lower_html.find("<head")
    head_end = lower_html.find(">", head_start) if head_start >= 0 else -1
    if head_end < 0:
        return _NETWORK_ISOLATION_CSP + html_content
    return html_content[: head_end + 1] + _NETWORK_ISOLATION_CSP + html_content[head_end + 1 :]


# Circuit breaker configuration
GOTENBERG_CIRCUIT_NAME = "gotenberg"
GOTENBERG_FAILURE_THRESHOLD = 3
GOTENBERG_TIMEOUT_SECONDS = 30.0

type MultipartFormData = dict[str, tuple[str | None, bytes | str, str]]

_PAGE_SIZES_INCHES: dict[str, tuple[str, str]] = {
    "letter": ("8.5", "11"),
    "a4": ("8.27", "11.69"),
}
_DEFAULT_PAGE_SIZE: str = "letter"
_DEFAULT_MARGINS: dict[str, str] = {
    "marginTop": "0.75",
    "marginBottom": "0.75",
    "marginLeft": "0.75",
    "marginRight": "0.75",
}


@dataclass(frozen=True, slots=True)
class GotenbergRequestConfig:
    """Configuration for a Gotenberg API request."""

    endpoint: str
    html_content: str
    accept_header: str
    extra_form_data: dict[str, str] | None = None


class ScreenshotOptions(NamedTuple):
    """Screenshot generation options."""

    image_format: str
    width: int = 800
    height: int = 600
    clip: bool = False
    quality: int = 100
    omit_background: bool = False
    optimize_for_speed: bool = False


class GotenbergError(Exception):
    """Exception raised for errors in the Gotenberg service."""

    def __init__(self, message: str, status_code: int | None = None, response_text: str | None = None) -> None:
        """Initialize the GotenbergError exception.

        Args:
            message: Error message
            status_code: Optional HTTP status code
            response_text: Optional response text from Gotenberg

        """
        self.message = message
        self.status_code = status_code
        self.response_text = response_text
        super().__init__(self.message)


class GotenbergService:
    """Client for interacting with Gotenberg PDF conversion service."""

    def __init__(
        self, base_url: str = str(settings.gotenberg.base_url), timeout: int = settings.gotenberg.request_timeout_s
    ) -> None:
        """Initialize the Gotenberg service client.

        Args:
            base_url: Base URL of the Gotenberg service
            timeout: Request timeout in seconds

        """
        self.base_url = base_url.removesuffix("/")
        self.timeout = timeout
        self.convert_endpoint = f"{self.base_url}/forms/chromium/convert/html"
        self.screenshot_endpoint = f"{self.base_url}/forms/chromium/screenshot/html"
        logger.debug("GotenbergService ready", base_url=base_url, timeout=timeout)

    @staticmethod
    def _reject_meta_refresh(html_content: str) -> None:
        """Reject browser navigation directives before constructing a request."""
        if any(issue.keyword == "meta_refresh" for issue in detect_javascript(html_content)):
            msg = "Meta refresh directives are not allowed"
            raise GotenbergError(msg)

    def _build_form_data(self, html_content: str, extra_data: dict[str, str] | None = None) -> MultipartFormData:
        """Build multipart form data for Gotenberg request."""
        self._reject_meta_refresh(html_content)
        protected_html = _apply_network_isolation_csp(html_content)
        files: MultipartFormData = {
            "files": (INDEX_HTML_FILENAME, protected_html.encode("utf-8"), CONTENT_TYPE_HTML),
        }
        if extra_data:
            for key, value in extra_data.items():
                files[key] = (None, value, "text/plain")

        return files

    def _build_screenshot_form_data(self, html_content: str, options: ScreenshotOptions) -> MultipartFormData:
        """Build form data specifically for screenshot requests."""
        extra_data: dict[str, str] = {
            "width": str(options.width),
            "height": str(options.height),
            "clip": "true" if options.clip else "false",
            "format": options.image_format,
            "omitBackground": "true" if options.omit_background else "false",
            "optimizeForSpeed": "true" if options.optimize_for_speed else "false",
            "preferCssPageSize": "true",
            "printBackground": "true",
            # Generated HTML is self-contained; waiting for network idle is unnecessary
            # and external resource loading can stall Chromium past the 30s deadline.
            "skipNetworkIdleEvent": "true",
        }

        if options.image_format == "jpeg":
            extra_data["quality"] = str(options.quality)

        return self._build_form_data(html_content, extra_data)

    @staticmethod
    def _parse_page_size(page_size: str) -> tuple[str, str]:
        key = page_size.strip().lower()
        if key not in _PAGE_SIZES_INCHES:
            msg = f"Unsupported page size: {page_size}"
            raise ValueError(msg)
        return _PAGE_SIZES_INCHES[key]

    def _build_pdf_form_data(
        self,
        html_content: str,
        page_size: str | None = None,
        margins: dict[str, str] | None = None,
    ) -> MultipartFormData:
        """Build form data specifically for PDF conversion requests."""
        extra_data: dict[str, str] = {
            "preferCssPageSize": "true",
            "printBackground": "true",
            "generateTaggedPdf": "true",
        }

        page_width, page_height = self._parse_page_size(page_size if page_size is not None else _DEFAULT_PAGE_SIZE)
        extra_data["paperWidth"] = page_width
        extra_data["paperHeight"] = page_height

        extra_data |= margins if margins is not None else _DEFAULT_MARGINS

        return self._build_form_data(html_content, extra_data)

    async def _execute_gotenberg_request(self, endpoint: str, files: MultipartFormData, accept_header: str) -> bytes:
        """Execute a Gotenberg API request with circuit breaker protection."""
        return await self._execute_request_with_circuit_breaker(endpoint, files, accept_header)

    @circuit_breaker(
        GOTENBERG_CIRCUIT_NAME,
        config=CircuitBreakerConfig(
            failure_threshold=GOTENBERG_FAILURE_THRESHOLD,
            timeout_seconds=GOTENBERG_TIMEOUT_SECONDS,
        ),
        excluded_exceptions=(GotenbergError,),
    )
    async def _execute_request_with_circuit_breaker(
        self, endpoint: str, files: MultipartFormData, accept_header: str
    ) -> bytes:
        """Execute raw request - circuit breaker handles retries/failures."""
        url = f"{self.base_url}{endpoint}"

        async with AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    url,
                    files=files,
                    headers={"Accept": accept_header},
                )
                response.raise_for_status()
                if len(response.content) > MAX_RESPONSE_SIZE_BYTES:
                    msg = f"Gotenberg response exceeds {MAX_RESPONSE_SIZE_BYTES} bytes"
                    raise GotenbergError(msg)
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "Gotenberg HTTP error",
                    endpoint=endpoint,
                    status_code=e.response.status_code,
                )
                msg = f"Gotenberg returned status {e.response.status_code}"
                raise GotenbergError(
                    msg,
                    status_code=e.response.status_code,
                    response_text=e.response.text[:1000],
                ) from e
            except httpx.TimeoutException as e:
                logger.warning("Gotenberg timeout", endpoint=endpoint)
                msg = f"Gotenberg request timed out after {self.timeout}s"
                raise GotenbergError(msg) from e
            except httpx.RequestError as e:
                logger.warning("Gotenberg connection error", endpoint=endpoint, error=str(e))
                msg = f"Failed to connect to Gotenberg: {e}"
                raise GotenbergError(msg) from e
            else:
                return response.content

    async def _execute_gotenberg_streaming_request(
        self, endpoint: str, files: MultipartFormData, accept_header: str
    ) -> AsyncIterator[bytes]:
        """Execute a Gotenberg API request and stream response."""
        url = f"{self.base_url}{endpoint}"

        async with AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream(
                    "POST",
                    url,
                    files=files,
                    headers={"Accept": accept_header},
                ) as response:
                    response.raise_for_status()
                    received_bytes = 0
                    async for chunk in response.aiter_bytes(chunk_size=CHUNK_SIZE):
                        received_bytes += len(chunk)
                        if received_bytes > MAX_RESPONSE_SIZE_BYTES:
                            msg = f"Gotenberg response exceeds {MAX_RESPONSE_SIZE_BYTES} bytes"
                            raise GotenbergError(msg)
                        yield chunk
            except httpx.HTTPStatusError as e:
                logger.exception(
                    "Gotenberg streaming request failed",
                    endpoint=endpoint,
                    status_code=e.response.status_code,
                )
                msg = f"Gotenberg returned status {e.response.status_code}"
                raise GotenbergError(
                    msg,
                    status_code=e.response.status_code,
                ) from e
            except httpx.TimeoutException as e:
                logger.exception(
                    "Gotenberg streaming request timed out",
                    endpoint=endpoint,
                    timeout=self.timeout,
                )
                msg = f"Streaming request to Gotenberg timed out after {self.timeout} seconds"
                raise GotenbergError(msg) from e
            except httpx.RequestError as e:
                logger.exception(
                    "Gotenberg streaming request error",
                    endpoint=endpoint,
                    error=str(e),
                )
                msg = f"Failed to connect to Gotenberg: {e}"
                raise GotenbergError(msg) from e

    async def convert_html_to_pdf(
        self,
        html_content: str,
        _filename: str = "document.pdf",
        *,
        page_size: str | None = None,
        margins: dict[str, str] | None = None,
    ) -> bytes:
        """Convert HTML content to PDF using Gotenberg service.

        Args:
            html_content: Raw HTML content to convert
            _filename: Optional filename for the generated PDF (unused)
            page_size: Optional page size name (e.g., "A4", "Letter")
            margins: Optional margin fields passed to Gotenberg (e.g., "marginTop")

        Returns:
            PDF content as bytes

        Raises:
            GotenbergError: If the conversion fails

        """
        files = self._build_pdf_form_data(html_content, page_size=page_size, margins=margins)
        return await self._execute_gotenberg_request(
            endpoint="/forms/chromium/convert/html",
            files=files,
            accept_header="application/pdf",
        )

    async def convert_html_to_pdf_stream(
        self,
        html_content: str,
        _filename: str = "document.pdf",
        *,
        page_size: str | None = None,
        margins: dict[str, str] | None = None,
    ) -> AsyncIterator[bytes]:
        """Convert HTML content to PDF using Gotenberg service with streaming response.

        Args:
            html_content: Raw HTML content to convert
            _filename: Optional filename for the generated PDF (unused)
            page_size: Optional page size name (e.g., "A4", "Letter")
            margins: Optional margin fields passed to Gotenberg (e.g., "marginTop")

        Yields:
            PDF content chunks as bytes

        Raises:
            GotenbergError: If the conversion fails

        """
        files = self._build_pdf_form_data(html_content, page_size=page_size, margins=margins)
        async for chunk in self._execute_gotenberg_streaming_request(
            endpoint="/forms/chromium/convert/html",
            files=files,
            accept_header="application/pdf",
        ):
            yield chunk

    async def screenshot_html(
        self,
        html_content: str,
        options: ScreenshotOptions,
        _filename: str = "screenshot",
    ) -> bytes:
        """Convert HTML content to image screenshot using Gotenberg service.

        Args:
            html_content: Raw HTML content to convert
            options: Screenshot generation options
            _filename: Optional filename (unused)

        Returns:
            Image content as bytes

        Raises:
            GotenbergError: If the screenshot generation fails

        """
        files = self._build_screenshot_form_data(html_content, options)
        return await self._execute_gotenberg_request(
            endpoint="/forms/chromium/screenshot/html",
            files=files,
            accept_header=f"image/{options.image_format}",
        )

    async def screenshot_html_stream(
        self,
        html_content: str,
        options: ScreenshotOptions,
        _filename: str = "screenshot",
    ) -> AsyncIterator[bytes]:
        """Convert HTML content to image screenshot using Gotenberg service with streaming response.

        Args:
            html_content: Raw HTML content to convert
            options: Screenshot generation options
            _filename: Optional filename (unused)

        Yields:
            Image content chunks as bytes

        Raises:
            GotenbergError: If the screenshot generation fails

        """
        files = self._build_screenshot_form_data(html_content, options)
        async for chunk in self._execute_gotenberg_streaming_request(
            endpoint="/forms/chromium/screenshot/html",
            files=files,
            accept_header=f"image/{options.image_format}",
        ):
            yield chunk

    async def health_check(self) -> bool:
        """Check if the Gotenberg service is accessible.

        Returns:
            True if the service is healthy, False otherwise

        """
        try:
            async with AsyncClient(timeout=HEALTH_CHECK_TIMEOUT) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == status.HTTP_200_OK
        except (httpx.TimeoutException, httpx.RequestError) as err:
            logger.warning("Gotenberg health check failed", error=str(err))
            return False


def get_gotenberg_service() -> GotenbergService:
    """Create and return a GotenbergService instance.

    Returns:
        A configured GotenbergService instance

    """
    return GotenbergService(
        base_url=str(settings.gotenberg.base_url),
        timeout=settings.gotenberg.request_timeout_s,
    )
