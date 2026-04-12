"""Template handling package for document generation.

This package contains template rendering and inspection functionality.
"""

from ._jinja_inspect import (
    collect_template_variables,
    count_loop_depth,
    flatten_variables,
    inspect_template,
)
from .jinja_engine import (
    EnvironmentConfig,
    TemplateComplexityError,
    TemplateRenderTimeoutError,
    TemplateSizeError,
    render_template,
)

__all__ = [
    "EnvironmentConfig",
    "TemplateComplexityError",
    "TemplateRenderTimeoutError",
    "TemplateSizeError",
    "collect_template_variables",
    "count_loop_depth",
    "flatten_variables",
    "inspect_template",
    "render_template",
]
