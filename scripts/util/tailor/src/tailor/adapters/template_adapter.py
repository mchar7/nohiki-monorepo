"""Template rendering adapter wrapping doc-template-service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Never, TypeGuard

import httpx
from doc_template_service.core.generator import (
    GenerationError as DocTemplateGenerationError,
)
from doc_template_service.core.generator import generate_document
from doc_template_service.schemas.models import ImageOptions
from doc_template_service.services.gotenberg import GotenbergService
from nohiki_observability import get_logger

from tailor.core.types import ImageFormat, JsonDict, RenderOutputFormat
from tailor.exceptions import GotenbergError, RenderError
from tailor.models.outputs import RenderResult

if TYPE_CHECKING:
    from tailor.core.config import TailorSettings

logger = get_logger(__name__)

_CONTENT_TYPE_HTML = "text/html"
_CONTENT_TYPE_PDF = "application/pdf"
_CONTENT_TYPE_TEXT = "text/plain"
_CONTENT_TYPE_IMAGE_PREFIX = "image/"


def _is_image_format(value: RenderOutputFormat) -> TypeGuard[ImageFormat]:
    """Narrow output format to supported image formats."""
    return value in {"png", "jpeg", "webp"}


class TailorTemplateAdapter:
    """Adapter wrapping doc-template-service for template rendering."""

    def __init__(self, settings: TailorSettings) -> None:
        """Initialize with settings."""
        self._settings = settings
        self._gotenberg = GotenbergService(
            base_url=settings.gotenberg_url,
            timeout=settings.gotenberg_timeout_s,
        )

    async def render(
        self,
        template_content: str,
        data: JsonDict,
        output_format: RenderOutputFormat = "pdf",
    ) -> RenderResult:
        """Render template with data and convert to output format."""
        try:
            result = await self._render_document(template_content, data, output_format)
        except (
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
            httpx.HTTPError,
            DocTemplateGenerationError,
        ) as e:
            self._handle_render_error(e, output_format)

        return self._build_render_result(result, output_format)

    def _build_render_result(
        self,
        result: str | bytes | tuple[str, str],
        output_format: RenderOutputFormat,
    ) -> RenderResult:
        """Build RenderResult from generate_document output."""
        content = result[0] if isinstance(result, tuple) else result
        match output_format:
            case "pdf":
                content_type = _CONTENT_TYPE_PDF
            case "html":
                content_type = _CONTENT_TYPE_HTML
            case "text":
                content_type = _CONTENT_TYPE_TEXT
            case _:
                content_type = f"{_CONTENT_TYPE_IMAGE_PREFIX}{output_format}"

        size_bytes = len(content.encode("utf-8")) if isinstance(content, str) else len(content)

        logger.info("Template rendered", output_format=output_format, size_bytes=size_bytes)
        return RenderResult(content=content, content_type=content_type, size_bytes=size_bytes)

    def _handle_render_error(self, error: Exception, output_format: str) -> Never:
        """Classify and re-raise render errors as typed tailor exceptions."""
        logger.exception("Template rendering failed")
        error_str = str(error).lower()

        if "gotenberg" in error_str or "connection" in error_str:
            msg = f"Gotenberg service error: {error}"
            raise GotenbergError(msg) from error

        msg = f"Template rendering failed: {error}"
        raise RenderError(msg, output_format=output_format) from error

    @staticmethod
    async def _render_document(
        template_content: str,
        data: JsonDict,
        output_format: RenderOutputFormat,
    ) -> str | bytes | tuple[str, str]:
        """Render document with image format mapping when needed."""
        if _is_image_format(output_format):
            return await generate_document(
                template=template_content,
                data=data,
                output_format="image",
                image_options=ImageOptions(format=output_format),
                use_cache=False,
            )

        match output_format:
            case "html":
                doc_output_format: Literal["html"] = "html"
            case "pdf":
                doc_output_format: Literal["pdf"] = "pdf"
            case _:
                doc_output_format: Literal["text"] = "text"

        return await generate_document(
            template=template_content,
            data=data,
            output_format=doc_output_format,
            use_cache=False,
        )

    async def health_check(self) -> bool:
        """Check if Gotenberg service is available."""
        try:
            return await self._gotenberg.health_check()
        except OSError:
            logger.warning("Gotenberg health check failed")
            return False

    async def ensure_gotenberg_available(self) -> None:
        """Ensure Gotenberg is available, raise if not."""
        if not await self.health_check():
            msg = (
                f"Gotenberg service not available at {self._settings.gotenberg_url}. "
                "Start it with: sh infra/compose/scripts/preflight.sh up -d nohiki-infra-gotenberg"
            )
            raise GotenbergError(msg)
