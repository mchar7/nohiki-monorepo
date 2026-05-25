"""CLI entry point for the health-check tool."""

from __future__ import annotations

from health_check.cli.app import app


def main() -> None:
    """Entry point registered as the ``health-check`` console script."""
    app()
