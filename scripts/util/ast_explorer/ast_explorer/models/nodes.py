"""AST node domain models with strict typing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path


class NodeKind(StrEnum):
    """Classification of extracted AST symbols."""

    MODULE = auto()
    CLASS = auto()
    FUNCTION = auto()
    METHOD = auto()
    ASYNC_FUNCTION = auto()
    ASYNC_METHOD = auto()
    PROPERTY = auto()
    VARIABLE = auto()
    CONSTANT = auto()
    TYPE_ALIAS = auto()
    PROTOCOL = auto()
    ENUM = auto()
    ENUM_MEMBER = auto()
    INTERFACE = auto()
    DECORATOR = auto()
    IMPORT = auto()
    EXPORT = auto()


class Visibility(StrEnum):
    """Symbol visibility classification."""

    PUBLIC = auto()
    PRIVATE = auto()
    PROTECTED = auto()
    INTERNAL = auto()


@dataclass(frozen=True, slots=True)
class Position:
    """Source code position (0-indexed)."""

    line: int
    column: int

    def __str__(self) -> str:
        """Return human-readable 1-indexed position."""
        return f"{self.line + 1}:{self.column}"


@dataclass(frozen=True, slots=True)
class Span:
    """Source code span with start and end positions."""

    start: Position
    end: Position

    @property
    def line_count(self) -> int:
        """Calculate number of lines spanned."""
        return self.end.line - self.start.line + 1

    def __str__(self) -> str:
        """Return human-readable span representation."""
        return f"{self.start}-{self.end}"


@dataclass(frozen=True, slots=True)
class TypeAnnotation:
    """Parsed type annotation."""

    raw: str
    is_optional: bool = False
    is_generic: bool = False
    base_type: str | None = None
    type_args: tuple[str, ...] = ()

    def __str__(self) -> str:
        """Return the raw type annotation string."""
        return self.raw


@dataclass(frozen=True, slots=True)
class Parameter:
    """Function/method parameter."""

    name: str
    type_annotation: TypeAnnotation | None = None
    default_value: str | None = None
    is_variadic: bool = False
    is_keyword_only: bool = False

    def __str__(self) -> str:
        """Return parameter as it would appear in a signature."""
        parts = [self.name]
        if self.type_annotation:
            parts.append(f": {self.type_annotation}")
        if self.default_value:
            parts.append(f" = {self.default_value}")
        return "".join(parts)


@dataclass(frozen=True, slots=True)
class ImportInfo:
    """Import statement information."""

    module: str
    names: tuple[str, ...] = ()
    alias: str | None = None
    is_from_import: bool = False
    is_relative: bool = False
    level: int = 0

    def __str__(self) -> str:
        """Return import statement as source code."""
        if self.is_from_import:
            prefix = "." * self.level if self.is_relative else ""
            names = ", ".join(self.names) if self.names else "*"
            return f"from {prefix}{self.module} import {names}"
        alias_part = f" as {self.alias}" if self.alias else ""
        return f"import {self.module}{alias_part}"


def _format_callable_signature(node: SymbolNode) -> str:
    """Format signature for function/method nodes."""
    async_prefix = "async " if node.is_async else ""
    params = ", ".join(str(p) for p in node.parameters)
    ret = f" -> {node.return_type}" if node.return_type else ""
    if node.kind in {NodeKind.METHOD, NodeKind.ASYNC_METHOD} and node.decorators:
        decorators = " ".join(f"@{d}" for d in node.decorators)
        return f"{decorators} {async_prefix}def {node.name}({params}){ret}"
    return f"{async_prefix}def {node.name}({params}){ret}"


def _format_symbol_signature(node: SymbolNode) -> str:
    """Generate a compact signature representation for a symbol node."""
    kind_formatters: dict[NodeKind, str] = {
        NodeKind.TYPE_ALIAS: f"type {node.name} = ...",
        NodeKind.ENUM: f"class {node.name}(Enum)",
        NodeKind.ENUM_MEMBER: f"{node.name} = ...",
    }
    if node.kind in kind_formatters:
        return kind_formatters[node.kind]

    if node.kind in {NodeKind.CLASS, NodeKind.PROTOCOL, NodeKind.INTERFACE}:
        bases = f"({', '.join(node.bases)})" if node.bases else ""
        return f"class {node.name}{bases}"

    if node.kind in {NodeKind.FUNCTION, NodeKind.ASYNC_FUNCTION, NodeKind.METHOD, NodeKind.ASYNC_METHOD}:
        return _format_callable_signature(node)

    if node.kind in {NodeKind.VARIABLE, NodeKind.CONSTANT}:
        type_part = f": {node.return_type}" if node.return_type else ""
        return f"{node.name}{type_part}"

    return node.name


@dataclass(slots=True)
class SymbolNode:
    """Represents an extracted code symbol from the AST.

    This is the primary unit of information extracted from source files.
    Symbols are hierarchical - classes contain methods, modules contain classes, etc.
    """

    name: str
    kind: NodeKind
    span: Span
    file_path: Path

    signature: str | None = None
    return_type: TypeAnnotation | None = None
    parameters: tuple[Parameter, ...] = ()
    decorators: tuple[str, ...] = ()
    bases: tuple[str, ...] = ()
    visibility: Visibility = Visibility.PUBLIC
    is_async: bool = False
    is_static: bool = False
    is_abstract: bool = False
    docstring: str | None = None

    children: list[SymbolNode] = field(default_factory=list)
    parent: SymbolNode | None = field(default=None, repr=False, compare=False)

    imports: tuple[ImportInfo, ...] = ()

    @property
    def qualified_name(self) -> str:
        """Full qualified name including parent hierarchy."""
        if self.parent and self.parent.kind != NodeKind.MODULE:
            return f"{self.parent.qualified_name}.{self.name}"
        return self.name

    @property
    def is_callable(self) -> bool:
        """Whether this symbol represents a callable."""
        return self.kind in {
            NodeKind.FUNCTION,
            NodeKind.METHOD,
            NodeKind.ASYNC_FUNCTION,
            NodeKind.ASYNC_METHOD,
        }

    @property
    def is_type_definition(self) -> bool:
        """Whether this symbol defines a type."""
        return self.kind in {
            NodeKind.CLASS,
            NodeKind.PROTOCOL,
            NodeKind.INTERFACE,
            NodeKind.TYPE_ALIAS,
            NodeKind.ENUM,
        }

    def add_child(self, child: SymbolNode) -> None:
        """Add a child symbol and set parent reference."""
        child.parent = self
        self.children.append(child)

    def walk(self) -> list[SymbolNode]:
        """Depth-first traversal of this node and all descendants."""
        result: list[SymbolNode] = [self]
        for child in self.children:
            result.extend(child.walk())
        return result

    def find_by_name(self, name: str) -> SymbolNode | None:
        """Find a direct child by name."""
        for child in self.children:
            if child.name == name:
                return child
        return None

    def to_signature_string(self) -> str:
        """Generate a compact signature representation."""
        return _format_symbol_signature(self)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        data: dict = {
            "name": self.name,
            "kind": self.kind.value,
            "qualified_name": self.qualified_name,
            "signature": self.to_signature_string(),
            "span": {"start_line": self.span.start.line + 1, "end_line": self.span.end.line + 1},
            "visibility": self.visibility.value,
        }
        if self.docstring:
            data["docstring"] = self.docstring[:200]
        if self.decorators:
            data["decorators"] = list(self.decorators)
        if self.bases:
            data["bases"] = list(self.bases)
        if self.parameters:
            data["parameters"] = [str(p) for p in self.parameters]
        if self.return_type:
            data["return_type"] = str(self.return_type)
        if self.children:
            data["children"] = [c.to_dict() for c in self.children]
        return data
