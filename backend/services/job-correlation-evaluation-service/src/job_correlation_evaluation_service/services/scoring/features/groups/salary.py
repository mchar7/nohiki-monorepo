"""Salary feature extraction with currency-aware comparison.

Extracts raw annualized salary values in minor units. When user preference and
job compensation currencies differ, all salary features are set to NaN since
cross-currency comparison without conversion is meaningless.

Future extensibility: A CurrencyConverter protocol could be injected to enable
cross-currency comparisons via Redis-cached exchange rates.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from nohiki.common.v1 import Compensation, CurrencyCode, PaymentFrequency, SalaryPreference

from job_correlation_evaluation_service.services.scoring.constants import FeatureIndex
from job_correlation_evaluation_service.services.scoring.features.base import FeatureGroup

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from job_correlation_evaluation_service.services.scoring.features.base import (
        FeatureExtractionContext,
    )


class SalaryFeatureGroup(FeatureGroup):
    """Extract raw salary features (indices 11-13) with currency validation.

    Features:
        - USER_MIN_SALARY: User's minimum acceptable salary (annualized minor units)
        - USER_TARGET_SALARY: User's target salary (annualized minor units)
        - JOB_SALARY: Job's annualized salary (annualized minor units, midpoint if range)

    Currency Handling:
        All three features are set to NaN when user and job currencies differ.
        Cross-currency comparison without conversion would pollute the ML signal.

    Design: Provides raw values for LightGBM to learn salary negotiation patterns.
    """

    def extract(
        self,
        features: NDArray[np.float32],
        context: FeatureExtractionContext,
    ) -> None:
        """Extract salary features into feature vector.

        Sets all salary features to NaN if currencies don't match.
        """
        salary_pref = context.profile.salary_preference
        compensation = context.job.compensation

        user_currency = _get_user_currency(salary_pref)
        job_currency = _get_job_currency(compensation)

        if not _currencies_comparable(user_currency, job_currency):
            features[FeatureIndex.USER_MIN_SALARY] = math.nan
            features[FeatureIndex.USER_TARGET_SALARY] = math.nan
            features[FeatureIndex.JOB_SALARY] = math.nan
            return

        if salary_pref:
            user_min, user_target = _extract_salary_values(salary_pref)
            features[FeatureIndex.USER_MIN_SALARY] = float(user_min) if user_min else math.nan
            features[FeatureIndex.USER_TARGET_SALARY] = float(user_target) if user_target else math.nan
        else:
            features[FeatureIndex.USER_MIN_SALARY] = math.nan
            features[FeatureIndex.USER_TARGET_SALARY] = math.nan

        if compensation:
            job_salary = _get_annualized_salary(compensation)
            features[FeatureIndex.JOB_SALARY] = float(job_salary) if job_salary else math.nan
        else:
            features[FeatureIndex.JOB_SALARY] = math.nan

        desired = features[FeatureIndex.USER_TARGET_SALARY]
        if math.isnan(desired):
            desired = features[FeatureIndex.USER_MIN_SALARY]
        job_salary = features[FeatureIndex.JOB_SALARY]
        if not math.isnan(desired) and desired > 0 and not math.isnan(job_salary) and job_salary > 0:
            context.factor_scores["salary"] = min(1.0, float(job_salary / desired))


def _get_user_currency(salary_pref: SalaryPreference | None) -> CurrencyCode | None:
    """Extract canonical currency from user salary preference.

    Returns the currency from min_salary or target_salary (whichever is present).
    Per proto validation, if both exist they must use the same currency.
    """
    if not salary_pref:
        return None
    if min_sal := salary_pref.min_salary:
        return min_sal.currency
    if target_sal := salary_pref.target_salary:
        return target_sal.currency
    return None


def _get_job_currency(compensation: Compensation | None) -> CurrencyCode | None:
    """Extract canonical currency from job compensation.

    Checks fixed_amount, then min_amount, then max_amount.
    Per proto validation, all bounds use the same currency.
    """
    if not compensation:
        return None
    if (fixed := compensation.fixed_amount) and fixed.amount:
        return fixed.amount.currency
    if (min_amt := compensation.min_amount) and min_amt.amount:
        return min_amt.amount.currency
    if (max_amt := compensation.max_amount) and max_amt.amount:
        return max_amt.amount.currency
    return None


def _currencies_comparable(
    user_currency: CurrencyCode | None,
    job_currency: CurrencyCode | None,
) -> bool:
    """Check if currencies allow meaningful salary comparison.

    Returns True if:
    - Both currencies are the same (and not UNSPECIFIED)
    - Either side is missing (NaN will be set for missing data anyway)

    Returns False if both are present but different.
    """
    if user_currency is None or job_currency is None:
        return True
    if CurrencyCode.UNSPECIFIED in {user_currency, job_currency}:
        return True
    return user_currency == job_currency


def _extract_salary_values(
    salary_pref: SalaryPreference,
) -> tuple[int | None, int | None]:
    """Extract min and target salary values from user preferences (annualized minor units)."""
    min_salary = salary_pref.min_salary
    target_salary = salary_pref.target_salary

    user_min = min_salary.minor_units if min_salary else None
    user_target = target_salary.minor_units if target_salary else None

    return user_min, user_target


def _get_annualized_salary(compensation: Compensation) -> int | None:
    """Extract annualized salary from compensation in minor units."""
    fixed_bound = compensation.fixed_amount
    if fixed_bound is not None:
        fixed_units = fixed_bound.amount.minor_units
        if fixed_units > 0:
            return _annualize(fixed_units, compensation)

    min_bound = compensation.min_amount
    max_bound = compensation.max_amount
    if min_bound is not None and max_bound is not None:
        min_units = min_bound.amount.minor_units
        max_units = max_bound.amount.minor_units
        if min_units > 0 and max_units > 0:
            return _annualize((min_units + max_units) // 2, compensation)

    return None


ANNUALIZATION_MULTIPLIERS: dict[PaymentFrequency, int] = {
    PaymentFrequency.HOURLY: 2080,  # 40 hrs/week * 52 weeks
    PaymentFrequency.DAILY: 260,  # 5 days/week * 52 weeks
    PaymentFrequency.WEEKLY: 52,
    PaymentFrequency.BIWEEKLY: 26,
    PaymentFrequency.MONTHLY: 12,
    PaymentFrequency.ANNUALLY: 1,
}


def _annualize(amount: int, compensation: Compensation) -> int:
    """Convert amount to annual based on payment frequency."""
    multiplier = ANNUALIZATION_MULTIPLIERS.get(compensation.frequency, 1)
    return amount * multiplier
