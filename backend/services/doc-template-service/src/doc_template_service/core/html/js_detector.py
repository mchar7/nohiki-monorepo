"""JavaScript Detection Utility for HTML Templates.

Provides detection of JavaScript code in HTML templates,
including inline scripts, external scripts, event handlers, and other
executable JavaScript patterns.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lxml.html import fromstring

if TYPE_CHECKING:
    from lxml.html import HtmlElement

from doc_template_service.schemas.models import ValidationIssue


class JavaScriptDetector:
    """Detects JavaScript presence in HTML templates."""

    def __init__(self) -> None:
        """Initialize the JavaScript detector with compiled regex patterns."""
        # Compile regex patterns for performance
        self.script_pattern = re.compile(r"<\s*script[^>]*>", re.IGNORECASE)
        self.javascript_protocol_pattern = re.compile(r"javascript\s*:", re.IGNORECASE)
        self.event_handler_pattern = re.compile(r"\bon\w+\s*=", re.IGNORECASE)

    def detect(self, html_content: str) -> list[ValidationIssue]:
        """Detect JavaScript in HTML content.

        Args:
            html_content: The HTML content to analyze

        Returns:
            List of ValidationIssue objects describing detected JavaScript

        """
        issues = []

        # Try DOM-based detection first
        try:
            issues.extend(self._detect_with_dom(html_content))
        except (ValueError, TypeError) as e:
            # Fall back to regex-based detection if DOM parsing fails
            issues.append(
                ValidationIssue(
                    path="unknown",
                    keyword="javascript_detection_fallback",
                    message=f"DOM parsing failed, using regex fallback: {e!s}",
                )
            )
            issues.extend(self._detect_with_regex(html_content))

        return issues

    def _detect_with_dom(self, html_content: str) -> list[ValidationIssue]:
        """Detect JavaScript using DOM parsing."""
        issues = []

        try:
            # Parse HTML with lxml
            doc = fromstring(html_content)

            # Delegate to specialized detection methods
            issues.extend(self._detect_script_tags(doc))
            issues.extend(self._detect_event_handlers(doc))
            issues.extend(self._detect_javascript_protocol(doc))
            issues.extend(self._detect_meta_refresh(doc))
            issues.extend(self._detect_svg_events(doc))

        except (ValueError, TypeError) as e:
            # If DOM parsing fails, add a generic issue
            issues.append(
                ValidationIssue(
                    path="unknown",
                    keyword="javascript_detection_error",
                    message=f"Failed to parse HTML for JavaScript detection: {e!s}",
                )
            )

        return issues

    def _get_line_path(self, element: HtmlElement) -> str:
        """Get line path string for an element."""
        line_number = getattr(element, "sourceline", None)
        return f"line {line_number}" if line_number else "unknown"

    def _create_script_issue(self, element: HtmlElement) -> ValidationIssue:
        """Create a validation issue for a script element."""
        path = self._get_line_path(element)
        src_attr = element.get("src")

        if src_attr:
            return ValidationIssue(
                path=path, keyword="javascript_external_script", message=f"External script detected: {src_attr}"
            )

        script_content = element.text or ""
        if script_content.strip():
            return ValidationIssue(
                path=path, keyword="javascript_inline_script", message="Inline script content detected"
            )

        return ValidationIssue(path=path, keyword="javascript_empty_script", message="Empty script tag detected")

    def _detect_script_tags(self, doc: HtmlElement) -> list[ValidationIssue]:
        """Detect script tags in the DOM."""
        return [self._create_script_issue(el) for el in doc.xpath("//script")]

    def _detect_event_handlers(self, doc: HtmlElement) -> list[ValidationIssue]:
        """Detect event handler attributes in the DOM."""
        issues = []
        all_elements = doc.xpath('//*[@*[starts-with(name(), "on")]]')

        for element in all_elements:
            line_number = getattr(element, "sourceline", None)
            event_attrs = [attr for attr in element.attrib if attr.lower().startswith("on")]

            issues.extend(
                [
                    ValidationIssue(
                        path=f"line {line_number}" if line_number else "unknown",
                        keyword="javascript_event_handler",
                        message=f"Event handler attribute detected: {attr}",
                    )
                    for attr in event_attrs
                ]
            )
        return issues

    def _detect_javascript_protocol(self, doc: HtmlElement) -> list[ValidationIssue]:
        """Detect javascript: protocol in various attributes."""
        issues = []
        protocol_attrs = ["href", "src", "action", "formaction", "cite", "background"]

        for attr in protocol_attrs:
            xpath_query = (
                f'//*[@{attr}[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", '
                '"abcdefghijklmnopqrstuvwxyz"), "javascript:")]]'
            )
            elements = doc.xpath(xpath_query)

            for element in elements:
                line_number = getattr(element, "sourceline", None)
                attr_value = element.get(attr, "")
                issues.append(
                    ValidationIssue(
                        path=f"line {line_number}" if line_number else "unknown",
                        keyword="javascript_protocol",
                        message=f"JavaScript protocol detected in {attr}: {attr_value[:50]}...",
                    )
                )
        return issues

    def _detect_meta_refresh(self, doc: HtmlElement) -> list[ValidationIssue]:
        """Reject every meta refresh directive, regardless of its destination."""
        issues = []

        for element in doc.xpath("//meta"):
            if element.get("http-equiv", "").strip().casefold() != "refresh":
                continue
            issues.append(
                ValidationIssue(
                    path=self._get_line_path(element),
                    keyword="meta_refresh",
                    message="Meta refresh directives are not allowed",
                )
            )
        return issues

    def _detect_svg_events(self, doc: HtmlElement) -> list[ValidationIssue]:
        """Detect event handlers in SVG elements."""
        issues = []
        svg_elements = doc.xpath('//svg//*[@*[starts-with(name(), "on")]]')

        for element in svg_elements:
            line_number = getattr(element, "sourceline", None)
            event_attrs = [attr for attr in element.attrib if attr.lower().startswith("on")]

            issues.extend(
                [
                    ValidationIssue(
                        path=f"line {line_number}" if line_number else "unknown",
                        keyword="javascript_svg_event",
                        message=f"SVG event handler detected: {attr}",
                    )
                    for attr in event_attrs
                ]
            )
        return issues

    def _detect_with_regex(self, html_content: str) -> list[ValidationIssue]:
        """Detect JavaScript using regex patterns as fallback."""
        issues = []
        lines = html_content.split("\n")

        for line_num, line in enumerate(lines, 1):
            # Check for script tags
            if self.script_pattern.search(line):
                issues.append(
                    ValidationIssue(
                        path=f"line {line_num}",
                        keyword="javascript_script_tag",
                        message="Script tag detected (regex fallback)",
                    )
                )

            # Check for event handlers
            if self.event_handler_pattern.search(line):
                issues.append(
                    ValidationIssue(
                        path=f"line {line_num}",
                        keyword="javascript_event_handler",
                        message="Event handler attribute detected (regex fallback)",
                    )
                )

            # Check for javascript: protocol
            if self.javascript_protocol_pattern.search(line):
                issues.append(
                    ValidationIssue(
                        path=f"line {line_num}",
                        keyword="javascript_protocol",
                        message="JavaScript protocol detected (regex fallback)",
                    )
                )

        return issues


def detect_javascript(html_content: str) -> list[ValidationIssue]:
    """Detect JavaScript in HTML content using the JavaScriptDetector.

    Args:
        html_content: The HTML content to analyze

    Returns:
        List of ValidationIssue objects describing detected JavaScript

    """
    detector = JavaScriptDetector()
    return detector.detect(html_content)
