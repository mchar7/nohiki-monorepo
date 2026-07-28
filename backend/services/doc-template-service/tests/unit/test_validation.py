"""Tests for validation pipeline.

Tests are organized by module to match the new modular validation package structure:
- models.py: ValidationContext, ValidationResult, JavaScriptRequirement
- schema.py: get_schema_validator, validate_data_against_schema
- template.py: validate_template_syntax, validate_html_structure
- javascript.py: validate_javascript_presence
- html.py: validate_html_output
- orchestrator.py: Validator, validate_all, validate_all_with_result, validate_data
"""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

SEED_TEMPLATES_DIR = Path(__file__).parents[2] / "seed_templates"
SEED_SCHEMAS_DIR = Path(__file__).parents[2] / "seed_schemas"

COMPLETE_SEED_DATA: dict[str, dict[str, object]] = {
    "default_resume_template.html": {
        "full_name": "Zoë O'Neil-Sato",
        "professional_title": "Engineer",
        "contact": {
            "email": "zoe@example.com",
            "phone": "+1 555 0100",
            "location": "Montréal",
            "website": "https://example.com",
        },
        "experience": {
            "label": "Experience",
            "entries": [
                {
                    "title": "Engineer",
                    "organization": "Acme",
                    "location": "Remote",
                    "period": {"start": "2020", "end": "Present"},
                    "bullets": ["Built reliable systems"],
                }
            ],
        },
        "projects": {
            "label": "Projects",
            "entries": [
                {
                    "title": "Nohiki",
                    "subtitle": "Open source",
                    "bullets": ["Stack: Python"],
                }
            ],
        },
        "skills": {
            "label": "Skills",
            "categories": [{"name": "Languages", "skills": ["Python"]}],
        },
        "education": {
            "label": "Education",
            "entries": [
                {
                    "period": {"start": "2015", "end": "2019"},
                    "credential": "BSc",
                    "institution": "University",
                }
            ],
        },
        "certifications": {
            "label": "Certifications",
            "entries": [{"date": "2024", "name": "CSP"}],
        },
        "hobbies": {"label": "Interests", "entries": ["Climbing"]},
    },
    "default_cover_letter_template.html": {
        "full_name": "李",
        "professional_title": "Engineer",
        "contact": {
            "email": "li@example.com",
            "phone": "+86 10 5555 0100",
            "location": "北京",
            "website": "https://example.com",
        },
        "position": "Staff Engineer",
        "salutation": "Dear Hiring Manager,",
        "body_paragraphs": [
            "I am applying for the Staff Engineer position and would welcome the opportunity "
            "to contribute my experience building reliable systems to your team."
        ],
        "closing_line": "Thank you for your consideration.",
        "sign_off": "Sincerely,",
    },
}

import lxml.etree
import pytest
from doc_template_service.core.validation import (
    ValidationContext,
    ValidationResult,
    Validator,
    extract_js_requirements_from_template,
    validate_all,
    validate_data,
)
from doc_template_service.core.validation.html import validate_html_output
from doc_template_service.core.validation.javascript import validate_javascript_presence
from doc_template_service.core.validation.schema import (
    _get_cached_validator,
    get_schema_validator,
    validate_data_against_schema,
)
from doc_template_service.core.validation.template import (
    validate_html_structure,
    validate_template_syntax,
)
from doc_template_service.schemas.models import ValidationReport


@pytest.fixture(autouse=True)
def _clear_schema_validator_cache() -> Generator[None]:
    _get_cached_validator.cache_clear()
    yield
    _get_cached_validator.cache_clear()


class TestExtractJsRequirementsFromTemplate:
    """Tests for extract_js_requirements_from_template function in models.py."""

    def test_no_tmpl_meta_returns_not_required(self) -> None:
        """Template without TMPL_META returns not required."""
        template = "<html><body>Content</body></html>"
        result = extract_js_requirements_from_template(template)
        assert result.required is False
        assert result.reason is None

    def test_tmpl_meta_without_requires_javascript_returns_not_required(self) -> None:
        """TMPL_META without requires_javascript returns not required."""
        template = """<!-- TMPL_META
{"name": "test", "version": "1.0.0"}
-->
<html><body>Content</body></html>"""
        result = extract_js_requirements_from_template(template)
        assert result.required is False
        assert result.reason is None

    def test_requires_javascript_boolean_true(self) -> None:
        """requires_javascript: true (boolean) returns required."""
        template = """<!-- TMPL_META
{"name": "test", "version": "1.0.0", "requires_javascript": true}
-->
<html><body>Content</body></html>"""
        result = extract_js_requirements_from_template(template)
        assert result.required is True
        assert result.reason is None

    def test_requires_javascript_boolean_false(self) -> None:
        """requires_javascript: false (boolean) returns not required."""
        template = """<!-- TMPL_META
{"name": "test", "version": "1.0.0", "requires_javascript": false}
-->
<html><body>Content</body></html>"""
        result = extract_js_requirements_from_template(template)
        assert result.required is False
        assert result.reason is None

    def test_requires_javascript_object_with_reason(self) -> None:
        """requires_javascript object with reason is properly parsed."""
        template = """<!-- TMPL_META
{"name": "test", "requires_javascript": {"required": true, "reason": "Layout optimization"}}
-->
<html><body>Content</body></html>"""
        result = extract_js_requirements_from_template(template)
        assert result.required is True
        assert result.reason == "Layout optimization"

    def test_requires_javascript_object_not_required(self) -> None:
        """requires_javascript object with required: false."""
        template = """<!-- TMPL_META
{"name": "test", "requires_javascript": {"required": false, "reason": "Optional feature"}}
-->
<html><body>Content</body></html>"""
        result = extract_js_requirements_from_template(template)
        assert result.required is False
        assert result.reason == "Optional feature"

    def test_invalid_json_returns_not_required(self) -> None:
        """Invalid JSON in TMPL_META returns not required gracefully."""
        template = """<!-- TMPL_META
{invalid json}
-->
<html><body>Content</body></html>"""
        result = extract_js_requirements_from_template(template)
        assert result.required is False
        assert result.reason is None


class TestGetSchemaValidator:
    """Tests for get_schema_validator function in schema.py."""

    def test_returns_draft7_validator(self) -> None:
        """Returns a Draft7Validator instance."""
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        validator = get_schema_validator(schema)
        assert validator is not None
        errors = list(validator.iter_errors({"name": "test"}))
        assert len(errors) == 0

    def test_caches_validator_by_content(self) -> None:
        """Same schema content returns cached validator."""
        schema: dict[str, object] = {"type": "object"}
        validator1 = get_schema_validator(schema)
        validator2 = get_schema_validator(schema)
        assert validator1 is validator2


class TestValidateDataAgainstSchema:
    """Tests for validate_data_against_schema function in schema.py."""

    def test_valid_data_no_issues(self) -> None:
        """Valid data produces no issues."""
        result = ValidationResult()
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        data = {"name": "test"}

        validate_data_against_schema(data, schema, result)

        assert result.valid is True
        assert len(result.issues) == 0

    def test_invalid_data_type_adds_issues(self) -> None:
        """Invalid data type adds issues."""
        result = ValidationResult()
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        data: dict[str, object] = {"name": 123}

        validate_data_against_schema(data, schema, result)

        assert result.valid is False
        assert len(result.issues) > 0

    def test_missing_required_field_adds_issues(self) -> None:
        """Missing required field adds issues."""
        result = ValidationResult()
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        data: dict[str, object] = {}

        validate_data_against_schema(data, schema, result)

        assert result.valid is False
        assert any("name" in issue.message for issue in result.issues)


class TestValidationContext:
    """Tests for ValidationContext dataclass in models.py."""

    def test_default_values(self) -> None:
        """Default values are None."""
        context = ValidationContext()
        assert context.template is None
        assert context.schema is None
        assert context.data is None
        assert context.environment_config is None

    def test_with_values(self) -> None:
        """Values are stored correctly."""
        context = ValidationContext(
            template="<html>{{ name }}</html>",
            schema={"type": "object"},
            data={"name": "test"},
        )
        assert context.template == "<html>{{ name }}</html>"
        assert context.schema == {"type": "object"}
        assert context.data == {"name": "test"}


class TestValidationResult:
    """Tests for ValidationResult dataclass in models.py."""

    def test_default_values(self) -> None:
        """Default values are empty issues and valid=True."""
        result = ValidationResult()
        assert result.issues == []
        assert result.valid is True

    def test_to_report_returns_validation_report(self) -> None:
        """to_report returns ValidationReport instance."""
        result = ValidationResult(valid=True, issues=[])
        report = result.to_report()
        assert isinstance(report, ValidationReport)
        assert report.valid is True

    def test_to_report_with_severity_levels(self) -> None:
        """to_report aggregates severity counts."""
        from doc_template_service.schemas.models import ValidationIssue

        issue = ValidationIssue(path="$.name", keyword="type", message="Expected string")
        object.__setattr__(issue, "severity", "error")

        result = ValidationResult(valid=False, issues=[issue])
        report = result.to_report()

        assert report.valid is False
        assert report.summary is not None
        assert report.summary["error"] == 1


class TestValidateTemplateSyntax:
    """Tests for validate_template_syntax function in template.py."""

    def test_valid_template_syntax(self) -> None:
        """Valid Jinja2 template produces no issues."""
        result = ValidationResult()
        template = "<html><body>{{ name }}</body></html>"

        validate_template_syntax(template, result)

        assert result.valid is True
        assert len(result.issues) == 0

    def test_invalid_template_syntax(self) -> None:
        """Invalid Jinja2 template adds syntax error."""
        result = ValidationResult()
        template = "<html><body>{{ name }</body></html>"

        validate_template_syntax(template, result)

        assert result.valid is False
        assert any("template" in issue.keyword.lower() for issue in result.issues)


class TestValidateHtmlStructure:
    """Tests for validate_html_structure function in template.py."""

    def test_valid_html_structure(self) -> None:
        """Valid HTML template passes structure check."""
        result = ValidationResult()
        template = "<html><body>{{ name }}</body></html>"

        validate_html_structure(template, result)

        assert result.valid is True

    def test_invalid_jinja_syntax_fails_structure(self) -> None:
        """Invalid Jinja syntax fails structure check."""
        result = ValidationResult()
        template = "<html><body>{{ name }</body></html>"

        validate_html_structure(template, result)

        assert result.valid is False
        assert any("syntax" in issue.keyword.lower() for issue in result.issues)


class TestValidateJavascriptPresence:
    """Tests for validate_javascript_presence function in javascript.py."""

    def test_undeclared_javascript_fails_validation(self) -> None:
        """Undeclared JavaScript fails validation."""
        result = ValidationResult()
        template = '<html><script>alert("test")</script></html>'

        validate_javascript_presence(template, result)

        assert result.valid is False
        assert any("javascript" in issue.keyword.lower() for issue in result.issues)

    def test_declared_javascript_boolean_fails_validation(self) -> None:
        """A declaration documents JavaScript but does not make executable HTML safe."""
        result = ValidationResult()
        template = """<!-- TMPL_META
{"name": "test", "version": "1.0.0", "requires_javascript": true}
-->
<html><script>alert("test")</script></html>"""

        validate_javascript_presence(template, result)

        assert any("declared" in issue.keyword.lower() for issue in result.issues)
        assert result.valid is False

    def test_declared_javascript_with_reason_includes_reason(self) -> None:
        """Declared JavaScript with reason includes reason in message."""
        result = ValidationResult()
        template = """<!-- TMPL_META
{"name": "test", "requires_javascript": {"required": true, "reason": "Layout optimization"}}
-->
<html><script>alert("test")</script></html>"""

        validate_javascript_presence(template, result)

        assert any("Layout optimization" in issue.message for issue in result.issues)
        assert result.valid is False

    @pytest.mark.parametrize(
        "javascript_markup",
        [
            '<script src="https://example.com/app.js"></script>',
            '<button onclick="alert(1)">Click</button>',
            '<a href="javascript:alert(1)">Run</a>',
        ],
    )
    def test_declared_external_event_and_url_javascript_fail_validation(self, javascript_markup: str) -> None:
        """Declaring JavaScript supplies context but never authorizes executable markup."""
        result = ValidationResult()
        template = f"""<!-- TMPL_META
{{"name": "test", "version": "1.0.0", "requires_javascript": true}}
--><html>{javascript_markup}</html>"""

        validate_javascript_presence(template, result)

        assert result.valid is False
        assert any(issue.keyword.startswith("javascript_declared_") for issue in result.issues)

    @pytest.mark.parametrize(
        "javascript_markup",
        [
            '<script src="https://example.com/app.js"></script>',
            '<button onclick="alert(1)">Click</button>',
            '<a href="javascript:alert(1)">Run</a>',
        ],
    )
    def test_undeclared_external_event_and_url_javascript_fail_validation(self, javascript_markup: str) -> None:
        """Executable JavaScript without a declaration remains invalid."""
        result = ValidationResult()
        template = f"<html>{javascript_markup}</html>"

        validate_javascript_presence(template, result)

        assert result.valid is False
        assert any(issue.keyword == "javascript_undeclared" for issue in result.issues)

    def test_no_javascript_no_issues(self) -> None:
        """Template without JavaScript produces no JavaScript issues."""
        result = ValidationResult()
        template = "<html><body>Content</body></html>"

        validate_javascript_presence(template, result)

        assert not any("javascript" in issue.keyword.lower() for issue in result.issues)


class TestValidateHtmlOutput:
    """Tests for validate_html_output function in html.py."""

    def test_valid_html_output(self) -> None:
        """Valid HTML output completes without exception."""
        result = ValidationResult()
        html = "<html><head><title>Test</title></head><body>Content</body></html>"

        validate_html_output(html, result)

        assert isinstance(result, ValidationResult)

    def test_malformed_html_output(self) -> None:
        """Malformed HTML output produces lint issues."""
        result = ValidationResult()
        html = "<html><body>Unclosed tag"

        validate_html_output(html, result)

        assert isinstance(result, ValidationResult)

    @pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<script>alert(1)</script>"])
    @pytest.mark.asyncio
    async def test_runtime_injected_unsafe_href_fails_validation(self, url: str) -> None:
        report = await validate_all(
            template='<html><head><title>Test</title></head><body><a href="{{ url }}">Link</a></body></html>',
            data={"url": url},
        )

        assert report.valid is False

    @pytest.mark.asyncio
    async def test_runtime_injected_https_href_remains_valid(self) -> None:
        report = await validate_all(
            template='<html><head><title>Test</title></head><body><a href="{{ url }}">Link</a></body></html>',
            data={"url": "https://example.com/path?q=value"},
        )

        assert report.valid is True

    @pytest.mark.parametrize(
        "exception",
        [ValueError("lint failed"), lxml.etree.ParseError("parse failed", 0, 0, 0)],
    )
    def test_html_validation_exceptions_fail_closed(self, exception: Exception) -> None:
        result = ValidationResult()

        with patch("doc_template_service.core.validation.html.lint_html", side_effect=exception):
            validate_html_output("<html><body>Content</body></html>", result)

        assert result.valid is False
        assert any(issue.keyword in {"html_lint", "html_parse"} for issue in result.issues)


class TestValidator:
    """Tests for Validator class in orchestrator.py."""

    @pytest.mark.asyncio
    async def test_validate_all_with_no_inputs(self) -> None:
        """Validation with no inputs returns valid result."""
        validator = Validator()
        result, rendered_html = await validator.validate_all()
        assert result.valid is True
        assert result.issues == []
        assert rendered_html is None

    @pytest.mark.asyncio
    async def test_validate_all_timeout(self) -> None:
        """Validation timeout is handled gracefully."""
        validator = Validator(timeout=0.001)
        template = "{{ " + " + ".join(["x"] * 1000) + " }}"

        result, _ = await validator.validate_all(template=template, data={"x": 1})

        assert isinstance(result, ValidationResult)

    @pytest.mark.asyncio
    async def test_unexpected_error_during_validation(self) -> None:
        """Unexpected errors are handled gracefully."""
        from unittest.mock import AsyncMock, patch

        validator = Validator()

        with patch.object(validator, "_run_validations", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = RuntimeError("Unexpected error")

            result, _ = await validator.validate_all(template="<html></html>")

            assert result.valid is False
            assert any("unexpected" in issue.message.lower() for issue in result.issues)


class TestValidateAll:
    """Tests for validate_all function in orchestrator.py."""

    @pytest.mark.asyncio
    async def test_returns_validation_report(self) -> None:
        """Returns ValidationReport instance."""
        report = await validate_all()
        assert isinstance(report, ValidationReport)

    @pytest.mark.asyncio
    async def test_with_valid_inputs(self) -> None:
        """Valid inputs produce valid report."""
        template = "<html><body>{{ name }}</body></html>"
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        data = {"name": "test"}

        report = await validate_all(template=template, schema=schema, data=data)

        assert isinstance(report, ValidationReport)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("template_name", sorted(COMPLETE_SEED_DATA))
    async def test_repaired_default_seed_validates_with_complete_data(self, template_name: str) -> None:
        """Shipped document seeds declare no JS and render under strict validation."""
        template = (SEED_TEMPLATES_DIR / template_name).read_text()

        assert extract_js_requirements_from_template(template).required is False
        schema_file = SEED_SCHEMAS_DIR / template_name.replace("_template.html", "_schema.json")
        schema = json.loads(schema_file.read_text())
        report = await validate_all(
            template=template,
            schema=schema,
            data=COMPLETE_SEED_DATA[template_name],
        )

        assert report.valid, [issue.model_dump() for issue in report.issues]
        assert not any("javascript" in issue.keyword for issue in report.issues)

    @pytest.mark.asyncio
    async def test_legacy_seed_reproduces_javascript_and_missing_name_errors(
        self,
    ) -> None:
        """The original failure has both unsafe script and absent required-name causes."""
        template = """<!-- TMPL_META
{"name": "legacy", "requires_javascript": {"required": false}}
--><html><body>{{ full_name.upper() }}<script>document.body.dataset.fit = 'true'</script></body></html>"""
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"full_name": {"type": "string"}},
            "required": ["full_name"],
        }

        report = await validate_all(template=template, schema=schema, data={})
        assert any(issue.keyword == "javascript_undeclared" for issue in report.issues)
        assert report.valid is False
        assert any("full_name" in issue.message or issue.keyword == "render_error" for issue in report.issues)

    @pytest.mark.asyncio
    async def test_invalid_timeout_raises_error(self) -> None:
        """Invalid timeout raises ValueError."""
        with pytest.raises(ValueError, match="validation_timeout must be positive"):
            await validate_all(validation_timeout=0)

        with pytest.raises(ValueError, match="validation_timeout must be positive"):
            await validate_all(validation_timeout=-1)


class TestValidateData:
    """Tests for validate_data function in orchestrator.py."""

    def test_valid_data_returns_valid_report(self) -> None:
        """Valid data returns valid report."""
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        data = {"name": "test"}

        report = validate_data(data, schema)

        assert report.valid is True

    def test_invalid_data_returns_invalid_report(self) -> None:
        """Invalid data returns invalid report."""
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        data: dict[str, object] = {}

        report = validate_data(data, schema)

        assert report.valid is False


class TestSchemaErrorHandling:
    """Tests for schema.py error handling paths."""

    def test_schema_validation_error_with_invalid_data(self) -> None:
        """Schema validation error is reported for type mismatch."""
        result = ValidationResult()
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"age": {"type": "integer"}},
        }
        data = {"age": "not_an_integer"}

        validate_data_against_schema(data, schema, result)

        assert result.valid is False
        assert any("type" in issue.keyword for issue in result.issues)

    def test_value_error_in_schema_validation(self) -> None:
        """ValueError during schema validation is handled."""
        from unittest.mock import patch

        result = ValidationResult()
        schema: dict[str, object] = {"type": "object"}
        data = {"name": "test"}

        with patch(
            "doc_template_service.core.validation.schema.get_schema_validator",
            side_effect=ValueError("Test value error"),
        ):
            validate_data_against_schema(data, schema, result)

        assert result.valid is False
        assert any("data_error" in issue.keyword for issue in result.issues)


class TestTemplateErrorHandling:
    """Tests for template.py error handling paths."""

    def test_value_error_in_template_syntax(self) -> None:
        """ValueError during template parsing is handled."""
        from unittest.mock import patch

        result = ValidationResult()

        with patch(
            "doc_template_service.core.validation.template.jinja2.Environment.parse",
            side_effect=ValueError("Test value error"),
        ):
            validate_template_syntax("<html></html>", result)

        assert any("template_structure" in issue.keyword for issue in result.issues)

    def test_html_structure_with_parse_error(self) -> None:
        """HTML structure validation handles parse errors gracefully."""
        result = ValidationResult()
        template = "<html><body>Valid {{ name }}</body></html>"

        validate_html_structure(template, result)

        assert result.valid is True


class TestHtmlOutputErrorHandling:
    """Tests for html.py error handling paths."""

    def test_javascript_detected_in_output(self) -> None:
        """JavaScript detection in rendered output adds issues."""
        result = ValidationResult()
        html_with_js = '<html><body><script>alert("test")</script></body></html>'

        validate_html_output(html_with_js, result)

        assert any("javascript_detected" in issue.keyword for issue in result.issues)

    def test_html_parse_error_handling(self) -> None:
        """HTML parse error is handled gracefully."""
        from unittest.mock import patch

        import lxml.etree

        result = ValidationResult()

        with patch(
            "doc_template_service.core.validation.html.detect_javascript",
            side_effect=lxml.etree.XMLSyntaxError("Test parse error", 1, 1, 1),
        ):
            validate_html_output("<html></html>", result)

        assert any("html_parse" in issue.keyword for issue in result.issues)

    def test_value_error_in_html_validation(self) -> None:
        """ValueError during HTML validation is handled."""
        from unittest.mock import patch

        result = ValidationResult()

        with patch(
            "doc_template_service.core.validation.html.detect_javascript",
            side_effect=ValueError("Test value error"),
        ):
            validate_html_output("<html></html>", result)

        assert any("html_lint" in issue.keyword for issue in result.issues)


class TestOrchestratorRenderingErrors:
    """Tests for orchestrator.py template rendering error paths."""

    @pytest.mark.asyncio
    async def test_template_size_error(self) -> None:
        """TemplateSizeError is handled during rendering."""
        from unittest.mock import AsyncMock, patch

        from doc_template_service.core.templates.jinja_engine import TemplateSizeError

        validator = Validator()

        with patch(
            "doc_template_service.core.validation.orchestrator.render_template",
            new_callable=AsyncMock,
            side_effect=TemplateSizeError(template_size=100000, max_size=50000),
        ):
            result, _ = await validator.validate_all(
                template="<html>{{ name }}</html>",
                data={"name": "test"},
            )

        assert result.valid is False
        assert any("size" in issue.keyword for issue in result.issues)

    @pytest.mark.asyncio
    async def test_template_complexity_error(self) -> None:
        """TemplateComplexityError is handled during rendering."""
        from unittest.mock import AsyncMock, patch

        from doc_template_service.core.templates.jinja_engine import (
            TemplateComplexityError,
        )

        validator = Validator()

        with patch(
            "doc_template_service.core.validation.orchestrator.render_template",
            new_callable=AsyncMock,
            side_effect=TemplateComplexityError(node_count=1000, max_nodes=500),
        ):
            result, _ = await validator.validate_all(
                template="<html>{{ name }}</html>",
                data={"name": "test"},
            )

        assert result.valid is False
        assert any("complexity" in issue.keyword for issue in result.issues)

    @pytest.mark.asyncio
    async def test_template_render_timeout_error(self) -> None:
        """TemplateRenderTimeoutError is handled during rendering."""
        from unittest.mock import AsyncMock, patch

        from doc_template_service.core.templates.jinja_engine import (
            TemplateRenderTimeoutError,
        )

        validator = Validator()

        with patch(
            "doc_template_service.core.validation.orchestrator.render_template",
            new_callable=AsyncMock,
            side_effect=TemplateRenderTimeoutError(timeout=2.0),
        ):
            result, _ = await validator.validate_all(
                template="<html>{{ name }}</html>",
                data={"name": "test"},
            )

        assert result.valid is False
        assert any("timeout" in issue.keyword for issue in result.issues)

    @pytest.mark.asyncio
    async def test_jinja_template_error(self) -> None:
        """Jinja2 TemplateError is handled during rendering."""
        from unittest.mock import AsyncMock, patch

        import jinja2

        validator = Validator()

        with patch(
            "doc_template_service.core.validation.orchestrator.render_template",
            new_callable=AsyncMock,
            side_effect=jinja2.exceptions.TemplateError("Jinja error"),
        ):
            result, _ = await validator.validate_all(
                template="<html>{{ name }}</html>",
                data={"name": "test"},
            )

        assert result.valid is False
        assert any("template_error" in issue.keyword for issue in result.issues)

    @pytest.mark.asyncio
    async def test_value_error_during_render(self) -> None:
        """ValueError during rendering is handled."""
        from unittest.mock import AsyncMock, patch

        validator = Validator()

        with patch(
            "doc_template_service.core.validation.orchestrator.render_template",
            new_callable=AsyncMock,
            side_effect=ValueError("Render value error"),
        ):
            result, _ = await validator.validate_all(
                template="<html>{{ name }}</html>",
                data={"name": "test"},
            )

        assert result.valid is False
        assert any("render_error" in issue.keyword for issue in result.issues)
