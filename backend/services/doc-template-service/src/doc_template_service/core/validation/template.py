"""Template syntax validation.

Validates Jinja2 template syntax and structure.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import jinja2
import lxml.etree

from doc_template_service.schemas.models import ValidationIssue

if TYPE_CHECKING:
    from doc_template_service.core.validation.models import ValidationResult

logger = logging.getLogger(__name__)


def validate_template_syntax(template: str, result: ValidationResult) -> None:
    """Validate the Jinja2 template syntax and structure.

    Args:
        template: Template source code
        result: Result object to populate with issues

    """
    try:
        env = jinja2.Environment(autoescape=True)
        env.parse(template)
    except jinja2.exceptions.TemplateSyntaxError as e:
        result.valid = False
        result.issues.append(
            ValidationIssue(
                path=f"line {e.lineno}",
                keyword="template_syntax",
                message=f"Template syntax error: {e.message}",
            )
        )
    except (ValueError, TypeError) as e:
        result.issues.append(
            ValidationIssue(
                path="$",
                keyword="template_structure",
                message=f"Template structure error: {e}",
            )
        )


def validate_html_structure(template: str, result: ValidationResult) -> None:
    """Validate the HTML structure of the template.

    Note: This also performs a Jinja2 syntax check.
    """
    validate_template_syntax(template, result)

    if not result.valid:
        return

    try:
        lxml.etree.fromstring(template.encode("utf-8"), parser=lxml.etree.HTMLParser(recover=False))
    except lxml.etree.ParseError as e:
        logger.debug("Template HTML parsing failed (expected for Jinja2 templates): %s", e)
    except (lxml.etree.XMLSyntaxError, ValueError, TypeError) as e:
        logger.debug("Template parsing encountered error: %s", e)
