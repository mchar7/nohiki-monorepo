"""Tests for tailor model dataclasses.

Covers ContextFile, JobFile, TailorInput, GenerationResult, RenderResult,
TailorOutput, TemplateInfo, and SchemaInfo properties and computed fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tailor.core.types import JsonDict, OutputSpec
from tailor.models.inputs import ContextFile, JobFile, TailorInput
from tailor.models.outputs import (
    _CACHE_COST_PER_MILLION,
    _INPUT_COST_PER_MILLION,
    _MILLION,
    _OUTPUT_COST_PER_MILLION,
    GenerationResult,
    OutputResult,
    RenderResult,
    TailorOutput,
)
from tailor.models.templates import SchemaInfo, TemplateInfo


def _make_output_with_lint(issues: list) -> TailorOutput:
    """Build a TailorOutput with the given lint_issues list."""
    gen = GenerationResult(
        content={},
        prompt_tokens=0,
        completion_tokens=0,
        model_used="test",
        duration_seconds=0.0,
    )
    render = RenderResult(content=b"", content_type="application/pdf", size_bytes=0)
    spec = OutputSpec(path=Path("/out/out.pdf"), format="pdf")
    output_result = OutputResult(spec=spec, render_result=render, written_path=Path("/out/out.pdf"))
    return TailorOutput(outputs=[output_result], generation_result=gen, lint_issues=issues)


class TestContextFile:
    """Tests for ContextFile frozen dataclass."""

    def test_filename_returns_path_name(self) -> None:
        """Filename property must return the final component of the path."""
        cf = ContextFile(path=Path("/some/dir/resume.txt"), content="text", size_bytes=4, word_count=1)
        assert cf.filename == "resume.txt"

    def test_equality_for_identical_instances(self) -> None:
        """Frozen dataclass equality must be structural (not identity-based)."""
        a = ContextFile(path=Path("/a/b.txt"), content="hi", size_bytes=2, word_count=1)
        b = ContextFile(path=Path("/a/b.txt"), content="hi", size_bytes=2, word_count=1)
        assert a == b

    def test_frozen_prevents_mutation(self) -> None:
        """ContextFile is frozen; direct attribute assignment must raise."""
        cf = ContextFile(path=Path("/x.txt"), content="x", size_bytes=1, word_count=1)
        field = "content"
        with pytest.raises(AttributeError):
            setattr(cf, field, "mutated")


class TestJobFile:
    """Tests for JobFile frozen dataclass."""

    def test_filename_returns_path_name(self) -> None:
        """Filename property must return just the file name portion of path."""
        jf = JobFile(path=Path("/jobs/senior_engineer.md"), content="job text", size_bytes=8)
        assert jf.filename == "senior_engineer.md"

    def test_frozen_prevents_mutation(self) -> None:
        """JobFile is frozen; direct attribute assignment must raise."""
        jf = JobFile(path=Path("/j.md"), content="c", size_bytes=1)
        field = "size_bytes"
        with pytest.raises(AttributeError):
            setattr(jf, field, 99)


class TestTailorInputContextSize:
    """Tests for TailorInput.total_context_size property."""

    def test_total_context_size_sums_bytes(self) -> None:
        """total_context_size must sum size_bytes across all context files."""
        files = [
            ContextFile(path=Path("a.txt"), content="a", size_bytes=100, word_count=1),
            ContextFile(path=Path("b.txt"), content="b", size_bytes=200, word_count=1),
        ]
        inp = TailorInput(context_files=files)
        assert inp.total_context_size == 300

    def test_total_context_size_zero_for_empty(self) -> None:
        """total_context_size must return 0 when no context files are present."""
        inp = TailorInput()
        assert inp.total_context_size == 0


class TestTailorInputJobSize:
    """Tests for TailorInput.total_job_size property."""

    def test_total_job_size_sums_bytes(self) -> None:
        """total_job_size must sum size_bytes across all job files."""
        files = [
            JobFile(path=Path("j1.md"), content="j1", size_bytes=50),
            JobFile(path=Path("j2.md"), content="j2", size_bytes=75),
        ]
        inp = TailorInput(job_files=files)
        assert inp.total_job_size == 125

    def test_total_job_size_zero_for_empty(self) -> None:
        """total_job_size must return 0 when no job files are present."""
        inp = TailorInput()
        assert inp.total_job_size == 0


class TestTailorInputCombinedContext:
    """Tests for TailorInput.combined_context_content property."""

    def test_empty_files_returns_empty_string(self) -> None:
        """combined_context_content must return '' when context_files is empty."""
        assert TailorInput().combined_context_content == ""

    def test_single_file_includes_separator_and_content(self) -> None:
        """combined_context_content with one file must contain the separator header and its content."""
        cf = ContextFile(path=Path("me.txt"), content="John Doe", size_bytes=8, word_count=2)
        inp = TailorInput(context_files=[cf])
        result = inp.combined_context_content
        assert "--- me.txt ---" in result
        assert "John Doe" in result

    def test_two_files_includes_both_separators(self) -> None:
        """combined_context_content with two files must include both filename headers."""
        files = [
            ContextFile(path=Path("a.txt"), content="Alice", size_bytes=5, word_count=1),
            ContextFile(path=Path("b.txt"), content="Bob", size_bytes=3, word_count=1),
        ]
        inp = TailorInput(context_files=files)
        result = inp.combined_context_content
        assert "--- a.txt ---" in result
        assert "--- b.txt ---" in result
        assert "Alice" in result
        assert "Bob" in result


class TestTailorInputCombinedJob:
    """Tests for TailorInput.combined_job_content property."""

    def test_empty_files_returns_empty_string(self) -> None:
        """combined_job_content must return '' when job_files is empty."""
        assert TailorInput().combined_job_content == ""

    def test_single_file_includes_separator_and_content(self) -> None:
        """combined_job_content with one file must include the separator and content."""
        jf = JobFile(path=Path("job.md"), content="Senior Eng role", size_bytes=15)
        inp = TailorInput(job_files=[jf])
        result = inp.combined_job_content
        assert "--- job.md ---" in result
        assert "Senior Eng role" in result


class TestGenerationResult:
    """Tests for GenerationResult computed properties."""

    def _make(
        self,
        prompt: int = 1000,
        completion: int = 200,
        cache_read: int = 0,
        cache_write: int = 0,
    ) -> GenerationResult:
        """Create a GenerationResult with test defaults."""
        return GenerationResult(
            content={"key": "value"},
            prompt_tokens=prompt,
            completion_tokens=completion,
            model_used="openrouter:test/model",
            duration_seconds=1.5,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )

    def test_total_tokens_sum(self) -> None:
        """total_tokens must equal prompt_tokens + completion_tokens."""
        gr = self._make(prompt=500, completion=100)
        assert gr.total_tokens == 600

    def test_cache_hit_ratio_zero_when_prompt_zero(self) -> None:
        """cache_hit_ratio must return 0.0 to guard against zero-division."""
        gr = GenerationResult(
            content={},
            prompt_tokens=0,
            completion_tokens=0,
            model_used="m",
            duration_seconds=0.0,
        )
        assert gr.cache_hit_ratio == 0.0

    def test_cache_hit_ratio_calculation(self) -> None:
        """cache_hit_ratio must equal cache_read_tokens / prompt_tokens."""
        gr = self._make(prompt=1000, cache_read=400)
        assert gr.cache_hit_ratio == pytest.approx(0.4)

    def test_estimated_cost_usd_positive_for_nonzero_tokens(self) -> None:
        """estimated_cost_usd must be positive for non-zero token counts."""
        gr = self._make(prompt=1000, completion=200)
        assert gr.estimated_cost_usd > 0

    @pytest.mark.parametrize(
        ("prompt", "completion", "cache_read"),
        [
            (1000, 200, 0),
            (2000, 500, 300),
            (5000, 1000, 2000),
        ],
    )
    def test_estimated_cost_formula(self, prompt: int, completion: int, cache_read: int) -> None:
        """estimated_cost_usd must use the documented per-token pricing formula."""
        gr = GenerationResult(
            content={},
            prompt_tokens=prompt,
            completion_tokens=completion,
            model_used="m",
            duration_seconds=1.0,
            cache_read_tokens=cache_read,
        )
        expected = (
            (prompt - cache_read) * _INPUT_COST_PER_MILLION / _MILLION
            + completion * _OUTPUT_COST_PER_MILLION / _MILLION
            + cache_read * _CACHE_COST_PER_MILLION / _MILLION
        )
        assert gr.estimated_cost_usd == pytest.approx(expected)

    def test_cache_tokens_default_to_zero(self) -> None:
        """cache_read_tokens and cache_write_tokens must default to 0."""
        gr = GenerationResult(
            content={},
            prompt_tokens=100,
            completion_tokens=50,
            model_used="m",
            duration_seconds=1.0,
        )
        assert gr.cache_read_tokens == 0
        assert gr.cache_write_tokens == 0


class TestRenderResult:
    """Tests for RenderResult.is_binary property."""

    def test_is_binary_true_for_bytes_content(self) -> None:
        """is_binary must return True when content is bytes (PDF, image)."""
        rr = RenderResult(content=b"binary data", content_type="application/pdf", size_bytes=11)
        assert rr.is_binary is True

    def test_is_binary_false_for_str_content(self) -> None:
        """is_binary must return False when content is a str (HTML, text)."""
        rr = RenderResult(content="<html/>", content_type="text/html", size_bytes=7)
        assert rr.is_binary is False


class TestTailorOutput:
    """Tests for TailorOutput delegation properties."""

    def _make_output(self) -> TailorOutput:
        """Create a minimal TailorOutput for property tests."""
        gen = GenerationResult(
            content={"name": "John"},
            prompt_tokens=800,
            completion_tokens=150,
            model_used="openrouter:test/model",
            duration_seconds=2.5,
        )
        render = RenderResult(content=b"pdf bytes", content_type="application/pdf", size_bytes=9)
        spec = OutputSpec(path=Path("/out/resume.pdf"), format="pdf")
        output_result = OutputResult(spec=spec, render_result=render, written_path=Path("/out/resume.pdf"))
        return TailorOutput(outputs=[output_result], generation_result=gen)

    def test_total_tokens_delegates_to_generation(self) -> None:
        """total_tokens on TailorOutput must equal generation_result.total_tokens."""
        out = self._make_output()
        assert out.total_tokens == out.generation_result.total_tokens

    def test_estimated_cost_usd_delegates_to_generation(self) -> None:
        """estimated_cost_usd must equal generation_result.estimated_cost_usd."""
        out = self._make_output()
        assert out.estimated_cost_usd == out.generation_result.estimated_cost_usd

    def test_total_duration_seconds_delegates_to_generation(self) -> None:
        """total_duration_seconds must equal generation_result.duration_seconds."""
        out = self._make_output()
        assert out.total_duration_seconds == out.generation_result.duration_seconds

    def test_lint_issues_defaults_to_empty(self) -> None:
        """TailorOutput.lint_issues must default to empty list."""
        out = self._make_output()
        assert out.lint_issues == []

    def test_has_lint_errors_false_when_no_issues(self) -> None:
        """has_lint_errors must be False when lint_issues is empty."""
        out = self._make_output()
        assert out.has_lint_errors is False

    def test_has_lint_errors_true_when_error_present(self) -> None:
        """has_lint_errors must be True when any issue has ERROR severity."""
        from tailor.lint.models import LintIssue, Severity

        issue = LintIssue(rule="r", severity=Severity.ERROR, path="p", message="m")
        out = _make_output_with_lint([issue])
        assert out.has_lint_errors is True

    def test_has_lint_errors_false_for_warnings_only(self) -> None:
        """has_lint_errors must be False when only WARNING issues exist."""
        from tailor.lint.models import LintIssue, Severity

        issue = LintIssue(rule="r", severity=Severity.WARNING, path="p", message="m")
        out = _make_output_with_lint([issue])
        assert out.has_lint_errors is False

    def test_lint_error_count(self) -> None:
        """lint_error_count must count only ERROR-severity issues."""
        from tailor.lint.models import LintIssue, Severity

        issues = [
            LintIssue(rule="r1", severity=Severity.ERROR, path="", message=""),
            LintIssue(rule="r2", severity=Severity.ERROR, path="", message=""),
            LintIssue(rule="r3", severity=Severity.WARNING, path="", message=""),
        ]
        out = _make_output_with_lint(issues)
        assert out.lint_error_count == 2

    def test_lint_warning_count(self) -> None:
        """lint_warning_count must count only WARNING-severity issues."""
        from tailor.lint.models import LintIssue, Severity

        issues = [
            LintIssue(rule="r1", severity=Severity.ERROR, path="", message=""),
            LintIssue(rule="r2", severity=Severity.WARNING, path="", message=""),
            LintIssue(rule="r3", severity=Severity.WARNING, path="", message=""),
        ]
        out = _make_output_with_lint(issues)
        assert out.lint_warning_count == 2

    def test_total_output_size_bytes_sums_all_outputs(self) -> None:
        """total_output_size_bytes must sum render_result.size_bytes across all outputs."""
        gen = GenerationResult(content={}, prompt_tokens=0, completion_tokens=0, model_used="m", duration_seconds=0.0)
        r1 = RenderResult(content=b"", content_type="application/pdf", size_bytes=100)
        r2 = RenderResult(content=b"", content_type="text/html", size_bytes=200)
        s1 = OutputSpec(path=Path("/out/a.pdf"), format="pdf")
        s2 = OutputSpec(path=Path("/out/b.html"), format="html")
        outputs = [
            OutputResult(spec=s1, render_result=r1, written_path=Path("/out/a.pdf")),
            OutputResult(spec=s2, render_result=r2, written_path=Path("/out/b.html")),
        ]
        out = TailorOutput(outputs=outputs, generation_result=gen)
        assert out.total_output_size_bytes == 300


class TestOutputResult:
    """Tests for OutputResult frozen dataclass."""

    def test_fields_stored_correctly(self) -> None:
        """OutputResult must store spec, render_result, and written_path."""
        spec = OutputSpec(path=Path("/out/r.pdf"), format="pdf")
        render = RenderResult(content=b"data", content_type="application/pdf", size_bytes=4)
        written = Path("/out/r.pdf")
        result = OutputResult(spec=spec, render_result=render, written_path=written)
        assert result.spec == spec
        assert result.render_result == render
        assert result.written_path == written

    def test_frozen_prevents_mutation(self) -> None:
        """OutputResult is frozen; direct assignment must raise."""
        spec = OutputSpec(path=Path("/out/r.pdf"), format="pdf")
        render = RenderResult(content=b"", content_type="application/pdf", size_bytes=0)
        result = OutputResult(spec=spec, render_result=render, written_path=Path("/out/r.pdf"))
        frozen_field = "written_path"
        with pytest.raises(AttributeError):
            setattr(result, frozen_field, Path("/other.pdf"))


class TestTemplateInfo:
    """Tests for TemplateInfo properties."""

    def _make_template(self, name: str = "my_resume_template") -> TemplateInfo:
        """Create a TemplateInfo for testing."""
        return TemplateInfo(
            path=Path(f"/templates/{name}.html"),
            name=name,
            content="<html/>",
            version="1.0.0",
            description="A test template",
            access_scope="PUBLIC",
        )

    def test_filename_returns_path_name(self) -> None:
        """Filename must return the basename of the path."""
        t = self._make_template("cover_letter")
        assert t.filename == "cover_letter.html"

    @pytest.mark.parametrize(
        ("name", "expected_display"),
        [
            ("my_resume_template", "My Resume Template"),
            ("cover-letter-template", "Cover Letter Template"),
            ("simple", "Simple"),
            ("two__underscores", "Two  Underscores"),
        ],
    )
    def test_display_name_converts_separators_to_title_case(self, name: str, expected_display: str) -> None:
        """display_name must replace underscores/dashes with spaces and title-case."""
        t = self._make_template(name)
        assert t.display_name == expected_display

    def test_schema_name_defaults_to_none(self) -> None:
        """schema_name must default to None when not explicitly set."""
        t = self._make_template()
        assert t.schema_name is None

    def test_schema_name_can_be_set(self) -> None:
        """schema_name must be stored when provided."""
        t = TemplateInfo(
            path=Path("/t.html"),
            name="tmpl",
            content="",
            version="1.0",
            description="d",
            access_scope="PUBLIC",
            schema_name="resume",
        )
        assert t.schema_name == "resume"


class TestSchemaInfo:
    """Tests for SchemaInfo properties."""

    def _make_schema(
        self,
        name: str = "resume",
        content: JsonDict | None = None,
        title: str | None = None,
    ) -> SchemaInfo:
        """Create a SchemaInfo for testing."""
        resolved: JsonDict = (
            content
            if content is not None
            else {
                "title": "Resume",
                "type": "object",
                "properties": {"name": {"type": "string"}, "email": {"type": "string"}},
                "required": ["name"],
            }
        )
        return SchemaInfo(path=Path(f"/schemas/{name}_schema.json"), name=name, content=resolved, title=title)

    def test_filename_returns_path_name(self) -> None:
        """Filename must return the basename of the schema file path."""
        s = self._make_schema("resume")
        assert s.filename == "resume_schema.json"

    def test_display_name_returns_title_when_set(self) -> None:
        """display_name must return the title field when it is set."""
        s = self._make_schema(title="My Fancy Schema")
        assert s.display_name == "My Fancy Schema"

    def test_display_name_falls_back_to_name_conversion(self) -> None:
        """display_name must fall back to name → space → title-case when title is None."""
        s = self._make_schema(name="cover_letter", title=None, content={})
        assert s.display_name == "Cover Letter"

    def test_required_fields_returns_list_from_content(self) -> None:
        """required_fields must return the list from schema content['required']."""
        s = self._make_schema()
        assert s.required_fields == ["name"]

    def test_required_fields_empty_when_key_missing(self) -> None:
        """required_fields must return [] when 'required' key is absent."""
        s = self._make_schema(content={"type": "object"})
        assert s.required_fields == []

    def test_required_fields_empty_when_value_not_list(self) -> None:
        """required_fields must return [] when 'required' is not a list."""
        s = self._make_schema(content={"required": "name"})
        assert s.required_fields == []

    def test_properties_returns_dict_from_content(self) -> None:
        """Properties must return the dict from schema content['properties']."""
        s = self._make_schema()
        assert "name" in s.properties
        assert "email" in s.properties

    def test_properties_empty_when_key_missing(self) -> None:
        """Properties must return {} when 'properties' key is absent."""
        s = self._make_schema(content={"type": "object"})
        assert s.properties == {}

    def test_properties_empty_when_value_not_dict(self) -> None:
        """Properties must return {} when 'properties' is not a dict."""
        s = self._make_schema(content={"properties": ["name"]})
        assert s.properties == {}
