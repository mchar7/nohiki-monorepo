"""Command-line interface for the document generator using API calls."""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import aiohttp
from fastapi import status
from nohiki_observability import Observability, get_logger

# Constants
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_QUALITY = 100
MIN_IMAGE_DIMENSION = 1
MIN_IMAGE_QUALITY = 0

# Error messages
_API_CONNECTION_ERROR_MSG = "Failed to connect to the document generator API"
_API_ERROR_MSG = "API request failed"


def setup_logging(*, verbose: bool) -> None:
    """Set up logging for the CLI."""
    level = "DEBUG" if verbose else "INFO"
    obs = (
        Observability.builder()
        .service("doc-generator-cli", "1.0.0")
        .environment("development")
        .otel_endpoint(None)
        .log_level(level)
        .build()
    )
    obs.init()

    if not verbose:
        # Suppress noisy HTTP libraries in non-verbose mode
        logging.getLogger("aiohttp").setLevel(logging.WARNING)
        logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def is_valid_url(url: str) -> bool:
    """Validate if a string is a valid HTTP URL."""
    try:
        result = urlparse(url)
        return bool(result.scheme in ("http", "https") and result.netloc)
    except ValueError:
        return False


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Generate HTML, PDF, and image documents from JSON data via API")
    parser.add_argument("--data", type=str, required=True, help="Path to the JSON file with document data")
    parser.add_argument(
        "--template",
        type=str,
        default="resume_template.html",
        help="Name of the template to use (from templates directory)",
    )
    parser.add_argument("--output", type=str, default=None, help="Path to save the generated document")
    parser.add_argument(
        "--format",
        type=str,
        choices=["html", "pdf", "image"],
        default="html",
        help="Output format (html, pdf, or image)",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default="http://localhost:8000",
        help="URL of the document generator API (default: http://localhost:8000)",
    )

    # Image-specific options
    parser.add_argument(
        "--image-format",
        type=str,
        choices=["png", "jpeg", "webp"],
        default="png",
        help="Image format when --format=image (default: png)",
    )
    parser.add_argument(
        "--image-width",
        type=int,
        default=800,
        help="Image width in pixels when --format=image (default: 800)",
    )
    parser.add_argument(
        "--image-height",
        type=int,
        default=600,
        help="Image height in pixels when --format=image (default: 600)",
    )
    parser.add_argument(
        "--image-quality",
        type=int,
        default=90,
        help="Image quality 0-100 for JPEG format (default: 90)",
    )
    parser.add_argument(
        "--image-clip",
        action="store_true",
        help="Clip image according to device dimensions",
    )
    parser.add_argument(
        "--image-omit-background",
        action="store_true",
        help="Hide default white background and allow transparency",
    )
    parser.add_argument(
        "--image-optimize-speed",
        action="store_true",
        help="Optimize image encoding for speed, not size",
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output with detailed error messages"
    )

    args = parser.parse_args()

    if not is_valid_url(args.api_url):
        parser.error(f"Invalid API URL: {args.api_url}")

    # Validate image-specific arguments
    if args.format == "image":
        if not MIN_IMAGE_DIMENSION <= args.image_width <= MAX_IMAGE_DIMENSION:
            parser.error(f"--image-width must be between {MIN_IMAGE_DIMENSION} and {MAX_IMAGE_DIMENSION}")
        if not MIN_IMAGE_DIMENSION <= args.image_height <= MAX_IMAGE_DIMENSION:
            parser.error(f"--image-height must be between {MIN_IMAGE_DIMENSION} and {MAX_IMAGE_DIMENSION}")
        if not MIN_IMAGE_QUALITY <= args.image_quality <= MAX_IMAGE_QUALITY:
            parser.error(f"--image-quality must be between {MIN_IMAGE_QUALITY} and {MAX_IMAGE_QUALITY}")

    return args


async def read_json_file(file_path: Path) -> dict[str, Any]:
    """Read and parse a JSON file."""
    file_content = await asyncio.to_thread(file_path.read_text)
    parsed = json.loads(file_content)
    if not isinstance(parsed, dict):
        msg = "JSON data must be an object"
        raise TypeError(msg)
    return cast("dict[str, Any]", parsed)


async def read_template_file(template_path: Path) -> str:
    """Read template file content."""
    return await asyncio.to_thread(template_path.read_text)


def setup_output_path(data_path: Path, output: str | None, format_type: str, image_format: str | None = None) -> Path:
    """Set up the output path for the generated document."""
    if output:
        return Path(output)

    output_dir = Path("./generated_documents")
    output_dir.mkdir(exist_ok=True)

    if format_type == "image" and image_format:
        # Map image format to file extension
        extension_map = {"jpeg": "jpg", "png": "png", "webp": "webp"}
        extension = extension_map.get(image_format, image_format)
        return output_dir / f"{data_path.stem}.{extension}"

    return output_dir / f"{data_path.stem}.{format_type}"


def create_image_options(args: argparse.Namespace) -> dict[str, Any] | None:
    """Create image options dictionary from command line arguments."""
    if args.format != "image":
        return None

    return {
        "format": args.image_format,
        "width": args.image_width,
        "height": args.image_height,
        "clip": args.image_clip,
        "quality": args.image_quality,
        "omit_background": args.image_omit_background,
        "optimize_for_speed": args.image_optimize_speed,
    }


async def generate_document_via_api(
    api_url: str,
    template_content: str,
    data: dict[str, Any],
    output_format: str,
    image_options: dict[str, Any] | None = None,
) -> bytes:
    """Generate document content via API call."""
    logger = get_logger(__name__)

    # Prepare the request payload
    payload = {
        "template": template_content,
        "data": data,
        "output_format": output_format,
    }

    if image_options:
        payload["image_options"] = image_options

    # Make the API request
    endpoint = f"{api_url.removesuffix('/')}/api/v1/templates/generate"

    timeout = aiohttp.ClientTimeout(total=300)  # 5 minutes timeout for document generation

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            logger.debug("Making API request", endpoint=endpoint, format=output_format)

            async with session.post(endpoint, json=payload) as response:
                if response.status == status.HTTP_200_OK:
                    content = await response.read()
                    logger.debug("API request successful", content_length=len(content))
                    return content
                error_text = await response.text()
                logger.exception("API request failed", status=response.status, error=error_text)

                try:
                    error_data = json.loads(error_text)
                    error_message = error_data.get("message", error_text)
                except json.JSONDecodeError:
                    error_message = error_text

                api_error_msg = f"{_API_ERROR_MSG}: {response.status} - {error_message}"
                raise RuntimeError(api_error_msg)

    except aiohttp.ClientError as e:
        logger.exception("API connection failed", error=str(e))
        connection_error_msg = f"{_API_CONNECTION_ERROR_MSG}: {e}"
        raise RuntimeError(connection_error_msg) from e


async def main() -> int:
    """Run the document generator via API."""
    args = parse_args()
    setup_logging(verbose=args.verbose)

    logger = get_logger(__name__)

    try:
        data_path = Path(args.data)

        # Set up image options if format is image
        image_options = create_image_options(args)

        output_path = setup_output_path(
            data_path, args.output, args.format, args.image_format if args.format == "image" else None
        )

        # Read input data
        data = await read_json_file(data_path)
        template_path = Path("./templates") / args.template

        if not template_path.exists():
            logger.error("Template file not found", template=args.template, path=str(template_path))
            return 1

        template_content = await read_template_file(template_path)

        if args.format == "image":
            logger.info(
                "Generating document via API",
                format=args.format.upper(),
                image_format=args.image_format,
                template=args.template,
                api_url=args.api_url,
            )
        else:
            logger.info(
                "Generating document via API",
                format=args.format.upper(),
                template=args.template,
                api_url=args.api_url,
            )

        # Generate document via API
        content = await generate_document_via_api(args.api_url, template_content, data, args.format, image_options)

        # Save the generated content
        if args.format == "html":
            # For HTML, decode bytes to string before writing
            output_path.write_text(content.decode("utf-8"))
        else:
            # For PDF and images, write bytes directly
            output_path.write_bytes(content)

        logger.info("Document saved", path=str(output_path))

    except json.JSONDecodeError, OSError, RuntimeError:
        logger.exception("Error processing document")
        return 1
    else:
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
