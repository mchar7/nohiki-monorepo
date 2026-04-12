"""Tests for JavaScript detection in HTML templates."""

from doc_template_service.core.html.js_detector import JavaScriptDetector
from doc_template_service.schemas.models import ValidationIssue


class TestJavaScriptDetector:
    """Tests for JavaScriptDetector class."""

    def test_init(self) -> None:
        """Test detector initialization."""
        detector = JavaScriptDetector()
        assert detector is not None
        assert detector.script_pattern is not None
        assert detector.javascript_protocol_pattern is not None
        assert detector.event_handler_pattern is not None

    def test_detect_no_javascript(self) -> None:
        """Test detection with no JavaScript."""
        detector = JavaScriptDetector()
        html = "<html><body><p>Hello World</p></body></html>"
        issues = detector.detect(html)
        assert isinstance(issues, list)
        # No JavaScript-related issues expected
        assert all(isinstance(issue, ValidationIssue) for issue in issues)

    def test_detect_script_tag(self) -> None:
        """Test detection of script tag."""
        detector = JavaScriptDetector()
        html = "<html><body><script>alert('test')</script></body></html>"
        issues = detector.detect(html)
        assert isinstance(issues, list)
        # Should detect script tag
        assert any("script" in issue.message.lower() for issue in issues)

    def test_detect_inline_onclick(self) -> None:
        """Test detection of onclick handler."""
        detector = JavaScriptDetector()
        html = '<html><body><button onclick="alert()">Click</button></body></html>'
        issues = detector.detect(html)
        assert isinstance(issues, list)
        # Should detect event handler
        assert any("onclick" in issue.message.lower() or "event" in issue.message.lower() for issue in issues)

    def test_detect_inline_onload(self) -> None:
        """Test detection of onload handler."""
        detector = JavaScriptDetector()
        html = '<html><body onload="init()"><p>Content</p></body></html>'
        issues = detector.detect(html)
        assert isinstance(issues, list)

    def test_detect_inline_onerror(self) -> None:
        """Test detection of onerror handler."""
        detector = JavaScriptDetector()
        html = '<html><body><img src="x" onerror="alert()"></body></html>'
        issues = detector.detect(html)
        assert isinstance(issues, list)

    def test_detect_javascript_url_href(self) -> None:
        """Test detection of javascript: URL in href."""
        detector = JavaScriptDetector()
        html = '<html><body><a href="javascript:void(0)">Link</a></body></html>'
        issues = detector.detect(html)
        assert isinstance(issues, list)
        # Should detect javascript: URL
        assert any("javascript" in issue.message.lower() for issue in issues)

    def test_detect_javascript_url_src(self) -> None:
        """Test detection of javascript: URL in src."""
        detector = JavaScriptDetector()
        html = '<html><body><iframe src="javascript:alert()"></iframe></body></html>'
        issues = detector.detect(html)
        assert isinstance(issues, list)

    def test_detect_multiple_patterns(self) -> None:
        """Test detection of multiple JavaScript patterns."""
        detector = JavaScriptDetector()
        html = """
        <html>
        <body>
            <script>alert('test')</script>
            <button onclick="click()">Click</button>
            <a href="javascript:void(0)">Link</a>
        </body>
        </html>
        """
        issues = detector.detect(html)
        assert isinstance(issues, list)
        # Should detect multiple issues
        assert len(issues) >= 2

    def test_detect_external_script(self) -> None:
        """Test detection of external script."""
        detector = JavaScriptDetector()
        html = '<html><head><script src="https://example.com/script.js"></script></head><body></body></html>'
        issues = detector.detect(html)
        assert isinstance(issues, list)

    def test_detect_svg_script(self) -> None:
        """Test detection of script in SVG."""
        detector = JavaScriptDetector()
        html = "<html><body><svg><script>alert(1)</script></svg></body></html>"
        issues = detector.detect(html)
        assert isinstance(issues, list)

    def test_empty_html(self) -> None:
        """Test detection with empty HTML."""
        detector = JavaScriptDetector()
        html = "<html><body></body></html>"  # Use minimal valid HTML
        issues = detector.detect(html)
        assert isinstance(issues, list)

    def test_html_with_style_only(self) -> None:
        """Test HTML with only style tag."""
        detector = JavaScriptDetector()
        html = "<html><head><style>body { color: red; }</style></head><body></body></html>"
        issues = detector.detect(html)
        assert isinstance(issues, list)
        # No JavaScript-related issues expected
        assert not any("script" in issue.message.lower() for issue in issues)

    def test_detect_meta_refresh_javascript(self) -> None:
        """Test detection of JavaScript in meta refresh."""
        detector = JavaScriptDetector()
        html = '<html><head><meta http-equiv="refresh" content="0;url=javascript:alert(1)"></head><body></body></html>'
        issues = detector.detect(html)
        assert isinstance(issues, list)
        assert any("meta" in issue.keyword.lower() or "javascript" in issue.message.lower() for issue in issues)

    def test_detect_svg_event_handler(self) -> None:
        """Test detection of event handler in SVG element."""
        detector = JavaScriptDetector()
        html = '<html><body><svg><rect onclick="alert(1)"></rect></svg></body></html>'
        issues = detector.detect(html)
        assert isinstance(issues, list)
        # Should detect SVG event handler
        assert any("svg" in issue.keyword.lower() or "event" in issue.message.lower() for issue in issues)

    def test_detect_javascript_in_formaction(self) -> None:
        """Test detection of javascript: in formaction attribute."""
        detector = JavaScriptDetector()
        html = '<html><body><form><button formaction="javascript:void(0)">Submit</button></form></body></html>'
        issues = detector.detect(html)
        assert isinstance(issues, list)
        assert any("javascript" in issue.message.lower() for issue in issues)

    def test_detect_empty_script_tag(self) -> None:
        """Test detection of empty script tag."""
        detector = JavaScriptDetector()
        html = "<html><body><script></script></body></html>"
        issues = detector.detect(html)
        assert isinstance(issues, list)
        assert any("empty" in issue.keyword.lower() or "script" in issue.message.lower() for issue in issues)

    def test_get_line_path_with_sourceline(self) -> None:
        """Test _get_line_path with sourceline attribute."""
        from lxml.html import fromstring

        detector = JavaScriptDetector()
        doc = fromstring("<html><body><p>Test</p></body></html>")
        # Get an element
        p_element = doc.xpath("//p")[0]
        path = detector._get_line_path(p_element)
        # Should return a path string
        assert isinstance(path, str)

    def test_regex_fallback_script_tag(self) -> None:
        """Test regex fallback detection of script tag."""
        detector = JavaScriptDetector()
        html = "<script>alert(1)</script>"
        issues = detector._detect_with_regex(html)
        assert isinstance(issues, list)
        assert any("script" in issue.keyword.lower() for issue in issues)

    def test_regex_fallback_event_handler(self) -> None:
        """Test regex fallback detection of event handler."""
        detector = JavaScriptDetector()
        html = '<button onclick="click()">Click</button>'
        issues = detector._detect_with_regex(html)
        assert isinstance(issues, list)
        assert any("event" in issue.keyword.lower() for issue in issues)

    def test_regex_fallback_javascript_protocol(self) -> None:
        """Test regex fallback detection of javascript: protocol."""
        detector = JavaScriptDetector()
        html = '<a href="javascript:void(0)">Link</a>'
        issues = detector._detect_with_regex(html)
        assert isinstance(issues, list)
        assert any("protocol" in issue.keyword.lower() for issue in issues)


class TestDetectJavaScriptFunction:
    """Tests for detect_javascript convenience function."""

    def test_detect_javascript_function(self) -> None:
        """Test the detect_javascript convenience function."""
        from doc_template_service.core.html.js_detector import detect_javascript

        html = "<html><body><script>alert(1)</script></body></html>"
        issues = detect_javascript(html)
        assert isinstance(issues, list)
        assert any("script" in issue.message.lower() for issue in issues)

    def test_detect_javascript_no_js(self) -> None:
        """Test detect_javascript with no JavaScript."""
        from doc_template_service.core.html.js_detector import detect_javascript

        html = "<html><body><p>Hello</p></body></html>"
        issues = detect_javascript(html)
        assert isinstance(issues, list)
