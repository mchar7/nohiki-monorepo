"""Validation package for document generation.

Validation for:
- Template syntax and structure (Jinja2)
- JSON Schema validation
- JavaScript detection (security)
- HTML output validation
"""

from doc_template_service.core.validation.models import (
    EnvironmentConfig,
    JavaScriptRequirement,
    ValidationContext,
    ValidationResult,
    extract_js_requirements_from_template,
)
from doc_template_service.core.validation.orchestrator import (
    Validator,
    validate_all,
    validate_all_with_result,
    validate_data,
)
from doc_template_service.schemas.models import ValidationReport

from ._jsonschema_ext import (
    RichValidator,
    get_validator,
)

__all__ = [
    "EnvironmentConfig",
    "JavaScriptRequirement",
    "RichValidator",
    "ValidationContext",
    "ValidationReport",
    "ValidationResult",
    "Validator",
    "extract_js_requirements_from_template",
    "get_validator",
    "validate_all",
    "validate_all_with_result",
    "validate_data",
]
