"""Template metadata parsing utilities for doc-template-service."""

from __future__ import annotations

import json
import re
from typing import Any

from nohiki.common.v1 import AccessScope
from nohiki.doc.template.v1 import TemplateAudience

ACCESS_SCOPE_MAP: dict[str, AccessScope] = {
    "PUBLIC": AccessScope.PUBLIC,
    "PRIVATE": AccessScope.PRIVATE,
    "SYSTEM": AccessScope.SYSTEM,
}

TEMPLATE_AUDIENCE_MAP: dict[str, TemplateAudience] = {
    "PUBLIC": TemplateAudience.DOCUMENT,
    "DOCUMENT": TemplateAudience.DOCUMENT,
    "INTERNAL": TemplateAudience.INTERNAL,
}


def parse_access_scope(value: str) -> AccessScope:
    """Parse access scope string to enum. Accepts uppercase enum names."""
    scope = ACCESS_SCOPE_MAP.get(value.upper())
    if scope is None:
        msg = f"Invalid access_scope value: {value}. Must be one of: PUBLIC, PRIVATE, SYSTEM"
        raise ValueError(msg)
    return scope


def parse_template_audience(value: str) -> TemplateAudience:
    """Parse the TMPL_META visibility into its template audience."""
    audience = TEMPLATE_AUDIENCE_MAP.get(value.upper())
    if audience is None:
        msg = f"Invalid visibility value: {value}. Must be one of: public, document, internal"
        raise ValueError(msg)
    return audience


_TMPL_META_PATTERN = re.compile(r"<!--\s*TMPL_META\s*([\s\S]*?)\s*-->", re.MULTILINE)


def parse_template_metadata(html_content: str) -> dict[str, Any]:
    """Parse metadata from HTML template TMPL_META comment."""
    match = _TMPL_META_PATTERN.search(html_content)

    if not match:
        msg = "No TMPL_META comment found in template"
        raise ValueError(msg)

    try:
        metadata = json.loads(match.group(1))
        if not isinstance(metadata, dict):
            msg = "TMPL_META must be a JSON object"
            raise TypeError(msg)
    except json.JSONDecodeError as e:
        msg = f"Invalid JSON in TMPL_META comment: {e}"
        raise ValueError(msg) from e

    required_fields = ["name", "title", "version", "description", "access_scope", "visibility"]
    missing_fields = [field for field in required_fields if field not in metadata]
    if missing_fields:
        msg = f"Missing required fields in TMPL_META: {missing_fields}"
        raise ValueError(msg)

    metadata["access_scope"] = parse_access_scope(metadata["access_scope"])
    metadata["audience"] = parse_template_audience(metadata["visibility"])
    return metadata
