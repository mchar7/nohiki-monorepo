"""Generate command for tailor CLI."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import typer

from tailor.core.config import DEFAULT_TEMPLATE_NAME, get_settings
from tailor.core.context import TailorContext
from tailor.core.orchestrator import TailorOrchestrator
from tailor.core.types import _EXTENSION_FORMAT, OutputSpec, infer_output_format
from tailor.display.console import console
from tailor.display.panels import display_error, display_lint_issues, display_success
from tailor.display.progress import StatusSpinner, status_spinner
from tailor.exceptions import TailorError


def generate_command(
    *,
    context: list[Path],
    job: list[Path],
    template: str = DEFAULT_TEMPLATE_NAME,
    schema: str | None = None,
    output: list[Path],
    data: Path | None = None,
) -> None:
    """Execute the generate pipeline from validated CLI arguments."""
    _validate_cli_args(
        context=context,
        job=job,
        data=data,
        output=output,
    )

    settings = get_settings()
    orchestrator = TailorOrchestrator.create(settings)
    schema_name = schema or orchestrator.file_adapter.resolve_schema_for_template(template)

    tailor_context = _build_context(
        context=context,
        job=job,
        data=data,
        template=template,
        schema_name=schema_name,
        output=output,
    )

    async def run_generation() -> None:
        try:
            with status_spinner("Generating document...") as spinner:
                spinner.update("Loading files...")
                _update_spinner_for_mode(spinner, tailor_context, orchestrator)
                result = await orchestrator.generate(tailor_context)
                spinner.update("Writing output...")

            display_success(result)
            display_lint_issues(result.lint_issues)

        except TailorError as e:
            display_error(str(e))
            raise typer.Exit(1) from e
        finally:
            close_result = orchestrator.aclose()
            if inspect.isawaitable(close_result):
                await close_result

    asyncio.run(run_generation())


def _validate_cli_args(
    *,
    context: list[Path],
    job: list[Path],
    data: Path | None,
    output: list[Path],
) -> None:
    """Validate CLI arguments and exit with user-friendly errors."""
    if data is None and not context:
        console.print("[red]At least one context file is required[/red]")
        raise typer.Exit(1)

    if data is None and not job:
        console.print("[red]At least one job file is required[/red]")
        raise typer.Exit(1)

    if data is not None and (context or job):
        console.print("[red]Manual data mode does not accept context or job files[/red]")
        raise typer.Exit(1)

    if len(context) > 10:
        console.print("[red]Maximum 10 context files allowed[/red]")
        raise typer.Exit(1)

    if len(job) > 10:
        console.print("[red]Maximum 10 job files allowed[/red]")
        raise typer.Exit(1)

    if not output:
        console.print("[red]At least one --output path is required[/red]")
        raise typer.Exit(1)

    for path in output:
        try:
            infer_output_format(path)
        except ValueError as err:
            supported = ", ".join(sorted(_EXTENSION_FORMAT))
            console.print(
                f"[red]Unsupported output extension '{path.suffix}' for {path.name}. Supported: {supported}[/red]"
            )
            raise typer.Exit(1) from err


def _build_context(
    *,
    context: list[Path],
    job: list[Path],
    data: Path | None,
    template: str,
    schema_name: str,
    output: list[Path],
) -> TailorContext:
    """Construct TailorContext from CLI args."""
    outputs = [OutputSpec(path=p, format=infer_output_format(p)) for p in output]
    return TailorContext(
        context_file_paths=list(context),
        job_file_paths=list(job),
        data_file_path=data,
        template_name=template,
        schema_name=schema_name,
        outputs=outputs,
    )


def _update_spinner_for_mode(
    spinner: StatusSpinner,
    tailor_context: TailorContext,
    orchestrator: TailorOrchestrator,
) -> None:
    """Update spinner based on manual vs LLM mode."""
    if tailor_context.is_manual_mode:
        spinner.update("Validating manual data...")
    else:
        spinner.update(f"Calling LLM ({orchestrator.llm_adapter.model_name})...")
