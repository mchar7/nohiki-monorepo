"""Document generation package.

Document generation with:
- Template rendering with Jinja2
- Validation (template syntax, schema, JavaScript detection)
- Multiple output formats (HTML, PDF, image, text)
- Memory-efficient streaming
- Redis caching for validation results
"""

from doc_template_service.core.generator.cache import (
    compute_hash,
    get_cache_key,
    get_cached_validation_report,
    set_cached_validation_report,
)
from doc_template_service.core.generator.errors import GenerationError
from doc_template_service.core.generator.generation import (
    _validate_and_render,
    _validate_inputs,
    _validate_inputs_with_result,
    generate_document,
    generate_document_streamed,
)
from doc_template_service.core.generator.output_formats import (
    DocumentOptions,
    TextAlternativeMode,
    stream_output_format,
)
from doc_template_service.core.generator.streaming import (
    generate_image_content,
    stream_html_chunks,
    stream_image_chunks,
    stream_pdf_chunks,
    stream_text_chunks,
)
from doc_template_service.core.generator.text_conversion import (
    convert_html_to_text,
    sanitize_text,
)

__all__ = [
    "DocumentOptions",
    "GenerationError",
    "TextAlternativeMode",
    "_validate_and_render",
    "_validate_inputs",
    "_validate_inputs_with_result",
    "compute_hash",
    "convert_html_to_text",
    "generate_document",
    "generate_document_streamed",
    "generate_image_content",
    "get_cache_key",
    "get_cached_validation_report",
    "sanitize_text",
    "set_cached_validation_report",
    "stream_html_chunks",
    "stream_image_chunks",
    "stream_output_format",
    "stream_pdf_chunks",
    "stream_text_chunks",
]
