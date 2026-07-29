"""Per-user notification frequency cap.

A user with a low correlation threshold and a broad search can be matched dozens
of times by one ingestion batch. The cap admits a bounded number of sends per
user per window and defers the rest.

State is a Redis token bucket, for two reasons the in-process circuit breakers
do not have to satisfy: the cap is a user-facing promise, so it has to survive a
pod restart, and every replica has to see the same count or N replicas each
grant a full window. The bucket's decision is one atomic Lua round trip, so
concurrent pods cannot both admit the last slot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nohiki_observability import get_logger

if TYPE_CHECKING:
    from uuid import UUID

    from nohiki_redis_utils import RateLimiter, RateLimitResult

logger = get_logger(__name__)


class FrequencyChecker:
    """Frequency gate for per-user notification volume.

    Args:
        rate_limiter: Redis-backed token bucket keyed per user.
        max_per_window: Admissions per window, for log context.
        window_seconds: Window duration in seconds, for log context.

    """

    def __init__(
        self,
        rate_limiter: RateLimiter,
        *,
        max_per_window: int,
        window_seconds: int,
    ) -> None:
        """Build a checker over an already-configured limiter."""
        self._limiter = rate_limiter
        self._max_per_window = max_per_window
        self._window_seconds = window_seconds

    async def check(self, user_id: UUID) -> RateLimitResult:
        """Consume one of the user's slots, reporting the bucket's decision.

        The full result is returned rather than a bool because a refusal
        carries ``retry_after``, which the caller needs to defer the row until
        the bucket has actually refilled.

        Args:
            user_id: Recipient being charged for this send.

        Returns:
            The bucket's decision. ``allowed`` is ``False`` when the user is
            over their cap or when a fail-closed backend was unavailable.

        """
        result = await self._limiter.check(f"user-notify:{user_id}")
        if not result.allowed:
            logger.info(
                "User notification frequency cap reached",
                user_id=str(user_id),
                max_per_window=self._max_per_window,
                window_seconds=self._window_seconds,
                retry_after=result.retry_after,
            )
        return result
