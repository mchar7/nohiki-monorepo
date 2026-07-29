"""Per-user frequency cap contract.

The cap is a Redis token bucket, so the observable contract here is that every
decision is delegated to the shared bucket under a per-user key. Nothing is
counted in process, which is what makes the cap survive a restart and hold
across replicas.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from nohiki_redis_utils import RateLimiter, RateLimitResult
from notification_service.services.frequency_checker import FrequencyChecker

_USER = UUID("00000000-0000-0000-0000-0000000000aa")
_OTHER_USER = UUID("00000000-0000-0000-0000-0000000000bb")


class _CountingLimiter(RateLimiter):
    """Token bucket double admitting a fixed number of calls per key."""

    def __init__(self, *, allowance: int) -> None:
        self._allowance = allowance
        self._spent: dict[str, int] = {}
        self.keys: list[str] = []

    async def check(self, key: str) -> RateLimitResult:
        self.keys.append(key)
        spent = self._spent.get(key, 0)
        now = datetime.now(UTC).timestamp()
        if spent >= self._allowance:
            return RateLimitResult(allowed=False, remaining=0, reset_at=now + 60, retry_after=60.0)
        self._spent[key] = spent + 1
        return RateLimitResult(
            allowed=True,
            remaining=self._allowance - self._spent[key],
            reset_at=now + 60,
        )

    async def reset(self, key: str) -> None:
        self._spent.pop(key, None)


def _checker(limiter: RateLimiter, *, allowance: int = 3) -> FrequencyChecker:
    return FrequencyChecker(limiter, max_per_window=allowance, window_seconds=3600)


class TestFrequencyChecker:
    """Boundary behaviour of the cap."""

    @pytest.mark.asyncio
    async def test_admits_up_to_the_cap_then_throttles(self) -> None:
        """The Nth send is admitted and the N+1th is refused."""
        limiter = _CountingLimiter(allowance=3)
        checker = _checker(limiter)

        verdicts = [(await checker.check(_USER)).allowed for _ in range(4)]

        assert verdicts == [True, True, True, False]

    @pytest.mark.asyncio
    async def test_stays_throttled_while_the_bucket_is_empty(self) -> None:
        """A capped user keeps being refused rather than leaking one through."""
        limiter = _CountingLimiter(allowance=1)
        checker = _checker(limiter, allowance=1)

        assert (await checker.check(_USER)).allowed is True
        assert (await checker.check(_USER)).allowed is False
        assert (await checker.check(_USER)).allowed is False

    @pytest.mark.asyncio
    async def test_cap_is_per_user(self) -> None:
        """One user exhausting their bucket does not affect another."""
        limiter = _CountingLimiter(allowance=1)
        checker = _checker(limiter, allowance=1)

        assert (await checker.check(_USER)).allowed is True
        assert (await checker.check(_USER)).allowed is False
        assert (await checker.check(_OTHER_USER)).allowed is True

    @pytest.mark.asyncio
    async def test_key_is_namespaced_by_user(self) -> None:
        """The bucket key identifies the user, not the provider or channel."""
        limiter = _CountingLimiter(allowance=1)

        await _checker(limiter).check(_USER)

        assert limiter.keys == [f"user-notify:{_USER}"]

    @pytest.mark.asyncio
    async def test_every_decision_reaches_the_shared_bucket(self) -> None:
        """No decision is cached in process, so replicas cannot diverge."""
        limiter = _CountingLimiter(allowance=5)
        checker = _checker(limiter, allowance=5)

        for _ in range(3):
            await checker.check(_USER)

        assert len(limiter.keys) == 3

    @pytest.mark.asyncio
    async def test_refusal_carries_the_buckets_retry_after(self) -> None:
        """The caller needs the bucket's own refill estimate to defer a row."""
        checker = _checker(_CountingLimiter(allowance=1), allowance=1)

        await checker.check(_USER)
        refused = await checker.check(_USER)

        assert refused.allowed is False
        assert refused.retry_after == 60.0
