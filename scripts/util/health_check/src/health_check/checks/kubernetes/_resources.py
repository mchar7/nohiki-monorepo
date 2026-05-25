"""Typed, redacted parsing helpers for Kubernetes health checks."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import cast

from health_check.platform.kubernetes import KubernetesPlatform

type JsonObject = dict[str, object]


def as_object(value: object) -> JsonObject | None:
    """Narrow an untrusted JSON value to an object."""
    return cast("JsonObject", value) if isinstance(value, dict) else None


def object_field(value: JsonObject, field: str) -> JsonObject:
    """Return an object field, or an empty object when it is absent or malformed."""
    return as_object(value.get(field)) or {}


def object_list(value: object) -> tuple[JsonObject, ...]:
    """Return only object elements from an untrusted JSON array."""
    if not isinstance(value, list):
        return ()
    return tuple(item for raw in value if (item := as_object(raw)) is not None)


def string_field(value: JsonObject, field: str, default: str = "Unknown") -> str:
    """Return a non-empty string field without stringifying arbitrary data."""
    raw = value.get(field)
    return raw if isinstance(raw, str) and raw else default


def integer_field(value: JsonObject, field: str) -> int | None:
    """Return an integer field, excluding booleans."""
    raw = value.get(field)
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


def true_field(value: JsonObject, field: str) -> bool:
    """Return whether a field is exactly boolean true."""
    return value.get(field) is True


def resource_name(value: JsonObject) -> str:
    """Return a resource's logical name."""
    return string_field(object_field(value, "metadata"), "name")


def conditions(value: JsonObject) -> tuple[JsonObject, ...]:
    """Return a resource status condition list."""
    return object_list(object_field(value, "status").get("conditions"))


def condition(value: Iterable[JsonObject], condition_type: str) -> JsonObject | None:
    """Find a condition by its exact type."""
    return next((item for item in value if item.get("type") == condition_type), None)


def read_resources(
    platform: KubernetesPlatform,
    resource: str,
    *,
    all_namespaces: bool = False,
) -> tuple[JsonObject, ...] | None:
    """Read and validate a kubectl resource list; return ``None`` on inspection failure."""
    code, stdout, _stderr = platform.get_resources(resource, all_namespaces=all_namespaces, timeout=15)
    if code != 0:
        return None
    try:
        document = as_object(json.loads(stdout))
    except json.JSONDecodeError:
        return None
    if document is None or not isinstance(document.get("items"), list):
        return None
    return object_list(document["items"])
