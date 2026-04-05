"""Versioned compensation projection policy."""

from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .currency import to_minor_units

ANNUALIZATION_POLICY_VERSION: Final = "2026-07-11"
HOURS_PER_WEEK: Final = 40
DAYS_PER_WEEK: Final = 5
WEEKS_PER_YEAR: Final = 52


class PayPeriod(StrEnum):
    """Supported compensation payment periods."""

    HOURLY = "HOURLY"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    SEMI_MONTHLY = "SEMI_MONTHLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUALLY = "ANNUALLY"


PAY_PERIOD_ANNUAL_MULTIPLIER: Final = MappingProxyType(
    {
        PayPeriod.HOURLY: HOURS_PER_WEEK * WEEKS_PER_YEAR,
        PayPeriod.DAILY: DAYS_PER_WEEK * WEEKS_PER_YEAR,
        PayPeriod.WEEKLY: WEEKS_PER_YEAR,
        PayPeriod.BIWEEKLY: WEEKS_PER_YEAR // 2,
        PayPeriod.SEMI_MONTHLY: 24,
        PayPeriod.MONTHLY: 12,
        PayPeriod.QUARTERLY: 4,
        PayPeriod.ANNUALLY: 1,
    }
)


def _pay_period(pay_period: PayPeriod | str) -> PayPeriod:
    try:
        return PayPeriod(pay_period)
    except ValueError:
        msg = f"Unsupported pay period: {pay_period!r}"
        raise ValueError(msg) from None


def annualize_to_minor_units(
    amount_major: Decimal,
    currency: str,
    pay_period: PayPeriod | str,
) -> int:
    """Project periodic compensation to annual minor units under this policy.

    The periodic amount is rounded to integral minor units before applying the
    annual multiplier. The result is versioned projection metadata governed by
    ``ANNUALIZATION_POLICY_VERSION``; it must not be persisted as unversioned
    domain truth.

    Args:
        amount_major: Finite periodic amount represented exactly as a Decimal.
        currency: A supported ISO 4217 code.
        pay_period: A supported payment period.

    Returns:
        Annualized integral minor units.

    Raises:
        ValueError: If the currency, period, or amount is unsupported.
    """
    multiplier = PAY_PERIOD_ANNUAL_MULTIPLIER[_pay_period(pay_period)]
    return to_minor_units(amount_major, currency) * multiplier
