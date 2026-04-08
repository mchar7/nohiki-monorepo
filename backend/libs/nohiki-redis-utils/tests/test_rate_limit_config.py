from __future__ import annotations

from collections.abc import Callable

import pytest
from nohiki_redis_utils.rate_limit_config import (
    RateLimit,
    TimeUnit,
    per_day,
    per_hour,
    per_minute,
    per_second,
)


def test_rate_limit_window_seconds() -> None:
    limit = RateLimit(requests=5, unit=TimeUnit.SECONDS)

    assert limit.window_seconds == 1


def test_rate_limit_window_seconds_with_count() -> None:
    limit = RateLimit(requests=200, unit=TimeUnit.DAYS, count=30)

    assert limit.window_seconds == 30 * 24 * 60 * 60


def test_rate_limit_display_name_defaults_count_one() -> None:
    limit = RateLimit(requests=5, unit=TimeUnit.SECONDS)

    assert limit.display_name == "5/second"


def test_rate_limit_display_name_defaults_count_multiple() -> None:
    limit = RateLimit(requests=200, unit=TimeUnit.DAYS, count=30)

    assert limit.display_name == "200/30_days"


def test_rate_limit_display_name_uses_name_when_set() -> None:
    limit = RateLimit(requests=200, unit=TimeUnit.DAYS, count=30, name="monthly")

    assert limit.display_name == "monthly"


@pytest.mark.parametrize(
    ("factory", "expected"),
    [
        (lambda: per_second(5), RateLimit(requests=5, unit=TimeUnit.SECONDS)),
        (lambda: per_minute(10), RateLimit(requests=10, unit=TimeUnit.MINUTES)),
        (lambda: per_hour(20), RateLimit(requests=20, unit=TimeUnit.HOURS)),
        (lambda: per_day(30), RateLimit(requests=30, unit=TimeUnit.DAYS, count=1)),
        (
            lambda: per_day(40, count=7),
            RateLimit(requests=40, unit=TimeUnit.DAYS, count=7),
        ),
    ],
)
def test_helpers_create_expected_rate_limits(factory: Callable[[], RateLimit], expected: RateLimit) -> None:
    assert factory() == expected
