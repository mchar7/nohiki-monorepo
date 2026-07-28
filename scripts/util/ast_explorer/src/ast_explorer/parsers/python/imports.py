"""Import parsing for Python source files."""

from __future__ import annotations

from ast_explorer.models.nodes import ImportInfo
from ast_explorer.parsers.python.utils import Node, get_node_text


def parse_import(node: Node, source: bytes) -> ImportInfo | None:
    """Parse an import statement."""
    name_node = node.child_by_field_name("name") or next((c for c in node.children if c.type == "dotted_name"), None)

    if not name_node:
        return None

    module = get_node_text(name_node, source)
    alias_node = node.child_by_field_name("alias")
    alias = get_node_text(alias_node, source) if alias_node else None

    return ImportInfo(module=module, alias=alias, is_from_import=False)


def parse_from_import(node: Node, source: bytes) -> ImportInfo | None:
    """Parse a from...import statement."""
    module_node = node.child_by_field_name("module_name") or next(
        (c for c in node.children if c.type == "dotted_name"), None
    )
    module = get_node_text(module_node, source) if module_node else ""
    level = sum(1 for c in node.children if c.type == ".")

    names: list[str] = []
    for child in node.children:
        match child.type:
            case "aliased_import":
                if name_node := child.child_by_field_name("name"):
                    names.append(get_node_text(name_node, source))
            case "dotted_name" if child != module_node:
                names.append(get_node_text(child, source))
            case "identifier" | "wildcard_import":
                names.append("*" if child.type == "wildcard_import" else get_node_text(child, source))

    return ImportInfo(
        module=module,
        names=tuple(names),
        is_from_import=True,
        is_relative=level > 0,
        level=level,
    )


def parse_node_to_import(node: Node, source: bytes) -> ImportInfo | None:
    """Parse a single node into an ImportInfo if it represents an import."""
    match node.type:
        case "import_statement":
            return parse_import(node, source)
        case "import_from_statement":
            return parse_from_import(node, source)
        case _:
            return None
