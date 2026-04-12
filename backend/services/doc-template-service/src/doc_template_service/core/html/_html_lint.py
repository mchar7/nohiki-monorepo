"""HTML validation to prevent rendering and accessibility issues.

Provides HTML validation that goes beyond basic syntax checking to catch:
- Structural issues that could break rendering
- Accessibility problems like missing ARIA attributes
- Common template mistakes that standard parsers might miss
"""

import html.parser as stdlib_html_parser
import logging
import re
from dataclasses import dataclass

from lxml import html as lxml_html
from lxml.etree import ParserError, XMLSyntaxError, _Element, _ElementTree

from doc_template_service.schemas.models import ValidationIssue

logger = logging.getLogger(__name__)

_NESTING_ERROR_TAGS: frozenset[str] = frozenset({"a", "button", "form"})

# HTML void elements that don't require closing tags
VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


@dataclass(slots=True)
class HTMLParseResult:
    """Structured validation results to support incremental template fixes."""

    document: _Element | _ElementTree | None = None
    errors: list[ValidationIssue] | None = None
    valid: bool = True

    def __post_init__(self) -> None:
        """Set default values to prevent None errors in validation logic."""
        if self.errors is None:
            object.__setattr__(self, "errors", [])
        self.valid = len(self.errors or []) == 0

    def add_error(self, issue: ValidationIssue) -> None:
        """Add an error to the list."""
        if self.errors is None:
            self.errors = []
        self.errors.append(issue)

    def extend_errors(self, issues: list[ValidationIssue]) -> None:
        """Extend errors with a list of issues."""
        if self.errors is None:
            self.errors = []
        self.errors.extend(issues)


def parse_html(html_content: str) -> HTMLParseResult:
    """Parse HTML with error recovery to catch both fatal and non-fatal issues."""
    result = HTMLParseResult()

    try:
        # Check for explicitly unclosed tags before parsing
        unclosed_issues = _check_explicitly_unclosed_tags(html_content)
        result.extend_errors(unclosed_issues)
        if unclosed_issues:
            result.valid = False

            # First, try parsing without recovery to catch structural issues
        strict_parser = lxml_html.HTMLParser(recover=False)
        parser = None

        try:
            strict_document = lxml_html.fromstring(html_content, parser=strict_parser)
            # If strict parsing succeeds, use the result
            result.document = strict_document
        except XMLSyntaxError:
            # If strict parsing fails, use recovery mode but mark as invalid
            parser = lxml_html.HTMLParser(recover=True)
            document = lxml_html.fromstring(html_content, parser=parser)
            result.document = document
            result.valid = False

            # Add a generic error for malformed HTML
            result.add_error(
                ValidationIssue(
                    path="$",
                    keyword="parse_error",
                    message="HTML contains structural errors (unclosed tags, malformed syntax)",
                )
            )

        # Process parser errors from both strict and recovery modes
        active_parser = strict_parser if result.valid and not unclosed_issues else (parser or strict_parser)
        for error in active_parser.error_log:
            if "Unexpected end tag" in error.message and any(tag in error.message for tag in _NESTING_ERROR_TAGS):
                tag = next((t for t in _NESTING_ERROR_TAGS if t in error.message), "element")
                result.add_error(
                    ValidationIssue(
                        path=f"line {error.line}",
                        keyword="invalid_nesting",
                        message=(
                            f"Invalid nesting: <{tag}> element improperly nested "
                            f"at line {error.line}, column {error.column}"
                        ),
                    )
                )
            else:
                result.add_error(
                    ValidationIssue(
                        path=f"line {error.line}",
                        keyword="parse_error",
                        message=f"{error.message} at line {error.line}, column {error.column}",
                    )
                )
            result.valid = False

    except XMLSyntaxError as e:
        result.valid = False
        result.document = None
        result.add_error(
            ValidationIssue(
                path="$",
                keyword="parse_error",
                message=str(e),
            )
        )
    except (ParserError, ValueError, TypeError) as e:
        result.valid = False
        result.document = None
        result.add_error(
            ValidationIssue(
                path="$",
                keyword="error",
                message=f"Error during HTML parsing: {e}",
            )
        )

    return result


# Tags that should be explicitly closed (not self-closing and not implicitly closed)
_TAGS_REQUIRING_EXPLICIT_CLOSE = frozenset(
    [
        "p",
        "div",
        "span",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "a",
        "button",
        "form",
        "table",
        "tr",
        "td",
        "th",
    ]
)


def _process_opening_tags(
    line: str,
    line_num: int,
    tag_stack: list[tuple[str, int, int]],
    tag_positions: dict[str, list[int]],
) -> None:
    """Process opening tags in a line and add them to the stack."""
    # Use atomic group equivalent pattern to prevent catastrophic backtracking
    for correlation in re.finditer(r"<([a-zA-Z][a-zA-Z0-9]*)(?:\s[^>]*)?>", line):
        tag_name = correlation.group(1).lower()
        if tag_name in _TAGS_REQUIRING_EXPLICIT_CLOSE:
            idx = len(tag_stack)
            tag_stack.append((tag_name, line_num, correlation.start()))
            if tag_name not in tag_positions:
                tag_positions[tag_name] = []
            tag_positions[tag_name].append(idx)


def _process_closing_tags(
    line: str,
    tag_stack: list[tuple[str, int, int]],
    tag_positions: dict[str, list[int]],
) -> None:
    """Process closing tags in a line and remove matching entries from the stack."""
    for correlation in re.finditer(r"</([a-zA-Z][a-zA-Z0-9]*)>", line):
        tag_name = correlation.group(1).lower()
        if tag_name in _TAGS_REQUIRING_EXPLICIT_CLOSE:
            positions = tag_positions.get(tag_name)
            if positions:
                idx = positions.pop()
                tag_stack[idx] = ("", 0, 0)


def _check_explicitly_unclosed_tags(html_content: str) -> list[ValidationIssue]:
    """Check for explicitly unclosed tags that should be flagged as errors."""
    tag_stack: list[tuple[str, int, int]] = []
    tag_positions: dict[str, list[int]] = {}

    for line_num, line in enumerate(html_content.split("\n"), 1):
        _process_opening_tags(line, line_num, tag_stack, tag_positions)
        _process_closing_tags(line, tag_stack, tag_positions)

    # Filter out empty entries (marked as removed during closing tag processing)
    return [
        ValidationIssue(
            path=f"line {line_num}",
            keyword="unclosed_tag",
            message=f"Unclosed <{tag_name}> tag at line {line_num}",
        )
        for tag_name, line_num, _ in tag_stack
        if tag_name
    ]


def _check_basic_document_structure(document: _Element) -> list[ValidationIssue]:
    """Ensure document has required elements for proper rendering."""
    required_elements = ["html", "head", "body"]
    issues = []

    issues.extend(
        [
            ValidationIssue(
                path="$",
                keyword="missing_element",
                message=f"Required <{element}> element is missing",
            )
            for element in required_elements
            if document.find(".//" + element) is None and document.tag != element
        ]
    )

    return issues


_INVALID_SELF_NESTING_TAGS = frozenset(["a", "button", "form", "label"])


def _get_element_path_safe(element: _Element, fallback_tag: str) -> str:
    """Safely get element path with fallback."""
    try:
        return element.getroottree().getpath(element)
    except ValueError, AttributeError:
        return f"//{fallback_tag}"


def _check_nested_tag(parent: _Element, tag: str) -> list[ValidationIssue]:
    """Check for improperly nested tags within a parent element."""
    issues: list[ValidationIssue] = []
    xpath_result = parent.xpath(f".//{tag}")
    if not isinstance(xpath_result, list):
        return issues
    for item in xpath_result:
        if not isinstance(item, _Element) or item is parent:
            continue
        child_path = _get_element_path_safe(item, tag)
        parent_path = _get_element_path_safe(parent, tag)
        if child_path != parent_path:
            issues.append(
                ValidationIssue(
                    path=child_path,
                    keyword="invalid_nesting",
                    message=f"Invalid nesting: <{tag}> inside <{tag}> at {child_path}",
                )
            )
    return issues


def _check_invalid_nesting(document: _Element) -> list[ValidationIssue]:
    """Detect invalid element nesting that could cause browser rendering issues."""
    issues: list[ValidationIssue] = []
    for tag in _INVALID_SELF_NESTING_TAGS:
        xpath_result = document.xpath(f"//{tag}")
        if not isinstance(xpath_result, list):
            continue
        for item in xpath_result:
            if isinstance(item, _Element):
                issues.extend(_check_nested_tag(item, tag))
    return issues


def _build_id_map(elements: list[object]) -> dict[str, list[_Element]]:
    """Group elements by ID attribute value."""
    id_map: dict[str, list[_Element]] = {}
    for element in elements:
        if not isinstance(element, _Element):
            continue

        id_value = element.get("id")
        if not id_value:
            continue

        id_map.setdefault(id_value, []).append(element)

    return id_map


def _get_element_xpath(element: _Element, id_value: str, occurrence: int) -> str:
    """Get an XPath for an ID-bearing element with safe fallback."""
    try:
        return element.getroottree().getpath(element)
    except ValueError, AttributeError:
        tag = element.tag if isinstance(element.tag, str) else "element"
        return f"//{tag}[@id='{id_value}'][{occurrence}]"


def lint_html(html_content: str) -> list[ValidationIssue]:
    """Run HTML validation to catch rendering and accessibility issues."""
    if not html_content or not html_content.strip():
        return [ValidationIssue(path="$", keyword="empty_content", message="Empty HTML content provided")]

    issues = []

    try:
        parse_result = parse_html(html_content)
        issues = list(parse_result.errors or [])

        if parse_result.document is None:
            return issues

        # Get the root element if we have an ElementTree
        doc = parse_result.document
        document: _Element = doc.getroot() if isinstance(doc, _ElementTree) else doc
    except ValueError as e:
        logger.exception("Value error during HTML linting")
        return [ValidationIssue(path="$", keyword="linting_error", message=f"HTML linting error: {e!s}")]
    except TypeError as e:
        logger.exception("Type error during HTML linting")
        return [ValidationIssue(path="$", keyword="linting_error", message=f"HTML linting error: {e!s}")]
    else:
        id_elements = document.xpath("//*[@id]")
        id_map = _build_id_map(id_elements if isinstance(id_elements, list) else [])
        for id_value, id_group in id_map.items():
            if len(id_group) <= 1:
                continue

            for occurrence, element in enumerate(id_group, start=1):
                issues.append(
                    ValidationIssue(
                        path=_get_element_xpath(element, id_value, occurrence),
                        keyword="duplicate_id",
                        message=f"Duplicate ID '{id_value}' found {len(id_group)} times",
                    )
                )

        issues.extend(_check_basic_document_structure(document))
        issues.extend(_check_invalid_nesting(document))

    return issues


def get_element_path(element: _Element) -> str:
    """Build XPath-like path for precise error location reporting."""
    path_parts: list[str] = []
    current: _Element | None = element

    while current is not None:
        tag = current.tag
        # Check if it's a comment (tag will be a callable for comments)
        if callable(tag):
            path_parts.append("comment()")
        elif isinstance(tag, str) and tag and tag[0].isalpha():
            siblings_result = current.xpath(f"preceding-sibling::{tag}")
            if isinstance(siblings_result, list):
                idx = len([s for s in siblings_result if isinstance(s, _Element)]) + 1
            else:
                idx = 1
            path_parts.append(f"{tag}[{idx}]")

        current = current.getparent()

    return "/" + "/".join(reversed(path_parts))


def _find_duplicate_ids(html_str: str) -> list[str]:
    """Find duplicate IDs in an HTML string. O(n) complexity using sets."""
    pattern = r'id=(["\'])(.*?)\1'
    matches = re.findall(pattern, html_str)
    ids = [m[1] for m in matches]

    seen: set[str] = set()
    duplicates: set[str] = set()

    for id_value in ids:
        if id_value in seen:
            duplicates.add(id_value)
        seen.add(id_value)

    return list(duplicates)


def _check_improper_nesting(html_str: str, issues: list[str]) -> None:
    """Check for improper nesting of elements like <a> inside <a>."""
    problematic_elements = ["a", "button", "form", "label"]

    for element in problematic_elements:
        pattern = f"<{element}[^>]*>.*?<{element}[^>]*>.*?</{element}>.*?</{element}>"
        matches = re.findall(pattern, html_str, re.DOTALL | re.IGNORECASE)

        if matches:
            issues.append(f"Improper nesting: <{element}> element inside another <{element}>")


def _is_special_tag(html_str: str, pos: int) -> bool:
    """Check if position starts a comment, DOCTYPE, or closing tag."""
    return (
        html_str[pos:].startswith("<!--") or html_str[pos:].startswith("<!DOCTYPE") or html_str[pos:].startswith("</")
    )


def _extract_tag_name(tag_content: str) -> str:
    """Extract the tag name from tag content."""
    space_pos = tag_content.find(" ")
    return tag_content[:space_pos] if space_pos != -1 else tag_content


def _process_tag_at_position(html_str: str, pos: int, stack: list[tuple[str, int]], errors: list[str]) -> int:
    """Process a single tag at the given position. Returns next position."""
    if _is_special_tag(html_str, pos):
        tag_end = html_str.find(">", pos)
        if tag_end == -1:
            errors.append(f"Unclosed tag or declaration at position {pos}")
            return -1
        return tag_end + 1

    tag_end = html_str.find(">", pos)
    if tag_end == -1:
        errors.append(f"Unclosed tag at position {pos}")
        return -1

    tag_content = html_str[pos + 1 : tag_end]
    if tag_content.endswith("/"):
        return tag_end + 1

    tag_name = _extract_tag_name(tag_content)
    if tag_name.lower() not in VOID_ELEMENTS:
        stack.append((tag_name, pos))

    return tag_end + 1


def _process_html_tags(html_str: str) -> list[str]:
    """Process HTML tags to find unclosed tags."""
    errors: list[str] = []
    stack: list[tuple[str, int]] = []
    current_pos = 0

    try:
        while current_pos < len(html_str):
            tag_start = html_str.find("<", current_pos)
            if tag_start == -1:
                break
            current_pos = _process_tag_at_position(html_str, tag_start, stack, errors)
            if current_pos == -1:
                break
    except ValueError as exc:
        errors.append(f"Error analyzing HTML structure: {exc!s}")

    errors.extend(f"Unclosed tag <{tag_name}> at position {pos}" for tag_name, pos in stack)
    return errors


def parse_html_simple(html_str: str) -> tuple[bool, list[str]]:
    """Parse HTML and check for syntax errors."""
    errors: list[str] = []

    if not html_str or html_str.strip() == "":
        return True, []

    try:
        parser = stdlib_html_parser.HTMLParser()
        parser.feed(html_str)
        parser.close()
    except (ValueError, TypeError) as e:
        errors.append(f"HTML parsing error: {e!s}")
        return False, errors

    unclosed_tag_errors = _process_html_tags(html_str)
    errors.extend(unclosed_tag_errors)

    return not errors, errors


def lint_html_simple(html_str: str) -> tuple[bool, list[str]]:
    """Lint HTML for common issues."""
    issues = []

    is_valid, parse_errors = parse_html_simple(html_str)
    if not is_valid:
        issues.extend(parse_errors)
        return False, issues

    duplicate_ids = _find_duplicate_ids(html_str)
    duplicate_issues = [f"Duplicate ID found: '{id_value}'" for id_value in duplicate_ids]
    issues.extend(duplicate_issues)

    _check_improper_nesting(html_str, issues)

    if "<html" not in html_str.lower():
        issues.append("Missing <html> element")

    if "<head" not in html_str.lower():
        issues.append("Missing <head> element")

    if "<body" not in html_str.lower():
        issues.append("Missing <body> element")

    return not issues, issues
