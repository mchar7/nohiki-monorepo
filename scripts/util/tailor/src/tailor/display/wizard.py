"""Interactive wizard for document tailoring."""

from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING

from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from tailor.core.config import get_settings
from tailor.core.context import TailorContext
from tailor.core.orchestrator import TailorOrchestrator
from tailor.core.types import OutputSpec, infer_output_format
from tailor.display.console import (
    ICON_GENERATE,
    ICON_SUCCESS,
    ICON_TARGET,
    STYLE_ERROR,
    STYLE_HIGHLIGHT,
    STYLE_SUCCESS,
    console,
    format_size,
)
from tailor.display.panels import (
    display_error,
    display_lint_issues,
    display_success,
    display_summary,
)
from tailor.display.prompts import (
    display_step_header,
    prompt_confirm_generation,
    prompt_context_files,
    prompt_job_files,
    prompt_output_path,
    prompt_template_selection,
)
from tailor.exceptions import GotenbergError, TailorError

if TYPE_CHECKING:
    from tailor.models.inputs import TailorInput
    from tailor.models.outputs import TailorOutput

_TOTAL_STEPS = 5


class InteractiveWizard:
    """Guided wizard for document tailoring."""

    def __init__(self) -> None:
        """Initialize wizard with settings and orchestrator."""
        self._settings = get_settings()
        self._orchestrator = TailorOrchestrator.create(self._settings)
        self._context = TailorContext()

    async def run(self) -> int:
        """Run the interactive wizard. Returns exit code (0=success, 1=error/cancel)."""
        self._display_header()

        if not await self._check_services():
            return 1

        steps = [
            self._step_context_files,
            self._step_job_files,
            self._step_select_template,
            self._step_output_options,
            self._step_confirm,
        ]

        for step in steps:
            if not await step():
                return 1

        return await self._execute_generation()

    def _display_header(self) -> None:
        """Display wizard header."""
        console.print()
        console.print(
            Panel(
                Text(
                    f"{ICON_TARGET} Nohiki Document Tailor",
                    justify="center",
                    style="bold cyan",
                ),
                border_style="cyan",
                padding=(0, 2),
            )
        )

    async def _check_services(self) -> bool:
        """Verify external dependencies before starting interactive steps."""
        console.print()
        with console.status("[bold cyan]Checking services..."):
            services = await self._orchestrator.check_services()

        if not services.get("gotenberg", False):
            display_error(
                f"Gotenberg service not available at {self._settings.gotenberg_url}\n"
                "Start it with: sh infra/compose/scripts/preflight.sh up -d nohiki-infra-gotenberg",
                title="Service Unavailable",
            )
            return False

        console.print(f"  {ICON_SUCCESS} Gotenberg available", style=STYLE_SUCCESS)
        return True

    async def _step_context_files(self) -> bool:
        """Step 1: Collect context files."""
        display_step_header(1, _TOTAL_STEPS, "Personal Context")
        if files := prompt_context_files():
            self._context.context_file_paths = files
            return True
        return False

    async def _step_job_files(self) -> bool:
        """Step 2: Collect job files."""
        display_step_header(2, _TOTAL_STEPS, "Job Listing")
        if files := prompt_job_files():
            self._context.job_file_paths = files
            return True
        return False

    async def _step_select_template(self) -> bool:
        """Step 3: Select template."""
        display_step_header(3, _TOTAL_STEPS, "Select Template")

        templates = self._orchestrator.file_adapter.discover_templates()
        if not templates:
            display_error("No templates found in templates directory")
            return False

        if not (selected := prompt_template_selection(templates)):
            return False

        self._context.template_name = selected.name
        try:
            self._context.schema_name = self._orchestrator.file_adapter.resolve_schema_for_template(selected.name)
        except TailorError:
            display_error("No schemas available for the selected template")
            return False

        console.print(f"  {ICON_SUCCESS} Schema: ", style=STYLE_SUCCESS, end="")
        console.print(self._context.schema_name, style=STYLE_HIGHLIGHT)

        return True

    async def _step_output_options(self) -> bool:
        """Step 4: Configure output options."""
        display_step_header(4, _TOTAL_STEPS, "Output Options")

        default_filename = self._orchestrator.file_adapter.generate_filename(
            self._context.template_name,
            "pdf",
        )
        default_path = str(self._settings.resolved_output_dir / default_filename)

        while True:
            output_path = prompt_output_path(default_path)
            try:
                output_format = infer_output_format(output_path)
                break
            except ValueError as e:
                console.print(f"  [{STYLE_ERROR}]{e}[/]")

        self._context.outputs = [OutputSpec(path=output_path, format=output_format)]
        return True

    async def _step_confirm(self) -> bool:
        """Step 5: Show summary and confirm."""
        display_step_header(5, _TOTAL_STEPS, "Confirm & Generate")
        display_summary(self._build_summary_input(), self._orchestrator.llm_adapter.model_name)
        return prompt_confirm_generation()

    def _build_summary_input(self) -> TailorInput:
        """Build TailorInput for summary display."""
        from tailor.models.inputs import ContextFile, JobFile, TailorInput

        return TailorInput(
            context_files=[
                ContextFile(path=p, content="", size_bytes=p.stat().st_size, word_count=0)
                for p in self._context.context_file_paths
            ],
            job_files=[JobFile(path=p, content="", size_bytes=p.stat().st_size) for p in self._context.job_file_paths],
            template_name=self._context.template_name,
            schema_name=self._context.schema_name,
            outputs=self._context.outputs,
        )

    async def _execute_generation(self) -> int:
        """Execute generation with progress display."""
        console.print()

        try:
            output = await self._run_generation_with_spinner()
            self._display_generation_success(output)

        except GotenbergError as e:
            display_error(str(e), title="Gotenberg Error")
            return 1

        except TailorError as e:
            display_error(str(e))
            return 1

        else:
            return 0

    async def _run_generation_with_spinner(self) -> TailorOutput:
        """Run generation with live spinner."""
        spinner = Spinner("dots", text=Text(f" {ICON_GENERATE} Calling LLM...", style=STYLE_HIGHLIGHT))
        with Live(spinner, console=console, refresh_per_second=10):
            return await self._orchestrator.generate(self._context)

    async def close(self) -> None:
        """Close resources owned by the wizard orchestrator."""
        close_result = self._orchestrator.aclose()
        if inspect.isawaitable(close_result):
            await close_result

    @staticmethod
    def _display_generation_success(output: TailorOutput) -> None:
        """Display generation success messages."""
        console.print(f"  {ICON_SUCCESS} Content generated", style=STYLE_SUCCESS)
        console.print(
            f"  {ICON_SUCCESS} Document rendered ({format_size(output.total_output_size_bytes)})",
            style=STYLE_SUCCESS,
        )
        console.print()
        display_success(output)
        display_lint_issues(output.lint_issues)


def run_wizard() -> int:
    """Run the interactive wizard (sync entry point)."""

    async def run() -> int:
        wizard = InteractiveWizard()
        try:
            return await wizard.run()
        finally:
            await wizard.close()

    return asyncio.run(run())
