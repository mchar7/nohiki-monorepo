"""Shared fixtures for benchmark CLI tests."""

import pytest
import typer.rich_utils


@pytest.fixture(autouse=True)
def _disable_typer_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep captured Typer output stable even when rich_utils was imported first."""
    monkeypatch.setenv("_TYPER_FORCE_DISABLE_TERMINAL", "1")
    monkeypatch.setattr(typer.rich_utils, "FORCE_TERMINAL", False)
