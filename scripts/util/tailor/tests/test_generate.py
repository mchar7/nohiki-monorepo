"""Tests for tailor.cli.generate -- validation helpers and generate_command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from tailor.cli.generate import (
    _build_context,
    _update_spinner_for_mode,
    _validate_cli_args,
    generate_command,
)
from tailor.core.context import TailorContext


class TestValidateCliArgs:
    """Tests for tailor.cli.generate._validate_cli_args."""

    def test_raises_exit1_when_no_context_and_no_data(self) -> None:
        """_validate_cli_args must exit 1 when context is empty and data is None."""
        with pytest.raises(typer.Exit) as exc_info:
            _validate_cli_args(context=[], job=[Path("/jobs/j.md")], data=None, output=[Path("/out/resume.pdf")])
        assert exc_info.value.exit_code == 1

    def test_raises_exit1_when_no_job_and_no_data(self) -> None:
        """_validate_cli_args must exit 1 when job is empty and data is None."""
        with pytest.raises(typer.Exit) as exc_info:
            _validate_cli_args(context=[Path("/ctx/c.txt")], job=[], data=None, output=[Path("/out/resume.pdf")])
        assert exc_info.value.exit_code == 1

    def test_raises_exit1_when_data_and_context_provided(self, tmp_path: Path) -> None:
        """_validate_cli_args must exit 1 when both data and context are supplied."""
        data_file = tmp_path / "data.json"
        with pytest.raises(typer.Exit) as exc_info:
            _validate_cli_args(
                context=[Path("/ctx/c.txt")],
                job=[],
                data=data_file,
                output=[Path("/out/resume.pdf")],
            )
        assert exc_info.value.exit_code == 1

    def test_raises_exit1_when_data_and_job_provided(self, tmp_path: Path) -> None:
        """_validate_cli_args must exit 1 when both data and job are supplied."""
        data_file = tmp_path / "data.json"
        with pytest.raises(typer.Exit) as exc_info:
            _validate_cli_args(
                context=[],
                job=[Path("/jobs/j.md")],
                data=data_file,
                output=[Path("/out/resume.pdf")],
            )
        assert exc_info.value.exit_code == 1

    def test_raises_exit1_when_11_context_files(self) -> None:
        """_validate_cli_args must exit 1 when more than 10 context files are provided."""
        context = [Path(f"/ctx/{i}.txt") for i in range(11)]
        with pytest.raises(typer.Exit) as exc_info:
            _validate_cli_args(context=context, job=[Path("/jobs/j.md")], data=None, output=[Path("/out/resume.pdf")])
        assert exc_info.value.exit_code == 1

    def test_raises_exit1_when_11_job_files(self) -> None:
        """_validate_cli_args must exit 1 when more than 10 job files are provided."""
        job = [Path(f"/jobs/{i}.md") for i in range(11)]
        with pytest.raises(typer.Exit) as exc_info:
            _validate_cli_args(context=[Path("/ctx/c.txt")], job=job, data=None, output=[Path("/out/resume.pdf")])
        assert exc_info.value.exit_code == 1

    def test_does_not_raise_for_valid_context_and_job(self) -> None:
        """_validate_cli_args must not raise when context and job are valid lists."""
        _validate_cli_args(
            context=[Path("/ctx/c.txt")],
            job=[Path("/jobs/j.md")],
            data=None,
            output=[Path("/out/resume.pdf")],
        )

    def test_does_not_raise_with_exactly_10_context_files(self) -> None:
        """_validate_cli_args must not raise for exactly 10 context files."""
        context = [Path(f"/ctx/{i}.txt") for i in range(10)]
        _validate_cli_args(context=context, job=[Path("/jobs/j.md")], data=None, output=[Path("/out/resume.pdf")])

    def test_does_not_raise_with_exactly_10_job_files(self) -> None:
        """_validate_cli_args must not raise for exactly 10 job files."""
        job = [Path(f"/jobs/{i}.md") for i in range(10)]
        _validate_cli_args(context=[Path("/ctx/c.txt")], job=job, data=None, output=[Path("/out/resume.pdf")])

    def test_does_not_raise_with_data_only(self, tmp_path: Path) -> None:
        """_validate_cli_args must not raise when only data is provided with no context or job."""
        data_file = tmp_path / "data.json"
        _validate_cli_args(context=[], job=[], data=data_file, output=[Path("/out/data.json")])

    def test_raises_exit1_when_no_output_paths(self) -> None:
        """_validate_cli_args must exit 1 when output list is empty."""
        with pytest.raises(typer.Exit) as exc_info:
            _validate_cli_args(context=[Path("/ctx/c.txt")], job=[Path("/jobs/j.md")], data=None, output=[])
        assert exc_info.value.exit_code == 1

    def test_raises_exit1_when_unsupported_extension(self) -> None:
        """_validate_cli_args must exit 1 when an output path has an unsupported extension."""
        with pytest.raises(typer.Exit) as exc_info:
            _validate_cli_args(
                context=[Path("/ctx/c.txt")],
                job=[Path("/jobs/j.md")],
                data=None,
                output=[Path("/out/resume.doc")],
            )
        assert exc_info.value.exit_code == 1

    def test_does_not_raise_for_valid_output_extension(self) -> None:
        """_validate_cli_args must not raise for a valid .pdf output."""
        _validate_cli_args(
            context=[Path("/ctx/c.txt")],
            job=[Path("/jobs/j.md")],
            data=None,
            output=[Path("/out/resume.pdf")],
        )


class TestBuildContext:
    """Tests for tailor.cli.generate._build_context."""

    def test_data_file_path_is_set_from_data_argument(self, tmp_path: Path) -> None:
        """_build_context must assign data_file_path from the data argument."""
        data_file = tmp_path / "data.json"
        ctx = _build_context(
            context=[],
            job=[],
            data=data_file,
            template="test_resume",
            schema_name="resume",
            output=[Path("/out/data.json")],
        )
        assert ctx.data_file_path == data_file

    def test_returns_tailor_context_instance(self) -> None:
        """_build_context must return a TailorContext instance."""
        ctx = _build_context(
            context=[Path("/ctx/c.txt")],
            job=[Path("/jobs/j.md")],
            data=None,
            template="test_resume",
            schema_name="resume",
            output=[Path("/out/resume.html")],
        )
        assert isinstance(ctx, TailorContext)

    def test_context_file_paths_from_context_arg(self) -> None:
        """_build_context must populate context_file_paths from the context arg."""
        paths = [Path("/ctx/a.txt"), Path("/ctx/b.txt")]
        ctx = _build_context(
            context=paths,
            job=[Path("/jobs/j.md")],
            data=None,
            template="test_resume",
            schema_name="resume",
            output=[Path("/out/resume.pdf")],
        )
        assert ctx.context_file_paths == paths

    def test_job_file_paths_from_job_arg(self) -> None:
        """_build_context must populate job_file_paths from the job arg."""
        jobs = [Path("/jobs/a.md")]
        ctx = _build_context(
            context=[Path("/ctx/c.txt")],
            job=jobs,
            data=None,
            template="test_resume",
            schema_name="resume",
            output=[Path("/out/resume.pdf")],
        )
        assert ctx.job_file_paths == jobs

    def test_single_pdf_output_builds_output_spec(self) -> None:
        """_build_context must build OutputSpec with pdf format from .pdf path."""
        from tailor.core.types import OutputSpec

        ctx = _build_context(
            context=[Path("/ctx/c.txt")],
            job=[Path("/jobs/j.md")],
            data=None,
            template="test_resume",
            schema_name="resume",
            output=[Path("/out/resume.pdf")],
        )
        assert ctx.outputs == [OutputSpec(path=Path("/out/resume.pdf"), format="pdf")]

    def test_multiple_outputs_build_multiple_specs(self) -> None:
        """_build_context must build one OutputSpec per output path."""
        from tailor.core.types import OutputSpec

        ctx = _build_context(
            context=[Path("/ctx/c.txt")],
            job=[Path("/jobs/j.md")],
            data=None,
            template="test_resume",
            schema_name="resume",
            output=[Path("/out/a.pdf"), Path("/out/b.png")],
        )
        assert len(ctx.outputs) == 2
        assert ctx.outputs[0] == OutputSpec(path=Path("/out/a.pdf"), format="pdf")
        assert ctx.outputs[1] == OutputSpec(path=Path("/out/b.png"), format="png")

    def test_json_output_builds_json_spec(self) -> None:
        """_build_context must infer json format from .json extension."""
        from tailor.core.types import OutputSpec

        ctx = _build_context(
            context=[],
            job=[],
            data=Path("/data/d.json"),
            template="test_resume",
            schema_name="resume",
            output=[Path("/out/data.json")],
        )
        assert ctx.outputs == [OutputSpec(path=Path("/out/data.json"), format="json")]


class TestUpdateSpinnerForMode:
    """Tests for tailor.cli.generate._update_spinner_for_mode."""

    def test_manual_mode_updates_spinner_with_validating_message(self) -> None:
        """_update_spinner_for_mode must call spinner.update with 'Validating manual data...' in manual mode."""
        spinner = MagicMock()
        ctx = TailorContext(
            data_file_path=Path("/data/d.json"),
            template_name="test_resume",
            schema_name="resume",
        )
        orchestrator = MagicMock()
        _update_spinner_for_mode(spinner, ctx, orchestrator)
        spinner.update.assert_called_once_with("Validating manual data...")

    def test_llm_mode_updates_spinner_with_model_name(self) -> None:
        """_update_spinner_for_mode must include the model name in the LLM spinner message."""
        spinner = MagicMock()
        ctx = TailorContext(
            context_file_paths=[Path("/ctx/c.txt")],
            job_file_paths=[Path("/jobs/j.md")],
            template_name="test_resume",
            schema_name="resume",
        )
        orchestrator = MagicMock()
        orchestrator.llm_adapter.model_name = "google/gemini-flash-1.5"
        _update_spinner_for_mode(spinner, ctx, orchestrator)
        spinner.update.assert_called_once_with("Calling LLM (google/gemini-flash-1.5)...")

    def test_llm_mode_message_format(self) -> None:
        """_update_spinner_for_mode LLM message must match expected format exactly."""
        spinner = MagicMock()
        ctx = TailorContext(
            context_file_paths=[Path("/ctx/c.txt")],
            job_file_paths=[Path("/jobs/j.md")],
            template_name="test_resume",
            schema_name="resume",
        )
        orchestrator = MagicMock()
        model_name = "openai/gpt-4o"
        orchestrator.llm_adapter.model_name = model_name
        _update_spinner_for_mode(spinner, ctx, orchestrator)
        expected = f"Calling LLM ({model_name})..."
        spinner.update.assert_called_once_with(expected)


class TestGenerateCommand:
    """Tests for tailor.cli.generate.generate_command."""

    def _base_context_job(self, tmp_path: Path) -> tuple[list[Path], list[Path]]:
        """Create temp context and job files for generate_command tests."""
        ctx_file = tmp_path / "context.txt"
        ctx_file.write_text("my resume content", encoding="utf-8")
        job_file = tmp_path / "job.md"
        job_file.write_text("software engineer role", encoding="utf-8")
        return [ctx_file], [job_file]

    def test_validation_errors_propagate_before_orchestrator_creation(self) -> None:
        """generate_command must raise typer.Exit(1) on validation failure before creating orchestrator."""
        with patch("tailor.cli.generate.TailorOrchestrator") as mock_orch_cls:
            with pytest.raises(typer.Exit) as exc_info:
                generate_command(context=[], job=[], template="test_resume", output=[Path("/out/resume.pdf")])
            assert exc_info.value.exit_code == 1
        # Orchestrator should NOT have been created if validation fails first
        mock_orch_cls.create.assert_not_called()

    def test_uses_schema_arg_directly_when_provided(self, tmp_path: Path) -> None:
        """generate_command must use the schema argument when explicitly provided."""
        ctx_files, job_files = self._base_context_job(tmp_path)
        mock_orch = MagicMock()
        mock_orch.file_adapter.resolve_schema_for_template = MagicMock()
        mock_orch.generate = AsyncMock()

        with (
            patch("tailor.cli.generate.get_settings"),
            patch("tailor.cli.generate.TailorOrchestrator") as mock_orch_cls,
            patch("tailor.cli.generate.asyncio") as mock_asyncio,
        ):
            mock_orch_cls.create.return_value = mock_orch
            mock_asyncio.run = MagicMock(side_effect=lambda coro: coro.close())
            generate_command(
                context=ctx_files,
                job=job_files,
                template="test_resume",
                schema="my_schema",
                output=[Path("/out/resume.pdf")],
            )
        # resolve_schema_for_template must NOT be called when schema is provided
        mock_orch.file_adapter.resolve_schema_for_template.assert_not_called()

    def test_calls_resolve_schema_when_schema_not_provided(self, tmp_path: Path) -> None:
        """generate_command must call resolve_schema_for_template when schema arg is None."""
        ctx_files, job_files = self._base_context_job(tmp_path)
        mock_orch = MagicMock()
        mock_orch.file_adapter.resolve_schema_for_template = MagicMock(return_value="resume")
        mock_orch.generate = AsyncMock()

        with (
            patch("tailor.cli.generate.get_settings"),
            patch("tailor.cli.generate.TailorOrchestrator") as mock_orch_cls,
            patch("tailor.cli.generate.asyncio") as mock_asyncio,
        ):
            mock_orch_cls.create.return_value = mock_orch
            mock_asyncio.run = MagicMock(side_effect=lambda coro: coro.close())
            generate_command(
                context=ctx_files,
                job=job_files,
                template="test_resume",
                schema=None,
                output=[Path("/out/resume.pdf")],
            )
        mock_orch.file_adapter.resolve_schema_for_template.assert_called_once_with("test_resume")

    def test_calls_asyncio_run(self, tmp_path: Path) -> None:
        """generate_command must call asyncio.run to drive the async generation coroutine."""
        ctx_files, job_files = self._base_context_job(tmp_path)
        mock_orch = MagicMock()
        mock_orch.file_adapter.resolve_schema_for_template = MagicMock(return_value="resume")

        with (
            patch("tailor.cli.generate.get_settings"),
            patch("tailor.cli.generate.TailorOrchestrator") as mock_orch_cls,
            patch("tailor.cli.generate.asyncio") as mock_asyncio,
        ):
            mock_orch_cls.create.return_value = mock_orch
            # Close the coroutine immediately to prevent RuntimeWarning about unawaited coroutines.
            # The test only asserts that asyncio.run was called once, not that it ran to completion.
            mock_asyncio.run = MagicMock(side_effect=lambda coro: coro.close())
            generate_command(
                context=ctx_files,
                job=job_files,
                template="test_resume",
                schema="resume",
                output=[Path("/out/resume.pdf")],
            )
        mock_asyncio.run.assert_called_once()

    def test_calls_display_lint_issues_after_success(self, tmp_path: Path) -> None:
        """generate_command must call display_lint_issues after display_success."""
        from tailor.lint.models import LintIssue, Severity

        ctx_files, job_files = self._base_context_job(tmp_path)
        mock_issue = LintIssue(rule="r", severity=Severity.WARNING, path="p", message="m")
        mock_result = MagicMock()
        mock_result.lint_issues = [mock_issue]

        async def _fake_generate(_ctx: object) -> MagicMock:
            return mock_result

        mock_orch = MagicMock()
        mock_orch.file_adapter.resolve_schema_for_template = MagicMock(return_value="resume")
        mock_orch.generate = _fake_generate

        with (
            patch("tailor.cli.generate.get_settings"),
            patch("tailor.cli.generate.TailorOrchestrator") as mock_orch_cls,
            patch("tailor.cli.generate.display_success") as mock_success,
            patch("tailor.cli.generate.display_lint_issues") as mock_lint_display,
            patch("tailor.cli.generate.status_spinner"),
        ):
            mock_orch_cls.create.return_value = mock_orch
            generate_command(
                context=ctx_files,
                job=job_files,
                template="test_resume",
                schema="resume",
                output=[Path("/out/resume.pdf")],
            )

        mock_success.assert_called_once_with(mock_result)
        mock_lint_display.assert_called_once_with([mock_issue])

    def test_exits_1_on_missing_job_files(self) -> None:
        """generate_command must raise typer.Exit(1) when no job files and no data provided."""
        ctx_file = Path("/nonexistent/ctx.txt")
        with pytest.raises(typer.Exit) as exc_info:
            generate_command(context=[ctx_file], job=[], template="test_resume", output=[Path("/out/resume.pdf")])
        assert exc_info.value.exit_code == 1

    def test_exits_1_on_too_many_context_files(self) -> None:
        """generate_command must raise typer.Exit(1) when more than 10 context files supplied."""
        contexts = [Path(f"/ctx/{i}.txt") for i in range(11)]
        jobs = [Path("/jobs/j.md")]
        with pytest.raises(typer.Exit) as exc_info:
            generate_command(context=contexts, job=jobs, template="test_resume", output=[Path("/out/resume.pdf")])
        assert exc_info.value.exit_code == 1

    def test_exits_with_typer_exit_when_tailor_error_raised(self, tmp_path: Path) -> None:
        """generate_command must raise typer.Exit(1) when orchestrator.generate raises TailorError."""
        from tailor.exceptions import TailorError

        ctx_files, job_files = self._base_context_job(tmp_path)
        mock_orch = MagicMock()
        mock_orch.file_adapter.resolve_schema_for_template = MagicMock(return_value="resume")
        error_msg = "Something failed"

        async def _generate_raises(*_args: object, **_kwargs: object) -> object:
            raise TailorError(error_msg)

        mock_orch.generate = _generate_raises

        mock_spinner = MagicMock()
        mock_spinner.__enter__ = MagicMock(return_value=mock_spinner)
        mock_spinner.__exit__ = MagicMock(return_value=False)

        with (
            patch("tailor.cli.generate.get_settings"),
            patch("tailor.cli.generate.TailorOrchestrator") as mock_orch_cls,
            patch("tailor.cli.generate.status_spinner", return_value=mock_spinner),
            patch("tailor.cli.generate.display_error"),
        ):
            mock_orch_cls.create.return_value = mock_orch
            with pytest.raises(typer.Exit) as exc_info:
                generate_command(
                    context=ctx_files,
                    job=job_files,
                    template="test_resume",
                    schema="resume",
                    output=[Path("/out/resume.pdf")],
                )
        assert exc_info.value.exit_code == 1
