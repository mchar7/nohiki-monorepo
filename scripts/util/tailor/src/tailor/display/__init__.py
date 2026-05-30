"""TUI display components for tailor CLI."""

from __future__ import annotations

from tailor.display.console import console
from tailor.display.panels import (
    display_error,
    display_lint_issues,
    display_metrics,
    display_success,
    display_summary,
)
from tailor.display.progress import StatusSpinner

__all__ = [
    "StatusSpinner",
    "console",
    "display_error",
    "display_lint_issues",
    "display_metrics",
    "display_success",
    "display_summary",
]
