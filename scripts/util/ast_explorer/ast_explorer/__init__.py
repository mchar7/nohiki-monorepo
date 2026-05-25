"""AST Explorer - Tree-sitter based codebase AST generation tool.

Provides a queryable structural map of codebases for AI-assisted code navigation
and refactoring. Uses tree-sitter for parsing and generates output optimized
for LLM context consumption.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "ASTExtractor",
    "CodebaseAST",
    "ExportFormat",
    "FileAST",
    "LanguageRegistry",
    "NodeKind",
    "QueryFilter",
    "SymbolNode",
]

from ast_explorer.analysis.extractor import ASTExtractor
from ast_explorer.analysis.query import QueryFilter
from ast_explorer.models.codebase import CodebaseAST, ExportFormat, FileAST
from ast_explorer.models.nodes import NodeKind, SymbolNode
from ast_explorer.parsers.registry import LanguageRegistry
