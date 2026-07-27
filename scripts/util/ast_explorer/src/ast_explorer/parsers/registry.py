"""Language parser registry and factory."""

from __future__ import annotations

from pathlib import Path

from ast_explorer.parsers.base import LanguageParser
from ast_explorer.parsers.python import PythonParser


class LanguageRegistry:
    """Registry of language parsers.

    Provides a factory for getting the appropriate parser based on file extension
    or language name. Uses O(1) lookups via pre-built extension mapping.
    """

    def __init__(self) -> None:
        """Initialize registry with default language parsers."""
        self._parsers: dict[str, LanguageParser] = {}
        self._extension_map: dict[str, LanguageParser] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default language parsers."""
        self.register(PythonParser())

    def register(self, parser: LanguageParser) -> None:
        """Register a language parser."""
        self._parsers[parser.language_name] = parser
        for ext in parser.file_extensions:
            self._extension_map[ext] = parser

    def get_parser(self, language: str) -> LanguageParser | None:
        """Get a parser by language name."""
        return self._parsers.get(language)

    def get_parser_for_file(self, path: Path) -> LanguageParser | None:
        """Get the appropriate parser for a file based on its extension."""
        ext = path.suffix.lstrip(".")
        return self._extension_map.get(ext)

    def can_parse(self, path: Path) -> bool:
        """Check if any registered parser can handle the given file."""
        return self.get_parser_for_file(path) is not None

    @property
    def supported_extensions(self) -> frozenset[str]:
        """Get all supported file extensions."""
        return frozenset(self._extension_map.keys())

    @property
    def supported_languages(self) -> frozenset[str]:
        """Get all supported language names."""
        return frozenset(self._parsers.keys())


class _RegistryHolder:
    """Holder class for singleton pattern without global statement."""

    instance: LanguageRegistry | None = None


def get_default_registry() -> LanguageRegistry:
    """Get or create the default language registry singleton."""
    if _RegistryHolder.instance is None:
        _RegistryHolder.instance = LanguageRegistry()
    return _RegistryHolder.instance
