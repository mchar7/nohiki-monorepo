"""Shared fixtures for benchmark CLI tests."""

import httpx
import pytest
import typer.rich_utils


@pytest.fixture(autouse=True)
def _disable_typer_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep captured Typer output stable even when rich_utils was imported first."""
    monkeypatch.setenv("_TYPER_FORCE_DISABLE_TERMINAL", "1")
    monkeypatch.setattr(typer.rich_utils, "FORCE_TERMINAL", False)


@pytest.fixture(autouse=True)
def _no_outbound_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail fast on a live request instead of waiting out a runner-only read timeout."""

    def _blocked(*args: object, **kwargs: object) -> object:
        target = args[0] if args else kwargs.get("url")
        message = f"unmocked outbound HTTP in a unit test: {target}"
        raise AssertionError(message)

    monkeypatch.setattr(httpx, "get", _blocked)
    monkeypatch.setattr(httpx, "post", _blocked)
