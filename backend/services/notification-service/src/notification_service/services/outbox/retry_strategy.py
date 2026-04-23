"""Retry strategy for message delivery with exponential backoff and jitter."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from notification_service.core.config import settings


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """Decision about whether and when to retry a message."""

    should_retry: bool
    retry_at: datetime | None
    delay_seconds: int


class RetryStrategy:
    """Exponential backoff with symmetric jitter.

    Jitter de-synchronises retries across the fleet. Without it, a batch of
    workers that all fail at the same instant will all retry at the same
    instant, and a single transient failure on the recovering provider
    re-trips every pod's circuit breaker simultaneously. The jitter factor
    is a fraction of the computed delay; 0 disables it (used in tests that
    need deterministic timing).
    """

    def __init__(
        self,
        max_retries: int | None = None,
        base_delay_seconds: int | None = None,
        max_delay_seconds: int | None = None,
        jitter_factor: float | None = None,
    ) -> None:
        """Initialize retry strategy.

        Args:
            max_retries: Maximum retry attempts. Defaults to settings.
            base_delay_seconds: Base delay for exponential backoff. Defaults to settings.
            max_delay_seconds: Maximum delay cap. Defaults to settings.
            jitter_factor: Fraction of delay used as symmetric jitter width;
                pass ``0`` to disable. Defaults to settings.

        """
        self._max_retries = max_retries if max_retries is not None else settings.outbox.max_retries
        self._base_delay = (
            base_delay_seconds if base_delay_seconds is not None else settings.outbox.retry_base_delay_seconds
        )
        self._max_delay = (
            max_delay_seconds if max_delay_seconds is not None else settings.outbox.max_retry_delay_seconds
        )
        self._jitter_factor = jitter_factor if jitter_factor is not None else settings.outbox.jitter_factor

    def calculate_delay(self, retry_count: int) -> int:
        """Calculate the delay before retry ``retry_count``.

        Computes ``base_delay * 2 ** (retry_count - 1)``, caps at
        ``max_delay``, then applies symmetric jitter as a fraction of the
        capped value. Result is floored at 1 second so we never schedule an
        immediate retry.

        Args:
            retry_count: Current retry attempt number (1-indexed).

        Returns:
            Delay in whole seconds.

        """
        capped = min(self._base_delay * (2 ** (retry_count - 1)), self._max_delay)
        if self._jitter_factor == 0:
            return capped
        # Symmetric jitter mirrors the nohiki-kafka-client supervisor pattern.
        # S311: jitter does not require cryptographic strength; it just needs
        # to de-correlate retry timing across workers.
        jitter = capped * self._jitter_factor * random.uniform(-1, 1)  # noqa: S311
        return max(1, round(capped + jitter))

    def should_retry(
        self,
        retry_count: int,
        *,
        retryable: bool,
        retry_after_seconds: int | None = None,
    ) -> RetryDecision:
        """Determine whether to retry and honor a provider's minimum delay."""
        if not retryable or retry_count >= self._max_retries:
            return RetryDecision(should_retry=False, retry_at=None, delay_seconds=0)

        delay = max(self.calculate_delay(retry_count), retry_after_seconds or 0)
        retry_at = datetime.now(UTC) + timedelta(seconds=delay)
        return RetryDecision(should_retry=True, retry_at=retry_at, delay_seconds=delay)
