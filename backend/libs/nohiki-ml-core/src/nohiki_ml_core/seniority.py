"""Seniority level derivation from experience years."""

from nohiki.common.v1 import SeniorityLevel


def derive_seniority_level(
    min_years: int | None,
    *,
    entry_max: int = 2,
    mid_max: int = 5,
    senior_max: int = 10,
) -> SeniorityLevel:
    """Derive seniority level from minimum years of experience.

    Maps experience years to seniority levels using configurable thresholds.
    Returns UNSPECIFIED when min_years is None or negative.

    Default thresholds:
    - ENTRY: 0-2 years (< entry_max)
    - MID: 2-5 years (< mid_max)
    - SENIOR: 5-10 years (< senior_max)
    - STAFF: 10+ years (>= senior_max)

    Args:
        min_years: Minimum years of experience from job listing.
        entry_max: Upper bound for entry level (exclusive).
        mid_max: Upper bound for mid level (exclusive).
        senior_max: Upper bound for senior level (exclusive).

    Returns:
        Derived SeniorityLevel enum value.

    Examples:
        >>> derive_seniority_level(0)
        SeniorityLevel.ENTRY
        >>> derive_seniority_level(3)
        SeniorityLevel.MID
        >>> derive_seniority_level(7)
        SeniorityLevel.SENIOR
        >>> derive_seniority_level(12)
        SeniorityLevel.STAFF
        >>> derive_seniority_level(None)
        SeniorityLevel.UNSPECIFIED

    """
    if min_years is None or min_years < 0:
        return SeniorityLevel.UNSPECIFIED

    if min_years < entry_max:
        return SeniorityLevel.ENTRY
    if min_years < mid_max:
        return SeniorityLevel.MID
    if min_years < senior_max:
        return SeniorityLevel.SENIOR
    return SeniorityLevel.STAFF
