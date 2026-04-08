"""Generic cache helper utilities."""

import hashlib
import json
from typing import Any
from uuid import UUID

from nohiki_observability import get_logger

logger = get_logger(__name__)


def make_cache_key(*parts: str | UUID | int, **kwargs: object) -> str:
    """Create a cache key from multiple parts and keyword arguments.

    Args:
        *parts: Positional parts to join into a cache key
        **kwargs: Keyword arguments to include in the key

    Returns:
        Cache key string

    """
    str_parts = [str(part) for part in parts]
    # Add sorted kwargs to key for deterministic ordering
    for key in sorted(kwargs.keys()):
        value = kwargs[key]
        if value is not None:
            str_parts.append(f"{key}={value}")
    return ":".join(str_parts)


def hash_dict(data: dict[str, Any]) -> str:
    """Create a deterministic hash of a dictionary.

    Args:
        data: Dictionary to hash

    Returns:
        SHA256 hash string

    """
    # Sort keys to ensure consistent hashing
    json_str = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(json_str.encode()).hexdigest()


type SanitizedValue = dict[str, "SanitizedValue"] | list["SanitizedValue"] | str | int | float | bool | None


def sanitize_cache_value(value: object) -> SanitizedValue:
    """Sanitize a value for caching by ensuring it's JSON serializable.

    Args:
        value: Value to sanitize

    Returns:
        JSON-serializable value

    """
    match value:
        case None | str() | int() | float() | bool():
            return value
        case UUID():
            return str(value)
        case dict():
            return {str(k): sanitize_cache_value(v) for k, v in value.items()}
        case list() | tuple():
            return [sanitize_cache_value(item) for item in value]
        case _ if hasattr(value, "model_dump") or hasattr(value, "__dataclass_fields__"):
            model_dump = getattr(value, "model_dump", None)
            as_dict: dict[str, object] = model_dump() if callable(model_dump) else value.__dict__
            return sanitize_cache_value(as_dict)
        case _:
            return str(value)
