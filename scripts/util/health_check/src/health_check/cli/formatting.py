"""Shared formatting helpers for the health-check CLI output."""

from __future__ import annotations

import os
import sys
from enum import StrEnum
from typing import Final

from health_check.core.models import CheckStatus


class OutputMode(StrEnum):
    """CLI output rendering mode."""

    RICH = "rich"
    BORING = "boring"


_PLAIN_STATUS_ICONS: Final[dict[CheckStatus, str]] = {
    CheckStatus.PASSED: "PASS",
    CheckStatus.FAILED: "FAIL",
    CheckStatus.SKIPPED: "SKIP",
    CheckStatus.ERROR: "ERR ",
}


def detect_output_mode() -> OutputMode:
    """Auto-detect the appropriate output mode for the current environment.

    Returns ``BORING`` when running in CI, NO_COLOR is set, or stdout is not
    a TTY -- all environments where Rich decoration adds noise rather than value.
    Returns ``RICH`` otherwise.

    Returns:
        The detected ``OutputMode``.
    """
    if (
        os.environ.get("CI")
        or os.environ.get("NO_COLOR")
        or os.environ.get("TERM") == "dumb"
        or not sys.stdout.isatty()
    ):
        return OutputMode.BORING
    return OutputMode.RICH


def plain_status_icon(status: CheckStatus) -> str:
    """Return the plain-text (no Rich markup) status label for a check.

    Args:
        status: The check result status.

    Returns:
        Four-character plain-text status label.
    """
    return _PLAIN_STATUS_ICONS.get(status, "??? ")


_MAX_SUMMARY_LEN: Final[int] = 60
_MAX_DETAIL_LEN: Final[int] = 120

_STATUS_ICONS: Final[dict[CheckStatus, str]] = {
    CheckStatus.PASSED: "[green]✓[/green]",
    CheckStatus.FAILED: "[red]✗[/red]",
    CheckStatus.SKIPPED: "[yellow]⊘[/yellow]",
    CheckStatus.ERROR: "[magenta]⚠[/magenta]",
}

_STATUS_STYLES: Final[dict[CheckStatus, str]] = {
    CheckStatus.PASSED: "green",
    CheckStatus.FAILED: "red",
    CheckStatus.SKIPPED: "yellow",
    CheckStatus.ERROR: "magenta",
}


def status_icon(status: CheckStatus) -> str:
    """Return the Rich-markup icon for a check status.

    Args:
        status: The check result status.

    Returns:
        Rich markup string with coloured icon.
    """
    return _STATUS_ICONS.get(status, "?")


def status_style(status: CheckStatus) -> str:
    """Return the Rich style name for a check status.

    Args:
        status: The check result status.

    Returns:
        Rich style string (e.g. ``"green"``).
    """
    return _STATUS_STYLES.get(status, "white")


def truncate(text: str, max_len: int = _MAX_SUMMARY_LEN) -> str:
    """Truncate text to max_len characters, appending '…' if truncated.

    Args:
        text: Input string.
        max_len: Maximum allowed length.

    Returns:
        Possibly truncated string.
    """
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def format_duration(ms: float) -> str:
    """Format a duration in milliseconds to a human-readable string.

    Args:
        ms: Duration in milliseconds.

    Returns:
        Human-readable duration string, e.g. ``"1.23s"`` or ``"234ms"``.
    """
    if ms >= 1000:
        return f"{ms / 1000:.2f}s"
    return f"{ms:.0f}ms"
