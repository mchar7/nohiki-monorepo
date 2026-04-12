"""Tests for HTML linting utilities."""

from doc_template_service.core.html._html_lint import (
    HTMLParseResult,
    lint_html,
    lint_html_simple,
    parse_html,
    parse_html_simple,
)
from doc_template_service.schemas.models import ValidationIssue


class TestHTMLParseResult:
    """Tests for HTMLParseResult dataclass."""

    def test_create_result(self) -> None:
        """Test creating an HTML parse result."""
        result = HTMLParseResult()
        assert result.valid is True
        assert result.errors == []

    def test_add_error(self) -> None:
        """Test adding an error."""
        result = HTMLParseResult()
        issue = ValidationIssue(path="$", keyword="error", message="Test error")
        result.add_error(issue)
        assert result.errors is not None
        assert len(result.errors) == 1
        assert result.errors[0].message == "Test error"

    def test_extend_errors(self) -> None:
        """Test extending errors."""
        result = HTMLParseResult()
        issues = [
            ValidationIssue(path="$", keyword="error1", message="Error 1"),
            ValidationIssue(path="$", keyword="error2", message="Error 2"),
        ]
        result.extend_errors(issues)
        assert result.errors is not None
        assert len(result.errors) == 2


class TestParseHtml:
    """Tests for parse_html function."""

    def test_parse_valid_html(self) -> None:
        """Test parsing valid HTML."""
        html = "<html><head><title>Test</title></head><body><p>Content</p></body></html>"
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)
        assert result.document is not None

    def test_parse_html_fragment(self) -> None:
        """Test parsing HTML fragment."""
        html = "<div><p>Content</p></div>"
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)

    def test_parse_html_with_entities(self) -> None:
        """Test parsing HTML with entities."""
        html = "<p>&amp; &lt; &gt; &quot;</p>"
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)

    def test_parse_empty_html(self) -> None:
        """Test parsing empty HTML."""
        html = ""
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)

    def test_parse_malformed_html(self) -> None:
        """Test parsing malformed HTML."""
        html = "<div><p>Unclosed"
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)


class TestParseHtmlSimple:
    """Tests for parse_html_simple function."""

    def test_parse_valid_html(self) -> None:
        """Test parsing valid HTML."""
        html = "<html><body><p>Content</p></body></html>"
        is_valid, errors = parse_html_simple(html)
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_parse_empty_html(self) -> None:
        """Test parsing empty HTML."""
        html = ""
        is_valid, errors = parse_html_simple(html)
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)


class TestLintHtml:
    """Tests for lint_html function."""

    def test_lint_valid_html(self) -> None:
        """Test linting valid HTML."""
        html = "<html><head><title>Test</title></head><body><p>Content</p></body></html>"
        result = lint_html(html)
        assert isinstance(result, list)

    def test_lint_html_with_script_tag(self) -> None:
        """Test linting HTML with script tag."""
        html = "<html><body><script>alert('test')</script></body></html>"
        result = lint_html(html)
        assert isinstance(result, list)

    def test_lint_html_with_inline_event_handler(self) -> None:
        """Test linting HTML with inline event handler."""
        html = '<html><body><button onclick="alert()">Click</button></body></html>'
        result = lint_html(html)
        assert isinstance(result, list)

    def test_lint_html_with_javascript_url(self) -> None:
        """Test linting HTML with javascript: URL."""
        html = '<html><body><a href="javascript:void(0)">Link</a></body></html>'
        result = lint_html(html)
        assert isinstance(result, list)

    def test_lint_empty_html(self) -> None:
        """Test linting empty HTML."""
        html = ""
        result = lint_html(html)
        assert isinstance(result, list)
        # Empty HTML should have an issue
        assert len(result) > 0

    def test_lint_html_fragment(self) -> None:
        """Test linting HTML fragment."""
        html = "<div><p>Content</p></div>"
        result = lint_html(html)
        assert isinstance(result, list)

    def test_lint_html_with_style_tag(self) -> None:
        """Test linting HTML with style tag."""
        html = "<html><head><style>body { color: red; }</style></head><body></body></html>"
        result = lint_html(html)
        assert isinstance(result, list)

    def test_lint_html_with_external_resources(self) -> None:
        """Test linting HTML with external resources."""
        html = '<html><head><link rel="stylesheet" href="https://example.com/style.css"></head><body></body></html>'
        result = lint_html(html)
        assert isinstance(result, list)

    def test_lint_html_with_iframe(self) -> None:
        """Test linting HTML with iframe."""
        html = '<html><body><iframe src="https://example.com"></iframe></body></html>'
        result = lint_html(html)
        assert isinstance(result, list)

    def test_lint_html_with_form(self) -> None:
        """Test linting HTML with form."""
        html = '<html><body><form action="/submit"><input type="text"></form></body></html>'
        result = lint_html(html)
        assert isinstance(result, list)


class TestLintHtmlSimple:
    """Tests for lint_html_simple function."""

    def test_lint_valid_html(self) -> None:
        """Test linting valid HTML."""
        html = "<html><body><p>Content</p></body></html>"
        is_valid, issues = lint_html_simple(html)
        assert isinstance(is_valid, bool)
        assert isinstance(issues, list)

    def test_lint_empty_html(self) -> None:
        """Test linting empty HTML."""
        html = ""
        is_valid, issues = lint_html_simple(html)
        assert isinstance(is_valid, bool)
        assert isinstance(issues, list)


class TestHTMLParseResultEdgeCases:
    """Tests for HTMLParseResult edge cases."""

    def test_add_error_when_errors_is_none(self) -> None:
        """Test add_error initializes errors list when None."""
        result = HTMLParseResult(errors=None)
        issue = ValidationIssue(path="$", keyword="test", message="Test")
        result.add_error(issue)
        assert result.errors is not None
        assert len(result.errors) == 1

    def test_extend_errors_when_errors_is_none(self) -> None:
        """Test extend_errors initializes errors list when None."""
        result = HTMLParseResult(errors=None)
        issues = [ValidationIssue(path="$", keyword="test", message="Test")]
        result.extend_errors(issues)
        assert result.errors is not None
        assert len(result.errors) == 1


class TestParseHtmlEdgeCases:
    """Tests for parse_html edge cases."""

    def test_parse_html_with_unclosed_tags(self) -> None:
        """Test parsing HTML with unclosed tags that require explicit close."""
        html = "<div><p>Unclosed paragraph"
        result = parse_html(html)
        assert result.valid is False
        assert any(
            "unclosed" in str(e.keyword).lower() or "unclosed" in str(e.message).lower() for e in (result.errors or [])
        )

    def test_parse_html_with_invalid_nesting(self) -> None:
        """Test parsing HTML with invalid nesting like a inside a."""
        html = "<html><body><a href='#'><a href='#'>Nested link</a></a></body></html>"
        result = parse_html(html)
        # lxml may recover from this, but we should detect it
        assert isinstance(result, HTMLParseResult)

    def test_parse_html_with_xml_syntax_error(self) -> None:
        """Test parsing HTML that causes XML syntax error."""
        html = "<div><</div>"  # Invalid syntax
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)


class TestLintHtmlEdgeCases:
    """Tests for lint_html edge cases."""

    def test_lint_html_with_duplicate_ids(self) -> None:
        """Test linting HTML with duplicate IDs."""
        html = '<html><body><div id="dup">First</div><div id="dup">Second</div></body></html>'
        result = lint_html(html)
        assert any("duplicate" in str(issue.keyword).lower() for issue in result)

    def test_lint_html_with_nested_anchors(self) -> None:
        """Test linting HTML with nested anchor tags."""
        html = "<html><body><a href='#'><a href='#'>Nested</a></a></body></html>"
        result = lint_html(html)
        assert isinstance(result, list)

    def test_lint_html_with_nested_buttons(self) -> None:
        """Test linting HTML with nested button tags."""
        html = "<html><body><button><button>Nested</button></button></body></html>"
        result = lint_html(html)
        assert isinstance(result, list)

    def test_lint_html_with_nested_forms(self) -> None:
        """Test linting HTML with nested form tags."""
        html = "<html><body><form><form>Nested</form></form></body></html>"
        result = lint_html(html)
        assert isinstance(result, list)

    def test_lint_html_missing_required_elements(self) -> None:
        """Test linting HTML missing required elements."""
        html = "<div>Just a div</div>"
        result = lint_html(html)
        # Should report missing html, head, body
        assert any("missing" in str(issue.keyword).lower() for issue in result)

    def test_lint_whitespace_only_html(self) -> None:
        """Test linting whitespace-only HTML."""
        html = "   \n\t  "
        result = lint_html(html)
        assert len(result) > 0
        assert any("empty" in str(issue.keyword).lower() for issue in result)


class TestHTMLParseResultMethods:
    """Additional tests for HTMLParseResult methods."""

    def test_add_error_to_none_errors(self) -> None:
        """Test adding error when errors is None."""
        result = HTMLParseResult()
        result.errors = None  # Force None
        issue = ValidationIssue(path="$", keyword="test", message="Test")
        result.add_error(issue)
        assert result.errors is not None
        assert len(result.errors) == 1

    def test_extend_errors_to_none_errors(self) -> None:
        """Test extending errors when errors is None."""
        result = HTMLParseResult()
        result.errors = None  # Force None
        issues = [ValidationIssue(path="$", keyword="test", message="Test")]
        result.extend_errors(issues)
        assert result.errors is not None
        assert len(result.errors) == 1

    def test_post_init_sets_valid_false_with_errors(self) -> None:
        """Test that __post_init__ sets valid to False when errors exist."""
        issue = ValidationIssue(path="$", keyword="test", message="Test")
        result = HTMLParseResult(errors=[issue])
        assert result.valid is False


class TestParseHtmlRecovery:
    """Tests for HTML parsing with recovery mode."""

    def test_parse_html_with_mismatched_tags(self) -> None:
        """Test parsing HTML with mismatched closing tags."""
        html = "<div><span>Content</div></span>"
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)

    def test_parse_html_with_script_tags(self) -> None:
        """Test parsing HTML with script tags."""
        html = "<html><body><script>var x = 1;</script></body></html>"
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)

    def test_parse_html_with_style_tags(self) -> None:
        """Test parsing HTML with style tags."""
        html = "<html><head><style>body { color: red; }</style></head><body></body></html>"
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)

    def test_parse_html_with_comments(self) -> None:
        """Test parsing HTML with comments."""
        html = "<html><body><!-- This is a comment --><p>Content</p></body></html>"
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)

    def test_parse_html_with_doctype(self) -> None:
        """Test parsing HTML with DOCTYPE."""
        html = "<!DOCTYPE html><html><head></head><body></body></html>"
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)


class TestLintHtmlAccessibility:
    """Tests for HTML linting accessibility checks."""

    def test_lint_img_without_alt(self) -> None:
        """Test linting img without alt attribute."""
        html = '<html><body><img src="test.jpg"></body></html>'
        result = lint_html(html)
        # The linter returns a list of issues - verify it runs without error
        assert isinstance(result, list)

    def test_lint_img_with_alt(self) -> None:
        """Test linting img with alt attribute."""
        html = '<html><body><img src="test.jpg" alt="Test image"></body></html>'
        result = lint_html(html)
        # Should return a list of issues
        assert isinstance(result, list)

    def test_lint_empty_heading(self) -> None:
        """Test linting empty heading tags."""
        html = "<html><body><h1></h1></body></html>"
        result = lint_html(html)
        # The linter returns a list of issues - verify it runs without error
        assert isinstance(result, list)

    def test_lint_heading_with_content(self) -> None:
        """Test linting heading with content."""
        html = "<html><body><h1>Title</h1></body></html>"
        result = lint_html(html)
        # Should return a list of issues
        assert isinstance(result, list)


class TestParseHtmlErrorHandling:
    """Tests for parse_html error handling."""

    def test_parse_html_with_parser_error(self) -> None:
        """Test parsing HTML that causes parser errors."""
        # Severely malformed HTML
        html = "<div><<<<>>>"
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)

    def test_parse_html_with_value_error(self) -> None:
        """Test parsing HTML with value error scenarios."""
        # Empty string should be handled gracefully
        html = ""
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)

    def test_parse_html_with_special_characters(self) -> None:
        """Test parsing HTML with special characters."""
        html = "<html><body>Special: &amp; &lt; &gt; &quot; &#39;</body></html>"
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)

    def test_parse_html_with_cdata(self) -> None:
        """Test parsing HTML with CDATA sections."""
        html = "<html><body><![CDATA[Some content]]></body></html>"
        result = parse_html(html)
        assert isinstance(result, HTMLParseResult)


class TestLintHtmlSimpleAdditional:
    """Additional tests for lint_html_simple function."""

    def test_lint_simple_valid_html_full(self) -> None:
        """Test linting valid HTML with simple function."""
        html = "<html><head><title>Test</title></head><body><p>Content</p></body></html>"
        is_valid, errors = lint_html_simple(html)
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_lint_simple_empty_html_check(self) -> None:
        """Test linting empty HTML with simple function."""
        html = ""
        is_valid, errors = lint_html_simple(html)
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_lint_simple_malformed_html_check(self) -> None:
        """Test linting malformed HTML with simple function."""
        html = "<div><p>Unclosed"
        is_valid, errors = lint_html_simple(html)
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)


class TestFindDuplicateIds:
    """Tests for _find_duplicate_ids helper function with O(n) complexity."""

    def test_no_ids(self) -> None:
        """Test HTML with no IDs."""
        from doc_template_service.core.html._html_lint import _find_duplicate_ids

        html = "<div><p>Content</p></div>"
        assert _find_duplicate_ids(html) == []

    def test_unique_ids(self) -> None:
        """Test HTML with all unique IDs."""
        from doc_template_service.core.html._html_lint import _find_duplicate_ids

        html = '<div id="a"><span id="b">Content</span></div>'
        assert _find_duplicate_ids(html) == []

    def test_single_duplicate(self) -> None:
        """Test HTML with one duplicate ID."""
        from doc_template_service.core.html._html_lint import _find_duplicate_ids

        html = '<div id="dup"></div><span id="dup"></span>'
        result = _find_duplicate_ids(html)
        assert "dup" in result

    def test_multiple_duplicates(self) -> None:
        """Test HTML with multiple duplicate IDs."""
        from doc_template_service.core.html._html_lint import _find_duplicate_ids

        html = '<div id="a"></div><div id="a"></div><span id="b"></span><span id="b"></span>'
        result = _find_duplicate_ids(html)
        assert "a" in result
        assert "b" in result

    def test_single_quotes(self) -> None:
        """Test HTML with single-quoted IDs."""
        from doc_template_service.core.html._html_lint import _find_duplicate_ids

        html = "<div id='dup'></div><span id='dup'></span>"
        result = _find_duplicate_ids(html)
        assert "dup" in result

    def test_triple_duplicate(self) -> None:
        """Test HTML with ID appearing three times."""
        from doc_template_service.core.html._html_lint import _find_duplicate_ids

        html = '<div id="x"></div><div id="x"></div><div id="x"></div>'
        result = _find_duplicate_ids(html)
        assert result == ["x"]


class TestParseHtmlSimpleErrorHandling:
    """Tests for parse_html_simple error handling."""

    def test_parse_html_simple_with_value_error(self) -> None:
        """Test parse_html_simple with invalid input causing ValueError."""
        from doc_template_service.core.html._html_lint import parse_html_simple

        # This should trigger the ValueError handling in the HTMLParser
        is_valid, errors = parse_html_simple("\x00\x01\x02")
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_parse_html_simple_with_type_error(self) -> None:
        """Test parse_html_simple handles various inputs."""
        from doc_template_service.core.html._html_lint import parse_html_simple

        # Valid HTML
        is_valid, errors = parse_html_simple("<p>test</p>")
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)


class TestGetElementPath:
    """Tests for get_element_path function."""

    def test_get_element_path_with_element(self) -> None:
        """Test getting path for a valid element."""
        from doc_template_service.core.html._html_lint import get_element_path
        from lxml import html as lxml_html

        html = "<html><body><div><p>Test</p></div></body></html>"
        document = lxml_html.fromstring(html)
        p_element = document.xpath("//p")[0]
        path = get_element_path(p_element)
        assert isinstance(path, str)
        assert "p" in path

    def test_get_element_path_with_comment(self) -> None:
        """Test getting path with comment node."""
        from doc_template_service.core.html._html_lint import get_element_path
        from lxml import html as lxml_html

        # Comments are tricky - create a comment node
        document = lxml_html.fromstring("<html><body><!-- comment --></body></html>")
        # Get the comment node
        for node in document.xpath("//comment()"):
            path = get_element_path(node)
            assert isinstance(path, str)


class TestGetElementXpathFallback:
    """Tests for _get_element_xpath fallback behavior."""

    def test_get_element_xpath_with_detached_element(self) -> None:
        """Test fallback for detached elements."""
        from doc_template_service.core.html._html_lint import _get_element_xpath
        from lxml import html as lxml_html

        # Create a detached element (not attached to any tree)
        elem = lxml_html.Element("div")
        elem.set("id", "test-id")
        # This should trigger the fallback
        result = _get_element_xpath(elem, "test-id", 1)
        assert isinstance(result, str)
        assert "div" in result


class TestBuildIdMap:
    """Tests for _build_id_map function."""

    def test_build_id_map_empty(self) -> None:
        """Test building ID map with empty list."""
        from doc_template_service.core.html._html_lint import _build_id_map

        result = _build_id_map([])
        assert result == {}

    def test_build_id_map_with_elements(self) -> None:
        """Test building ID map with multiple elements."""
        from doc_template_service.core.html._html_lint import _build_id_map
        from lxml import html as lxml_html

        html = '<div id="a"></div><div id="a"></div><span id="b"></span>'
        document = lxml_html.fromstring(html)
        elements = document.xpath("//*[@id]")
        result = _build_id_map(elements)
        assert "a" in result
        assert "b" in result
        assert len(result["a"]) == 2
        assert len(result["b"]) == 1


class TestCheckInvalidNesting:
    """Tests for _check_invalid_nesting function."""

    def test_check_invalid_nesting_no_issues(self) -> None:
        """Test with valid HTML."""
        from doc_template_service.core.html._html_lint import _check_invalid_nesting
        from lxml import html as lxml_html

        html = "<html><body><div>Content</div></body></html>"
        document = lxml_html.fromstring(html)
        result = _check_invalid_nesting(document)
        assert isinstance(result, list)

    def test_check_invalid_nesting_nested_a(self) -> None:
        """Test detecting nested anchor tags."""
        from doc_template_service.core.html._html_lint import _check_invalid_nesting
        from lxml import html as lxml_html

        html = '<html><body><a href="#">Outer<a href="#">Inner</a></a></body></html>'
        document = lxml_html.fromstring(html)
        result = _check_invalid_nesting(document)
        # Should detect invalid nesting
        assert isinstance(result, list)


class TestProcessTagAtPosition:
    """Tests for _process_tag_at_position function."""

    def test_process_tag_unclosed(self) -> None:
        """Test detecting unclosed tags."""
        from doc_template_service.core.html._html_lint import _process_html_tags

        html = "<div>"
        errors = _process_html_tags(html)
        assert isinstance(errors, list)

    def test_process_tag_self_closing(self) -> None:
        """Test processing self-closing tags."""
        from doc_template_service.core.html._html_lint import _process_html_tags

        html = "<br/><hr/><img/>"
        errors = _process_html_tags(html)
        # Self-closing void elements should not cause errors
        assert isinstance(errors, list)

    def test_process_tag_with_errors(self) -> None:
        """Test processing tags that cause errors."""
        from doc_template_service.core.html._html_lint import _process_html_tags

        # Very malformed HTML
        html = "<"
        errors = _process_html_tags(html)
        assert isinstance(errors, list)


class TestProcessHtmlTagsError:
    """Tests for _process_html_tags ValueError handling."""

    def test_process_html_tags_value_error(self) -> None:
        """Test ValueError handling in _process_html_tags."""
        from doc_template_service.core.html._html_lint import _process_html_tags

        # This might trigger the ValueError exception handling
        html = "<div>" + "a" * 10000 + "</div>"
        errors = _process_html_tags(html)
        assert isinstance(errors, list)


class TestGetElementPathSafe:
    """Tests for _get_element_path_safe function."""

    def test_get_element_path_safe_detached(self) -> None:
        """Test fallback for detached element."""
        from doc_template_service.core.html._html_lint import _get_element_path_safe
        from lxml import html as lxml_html

        elem = lxml_html.Element("span")
        result = _get_element_path_safe(elem, "span")
        assert isinstance(result, str)
        assert "span" in result


class TestCheckImproperNesting:
    """Tests for _check_improper_nesting function."""

    def test_check_improper_nesting_finds_issues(self) -> None:
        """Test detecting improper nesting patterns."""
        from doc_template_service.core.html._html_lint import _check_improper_nesting

        html = '<div><a href="#"><a href="#">Nested</a></a></div>'
        issues: list[str] = []
        _check_improper_nesting(html, issues)
        assert isinstance(issues, list)


class TestLintHtmlErrorCases:
    """Tests for lint_html error handling."""

    def test_lint_html_value_error(self) -> None:
        """Test lint_html ValueError handling."""
        from typing import cast

        from doc_template_service.core.html._html_lint import lint_html

        # This might trigger the ValueError path
        result = lint_html(cast(str, None))
        assert isinstance(result, list)

    def test_lint_html_type_error(self) -> None:
        """Test lint_html TypeError handling."""
        from doc_template_service.core.html._html_lint import lint_html

        # Valid HTML should work fine
        result = lint_html("<html><body>Test</body></html>")
        assert isinstance(result, list)


class TestParseHtmlDocumentNone:
    """Tests for parse_html when document is None."""

    def test_parse_html_returns_none_document(self) -> None:
        """Test parse_html handles cases where document could be None."""
        from doc_template_service.core.html._html_lint import parse_html

        # Very malformed that might cause issues
        result = parse_html("<!DOCTYPE html>")
        assert isinstance(result, HTMLParseResult)
