"""Streaming utilities for document generation.

Provides chunked streaming for memory-efficient document delivery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from doc_template_service.core.generator.text_conversion import convert_html_to_text
from doc_template_service.services.gotenberg import ScreenshotOptions, get_gotenberg_service

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from doc_template_service.schemas.models import ImageOptions

DEFAULT_CHUNK_SIZE = 16384


async def stream_pdf_chunks(html: str) -> AsyncGenerator[bytes]:
    """Stream PDF content in chunks.

    Args:
        html: HTML content to convert to PDF

    Yields:
        PDF content chunks

    """
    gotenberg_service = get_gotenberg_service()
    pdf_content = await gotenberg_service.convert_html_to_pdf(html)

    for i in range(0, len(pdf_content), DEFAULT_CHUNK_SIZE):
        yield pdf_content[i : i + DEFAULT_CHUNK_SIZE]


async def stream_html_chunks(html: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> AsyncGenerator[bytes]:
    """Stream HTML content in chunks.

    Args:
        html: HTML content to stream
        chunk_size: Size of each chunk in bytes

    Yields:
        HTML content chunks as bytes

    """
    html_bytes = html.encode("utf-8")
    for i in range(0, len(html_bytes), chunk_size):
        yield html_bytes[i : i + chunk_size]


async def stream_image_chunks(html: str, image_options: ImageOptions) -> AsyncGenerator[bytes]:
    """Stream image content in chunks.

    Args:
        html: HTML content to convert to image
        image_options: Image generation options

    Yields:
        Image content chunks

    """
    image_content = await generate_image_content(html, image_options)

    for i in range(0, len(image_content), DEFAULT_CHUNK_SIZE):
        yield image_content[i : i + DEFAULT_CHUNK_SIZE]


async def generate_image_content(html: str, image_options: ImageOptions) -> bytes:
    """Generate image content from HTML.

    Args:
        html: HTML content to convert
        image_options: Image generation options

    Returns:
        Image content as bytes

    """
    gotenberg_service = get_gotenberg_service()
    screenshot_options = ScreenshotOptions(
        image_format=image_options.format,
        width=image_options.width or 800,
        height=image_options.height or 600,
        quality=image_options.quality or 90,
    )
    return await gotenberg_service.screenshot_html(html, screenshot_options)


async def stream_text_chunks(html: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> AsyncGenerator[bytes]:
    """Stream text content in chunks.

    Args:
        html: HTML content to convert to text
        chunk_size: Size of each chunk in bytes

    Yields:
        Text content chunks as bytes

    """
    text_content = convert_html_to_text(html)
    text_bytes = text_content.encode("utf-8")

    for i in range(0, len(text_bytes), chunk_size):
        yield text_bytes[i : i + chunk_size]
