"""Output format handling for document generation.

Provides format-specific generation and streaming functions.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, TypedDict, Unpack

from nohiki_observability import get_logger

from doc_template_service.core.generator.errors import GenerationError
from doc_template_service.core.generator.streaming import (
    generate_image_content,
    stream_html_chunks,
    stream_image_chunks,
    stream_pdf_chunks,
    stream_text_chunks,
)
from doc_template_service.core.generator.text_conversion import convert_html_to_text
from doc_template_service.schemas.models import ImageOptions
from doc_template_service.services.gotenberg import get_gotenberg_service

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from doc_template_service.core.templates.jinja_engine import EnvironmentConfig


logger = get_logger(__name__)

LOG_DOC_GEN_COMPLETED = "Document generation completed"
LOG_STREAMED_DOC_GEN_COMPLETED = "Streamed document generation completed"
IMAGE_OPTIONS_REQUIRED_MSG = "Image options are required for image format"


class TextAlternativeMode(Enum):
    """Options for text alternative generation."""

    DISABLED = "disabled"
    ENABLED = "enabled"


class DocumentOptions(TypedDict, total=False):
    """Optional parameters for customizing document generation."""

    schema: dict[str, Any] | None
    environment_config: EnvironmentConfig | None
    use_cache: bool
    image_options: ImageOptions | None


async def generate_output(
    rendered_html: str,
    output_format: str,
    text_alternative: TextAlternativeMode,
    **kwargs: Unpack[DocumentOptions],
) -> str | bytes | tuple[str, str]:
    """Generate the final output in the requested format.

    Args:
        rendered_html: Rendered HTML content
        output_format: Target format (html, pdf, image, text)
        text_alternative: Whether to include plain text alternative
        **kwargs: Additional options

    Returns:
        Generated content in requested format

    """
    match output_format:
        case "html":
            if text_alternative == TextAlternativeMode.ENABLED:
                plain_text = convert_html_to_text(rendered_html)
                logger.info(
                    LOG_DOC_GEN_COMPLETED,
                    output_format="html",
                    html_size=len(rendered_html),
                    text_size=len(plain_text),
                )
                return rendered_html, plain_text
            logger.info(
                LOG_DOC_GEN_COMPLETED,
                output_format="html",
                size=len(rendered_html),
            )
            return rendered_html

        case "text":
            logger.debug("Converting HTML to plain text")
            plain_text = convert_html_to_text(rendered_html)
            logger.info(
                LOG_DOC_GEN_COMPLETED,
                output_format="text",
                size=len(plain_text),
            )
            return plain_text

        case "image":
            image_options = kwargs.get("image_options")
            if image_options is None:
                image_options = ImageOptions(format="png")

            logger.debug("Converting HTML to image", format=image_options.format)
            image_content = await generate_image_content(rendered_html, image_options)
            logger.info(
                LOG_DOC_GEN_COMPLETED,
                output_format="image",
                format=image_options.format,
                size=len(image_content),
            )
            return image_content

        case _:
            logger.debug("Converting HTML to PDF")
            gotenberg_service = get_gotenberg_service()
            pdf_content = await gotenberg_service.convert_html_to_pdf(rendered_html)
            logger.info(
                LOG_DOC_GEN_COMPLETED,
                output_format="pdf",
                size=len(pdf_content),
            )
            return pdf_content


async def stream_output_format(
    rendered_html: str,
    output_format: str,
    image_options: ImageOptions | None,
) -> AsyncGenerator[bytes]:
    """Stream output in the requested format.

    Args:
        rendered_html: Rendered HTML content
        output_format: Target format
        image_options: Image options for image format

    Yields:
        Content chunks

    Raises:
        GenerationError: If image format requested without options

    """
    match output_format:
        case "html":
            async for chunk in stream_html_chunks(rendered_html):
                yield chunk
            logger.info(LOG_STREAMED_DOC_GEN_COMPLETED, output_format="html")

        case "text":
            async for chunk in stream_text_chunks(rendered_html):
                yield chunk
            logger.info(LOG_STREAMED_DOC_GEN_COMPLETED, output_format="text")

        case "image":
            if image_options is None:
                raise GenerationError(IMAGE_OPTIONS_REQUIRED_MSG)
            logger.debug("Converting HTML to image with streaming", format=image_options.format)
            async for chunk in stream_image_chunks(rendered_html, image_options):
                yield chunk
            logger.info(LOG_STREAMED_DOC_GEN_COMPLETED, output_format="image", format=image_options.format)

        case _:
            logger.debug("Converting HTML to PDF with streaming")
            async for chunk in stream_pdf_chunks(rendered_html):
                yield chunk
            logger.info(LOG_STREAMED_DOC_GEN_COMPLETED, output_format="pdf")
