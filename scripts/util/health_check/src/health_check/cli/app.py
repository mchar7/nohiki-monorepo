"""Typer application definition for the health-check CLI."""

from __future__ import annotations

import typer

from health_check.cli.commands.info import info_command
from health_check.cli.commands.inventory import inventory_command
from health_check.cli.commands.list_checks import list_command
from health_check.cli.commands.run import run_command

app = typer.Typer(
    name="health-check",
    help="[bold cyan]Nohiki Health Check[/bold cyan] - Deployment health diagnostics.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.command("run")(run_command)
app.command("list")(list_command)
app.command("inventory")(inventory_command)
app.command("info")(info_command)
