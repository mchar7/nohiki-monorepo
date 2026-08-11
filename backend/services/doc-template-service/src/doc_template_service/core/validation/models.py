"""Validation data models and type definitions.

Contains DTOs and dataclasses used throughout the validation pipeline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, TypedDict

from doc_template_service.schemas.models import ValidationIssue, ValidationReport


class EnvironmentConfig(TypedDict, total=False):
    """Configuration for the Jinja2 environment."""

    block_start_string: str
    block_end_string: str
    variable_start_string: str
    variable_end_string: str
    comment_start_string: str
    comment_end_string: str
    line_statement_prefix: str
    line_comment_prefix: str
    trim_blocks: bool
    lstrip_blocks: bool
    keep_trailing_newline: bool
    extensions: list[str]


@dataclass(slots=True)
class ValidationContext:
    """Context for validation operations."""

    template: str | None = None
    schema: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    environment_config: EnvironmentConfig | None = None


@dataclass(slots=True)
class ValidationResult:
    """Result of validation operations."""

    issues: list[ValidationIssue] = field(default_factory=list)
    valid: bool = True

    def to_report(self) -> ValidationReport:
        """Convert the result to a ValidationReport.

        The ValidationReport pydantic model requires a summary mapping that
        aggregates issue counts by severity level.

        Returns:
            ValidationReport instance

        """
        summary: dict[str, int] = {"error": 0, "warning": 0, "info": 0}
        for issue in self.issues:
            level = getattr(issue, "severity", None)
            if level in summary:
                summary[level] += 1

        return ValidationReport(
            valid=self.valid,
            issues=self.issues,
            summary=summary,
        )


@dataclass(frozen=True, slots=True)
class JavaScriptRequirement:
    """JavaScript requirement extracted from template TMPL_META."""

    required: bool
    reason: str | None = None


_TMPL_META_PATTERN = re.compile(r"<!--\s*TMPL_META\s*([\s\S]*?)\s*-->", re.MULTILINE)


def extract_js_requirements_from_template(template: str) -> JavaScriptRequirement:
    """Extract JavaScript requirements from template TMPL_META metadata.

    JavaScript declaration belongs in the template, not the schema, because:
    - A schema defines data structure
    - Multiple templates can implement the same schema with different layouts
    - JavaScript is a template-level presentation concern

    Supports both formats:
    - Boolean: "requires_javascript": true
    - Object: "requires_javascript": {"required": true, "reason": "..."}

    Args:
        template: Template HTML content with TMPL_META block

    Returns:
        JavaScriptRequirement with required flag and optional reason

    """
    match = _TMPL_META_PATTERN.search(template)
    if not match:
        return JavaScriptRequirement(required=False)

    try:
        metadata = json.loads(match.group(1))
        js_config = metadata.get("requires_javascript", False)

        if isinstance(js_config, bool):
            return JavaScriptRequirement(required=js_config)

        if isinstance(js_config, dict):
            return JavaScriptRequirement(
                required=bool(js_config.get("required", False)),
                reason=js_config.get("reason"),
            )

        return JavaScriptRequirement(required=False)
    except json.JSONDecodeError, TypeError, AttributeError:
        return JavaScriptRequirement(required=False)
