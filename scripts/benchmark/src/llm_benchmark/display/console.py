"""Shared Console instance and style constants.

Provides a singleton :data:`console` instance and reusable style constants
for consistent terminal output across all CLI commands.
"""

from __future__ import annotations

from rich.console import Console

__all__ = [
    "console",
]

console = Console()
