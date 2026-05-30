"""Progress indicators for tailor CLI."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Self

from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from tailor.display.console import (
    STYLE_HIGHLIGHT,
    console,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType


class StatusSpinner:
    """A spinner with status text that can be updated."""

    def __init__(self, initial_status: str = "Working...") -> None:
        """Initialize spinner with status text."""
        self._status = initial_status
        self._spinner = Spinner("dots", text=self._build_text())
        self._live: Live | None = None

    def _build_text(self) -> Text:
        """Build the spinner text."""
        return Text(f" {self._status}", style=STYLE_HIGHLIGHT)

    def update(self, status: str) -> None:
        """Update the status text."""
        self._status = status
        self._spinner.text = self._build_text()
        if self._live:
            self._live.refresh()

    def __enter__(self) -> Self:
        """Enter context manager."""
        self._live = Live(self._spinner, console=console, refresh_per_second=10)
        self._live.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit context manager."""
        if self._live:
            self._live.__exit__(exc_type, exc_val, exc_tb)
            self._live = None


@contextmanager
def status_spinner(initial_status: str = "Working...") -> Iterator[StatusSpinner]:
    """Context manager for a status spinner."""
    spinner = StatusSpinner(initial_status)
    with spinner:
        yield spinner
