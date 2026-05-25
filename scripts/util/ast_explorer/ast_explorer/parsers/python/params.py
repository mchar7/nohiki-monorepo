"""Parameter parsing for Python functions and methods."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ast_explorer.models.nodes import Parameter, TypeAnnotation
from ast_explorer.parsers.python.utils import get_node_text

if TYPE_CHECKING:
    from tree_sitter import Node


def parse_parameters(func_node: Node, source: bytes) -> tuple[Parameter, ...]:
    """Parse function parameters."""
    if not (params_node := func_node.child_by_field_name("parameters")):
        return ()

    params: list[Parameter] = []
    keyword_only = False

    for child in params_node.children:
        match child.type:
            case "/":
                continue
            case "*":
                keyword_only = True
            case _:
                if param := _parse_single_parameter(child, source, keyword_only=keyword_only):
                    params.append(param)

    return tuple(params)


def _parse_single_parameter(node: Node, source: bytes, *, keyword_only: bool) -> Parameter | None:
    """Parse a single parameter node."""
    match node.type:
        case "identifier":
            return Parameter(name=get_node_text(node, source), is_keyword_only=keyword_only)
        case "typed_parameter":
            return _handle_typed_parameter(node, source, keyword_only=keyword_only)
        case "default_parameter":
            return _handle_default_parameter(node, source, keyword_only=keyword_only)
        case "typed_default_parameter":
            return _handle_typed_default_parameter(node, source, keyword_only=keyword_only)
        case "list_splat_pattern" | "dictionary_splat_pattern":
            if name_node := node.child(0):
                name = get_node_text(name_node, source)
                prefix = "**" if node.type == "dictionary_splat_pattern" else "*"
                return Parameter(name=f"{prefix}{name}", is_variadic=True)
    return None


def _handle_typed_parameter(node: Node, source: bytes, *, keyword_only: bool) -> Parameter | None:
    name, type_ann = "", None
    for child in node.children:
        match child.type:
            case "identifier":
                name = get_node_text(child, source)
            case "type":
                type_ann = TypeAnnotation(raw=get_node_text(child, source))
    return Parameter(name=name, type_annotation=type_ann, is_keyword_only=keyword_only) if name else None


def _handle_default_parameter(node: Node, source: bytes, *, keyword_only: bool) -> Parameter | None:
    name, default, type_ann = "", None, None
    for child in node.children:
        match child.type:
            case "identifier":
                name = get_node_text(child, source)
            case "typed_parameter":
                if p := _handle_typed_parameter(child, source, keyword_only=keyword_only):
                    name, type_ann = p.name, p.type_annotation
            case t if t not in {"=", ":"}:
                default = get_node_text(child, source)
    return (
        Parameter(name=name, type_annotation=type_ann, default_value=default, is_keyword_only=keyword_only)
        if name
        else None
    )


def _handle_typed_default_parameter(node: Node, source: bytes, *, keyword_only: bool) -> Parameter | None:
    name, type_ann, default = "", None, None
    for child in node.children:
        match child.type:
            case "identifier":
                name = get_node_text(child, source)
            case "type":
                type_ann = TypeAnnotation(raw=get_node_text(child, source))
            case t if t not in {"=", ":"}:
                default = get_node_text(child, source)
    return (
        Parameter(name=name, type_annotation=type_ann, default_value=default, is_keyword_only=keyword_only)
        if name
        else None
    )
