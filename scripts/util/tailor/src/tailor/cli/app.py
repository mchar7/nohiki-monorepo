"""Main typer application for tailor CLI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from tailor.adapters.file_adapter import TailorFileAdapter

import typer
from rich.panel import Panel

from tailor import __version__
from tailor.core.config import DEFAULT_TEMPLATE_NAME
from tailor.display.console import console
from tailor.exceptions import TailorError

app = typer.Typer(
    name="tailor",
    help="Nohiki Document Tailoring CLI - Generate tailored documents from templates",
    no_args_is_help=False,
    invoke_without_command=True,
    rich_markup_mode="rich",
)


def version_callback(*, value: bool) -> None:
    """Show version and exit."""
    if value:
        console.print(f"tailor version {__version__}")
        raise typer.Exit


@app.callback()
def main_callback(
    ctx: typer.Context,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Show detailed logging information",
        ),
    ] = False,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            help="Show version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Nohiki Document Tailoring CLI.

    Run without arguments for interactive wizard mode.
    """
    import contextlib
    import logging

    import structlog

    _ = version

    level = logging.DEBUG if verbose else logging.WARNING

    logging.getLogger().setLevel(level)

    # structlog may already be configured by nohiki-observability
    with contextlib.suppress(Exception):
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(level),
        )

    for logger_name in ["doc_template_service", "tailor", "nohiki", "redis"]:
        logging.getLogger(logger_name).setLevel(level)

    if not verbose:
        for logger_name in ["redis", "urllib3", "asyncio"]:
            logging.getLogger(logger_name).setLevel(logging.ERROR)

    if ctx.invoked_subcommand is None:
        from tailor.display.wizard import run_wizard

        exit_code = run_wizard()
        raise typer.Exit(exit_code)


@app.command()
def templates(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show detailed template information"),
    ] = False,
) -> None:
    """List available document templates."""
    from tailor.adapters.file_adapter import TailorFileAdapter
    from tailor.core.config import get_settings
    from tailor.display.panels import display_templates_table

    settings = get_settings()
    adapter = TailorFileAdapter(settings)
    template_list = adapter.discover_templates()

    if not template_list:
        console.print("[yellow]No templates found[/yellow]")
        raise typer.Exit(1)

    display_templates_table(template_list)

    if verbose:
        for template in template_list:
            console.print(f"\n[bold]{template.name}[/bold]")
            console.print(f"  Path: {template.path}")
            console.print(f"  Version: {template.version}")
            console.print(f"  Namespace: {template.namespace}")
            if template.schema_name:
                console.print(f"  Schema: {template.schema_name}")


@app.command()
def schemas(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show detailed schema information"),
    ] = False,
) -> None:
    """List available document schemas."""
    from rich.table import Table

    from tailor.adapters.file_adapter import TailorFileAdapter
    from tailor.core.config import get_settings

    settings = get_settings()
    adapter = TailorFileAdapter(settings)
    schema_list = adapter.discover_schemas()

    if not schema_list:
        console.print("[yellow]No schemas found[/yellow]")
        raise typer.Exit(1)

    table = Table(
        title="[bold]Available Schemas[/bold]",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Name", style="cyan bold")
    table.add_column("Title")
    table.add_column("Required Fields")

    for schema in schema_list:
        required = ", ".join(schema.required_fields[:3])
        if len(schema.required_fields) > 3:
            required += f" (+{len(schema.required_fields) - 3})"
        table.add_row(
            schema.name,
            schema.title or "-",
            required or "-",
        )

    console.print(table)

    if verbose:
        for schema in schema_list:
            console.print(f"\n[bold]{schema.name}[/bold]")
            console.print(f"  Path: {schema.path}")
            if schema.description:
                console.print(f"  Description: {schema.description[:100]}...")
            console.print(f"  Properties: {len(schema.properties)}")


@app.command(name="generate")
def generate(
    context: Annotated[
        list[Path] | None,
        typer.Option(
            "--context",
            "-c",
            help="Personal context files (1-10 files)",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    job: Annotated[
        list[Path] | None,
        typer.Option(
            "--job",
            "-j",
            help="Job listing files (1-10 files)",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    template: Annotated[
        str,
        typer.Option(
            "--template",
            "-t",
            help="Template name to use",
        ),
    ] = DEFAULT_TEMPLATE_NAME,
    schema: Annotated[
        str | None,
        typer.Option(
            "--schema",
            "-s",
            help="Schema name (auto-detected from template if not specified)",
        ),
    ] = None,
    output: Annotated[
        list[Path] | None,
        typer.Option(
            "--output",
            "-o",
            help="Output file path(s) — format inferred from extension (e.g. .pdf, .png, .json)",
        ),
    ] = None,
    data: Annotated[
        Path | None,
        typer.Option(
            "--data",
            "-d",
            help="Manual JSON data file (bypass LLM)",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Generate a tailored document from context and job files."""
    from tailor.cli.generate import generate_command

    generate_command(
        context=context or [],
        job=job or [],
        template=template,
        schema=schema,
        output=output or [],
        data=data,
    )


def _display_schema_details(adapter: TailorFileAdapter, schema_name: str) -> None:
    """Display schema structure and required fields for a named schema."""
    from tailor.exceptions import SchemaError

    try:
        schema = adapter.load_schema(schema_name)
        console.print(f"\n[bold]Schema: {schema.name}[/bold]")
        console.print(f"Required fields: {', '.join(schema.required_fields)}")
        console.print("\n[dim]Schema structure (top-level):[/dim]")
        for prop_name, prop_def in list(schema.properties.items())[:10]:
            prop_type = prop_def.get("type", "object") if isinstance(prop_def, dict) else "object"
            console.print(f"  • {prop_name}: {prop_type}")
    except SchemaError:
        console.print(f"[yellow]Schema {schema_name} not found[/yellow]")


@app.command()
def preview(
    template_name: Annotated[
        str,
        typer.Argument(help="Template name to preview"),
    ],
) -> None:
    """Preview a template's schema requirements."""
    from tailor.adapters.file_adapter import TailorFileAdapter
    from tailor.core.config import get_settings
    from tailor.exceptions import TemplateError

    settings = get_settings()
    adapter = TailorFileAdapter(settings)

    try:
        template = adapter.load_template(template_name)
    except TemplateError as e:
        console.print(f"[red]Template not found: {template_name}[/red]")
        raise typer.Exit(1) from e

    console.print(
        Panel(
            f"[bold cyan]{template.name}[/bold cyan]\nVersion: {template.version}\nDescription: {template.description}",
            title="Template Info",
        )
    )

    try:
        schema_name = adapter.resolve_schema_for_template(template_name)
        _display_schema_details(adapter, schema_name)
    except TailorError, KeyError:
        console.print("[yellow]No matching schema found[/yellow]")


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
