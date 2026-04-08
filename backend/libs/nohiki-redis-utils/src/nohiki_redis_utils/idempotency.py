"""Redis-based idempotency for stateless services (no database)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nohiki_observability import get_logger

if TYPE_CHECKING:
    from .redis_cache import RedisCache

logger = get_logger(__name__)

_DEFAULT_TTL_SECONDS = 604800  # 7 days


async def check_and_mark_processed_redis(
    cache: RedisCache,
    event_id: str,
    handler_name: str,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> bool:
    """Redis-based idempotency check for stateless services.

    Uses SETNX (set-if-not-exists) with TTL for automatic cleanup.
    Suitable for services without a database (e.g., ml-gateway-service).

    Args:
        cache: RedisCache instance.
        event_id: Unique event identifier (from EventMetadata.event_id).
        handler_name: Handler function name for per-handler deduplication.
        ttl_seconds: Time-to-live for the dedup key (default: 7 days).

    Returns:
        True if the event is NEW (not yet processed).
        False if the event was ALREADY processed (duplicate).

    """
    key = f"processed:{handler_name}:{event_id}"
    was_set = await cache.setnx_strict(key, "1", ttl=ttl_seconds)
    if not was_set:
        logger.debug(
            "Duplicate event detected (Redis), skipping",
            event_id=event_id,
            handler_name=handler_name,
        )
    return was_set
