"""Base protocol for language parsers."""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import Protocol

from ast_explorer.models.nodes import SymbolNode


class LanguageParser(Protocol):
    """Protocol defining the interface for language-specific parsers."""

    @property
    @abstractmethod
    def language_name(self) -> str:
        """The name of the language this parser handles."""
        ...

    @property
    @abstractmethod
    def file_extensions(self) -> frozenset[str]:
        """Set of file extensions this parser handles (without dots)."""
        ...

    @abstractmethod
    def parse_file(self, path: Path, source: bytes) -> tuple[list[SymbolNode], list[str]]:
        """Parse source code and extract symbols.

        Args:
            path: Path to the source file (for error reporting).
            source: Raw source code bytes.

        Returns:
            Tuple of (extracted symbols, parse errors).
        """
        ...

    @abstractmethod
    def can_parse(self, path: Path) -> bool:
        """Check if this parser can handle the given file."""
        ...
