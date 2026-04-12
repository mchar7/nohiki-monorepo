"""Main document generation logic.

Provides the primary API for generating documents with validation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Unpack

from nohiki_observability import get_logger

from doc_template_service.core.generator.cache import (
    get_cache_key,
    get_cached_validation_report,
    set_cached_validation_report,
)
from doc_template_service.core.generator.errors import GenerationError
from doc_template_service.core.generator.output_formats import (
    DocumentOptions,
    TextAlternativeMode,
    generate_output,
    stream_output_format,
)
from doc_template_service.core.generator.text_conversion import sanitize_text
from doc_template_service.core.templates.jinja_engine import render_template
from doc_template_service.core.validation import validate_all_with_result

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from doc_template_service.schemas.models import ValidationReport

logger = get_logger(__name__)


async def generate_document(
    template: str,
    data: dict[str, Any],
    output_format: Literal["html", "pdf", "image", "text"] = "html",
    *,
    text_alternative: TextAlternativeMode = TextAlternativeMode.DISABLED,
    **kwargs: Unpack[DocumentOptions],
) -> str | bytes | tuple[str, str]:
    """Generate a complete document with validation and optional PDF conversion.

    Provides a high-level interface for document generation with:
    - Full security validation including JavaScript detection
    - Template environment customization
    - Optional schema validation
    - Caching for improved performance

    Args:
        template: Template source code
        data: Data to render in template
        output_format: Target output format
        text_alternative: Whether to include plain text alternative
        **kwargs: Additional document options

    Returns:
        Generated content in requested format

    Raises:
        GenerationError: If validation fails or rendering errors occur

    """
    schema = kwargs.get("schema")
    environment_config = kwargs.get("environment_config")
    use_cache = kwargs.get("use_cache", True)

    logger.info(
        "Starting document generation",
        output_format=output_format,
        has_schema=schema is not None,
        use_cache=use_cache,
    )

    validation_report, rendered_html = await _validate_inputs_with_result(
        template=template,
        data=data,
        schema=schema,
        use_cache=use_cache,
    )

    if not validation_report.valid:
        issue_details = "; ".join(f"[{i.keyword}] {i.message}" for i in validation_report.issues)
        logger.error("Validation failed", issues_count=len(validation_report.issues), issues=issue_details)
        error_msg = f"Document generation failed: {issue_details}"
        raise GenerationError(error_msg, validation_report=validation_report)

    if rendered_html is None:
        try:
            rendered_html = await render_template(
                template_source=template,
                context=data,
                config=environment_config,
            )
            rendered_html = sanitize_text(rendered_html)
        except Exception as err:
            logger.exception("Template rendering failed")
            error_msg = f"Document generation failed: template error - {err!s}"
            raise GenerationError(error_msg, original_error=err) from err

    return await generate_output(rendered_html, output_format, text_alternative, **kwargs)


async def generate_document_streamed(
    template: str,
    data: dict[str, Any],
    output_format: Literal["html", "pdf", "image", "text"] = "html",
    **kwargs: Unpack[DocumentOptions],
) -> AsyncGenerator[bytes]:
    """Generate and stream document content with validation.

    Memory-efficient streaming approach for large documents with:
    - Full security validation including JavaScript detection
    - Chunked output to prevent memory spikes
    - Support for HTML, PDF, image, and text formats

    Args:
        template: Template source code
        data: Data to render in template
        output_format: Target output format
        **kwargs: Additional document options

    Yields:
        Content chunks

    Raises:
        GenerationError: If validation fails or rendering errors occur

    """
    image_options = kwargs.get("image_options")

    logger.info(
        "Starting streamed document generation",
        output_format=output_format,
        has_schema=kwargs.get("schema") is not None,
        use_cache=kwargs.get("use_cache", True),
    )

    if output_format == "image" and image_options is None:
        msg = "Image options are required for image format"
        raise GenerationError(msg)

    rendered_html = await _validate_and_render(template, data, **kwargs)

    logger.debug("Pre-validation and rendering completed")

    async for chunk in stream_output_format(rendered_html, output_format, image_options):
        yield chunk


async def _validate_and_render(
    template: str,
    data: dict[str, Any],
    **kwargs: Unpack[DocumentOptions],
) -> str:
    """Validate inputs and render the template.

    Args:
        template: Template source code
        data: Data to render
        **kwargs: Additional document options

    Returns:
        Rendered HTML string

    Raises:
        GenerationError: If validation fails

    """
    schema = kwargs.get("schema")
    environment_config = kwargs.get("environment_config")
    use_cache = kwargs.get("use_cache", True)

    validation_report = await _validate_inputs(
        template=template,
        data=data,
        schema=schema,
        use_cache=use_cache,
    )

    if not validation_report.valid:
        issue_details = "; ".join(f"[{i.keyword}] {i.message}" for i in validation_report.issues)
        logger.error("Validation failed", issues_count=len(validation_report.issues), issues=issue_details)
        error_msg = f"Document generation failed: {issue_details}"
        raise GenerationError(error_msg, validation_report=validation_report)

    try:
        rendered_html = await render_template(
            template_source=template,
            context=data,
            config=environment_config,
        )
        return sanitize_text(rendered_html)
    except Exception as err:
        logger.exception("Template rendering failed")
        error_msg = f"Document generation failed: template error - {err!s}"
        raise GenerationError(error_msg, original_error=err) from err


async def _validate_inputs(
    template: str,
    data: dict[str, Any],
    *,
    schema: dict[str, Any] | None = None,
    use_cache: bool = True,
) -> ValidationReport:
    """Validate template, schema, and data with security checks.

    Always performs full validation including JavaScript detection for security.
    Uses Redis caching to avoid redundant validation of identical inputs.

    Args:
        template: Template source code
        data: Data to render
        schema: Optional JSON Schema for data validation
        use_cache: Whether to use Redis caching

    Returns:
        ValidationReport with validation results

    """
    report, _ = await _validate_inputs_with_result(
        template=template,
        data=data,
        schema=schema,
        use_cache=use_cache,
    )
    return report


async def _validate_inputs_with_result(
    template: str,
    data: dict[str, Any],
    *,
    schema: dict[str, Any] | None = None,
    use_cache: bool = True,
) -> tuple[ValidationReport, str | None]:
    """Validate template, schema, and data and return both report and rendered HTML.

    Always performs full validation including JavaScript detection for security.
    Uses Redis caching to avoid redundant validation of identical inputs.
    Returns (ValidationReport, rendered_html or None).

    Args:
        template: Template source code
        data: Data to render
        schema: Optional JSON Schema for data validation
        use_cache: Whether to use Redis caching

    Returns:
        Tuple of (ValidationReport, rendered_html or None)

    Raises:
        GenerationError: If validation times out or encounters unexpected errors

    """
    cache_key = get_cache_key(template=template, schema=schema, data=data)

    if use_cache:
        cached_report = await get_cached_validation_report(cache_key)
        if cached_report is not None:
            logger.debug("Using cached validation result")
            return cached_report, None

    logger.debug("Running validation")
    try:
        validation_report, rendered_html = await validate_all_with_result(
            template=template,
            schema=schema,
            data=data,
        )
    except TimeoutError as err:
        logger.exception("Validation timed out")
        error_msg = "Document generation failed: validation timed out"
        raise GenerationError(error_msg, original_error=err) from err
    except Exception as err:
        logger.exception("Validation failed with an unexpected error")
        error_msg = f"Document generation failed: validation error - {err!s}"
        raise GenerationError(error_msg, original_error=err) from err
    else:
        if use_cache:
            await set_cached_validation_report(cache_key, validation_report)

        return validation_report, rendered_html
