"""Caching utilities for document generation.

Provides hash computation, cache key generation, and Redis cache operations
for validation results.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypedDict, cast

from nohiki_redis_utils import create_cache

from doc_template_service.core.config import get_settings
from doc_template_service.schemas.models import ValidationIssue, ValidationReport

settings = get_settings()

_cache = create_cache(settings.service_name, redis_url=settings.redis_url)
VALIDATION_CACHE_TTL = 3600


class CacheKey(TypedDict, total=False):
    """Components for deterministic cache key generation."""

    template_hash: str
    schema_hash: str
    data_hash: str


def compute_hash(content: str | dict[str, Any] | None) -> str:
    """Compute a content-based SHA-256 hash for validation caching.

    Object identities are intentionally not cached: mutable dictionaries and
    Python ID reuse would allow stale validation results to be returned.

    Args:
        content: String or dict to hash

    Returns:
        SHA-256 hex digest of content

    """
    if content is None:
        return ""

    content_str = json.dumps(content, sort_keys=True) if isinstance(content, dict) else content
    return hashlib.sha256(content_str.encode()).hexdigest()


def get_cache_key(
    template: str | None = None,
    schema: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> str:
    """Generate a deterministic cache key from inputs.

    Args:
        template: Template source
        schema: JSON Schema
        data: Template data

    Returns:
        Cache key string

    """
    components = CacheKey(
        template_hash=compute_hash(template),
        schema_hash=compute_hash(schema),
        data_hash=compute_hash(data),
    )

    key_parts = [
        f"template:{components['template_hash']}",
        f"schema:{components['schema_hash']}",
        f"data:{components['data_hash']}",
    ]

    return "|".join(key_parts)


async def get_cached_validation_report(cache_key: str) -> ValidationReport | None:
    """Get cached validation report from Redis.

    Args:
        cache_key: Cache key for validation result

    Returns:
        Cached ValidationReport or None

    """
    cached = await _cache.get(f"validation:{cache_key}")
    if cached is None:
        return None
    if not isinstance(cached, dict):
        return None

    cached_data = cast("dict[str, Any]", cached)
    valid = bool(cached_data.get("valid", True))
    cached_issues = cached_data.get("issues", [])
    issues = [ValidationIssue(**issue) for issue in cached_issues] if cached_issues else []
    return ValidationReport(valid=valid, issues=issues)


async def set_cached_validation_report(cache_key: str, report: ValidationReport) -> None:
    """Store validation report in Redis cache.

    Args:
        cache_key: Cache key for validation result
        report: ValidationReport to cache

    """
    report_dict = {
        "valid": report.valid,
        "issues": [issue.model_dump() for issue in report.issues],
    }
    await _cache.set(f"validation:{cache_key}", report_dict, ttl=VALIDATION_CACHE_TTL)
