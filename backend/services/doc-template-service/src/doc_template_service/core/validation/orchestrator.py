"""Validation orchestrator.

Coordinates all validation checks and provides the main entry points.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import jinja2

from doc_template_service.core.templates.jinja_engine import (
    TemplateComplexityError,
    TemplateRenderTimeoutError,
    TemplateSizeError,
    render_template,
)
from doc_template_service.core.validation.html import validate_html_output
from doc_template_service.core.validation.javascript import validate_javascript_presence
from doc_template_service.core.validation.models import (
    EnvironmentConfig,
    ValidationContext,
    ValidationResult,
)
from doc_template_service.core.validation.schema import validate_data_against_schema
from doc_template_service.core.validation.template import validate_template_syntax
from doc_template_service.schemas.models import ValidationIssue, ValidationReport

logger = logging.getLogger(__name__)


class Validator:
    """Validation orchestrator for templates, schemas, and data."""

    def __init__(
        self,
        environment_config: EnvironmentConfig | None = None,
        timeout: float = 2.0,
    ) -> None:
        """Initialize the validator with configuration options.

        Args:
            environment_config: Configuration for the Jinja environment
            timeout: Timeout in seconds for the entire validation process

        """
        self.environment_config = environment_config
        self.timeout = timeout

    async def validate_all(
        self,
        template: str | None = None,
        schema: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> tuple[ValidationResult, str | None]:
        """Validate template, schema, and data comprehensively.

        All validation checks are performed including:
        - Schema validation
        - Data validation against schema
        - Template syntax validation
        - JavaScript detection (security requirement)
        - Template rendering validation
        - HTML structure validation

        Args:
            template: Template source code
            schema: JSON Schema for data validation
            data: Data to validate and use for rendering

        Returns:
            Tuple of (ValidationResult, rendered_html or None)

        """
        result = ValidationResult()
        context = ValidationContext(
            template=template,
            schema=schema,
            data=data,
            environment_config=self.environment_config,
        )

        rendered_html: str | None = None
        try:
            async with asyncio.timeout(self.timeout):
                rendered_html = await self._run_validations(context, result)
        except TimeoutError:
            result.valid = False
            result.issues.append(
                ValidationIssue(
                    path="$",
                    keyword="timeout",
                    message=f"Validation exceeded timeout of {self.timeout} seconds",
                )
            )
        except Exception as e:
            result.valid = False
            result.issues.append(
                ValidationIssue(
                    path="$",
                    keyword="validation_error",
                    message=f"Unexpected validation error: {e}",
                )
            )
            logger.exception("Unexpected error during validation")

        return result, rendered_html

    async def _run_validations(self, context: ValidationContext, result: ValidationResult) -> str | None:
        """Run all validation checks comprehensively.

        Args:
            context: Validation context with template, schema, and data
            result: Result object to populate with issues

        Returns:
            Rendered HTML if validation included rendering, otherwise None

        """
        rendered_html: str | None = None

        if context.schema is not None and context.data is not None:
            validate_data_against_schema(context.data, context.schema, result)

        if context.template is not None:
            validate_template_syntax(context.template, result)
            validate_javascript_presence(context.template, result)

            if context.data is not None:
                rendered_html = await self._validate_template_rendering(context.template, context.data, result)

        return rendered_html

    async def _validate_template_rendering(
        self, template: str, data: dict[str, Any], result: ValidationResult
    ) -> str | None:
        """Validate the template rendering with the provided data.

        Args:
            template: Template source code
            data: Data to use for rendering
            result: Result object to populate with issues

        Returns:
            Rendered HTML string on success, None on failure

        """
        try:
            rendered = await render_template(template, data)
            validate_html_output(rendered, result)
        except TemplateSizeError as e:
            result.valid = False
            result.issues.append(ValidationIssue(path="$", keyword="size", message=str(e)))
            return None
        except TemplateComplexityError as e:
            result.valid = False
            result.issues.append(ValidationIssue(path="$", keyword="complexity", message=str(e)))
            return None
        except TemplateRenderTimeoutError as e:
            result.valid = False
            result.issues.append(ValidationIssue(path="$", keyword="timeout", message=str(e)))
            return None
        except jinja2.exceptions.TemplateError as e:
            result.valid = False
            result.issues.append(
                ValidationIssue(
                    path="$",
                    keyword="template_error",
                    message=f"Template error: {e}",
                )
            )
            return None
        except (ValueError, TypeError) as e:
            result.valid = False
            result.issues.append(
                ValidationIssue(
                    path="$",
                    keyword="render_error",
                    message=f"Rendering error: {e}",
                )
            )
            return None
        else:
            return rendered


def validate_data(data: dict[str, Any], schema: dict[str, Any]) -> ValidationReport:
    """Validate data against a JSON schema.

    Args:
        data: Data to validate
        schema: JSON schema to validate against

    Returns:
        ValidationReport with validation results

    """
    result = ValidationResult()
    validate_data_against_schema(data, schema, result)
    return result.to_report()


async def validate_all(
    template: str | None = None,
    schema: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    validation_timeout: float = 2.0,
) -> ValidationReport:
    """Validate a template, schema, and data comprehensively.

    This is the main entry point for validation, providing a simple interface
    that performs all necessary checks including JavaScript detection.

    Args:
        template: Template source code to validate and render
        schema: JSON Schema to validate data against
        data: Data to validate against schema and use in template rendering
        validation_timeout: Maximum time in seconds for validation to complete

    Returns:
        ValidationReport with all validation results

    Raises:
        ValueError: If validation_timeout is not positive

    """
    report, _ = await validate_all_with_result(
        template=template,
        schema=schema,
        data=data,
        validation_timeout=validation_timeout,
    )
    return report


async def validate_all_with_result(
    template: str | None = None,
    schema: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    validation_timeout: float = 2.0,
) -> tuple[ValidationReport, str | None]:
    """Validate a template, schema, and data comprehensively and return rendered result.

    This avoids redundant rendering if the caller needs the rendered HTML.

    Args:
        template: Template source code to validate and render
        schema: JSON Schema to validate data against
        data: Data to validate against schema and use in template rendering
        validation_timeout: Maximum time in seconds for validation to complete

    Returns:
        Tuple of (ValidationReport, rendered_html or None)

    Raises:
        ValueError: If validation_timeout is not positive

    """
    if validation_timeout <= 0:
        msg = "validation_timeout must be positive"
        raise ValueError(msg)

    validator = Validator(timeout=validation_timeout)
    result, rendered_html = await validator.validate_all(template, schema, data)

    return result.to_report(), rendered_html
