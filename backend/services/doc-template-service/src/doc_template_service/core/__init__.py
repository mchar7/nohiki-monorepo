"""Core functionality for document generation.

This package contains the core business logic for document generation,
including template rendering, validation, and caching.
"""

from .html._html_lint import lint_html, parse_html
from .templates.jinja_engine import EnvironmentConfig, render_template
from .validation import (
    RichValidator,
    get_validator,
    validate_all,
    validate_data,
)

__all__ = [
    "EnvironmentConfig",
    "RichValidator",
    "get_validator",
    "lint_html",
    "parse_html",
    "render_template",
    "validate_all",
    "validate_data",
]
