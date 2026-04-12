"""JavaScript detection and validation.

Validates JavaScript presence in templates against TMPL_META declarations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from doc_template_service.core.html.js_detector import detect_javascript
from doc_template_service.core.validation.models import extract_js_requirements_from_template
from doc_template_service.schemas.models import ValidationIssue

if TYPE_CHECKING:
    from doc_template_service.core.validation.models import ValidationResult


def validate_javascript_presence(template: str, result: ValidationResult) -> None:
    """Validate JavaScript presence in template against TMPL_META declaration.

    Args:
        template: Template source code with TMPL_META block
        result: Result object to populate with issues

    """
    try:
        js_requirement = extract_js_requirements_from_template(template)
        js_issues = detect_javascript(template)

        if js_issues:
            result.valid = False
            if js_requirement.required:
                reason_suffix = f" ({js_requirement.reason})" if js_requirement.reason else ""
                for issue in js_issues:
                    result.issues.append(
                        ValidationIssue(
                            path=issue.path,
                            keyword=f"javascript_declared_{issue.keyword}",
                            message=f"Declared JavaScript usage{reason_suffix}: {issue.message}",
                        )
                    )
            else:
                result.valid = False
                for issue in js_issues:
                    result.issues.append(
                        ValidationIssue(
                            path=issue.path,
                            keyword="javascript_undeclared",
                            message=f"Undeclared JavaScript detected: {issue.message}",
                        )
                    )
    except (ValueError, TypeError) as e:
        result.issues.append(
            ValidationIssue(
                path="$",
                keyword="javascript_detection_error",
                message=f"Error during JavaScript detection: {e}",
            )
        )
