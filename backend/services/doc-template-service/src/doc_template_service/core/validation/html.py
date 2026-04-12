"""HTML output validation.

Validates rendered HTML structure and performs linting.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import lxml.etree

from doc_template_service.core.html._html_lint import lint_html
from doc_template_service.core.html.js_detector import detect_javascript
from doc_template_service.schemas.models import ValidationIssue

if TYPE_CHECKING:
    from doc_template_service.core.validation.models import ValidationResult

logger = logging.getLogger(__name__)

_DATA_URL_PATTERN = re.compile(r"^[\x00-\x20]*d[\x00-\x20]*a[\x00-\x20]*t[\x00-\x20]*a[\x00-\x20]*:", re.IGNORECASE)
_URL_ATTRIBUTES = ("href", "src", "action", "formaction", "cite", "background")


def validate_html_output(html: str, result: ValidationResult) -> None:
    """Validate the HTML output after template rendering.

    Args:
        html: Rendered HTML
        result: Result object to populate with issues

    """
    try:
        js_issues = detect_javascript(html)
        if js_issues:
            result.valid = False
            for issue in js_issues:
                result.issues.append(
                    ValidationIssue(
                        path="$.rendered_output",
                        keyword="javascript_detected",
                        message=f"JavaScript detected in rendered output: {issue.message}",
                    )
                )

        document = lxml.etree.HTML(html)
        if document is not None:
            for element in document.iter():
                for attribute in _URL_ATTRIBUTES:
                    value = element.get(attribute)
                    if value is not None and _DATA_URL_PATTERN.match(value):
                        result.valid = False
                        result.issues.append(
                            ValidationIssue(
                                path="$.rendered_output",
                                keyword="javascript_detected",
                                message=(
                                    f"JavaScript detected in rendered output: data URL detected in {attribute}: "
                                    f"{value[:50]}..."
                                ),
                            )
                        )

        lint_issues = lint_html(html)
        if lint_issues:
            result.valid = False
            result.issues.extend(lint_issues)
    except lxml.etree.ParseError as e:
        result.valid = False
        result.issues.append(
            ValidationIssue(
                path="$",
                keyword="html_parse",
                message=f"HTML parsing error: {e}",
            )
        )
    except (ValueError, TypeError) as e:
        result.valid = False
        result.issues.append(
            ValidationIssue(
                path="$",
                keyword="html_lint",
                message=f"HTML linting error: {e}",
            )
        )
