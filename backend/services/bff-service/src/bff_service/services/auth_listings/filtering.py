"""Diversity filter for auth-listings pipeline."""

from __future__ import annotations

from collections import defaultdict

from bff_service.services.auth_listings.schemas import WeightedCandidate


def apply_diversity_filter(
    candidates: list[WeightedCandidate],
    *,
    max_per_company: int,
    max_total: int,
) -> list[WeightedCandidate]:
    """Apply company diversity limits to weighted candidates.

    Performs a single O(n) pass over pre-sorted (by weight DESC) candidates,
    enforcing a per-company cap and an overall total cap. Uses a defaultdict
    for O(1) company count lookups.

    Args:
        candidates: Weighted candidates sorted by weight descending.
        max_per_company: Maximum listings per company in the result.
        max_total: Maximum total listings to return.

    Returns:
        Diversity-filtered candidates preserving weight-descending order.
    """
    company_counts: defaultdict[str, int] = defaultdict(int)
    result: list[WeightedCandidate] = []

    for candidate in candidates:
        if len(result) >= max_total:
            break

        company = candidate.company_name
        if company_counts[company] >= max_per_company:
            continue

        company_counts[company] += 1
        result.append(candidate)

    return result
