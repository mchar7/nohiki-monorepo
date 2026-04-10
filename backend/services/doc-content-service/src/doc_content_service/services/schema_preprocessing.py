"""JSON schema preprocessing for LLM structured output consumption.

Prepares data-driven JSON schemas (from doc-template-service) for LLM use by:
- Stripping frontend-only ``x-*`` extensions the LLM cannot interpret
- Merging ``x-llm-hint`` text into ``description`` where LLMs actually read it
- Adding ``additionalProperties: false`` to all objects for reliable output
- Removing ``format`` constraints unsupported by GBNF grammars (Ollama)
"""

from __future__ import annotations

import copy
from typing import Any

_UNSUPPORTED_FORMATS: frozenset[str] = frozenset(
    {"email", "uri", "uri-reference", "hostname", "ipv4", "ipv6", "iri", "iri-reference"}
)


def preprocess_schema_for_llm(schema: dict[str, Any]) -> dict[str, Any]:
    """Prepare a JSON schema for LLM structured output.

    Returns a deep copy with all transformations applied: the original
    schema dict is never mutated.

    Args:
        schema: Raw JSON schema dict from doc-template-service.

    Returns:
        Transformed schema optimized for LLM consumption.
    """
    result = copy.deepcopy(schema)
    _process_node(result)
    return result


def _process_node(node: dict[str, Any]) -> None:
    """Recursively transform a single JSON schema node in-place."""
    _merge_llm_hint_into_description(node)
    _strip_x_extensions(node)
    _enforce_additional_properties(node)
    _strip_unsupported_formats(node)
    _recurse_children(node)


def _merge_llm_hint_into_description(node: dict[str, Any]) -> None:
    """Merge ``x-llm-hint`` into ``description`` before stripping extensions."""
    hint = node.pop("x-llm-hint", None)
    if not isinstance(hint, str) or not hint:
        return

    existing = node.get("description", "")
    if existing:
        node["description"] = f"{existing}. {hint}"
    else:
        node["description"] = hint


def _strip_x_extensions(node: dict[str, Any]) -> None:
    """Remove all remaining ``x-*`` vendor extensions."""
    x_keys = [k for k in node if k.startswith("x-")]
    for key in x_keys:
        del node[key]


def _enforce_additional_properties(node: dict[str, Any]) -> None:
    """Add ``additionalProperties: false`` to object nodes with properties."""
    if node.get("type") == "object" and "properties" in node:
        node["additionalProperties"] = False


def _strip_unsupported_formats(node: dict[str, Any]) -> None:
    """Remove ``format`` values that break GBNF grammar generation."""
    if node.get("format") in _UNSUPPORTED_FORMATS:
        del node["format"]


def _recurse_children(node: dict[str, Any]) -> None:
    """Recurse into all child schema nodes."""
    _recurse_properties(node)
    _recurse_items(node)
    _recurse_composition_keywords(node)
    _recurse_conditional_keywords(node)


def _recurse_properties(node: dict[str, Any]) -> None:
    """Process ``properties`` and ``prefixItems`` children."""
    for prop in node.get("properties", {}).values():
        if isinstance(prop, dict):
            _process_node(prop)

    for item in node.get("prefixItems", []):
        if isinstance(item, dict):
            _process_node(item)


def _recurse_items(node: dict[str, Any]) -> None:
    """Process ``items`` child."""
    items = node.get("items")
    if isinstance(items, dict):
        _process_node(items)


def _recurse_composition_keywords(node: dict[str, Any]) -> None:
    """Process ``anyOf``, ``oneOf``, ``allOf`` children."""
    for keyword in ("anyOf", "oneOf", "allOf"):
        subschemas = node.get(keyword)
        if isinstance(subschemas, list):
            for sub in subschemas:
                if isinstance(sub, dict):
                    _process_node(sub)


def _recurse_conditional_keywords(node: dict[str, Any]) -> None:
    """Process ``if``, ``then``, ``else``, ``not`` children."""
    for keyword in ("if", "then", "else", "not"):
        subschema = node.get(keyword)
        if isinstance(subschema, dict):
            _process_node(subschema)
