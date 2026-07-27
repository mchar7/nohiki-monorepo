"""AST Explorer command line interface."""

from __future__ import annotations

import typer

from ast_explorer.cli.commands.deps import deps_cmd
from ast_explorer.cli.commands.events import events_cmd
from ast_explorer.cli.commands.export import export_cmd
from ast_explorer.cli.commands.impact import impact_cmd
from ast_explorer.cli.commands.inspect import inspect_cmd
from ast_explorer.cli.commands.query import query_cmd
from ast_explorer.cli.commands.scan import scan_cmd

app = typer.Typer(
    name="ast-explorer",
    help="[bold cyan]AST Explorer[/bold cyan] - Tree-sitter based codebase structure analysis.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Register commands
app.command("scan")(scan_cmd)
app.command("query")(query_cmd)
app.command("inspect")(inspect_cmd)
app.command("export")(export_cmd)
app.command("events")(events_cmd)
app.command("deps")(deps_cmd)
app.command("impact")(impact_cmd)


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
