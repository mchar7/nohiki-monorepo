"""Tests for retry strategy with exponential backoff and jitter."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from notification_service.services.outbox.retry_strategy import RetryDecision, RetryStrategy


class TestRetryDecision:
    """Tests for RetryDecision dataclass."""

    def test_retry_decision_should_retry_true(self) -> None:
        """RetryDecision correctly represents retry state."""
        decision = RetryDecision(
            should_retry=True,
            retry_at=datetime.now(UTC),
            delay_seconds=30,
        )
        assert decision.should_retry is True
        assert decision.retry_at is not None
        assert decision.delay_seconds == 30

    def test_retry_decision_should_retry_false(self) -> None:
        """RetryDecision correctly represents no-retry state."""
        decision = RetryDecision(
            should_retry=False,
            retry_at=None,
            delay_seconds=0,
        )
        assert decision.should_retry is False
        assert decision.retry_at is None
        assert decision.delay_seconds == 0


class TestRetryStrategyInit:
    """Tests for RetryStrategy initialization."""

    def test_init_accepts_custom_params(self) -> None:
        """Strategy accepts custom parameters."""
        strategy = RetryStrategy(
            max_retries=3,
            base_delay_seconds=5,
            max_delay_seconds=60,
            jitter_factor=0.1,
        )
        assert strategy._max_retries == 3
        assert strategy._base_delay == 5
        assert strategy._max_delay == 60
        assert strategy._jitter_factor == pytest.approx(0.1)

    def test_init_jitter_zero_is_explicit_disable(self) -> None:
        """Passing jitter_factor=0 disables jitter even if settings default differs."""
        with patch("notification_service.services.outbox.retry_strategy.settings") as mock_settings:
            mock_settings.outbox.max_retries = 5
            mock_settings.outbox.retry_base_delay_seconds = 10
            mock_settings.outbox.max_retry_delay_seconds = 300
            mock_settings.outbox.jitter_factor = 0.4

            strategy = RetryStrategy(jitter_factor=0)

            assert strategy._jitter_factor == 0


class TestCalculateDelayWithoutJitter:
    """Deterministic exponential backoff with jitter disabled."""

    @pytest.fixture
    def strategy(self) -> RetryStrategy:
        """Strategy with jitter disabled for exact-value assertions."""
        return RetryStrategy(
            max_retries=5,
            base_delay_seconds=10,
            max_delay_seconds=300,
            jitter_factor=0,
        )

    def test_first_retry_returns_base_delay(self, strategy: RetryStrategy) -> None:
        """First retry (count=1) returns base delay."""
        delay = strategy.calculate_delay(retry_count=1)
        assert delay == 10

    def test_second_retry_doubles_delay(self, strategy: RetryStrategy) -> None:
        """Second retry doubles the delay."""
        delay = strategy.calculate_delay(retry_count=2)
        assert delay == 20

    def test_third_retry_quadruples_delay(self, strategy: RetryStrategy) -> None:
        """Third retry quadruples the delay."""
        delay = strategy.calculate_delay(retry_count=3)
        assert delay == 40

    def test_delay_capped_at_max(self, strategy: RetryStrategy) -> None:
        """High retry count is capped at max_delay."""
        delay = strategy.calculate_delay(retry_count=10)
        assert delay == 300

    def test_exponential_growth_pattern(self, strategy: RetryStrategy) -> None:
        """Verify exponential backoff pattern: base * 2^(n-1)."""
        delays = [strategy.calculate_delay(i) for i in range(1, 6)]
        assert delays == [10, 20, 40, 80, 160]


class TestCalculateDelayWithJitter:
    """Symmetric jitter applied on top of exponential backoff."""

    def test_jitter_stays_within_symmetric_band(self) -> None:
        """With factor=0.2, delay falls within [80, 120] for base=100."""
        strategy = RetryStrategy(
            max_retries=5,
            base_delay_seconds=100,
            max_delay_seconds=10_000,
            jitter_factor=0.2,
        )
        # Many samples; every one must fall inside the symmetric band.
        # base*2^0 = 100, so jitter is in [-20, +20] for capped=100.
        delays = [strategy.calculate_delay(retry_count=1) for _ in range(500)]
        assert all(80 <= d <= 120 for d in delays), f"out-of-band: {min(delays)}..{max(delays)}"

    def test_jitter_actually_varies(self) -> None:
        """Repeated calls produce more than one distinct value."""
        strategy = RetryStrategy(
            max_retries=5,
            base_delay_seconds=100,
            max_delay_seconds=10_000,
            jitter_factor=0.2,
        )
        delays = {strategy.calculate_delay(retry_count=1) for _ in range(50)}
        # With factor=0.2 over base=100 → 41 integer outcomes available.
        # 50 draws should hit several distinct values with overwhelming probability.
        assert len(delays) >= 5, f"jitter looks frozen: {delays}"

    def test_jitter_distribution_is_centred(self) -> None:
        """Mean of many jittered samples is close to the capped delay."""
        # Seed the global RNG so this test is reproducible without weakening
        # the fact that calculate_delay reaches for the module-level random.
        random.seed(20260511)
        strategy = RetryStrategy(
            max_retries=5,
            base_delay_seconds=100,
            max_delay_seconds=10_000,
            jitter_factor=0.2,
        )
        samples = [strategy.calculate_delay(retry_count=1) for _ in range(2000)]
        mean = sum(samples) / len(samples)
        # 95% CI half-width on a uniform[-20,20] mean over n=2000 is ~0.51,
        # well below 2. A drift outside ±2 would signal a sign error or
        # non-symmetric distribution.
        assert abs(mean - 100) < 2, f"mean drifted: {mean:.2f}"

    def test_jitter_floor_at_one_second(self) -> None:
        """A tiny capped value plus negative jitter cannot drop below 1."""
        # With factor=1.0 and base=1 the band is [0, 2]; the implementation
        # floors at 1 so 0 is unreachable.
        strategy = RetryStrategy(
            max_retries=5,
            base_delay_seconds=1,
            max_delay_seconds=10,
            jitter_factor=1.0,
        )
        for _ in range(200):
            assert strategy.calculate_delay(retry_count=1) >= 1

    def test_jitter_respects_max_delay_ceiling_indirectly(self) -> None:
        """Cap is applied before jitter, so the *jittered* value may exceed max.

        This codifies the current contract: jitter is layered on top of the
        capped backoff, so a large jitter factor can push a sample above
        ``max_delay``. The thundering-herd goal is served either way; if a
        hard ceiling on the jittered value is later required, this test
        should be updated alongside the implementation change.
        """
        strategy = RetryStrategy(
            max_retries=10,
            base_delay_seconds=10,
            max_delay_seconds=100,
            jitter_factor=0.5,
        )
        delays = [strategy.calculate_delay(retry_count=10) for _ in range(200)]
        # Capped at 100; ±50% jitter band is [50, 150].
        assert max(delays) > 100  # documents the over-cap behaviour
        assert min(delays) >= 50


class TestShouldRetry:
    """Tests for should_retry method."""

    @pytest.fixture
    def strategy(self) -> RetryStrategy:
        """Strategy with jitter disabled for deterministic retry_at assertions."""
        return RetryStrategy(
            max_retries=3,
            base_delay_seconds=10,
            max_delay_seconds=300,
            jitter_factor=0,
        )

    def test_retryable_below_max_returns_true(self, strategy: RetryStrategy) -> None:
        """Retryable error below max retries returns should_retry=True."""
        decision = strategy.should_retry(retry_count=1, retryable=True)
        assert decision.should_retry is True
        assert decision.retry_at is not None
        assert decision.delay_seconds == 10

    def test_retry_after_delays_retry_beyond_backoff(self, strategy: RetryStrategy) -> None:
        """A provider Retry-After value is the minimum retry delay."""
        before = datetime.now(UTC)

        decision = strategy.should_retry(
            retry_count=1,
            retryable=True,
            retry_after_seconds=120,
        )

        assert decision.should_retry is True
        assert decision.delay_seconds == 120
        assert decision.retry_at is not None
        assert decision.retry_at >= before + timedelta(seconds=120)

    def test_retryable_at_max_returns_false(self, strategy: RetryStrategy) -> None:
        """Retryable error at max retries returns should_retry=False."""
        decision = strategy.should_retry(retry_count=3, retryable=True)
        assert decision.should_retry is False
        assert decision.retry_at is None
        assert decision.delay_seconds == 0

    def test_retryable_above_max_returns_false(self, strategy: RetryStrategy) -> None:
        """Retryable error above max retries returns should_retry=False."""
        decision = strategy.should_retry(retry_count=5, retryable=True)
        assert decision.should_retry is False

    def test_non_retryable_returns_false(self, strategy: RetryStrategy) -> None:
        """Non-retryable error always returns should_retry=False."""
        decision = strategy.should_retry(retry_count=1, retryable=False)
        assert decision.should_retry is False
        assert decision.retry_at is None

    def test_retry_at_matches_delay(self, strategy: RetryStrategy) -> None:
        """retry_at lies within [now, now + delay + 1s] tolerance window."""
        before = datetime.now(UTC)
        decision = strategy.should_retry(retry_count=1, retryable=True)
        after = datetime.now(UTC)

        assert decision.retry_at is not None
        assert decision.retry_at >= before
        assert decision.retry_at <= after + timedelta(seconds=decision.delay_seconds + 1)
