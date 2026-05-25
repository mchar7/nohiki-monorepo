"""Symbol parsing for Python source files."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ast_explorer.models.nodes import NodeKind, SymbolNode, TypeAnnotation
from ast_explorer.parsers.python.params import parse_parameters
from ast_explorer.parsers.python.utils import (
    extract_docstring,
    get_node_text,
    infer_visibility,
    make_span,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tree_sitter import Node


def parse_class(node: Node, path: Path, source: bytes) -> SymbolNode | None:
    """Parse a class definition."""
    if not (name_node := node.child_by_field_name("name")):
        return None

    name = get_node_text(name_node, source)
    symbol = SymbolNode(
        name=name,
        kind=NodeKind.CLASS,
        span=make_span(node),
        file_path=path,
        bases=_parse_class_bases(node, source),
        visibility=infer_visibility(name),
        docstring=extract_docstring(node, source),
    )

    if body_node := node.child_by_field_name("body"):
        _parse_class_body(body_node, symbol, path, source)

    return symbol


def parse_function(node: Node, path: Path, source: bytes, *, is_async: bool = False) -> SymbolNode | None:
    """Parse a function definition."""
    if not (name_node := node.child_by_field_name("name")):
        return None

    name = get_node_text(name_node, source)
    return SymbolNode(
        name=name,
        kind=NodeKind.ASYNC_FUNCTION if is_async else NodeKind.FUNCTION,
        span=make_span(node),
        file_path=path,
        parameters=parse_parameters(node, source),
        return_type=parse_return_type(node, source),
        visibility=infer_visibility(name),
        is_async=is_async,
        docstring=extract_docstring(node, source),
    )


def parse_method(node: Node, path: Path, source: bytes, *, is_async: bool = False) -> SymbolNode | None:
    """Parse a method definition (function inside a class)."""
    if not (name_node := node.child_by_field_name("name")):
        return None

    name = get_node_text(name_node, source)
    return SymbolNode(
        name=name,
        kind=NodeKind.ASYNC_METHOD if is_async else NodeKind.METHOD,
        span=make_span(node),
        file_path=path,
        parameters=parse_parameters(node, source),
        return_type=parse_return_type(node, source),
        visibility=infer_visibility(name),
        is_async=is_async,
        is_static=False,
        docstring=extract_docstring(node, source),
    )


def parse_decorated(node: Node, path: Path, source: bytes, *, is_method: bool = False) -> SymbolNode | None:
    """Parse a decorated definition."""
    decorators: list[str] = []
    definition_node: Node | None = None

    for child in node.children:
        if child.type == "decorator":
            decorators.append(get_node_text(child, source).lstrip("@").strip())
        elif child.type in {"function_definition", "async_function_definition", "class_definition"}:
            definition_node = child

    if not definition_node:
        return None

    is_async = definition_node.type == "async_function_definition"
    symbol: SymbolNode | None = None

    match definition_node.type:
        case "class_definition":
            symbol = parse_class(definition_node, path, source)
        case _ if is_method:
            symbol = parse_method(definition_node, path, source, is_async=is_async)
        case _:
            symbol = parse_function(definition_node, path, source, is_async=is_async)

    if symbol:
        symbol.decorators = tuple(decorators)
        _apply_decorator_metadata(symbol, decorators)

    return symbol


def _apply_decorator_metadata(symbol: SymbolNode, decorators: list[str]) -> None:
    """Apply metadata to symbol based on decorators."""
    if "property" in decorators:
        symbol.kind = NodeKind.PROPERTY
    if "staticmethod" in decorators:
        symbol.is_static = True
    if "abstractmethod" in decorators:
        symbol.is_abstract = True


def parse_assignment(node: Node, path: Path, source: bytes) -> SymbolNode | None:
    """Parse a module-level assignment."""
    if node.type != "expression_statement" or not (assign_node := node.child(0)) or assign_node.type != "assignment":
        return None

    if not (left := assign_node.child_by_field_name("left")) or left.type != "identifier":
        return None

    name = get_node_text(left, source)
    if not name or name.startswith("_"):
        return None

    type_node = assign_node.child_by_field_name("type")
    return SymbolNode(
        name=name,
        kind=NodeKind.CONSTANT if name.isupper() else NodeKind.VARIABLE,
        span=make_span(node),
        file_path=path,
        return_type=TypeAnnotation(raw=get_node_text(type_node, source)) if type_node else None,
        visibility=infer_visibility(name),
    )


def parse_type_alias(node: Node, path: Path, source: bytes) -> SymbolNode | None:
    """Parse a PEP 695 type alias statement."""
    if not (name_node := node.child_by_field_name("name")):
        return None

    name = get_node_text(name_node, source)
    return SymbolNode(
        name=name,
        kind=NodeKind.TYPE_ALIAS,
        span=make_span(node),
        file_path=path,
        visibility=infer_visibility(name),
    )


def parse_return_type(func_node: Node, source: bytes) -> TypeAnnotation | None:
    """Parse function return type annotation."""
    if rt_node := func_node.child_by_field_name("return_type"):
        return TypeAnnotation(raw=get_node_text(rt_node, source))
    return None


def _parse_class_bases(class_node: Node, source: bytes) -> tuple[str, ...]:
    """Extract base classes from a class definition."""
    if not (superclasses := class_node.child_by_field_name("superclasses")):
        return ()
    return tuple(
        get_node_text(child, source)
        for child in superclasses.children
        if child.type in {"identifier", "attribute", "subscript"}
    )


def _parse_class_body(body: Node, parent: SymbolNode, path: Path, source: bytes) -> None:
    """Parse the body of a class and add members as children."""
    for child in body.children:
        match child.type:
            case "function_definition":
                if method := parse_method(child, path, source):
                    parent.add_child(method)
            case "decorated_definition":
                if member := parse_decorated(child, path, source, is_method=True):
                    parent.add_child(member)
            case "expression_statement":
                if attr := parse_assignment(child, path, source):
                    parent.add_child(attr)


def parse_node_to_symbol(node: Node, path: Path, source: bytes) -> SymbolNode | None:
    """Parse a single node into a SymbolNode if it represents a symbol."""
    match node.type:
        case "class_definition":
            return parse_class(node, path, source)
        case "function_definition" | "async_function_definition":
            return parse_function(node, path, source, is_async=node.type.startswith("async"))
        case "decorated_definition":
            return parse_decorated(node, path, source)
        case "expression_statement":
            return parse_assignment(node, path, source)
        case "type_alias_statement":
            return parse_type_alias(node, path, source)
        case _:
            return None
