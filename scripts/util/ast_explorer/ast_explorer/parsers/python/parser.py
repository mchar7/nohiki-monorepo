"""Python language parser using tree-sitter."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ast_explorer.parsers.python.imports import parse_node_to_import
from ast_explorer.parsers.python.symbols import (
    parse_node_to_symbol,
)

if TYPE_CHECKING:
    from tree_sitter import Language, Node, Parser

    from ast_explorer.models.nodes import ImportInfo, SymbolNode


class PythonParser:
    """Tree-sitter based Python parser."""

    _LANGUAGE: Language | None = None
    _PARSER: Parser | None = None

    QUERIES = """
    (module) @module

    (class_definition
      name: (identifier) @class.name
      superclasses: (argument_list)? @class.bases
      body: (block) @class.body) @class.def

    (function_definition
      name: (identifier) @func.name
      parameters: (parameters) @func.params
      return_type: (type)? @func.return
      body: (block) @func.body) @func.def

    (decorated_definition
      (decorator)+ @decorator
      definition: (_) @decorated.def) @decorated

    (import_statement) @import
    (import_from_statement) @import_from

    (assignment
      left: (identifier) @assign.name
      type: (type)? @assign.type) @assign

    (type_alias_statement
      name: (type) @alias.name
      value: (type) @alias.value) @type_alias
    """

    @classmethod
    def _get_language(cls) -> Language:
        if cls._LANGUAGE is None:
            import tree_sitter_python
            from tree_sitter import Language

            cls._LANGUAGE = Language(tree_sitter_python.language())
        return cls._LANGUAGE

    @classmethod
    def _get_parser(cls) -> Parser:
        if cls._PARSER is None:
            from tree_sitter import Parser

            cls._PARSER = Parser(cls._get_language())
        return cls._PARSER

    @property
    def language_name(self) -> str:
        """Return the language identifier."""
        return "python"

    @property
    def file_extensions(self) -> frozenset[str]:
        """Return supported file extensions."""
        return frozenset({"py", "pyi"})

    def can_parse(self, path: Path) -> bool:
        """Check if this parser can handle the given file."""
        return path.suffix.lstrip(".") in self.file_extensions

    def parse_file(self, path: Path, source: bytes) -> tuple[list[SymbolNode], list[str]]:
        """Parse a Python file and extract symbols."""
        parser = self._get_parser()
        tree = parser.parse(source)
        errors: list[str] = []

        if tree.root_node.has_error:
            errors.append(f"Parse error in {path}")

        symbols = self._extract_symbols(tree.root_node, path, source)
        return symbols, errors

    def _extract_symbols(self, root: Node, path: Path, source: bytes) -> list[SymbolNode]:
        """Extract all symbols from the AST."""
        symbols: list[SymbolNode] = []
        imports: list[ImportInfo] = []

        for child in root.children:
            if sym := parse_node_to_symbol(child, path, source):
                symbols.append(sym)
            elif imp := parse_node_to_import(child, source):
                imports.append(imp)

        if imports:
            for sym in symbols:
                sym.imports = tuple(imports)

        return symbols
