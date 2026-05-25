"""Typer application wiring for ``nohiki-scaffold``.

Command tree::

    nohiki-scaffold
    |-- new
    |   |-- service
    |   +-- lib
    +-- preview
        |-- service
        +-- lib
"""

from __future__ import annotations

import typer

from nohiki_scaffold.cli.commands.new_lib import new_lib_command
from nohiki_scaffold.cli.commands.new_service import new_service_command
from nohiki_scaffold.cli.commands.preview import preview_lib_command, preview_service_command

app = typer.Typer(
    name="nohiki-scaffold",
    help="[bold cyan]Scaffold monorepo-compliant Nohiki services and libraries[/bold cyan]",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)

new_app = typer.Typer(
    name="new",
    help="Create a new service or library.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
preview_app = typer.Typer(
    name="preview",
    help="Preview a scaffold plan without writing anything.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

new_app.command("service")(new_service_command)
new_app.command("lib")(new_lib_command)
preview_app.command("service")(preview_service_command)
preview_app.command("lib")(preview_lib_command)

app.add_typer(new_app, name="new")
app.add_typer(preview_app, name="preview")

__all__ = ["app"]
