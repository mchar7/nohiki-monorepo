"""Tests for tailor.display.wizard -- InteractiveWizard and run_wizard()."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture
from tailor.display.wizard import InteractiveWizard, run_wizard
from tailor.exceptions import GotenbergError, SchemaError, TailorError
from tailor.models.templates import TemplateInfo


def _make_template_info(name: str = "test_resume") -> TemplateInfo:
    """Build a minimal TemplateInfo for use in wizard step mocks."""
    return TemplateInfo(
        path=Path(f"/templates/{name}.html"),
        name=name,
        content="<html/>",
        version="1.0.0",
        description="Test template",
        access_scope="PUBLIC",
    )


def _make_mock_output() -> MagicMock:
    """Build a MagicMock resembling TailorOutput for the full-run test."""
    mock_output = MagicMock()
    mock_output.total_output_size_bytes = 5000
    mock_output.generation_result.total_tokens = 100
    mock_output.generation_result.prompt_tokens = 80
    mock_output.generation_result.completion_tokens = 20
    mock_output.generation_result.duration_seconds = 1.5
    mock_output.generation_result.estimated_cost_usd = 0.001
    mock_output.generation_result.cache_read_tokens = 0
    mock_output.generation_result.cache_write_tokens = 0
    return mock_output


@pytest.fixture
def mock_tailor_settings(tmp_path: Path) -> MagicMock:
    """Override conftest mock_tailor_settings with a plain MagicMock (no spec).

    Uses a flat ``llm_model`` string matching the refactored TailorSettings,
    which no longer depends on LLMMixin's nested provider configuration.
    """
    settings = MagicMock()
    settings.gotenberg_url = "http://localhost:3000"
    settings.gotenberg_timeout_s = 30
    settings.resolved_output_dir = tmp_path / "output"
    settings.llm_model = "openrouter:google/gemini-flash-1.5"
    return settings


@pytest.fixture
def mock_orchestrator() -> MagicMock:
    """Create a MagicMock orchestrator with sensible defaults for wizard tests."""
    orch = MagicMock()
    orch.check_services = AsyncMock(return_value={"gotenberg": True})
    orch.generate = AsyncMock(return_value=_make_mock_output())
    orch.file_adapter.discover_templates.return_value = [_make_template_info()]
    orch.file_adapter.resolve_schema_for_template.return_value = "resume"
    orch.file_adapter.generate_filename.return_value = "output.pdf"
    orch.llm_adapter.model_name = "google/gemini-flash-1.5"
    return orch


@pytest.fixture
def wizard_factory(
    mocker: MockerFixture,
    mock_tailor_settings: MagicMock,
    mock_orchestrator: MagicMock,
) -> tuple[type[InteractiveWizard], MagicMock]:
    """Patch get_settings and TailorOrchestrator.create before wizard creation.

    Returns the InteractiveWizard class and the mock orchestrator so callers
    can further configure the orchestrator per test.
    """
    mocker.patch("tailor.display.wizard.get_settings", return_value=mock_tailor_settings)
    mocker.patch("tailor.display.wizard.TailorOrchestrator.create", return_value=mock_orchestrator)
    mocker.patch("tailor.display.wizard.Live")
    mocker.patch("tailor.display.wizard.display_success")
    mocker.patch("tailor.display.wizard.display_error")
    mocker.patch("tailor.display.wizard.console")
    return InteractiveWizard, mock_orchestrator


@pytest.fixture
def _all_prompts_succeed(mocker: MockerFixture, tmp_path: Path) -> None:
    """Patch all wizard prompt helpers so every step succeeds."""
    context_file = tmp_path / "context.txt"
    context_file.write_text("context content")
    job_file = tmp_path / "job.txt"
    job_file.write_text("job content")

    mocker.patch("tailor.display.wizard.prompt_context_files", return_value=[context_file])
    mocker.patch("tailor.display.wizard.prompt_job_files", return_value=[job_file])
    mocker.patch("tailor.display.wizard.prompt_template_selection", return_value=_make_template_info())
    mocker.patch("tailor.display.wizard.prompt_output_path", return_value=Path("/tmp/out.pdf"))
    mocker.patch("tailor.display.wizard.prompt_confirm_generation", return_value=True)
    mocker.patch("tailor.display.wizard.display_summary")
    mocker.patch("tailor.display.wizard.display_step_header")


class TestRunWizard:
    """Tests for the run_wizard() synchronous entry point."""

    def test_returns_exit_code_from_wizard_run(
        self,
        mocker: MockerFixture,
        mock_tailor_settings: MagicMock,
        mock_orchestrator: MagicMock,
    ) -> None:
        """run_wizard() must return the integer exit code from InteractiveWizard.run()."""
        mocker.patch("tailor.display.wizard.get_settings", return_value=mock_tailor_settings)
        mocker.patch("tailor.display.wizard.TailorOrchestrator.create", return_value=mock_orchestrator)
        mocker.patch("tailor.display.wizard.Live")
        mocker.patch("tailor.display.wizard.display_error")
        mocker.patch("tailor.display.wizard.console")
        mock_orchestrator.check_services = AsyncMock(return_value={"gotenberg": False})

        result = run_wizard()
        assert result == 1


class TestWizardServiceCheck:
    """Tests for InteractiveWizard._check_services()."""

    async def test_gotenberg_unavailable_returns_1(
        self,
        wizard_factory: tuple[type[InteractiveWizard], MagicMock],
    ) -> None:
        """run() must return 1 when Gotenberg reports as unavailable."""
        wizard_class, orch = wizard_factory
        orch.check_services = AsyncMock(return_value={"gotenberg": False})
        wizard = wizard_class()
        result = await wizard.run()
        assert result == 1

    async def test_gotenberg_available_proceeds_to_steps(
        self,
        wizard_factory: tuple[type[InteractiveWizard], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        """run() must proceed past service check when Gotenberg is available."""
        wizard_class, orch = wizard_factory
        orch.check_services = AsyncMock(return_value={"gotenberg": True})
        mocker.patch("tailor.display.wizard.prompt_context_files", return_value=[])
        wizard = wizard_class()
        result = await wizard.run()
        # Returns 1 because step_context_files is cancelled, not because of service check
        assert result == 1


class TestWizardStepContextFiles:
    """Tests for InteractiveWizard._step_context_files()."""

    async def test_no_context_files_returns_1(
        self,
        wizard_factory: tuple[type[InteractiveWizard], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        """run() must return 1 when prompt_context_files returns an empty list."""
        wizard_class, _ = wizard_factory
        mocker.patch("tailor.display.wizard.prompt_context_files", return_value=[])
        mocker.patch("tailor.display.wizard.display_step_header")
        wizard = wizard_class()
        result = await wizard.run()
        assert result == 1


class TestWizardStepJobFiles:
    """Tests for InteractiveWizard._step_job_files()."""

    async def test_no_job_files_returns_1(
        self,
        wizard_factory: tuple[type[InteractiveWizard], MagicMock],
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """run() must return 1 when prompt_job_files returns an empty list."""
        wizard_class, _ = wizard_factory
        context_file = tmp_path / "ctx.txt"
        context_file.write_text("ctx")
        mocker.patch("tailor.display.wizard.prompt_context_files", return_value=[context_file])
        mocker.patch("tailor.display.wizard.prompt_job_files", return_value=[])
        mocker.patch("tailor.display.wizard.display_step_header")
        wizard = wizard_class()
        result = await wizard.run()
        assert result == 1


class TestWizardStepSelectTemplate:
    """Tests for InteractiveWizard._step_select_template()."""

    async def test_no_templates_returns_1(
        self,
        wizard_factory: tuple[type[InteractiveWizard], MagicMock],
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """run() must return 1 when no templates are discovered."""
        wizard_class, orch = wizard_factory
        context_file = tmp_path / "ctx.txt"
        context_file.write_text("ctx")
        job_file = tmp_path / "job.txt"
        job_file.write_text("job")
        mocker.patch("tailor.display.wizard.prompt_context_files", return_value=[context_file])
        mocker.patch("tailor.display.wizard.prompt_job_files", return_value=[job_file])
        mocker.patch("tailor.display.wizard.display_step_header")
        orch.file_adapter.discover_templates.return_value = []
        wizard = wizard_class()
        result = await wizard.run()
        assert result == 1

    async def test_template_selection_cancelled_returns_1(
        self,
        wizard_factory: tuple[type[InteractiveWizard], MagicMock],
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """run() must return 1 when prompt_template_selection returns None."""
        wizard_class, orch = wizard_factory
        context_file = tmp_path / "ctx.txt"
        context_file.write_text("ctx")
        job_file = tmp_path / "job.txt"
        job_file.write_text("job")
        mocker.patch("tailor.display.wizard.prompt_context_files", return_value=[context_file])
        mocker.patch("tailor.display.wizard.prompt_job_files", return_value=[job_file])
        mocker.patch("tailor.display.wizard.display_step_header")
        mocker.patch("tailor.display.wizard.prompt_template_selection", return_value=None)
        orch.file_adapter.discover_templates.return_value = [_make_template_info()]
        wizard = wizard_class()
        result = await wizard.run()
        assert result == 1

    async def test_schema_resolution_failure_returns_1(
        self,
        wizard_factory: tuple[type[InteractiveWizard], MagicMock],
        mocker: MockerFixture,
        tmp_path: Path,
    ) -> None:
        """run() must return 1 when resolve_schema_for_template raises SchemaError."""
        wizard_class, orch = wizard_factory
        context_file = tmp_path / "ctx.txt"
        context_file.write_text("ctx")
        job_file = tmp_path / "job.txt"
        job_file.write_text("job")
        mocker.patch("tailor.display.wizard.prompt_context_files", return_value=[context_file])
        mocker.patch("tailor.display.wizard.prompt_job_files", return_value=[job_file])
        mocker.patch("tailor.display.wizard.display_step_header")
        mocker.patch("tailor.display.wizard.prompt_template_selection", return_value=_make_template_info())
        orch.file_adapter.discover_templates.return_value = [_make_template_info()]
        orch.file_adapter.resolve_schema_for_template.side_effect = SchemaError("no schema")
        wizard = wizard_class()
        result = await wizard.run()
        assert result == 1


@pytest.mark.usefixtures("_all_prompts_succeed")
class TestWizardFullRun:
    """Tests for InteractiveWizard end-to-end happy path."""

    async def test_full_successful_run_returns_0(
        self,
        wizard_factory: tuple[type[InteractiveWizard], MagicMock],
    ) -> None:
        """run() must return 0 when all steps succeed and generation completes."""
        wizard_class, _ = wizard_factory
        wizard = wizard_class()
        result = await wizard.run()
        assert result == 0

    async def test_calls_display_lint_issues_on_success(
        self,
        wizard_factory: tuple[type[InteractiveWizard], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        """Wizard must call display_lint_issues after successful generation."""
        from tailor.core.types import OutputSpec
        from tailor.lint.models import LintIssue, Severity
        from tailor.models.outputs import GenerationResult, OutputResult, RenderResult, TailorOutput

        wizard_class, orch = wizard_factory
        mock_issue = LintIssue(rule="r", severity=Severity.WARNING, path="p", message="m")
        generation_result = GenerationResult(
            content={},
            prompt_tokens=0,
            completion_tokens=0,
            model_used="test-model",
            duration_seconds=0.0,
        )
        render_result = RenderResult(content=b"", content_type="application/pdf", size_bytes=0)
        spec = OutputSpec(path=Path("/tmp/output.pdf"), format="pdf")
        output_result = OutputResult(spec=spec, render_result=render_result, written_path=Path("/tmp/output.pdf"))
        output = TailorOutput(outputs=[output_result], generation_result=generation_result, lint_issues=[mock_issue])
        orch.generate = AsyncMock(return_value=output)
        mock_lint_display = mocker.patch("tailor.display.wizard.display_lint_issues")

        wizard = wizard_class()
        result = await wizard.run()

        assert result == 0
        mock_lint_display.assert_called_once_with([mock_issue])


@pytest.mark.usefixtures("_all_prompts_succeed")
class TestWizardGenerationErrors:
    """Tests for error handling during the generation phase."""

    async def test_gotenberg_error_during_generation_returns_1(
        self,
        wizard_factory: tuple[type[InteractiveWizard], MagicMock],
    ) -> None:
        """run() must return 1 when orchestrator.generate raises GotenbergError."""
        wizard_class, orch = wizard_factory
        orch.generate = AsyncMock(side_effect=GotenbergError("connection refused", status_code=503))
        wizard = wizard_class()
        result = await wizard.run()
        assert result == 1

    async def test_tailor_error_during_generation_returns_1(
        self,
        wizard_factory: tuple[type[InteractiveWizard], MagicMock],
    ) -> None:
        """run() must return 1 when orchestrator.generate raises a TailorError."""
        wizard_class, orch = wizard_factory
        orch.generate = AsyncMock(side_effect=TailorError("generation failed"))
        wizard = wizard_class()
        result = await wizard.run()
        assert result == 1
