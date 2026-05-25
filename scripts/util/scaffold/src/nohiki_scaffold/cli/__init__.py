"""Typer CLI entry point for ``nohiki-scaffold``."""

from __future__ import annotations

from nohiki_scaffold.cli.app import app

__all__ = ["app", "main"]


def main() -> None:
    """Run the Typer application."""
    app()
