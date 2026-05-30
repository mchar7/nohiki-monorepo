"""Tests for tailor.display.panels -- Rich display functions."""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from rich.console import Console
from tailor.core.types import OutputSpec
from tailor.display.console import tailor_theme
from tailor.display.panels import (
    display_error,
    display_lint_issues,
    display_metrics,
    display_success,
    display_summary,
    display_templates_table,
)
from tailor.models.inputs import ContextFile, JobFile, TailorInput
from tailor.models.outputs import GenerationResult, OutputResult, RenderResult, TailorOutput
from tailor.models.templates import TemplateInfo

if TYPE_CHECKING:
    from tailor.lint.models import LintIssue


def _make_console() -> tuple[Console, io.StringIO]:
    """Create an in-memory console for capturing Rich output in tests."""
    buf = io.StringIO()
    return Console(file=buf, no_color=True, width=120, theme=tailor_theme), buf


def _make_generation_result(
    *,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    cache_read: int = 0,
    cache_write: int = 0,
) -> GenerationResult:
    """Build a GenerationResult for panel tests."""
    return GenerationResult(
        content={"name": "Alice"},
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model_used="test-model",
        duration_seconds=2.5,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )


def _make_render_result(*, size_bytes: int = 1024) -> RenderResult:
    """Build a RenderResult for panel tests."""
    return RenderResult(
        content=b"pdf bytes",
        content_type="application/pdf",
        size_bytes=size_bytes,
    )


def _make_tailor_output(*, cache_read: int = 0, cache_write: int = 0) -> TailorOutput:
    """Build a TailorOutput for panel tests."""
    spec = OutputSpec(path=Path("/out/resume.pdf"), format="pdf")
    output_result = OutputResult(
        spec=spec,
        render_result=_make_render_result(),
        written_path=Path("/out/resume.pdf"),
    )
    return TailorOutput(
        outputs=[output_result],
        generation_result=_make_generation_result(cache_read=cache_read, cache_write=cache_write),
    )


def _make_template_info(name: str = "test_resume") -> TemplateInfo:
    """Build a TemplateInfo for panel tests."""
    return TemplateInfo(
        path=Path(f"/templates/{name}.html"),
        name=name,
        content="<html/>",
        version="1.0.0",
        description="A test resume template",
        access_scope="PUBLIC",
    )


class TestDisplaySuccess:
    """Tests for display_success panel."""

    def test_output_contains_path(self, mocker: MagicMock) -> None:
        """display_success must print the output file path."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        output = _make_tailor_output()
        display_success(output)
        result = buf.getvalue()
        assert "/out/resume.pdf" in result

    def test_output_contains_token_counts(self, mocker: MagicMock) -> None:
        """display_success must show prompt and completion token counts."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        output = _make_tailor_output()
        display_success(output)
        result = buf.getvalue()
        assert "100" in result
        assert "50" in result

    def test_output_contains_size(self, mocker: MagicMock) -> None:
        """display_success must show the rendered document size."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        output = _make_tailor_output()
        display_success(output)
        result = buf.getvalue()
        assert "1.0 KB" in result

    def test_cache_section_shown_when_cache_tokens_present(self, mocker: MagicMock) -> None:
        """display_success must show cache stats when cache tokens are non-zero."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        output = _make_tailor_output(cache_read=40, cache_write=10)
        display_success(output)
        result = buf.getvalue()
        assert "Cache" in result or "cache" in result.lower()

    def test_cache_section_absent_when_no_cache_tokens(self, mocker: MagicMock) -> None:
        """display_success must not show cache section when cache tokens are zero."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        output = _make_tailor_output(cache_read=0, cache_write=0)
        display_success(output)
        result = buf.getvalue()
        assert "Cache" not in result


class TestDisplayLintIssues:
    """Tests for display_lint_issues panel."""

    def _make_issue(
        self,
        *,
        rule: str = "content.test.min_items",
        severity: str = "warning",
        path: str = "items",
        message: str = "Test issue",
    ) -> LintIssue:
        """Build a LintIssue for panel tests."""
        from tailor.lint.models import LintIssue, Severity

        return LintIssue(rule=rule, severity=Severity(severity), path=path, message=message)

    def test_empty_issues_prints_nothing(self, mocker: MagicMock) -> None:
        """display_lint_issues must print nothing when issues list is empty."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_lint_issues([])
        assert buf.getvalue() == ""

    def test_prints_table_for_single_issue(self, mocker: MagicMock) -> None:
        """display_lint_issues must print output when at least one issue exists."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_lint_issues([self._make_issue()])
        output = buf.getvalue()
        assert len(output) > 0

    def test_shows_rule_id_in_output(self, mocker: MagicMock) -> None:
        """display_lint_issues must include the rule ID in the output."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_lint_issues([self._make_issue(rule="content.experience_bullets.min_items")])
        assert "content.experience_bullets.min_items" in buf.getvalue()

    def test_shows_message_in_output(self, mocker: MagicMock) -> None:
        """display_lint_issues must include the issue message in the output."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_lint_issues([self._make_issue(message="Too few bullets")])
        assert "Too few bullets" in buf.getvalue()

    def test_shows_path_in_output(self, mocker: MagicMock) -> None:
        """display_lint_issues must include the issue path in the output."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_lint_issues([self._make_issue(path="experience.entries[0].bullets")])
        assert "experience.entries[0].bullets" in buf.getvalue()

    def test_errors_appear_before_warnings(self, mocker: MagicMock) -> None:
        """Issues must be sorted ERROR before WARNING in output."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        issues = [
            self._make_issue(rule="warn.rule", severity="warning", message="Warning message"),
            self._make_issue(rule="err.rule", severity="error", message="Error message"),
        ]
        display_lint_issues(issues)
        output = buf.getvalue()
        assert output.index("Error message") < output.index("Warning message")

    def test_multiple_issues_all_shown(self, mocker: MagicMock) -> None:
        """All issues must appear in output, not just the first."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        issues = [
            self._make_issue(rule="r1", message="First issue"),
            self._make_issue(rule="r2", message="Second issue"),
            self._make_issue(rule="r3", message="Third issue"),
        ]
        display_lint_issues(issues)
        output = buf.getvalue()
        assert "First issue" in output
        assert "Second issue" in output
        assert "Third issue" in output


class TestDisplayError:
    """Tests for display_error panel."""

    def test_output_contains_message(self, mocker: MagicMock) -> None:
        """display_error must print the error message."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_error("Something went wrong")
        result = buf.getvalue()
        assert "Something went wrong" in result

    def test_output_contains_default_title(self, mocker: MagicMock) -> None:
        """display_error must use 'Error' as the default title."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_error("Oops")
        result = buf.getvalue()
        assert "Error" in result

    def test_output_contains_custom_title(self, mocker: MagicMock) -> None:
        """display_error must use the provided custom title."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_error("Service down", title="Service Unavailable")
        result = buf.getvalue()
        assert "Service Unavailable" in result


class TestDisplayMetrics:
    """Tests for display_metrics standalone metric display."""

    def test_output_contains_token_counts(self, mocker: MagicMock) -> None:
        """display_metrics must print prompt and completion token counts."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_metrics(prompt_tokens=200, completion_tokens=80, duration_seconds=3.0, cost_usd=0.001)
        result = buf.getvalue()
        assert "200" in result
        assert "80" in result

    def test_output_contains_duration(self, mocker: MagicMock) -> None:
        """display_metrics must print the formatted duration."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_metrics(prompt_tokens=100, completion_tokens=50, duration_seconds=1.5, cost_usd=0.0005)
        result = buf.getvalue()
        assert "1.5s" in result

    def test_output_contains_cost(self, mocker: MagicMock) -> None:
        """display_metrics must print the estimated cost."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_metrics(prompt_tokens=100, completion_tokens=50, duration_seconds=1.0, cost_usd=0.05)
        result = buf.getvalue()
        assert "$0.05" in result

    def test_total_tokens_shown(self, mocker: MagicMock) -> None:
        """display_metrics must show the total token sum."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_metrics(prompt_tokens=300, completion_tokens=100, duration_seconds=2.0, cost_usd=0.001)
        result = buf.getvalue()
        assert "400" in result


class TestDisplaySummary:
    """Tests for display_summary pre-generation summary panel."""

    def _make_tailor_input(self, tmp_path: Path) -> TailorInput:
        """Build a TailorInput with real temp files for stat() calls."""
        ctx_file = tmp_path / "ctx.txt"
        ctx_file.write_text("resume content", encoding="utf-8")
        job_file = tmp_path / "job.md"
        job_file.write_text("job posting", encoding="utf-8")
        return TailorInput(
            context_files=[ContextFile(path=ctx_file, content="resume content", size_bytes=14, word_count=2)],
            job_files=[JobFile(path=job_file, content="job posting", size_bytes=11)],
            template_name="test_resume",
            schema_name="resume",
            outputs=[OutputSpec(path=Path("/out/resume.pdf"), format="pdf")],
        )

    def test_output_contains_template_name(self, mocker: MagicMock, tmp_path: Path) -> None:
        """display_summary must include the template name."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        tailor_input = self._make_tailor_input(tmp_path)
        display_summary(tailor_input, "google/gemini-flash")
        result = buf.getvalue()
        assert "test_resume" in result

    def test_output_contains_model_name(self, mocker: MagicMock, tmp_path: Path) -> None:
        """display_summary must include the LLM model name."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        tailor_input = self._make_tailor_input(tmp_path)
        display_summary(tailor_input, "google/gemini-flash")
        result = buf.getvalue()
        assert "google/gemini-flash" in result

    def test_output_contains_file_counts(self, mocker: MagicMock, tmp_path: Path) -> None:
        """display_summary must show context and job file counts."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        tailor_input = self._make_tailor_input(tmp_path)
        display_summary(tailor_input, "model")
        result = buf.getvalue()
        assert "1" in result

    def test_outputs_shown(self, mocker: MagicMock, tmp_path: Path) -> None:
        """display_summary must show each output spec path."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        tailor_input = self._make_tailor_input(tmp_path)
        display_summary(tailor_input, "model")
        result = buf.getvalue()
        assert "resume.pdf" in result


class TestDisplayTemplatesTable:
    """Tests for display_templates_table table display."""

    def test_output_contains_template_names(self, mocker: MagicMock) -> None:
        """display_templates_table must print each template's name."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        templates = [_make_template_info("resume"), _make_template_info("cover_letter")]
        display_templates_table(templates)
        result = buf.getvalue()
        assert "resume" in result
        assert "cover_letter" in result

    def test_output_contains_version(self, mocker: MagicMock) -> None:
        """display_templates_table must print the version column."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_templates_table([_make_template_info("resume")])
        result = buf.getvalue()
        assert "1.0.0" in result

    def test_output_contains_description(self, mocker: MagicMock) -> None:
        """display_templates_table must print the description or a placeholder."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        display_templates_table([_make_template_info()])
        result = buf.getvalue()
        assert "test resume" in result.lower() or "-" in result

    @pytest.mark.parametrize("count", [1, 2, 5])
    def test_row_count_matches_template_count(self, mocker: MagicMock, count: int) -> None:
        """display_templates_table must render one row per template."""
        test_console, buf = _make_console()
        mocker.patch("tailor.display.panels.console", test_console)
        templates = [_make_template_info(f"tmpl_{i}") for i in range(count)]
        display_templates_table(templates)
        result = buf.getvalue()
        for i in range(count):
            assert f"tmpl_{i}" in result
