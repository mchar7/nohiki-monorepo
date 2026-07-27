"""Query and filtering system for AST symbols."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ast_explorer.models.nodes import NodeKind, Visibility

if TYPE_CHECKING:
    from ast_explorer.models.codebase import CodebaseAST
    from ast_explorer.models.nodes import SymbolNode


@dataclass(slots=True)
class QueryFilter:
    """Filter criteria for querying symbols.

    Supports filtering by kind, visibility, name patterns, and location.
    All filters are combined with AND logic.
    """

    kinds: frozenset[NodeKind] | None = None
    visibilities: frozenset[Visibility] | None = None
    name_pattern: str | None = None
    name_exact: str | None = None
    in_file: str | None = None
    in_directory: str | None = None
    has_decorator: str | None = None
    is_async: bool | None = None
    min_line_count: int | None = None

    _compiled_pattern: re.Pattern[str] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Compile name pattern regex if provided."""
        if self.name_pattern:
            self._compiled_pattern = re.compile(self.name_pattern, re.IGNORECASE)

    def matches(self, symbol: SymbolNode) -> bool:
        """Check if a symbol matches all filter criteria."""
        return (
            (not self.kinds or symbol.kind in self.kinds)
            and (not self.visibilities or symbol.visibility in self.visibilities)
            and self._check_name(symbol)
            and self._check_location(symbol)
            and self._check_decorator(symbol)
            and (self.is_async is None or symbol.is_async == self.is_async)
            and (self.min_line_count is None or symbol.span.line_count >= self.min_line_count)
        )

    def _check_name(self, symbol: SymbolNode) -> bool:
        """Check name filters (exact and pattern)."""
        if self.name_exact and symbol.name != self.name_exact:
            return False
        return not self._compiled_pattern or bool(self._compiled_pattern.search(symbol.name))

    def _check_location(self, symbol: SymbolNode) -> bool:
        """Check file and directory filters."""
        if self.in_file and self.in_file not in str(symbol.file_path):
            return False
        return not self.in_directory or self.in_directory in str(symbol.file_path.parent)

    def _check_decorator(self, symbol: SymbolNode) -> bool:
        """Check decorator filter."""
        if not (dec := self.has_decorator):
            return True
        dec_lower = dec.lower()
        return any(dec_lower in d.lower() for d in symbol.decorators)


def query_symbols(
    codebase: CodebaseAST,
    filter_: QueryFilter,
    *,
    include_tests: bool = False,
) -> list[SymbolNode]:
    """Query symbols from a codebase using filter criteria.

    Uses efficient filtering by checking most selective criteria first.
    """
    return [symbol for symbol in codebase.get_all_symbols(include_tests=include_tests) if filter_.matches(symbol)]


def get_public_api(codebase: CodebaseAST, *, include_tests: bool = False) -> list[SymbolNode]:
    """Get all public API symbols (classes, functions, constants)."""
    filter_ = QueryFilter(
        kinds=frozenset(
            {
                NodeKind.CLASS,
                NodeKind.FUNCTION,
                NodeKind.ASYNC_FUNCTION,
                NodeKind.CONSTANT,
                NodeKind.TYPE_ALIAS,
                NodeKind.PROTOCOL,
            }
        ),
        visibilities=frozenset({Visibility.PUBLIC}),
    )
    return query_symbols(codebase, filter_, include_tests=include_tests)
