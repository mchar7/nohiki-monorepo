"""Utilities for Python AST parsing."""

from __future__ import annotations

from tree_sitter import Node

from ast_explorer.models.nodes import Position, Span, Visibility


def get_node_text(node: Node, source: bytes) -> str:
    """Get the text content of a node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def make_span(node: Node) -> Span:
    """Create a Span from a tree-sitter node."""
    return Span(
        start=Position(line=node.start_point.row, column=node.start_point.column),
        end=Position(line=node.end_point.row, column=node.end_point.column),
    )


def infer_visibility(name: str) -> Visibility:
    """Infer visibility from Python naming conventions."""
    match name:
        case n if n.startswith("__") and not n.endswith("__"):
            return Visibility.PRIVATE
        case n if n.startswith("_"):
            return Visibility.PROTECTED
        case _:
            return Visibility.PUBLIC


def extract_docstring(node: Node, source: bytes) -> str | None:
    """Extract docstring from a class or function."""
    if not (body := node.child_by_field_name("body")) or not body.children:
        return None

    first_child = body.children[0]
    if first_child.type == "expression_statement":
        string_node = first_child.child(0)
        if string_node and string_node.type == "string":
            doc = get_node_text(string_node, source)
            return doc.strip("\"'").strip()
    return None
