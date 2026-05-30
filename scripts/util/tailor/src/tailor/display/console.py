"""Shared console instance and style constants for tailor CLI."""

from __future__ import annotations

from typing import Final

from rich.console import Console
from rich.style import Style
from rich.theme import Theme

STYLE_SUCCESS: Final[str] = "success"
STYLE_ERROR: Final[str] = "error"
STYLE_WARNING: Final[str] = "warning"
STYLE_INFO: Final[str] = "info"
STYLE_DIM: Final[str] = "dim"
STYLE_HIGHLIGHT: Final[str] = "highlight"
STYLE_ACCENT: Final[str] = "accent"

ICON_SUCCESS: Final[str] = "✓"
ICON_ERROR: Final[str] = "✗"
ICON_WARNING: Final[str] = "⚠"
ICON_INFO: Final[str] = "i"
ICON_SPINNER: Final[str] = "◐"
ICON_BULLET: Final[str] = "•"
ICON_ARROW: Final[str] = "→"
ICON_FILE: Final[str] = "📁"
ICON_DOC: Final[str] = "📄"
ICON_TEMPLATE: Final[str] = "📋"
ICON_GENERATE: Final[str] = "⚙️"
ICON_RENDER: Final[str] = "🎨"
ICON_TARGET: Final[str] = "🎯"

tailor_theme = Theme(
    {
        STYLE_SUCCESS: Style(color="green", bold=True),
        STYLE_ERROR: Style(color="red", bold=True),
        STYLE_WARNING: Style(color="yellow", bold=True),
        STYLE_INFO: Style(color="cyan"),
        STYLE_DIM: Style(color="bright_black"),
        STYLE_HIGHLIGHT: Style(color="cyan", bold=True),
        STYLE_ACCENT: Style(color="magenta"),
    }
)

console = Console(theme=tailor_theme)


def format_size(size_bytes: int) -> str:
    """Format byte count as human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def format_duration(seconds: float) -> str:
    """Format duration as human-readable string."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"


def format_tokens(count: int) -> str:
    """Format token count with thousands separator."""
    return f"{count:,}"


def format_cost(usd: float) -> str:
    """Format cost in USD."""
    if usd < 0.01:
        return f"~${usd:.4f}"
    return f"~${usd:.2f}"
