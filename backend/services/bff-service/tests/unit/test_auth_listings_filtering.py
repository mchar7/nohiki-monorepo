"""Unit tests for auth-listings diversity filter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from bff_service.services.auth_listings.filtering import apply_diversity_filter
from bff_service.services.auth_listings.schemas import WeightedCandidate

# Helpers


def _candidate(
    company: str = "Acme Corp",
    weight: float = 0.5,
    title: str = "Software Engineer",
) -> WeightedCandidate:
    """Create a WeightedCandidate with sensible defaults."""
    return WeightedCandidate(
        title=title,
        company_name=company,
        location_raw="Berlin, Germany",
        work_arrangement="REMOTE",
        required_skills=["Python"],
        posted_at=datetime.now(UTC) - timedelta(days=1),
        language="en",
        weight=weight,
    )


# Company diversity cap


class TestCompanyDiversityCap:
    """Verify per-company limits are enforced."""

    def test_all_same_company_capped(self) -> None:
        """10 listings from 1 company, max_per_company=3 → only 3 returned."""
        candidates = [_candidate(company="MegaCorp", weight=1.0 - i * 0.01) for i in range(10)]
        result = apply_diversity_filter(candidates, max_per_company=3, max_total=10)

        assert len(result) == 3
        assert all(c.company_name == "MegaCorp" for c in result)

    def test_mixed_companies_proper_diversity(self) -> None:
        """Candidates from 3 companies, max_per_company=2 → at most 2 per company."""
        candidates = [
            _candidate(company="Alpha", weight=0.9),
            _candidate(company="Beta", weight=0.85),
            _candidate(company="Alpha", weight=0.8),
            _candidate(company="Gamma", weight=0.75),
            _candidate(company="Beta", weight=0.7),
            _candidate(company="Alpha", weight=0.65),
            _candidate(company="Gamma", weight=0.6),
        ]
        result = apply_diversity_filter(candidates, max_per_company=2, max_total=10)

        # Alpha: 2, Beta: 2, Gamma: 2 → 6 total (Alpha 3rd is skipped)
        assert len(result) == 6
        company_counts = {}
        for c in result:
            company_counts[c.company_name] = company_counts.get(c.company_name, 0) + 1
        assert company_counts["Alpha"] == 2
        assert company_counts["Beta"] == 2
        assert company_counts["Gamma"] == 2


# Edge cases


class TestEdgeCases:
    """Boundary conditions and degenerate inputs."""

    def test_empty_input_returns_empty(self) -> None:
        """No candidates → no results."""
        result = apply_diversity_filter([], max_per_company=3, max_total=10)
        assert result == []

    def test_fewer_than_max_total_returns_all(self) -> None:
        """Input smaller than max_total → all candidates pass through."""
        candidates = [_candidate(weight=0.9 - i * 0.1) for i in range(3)]
        result = apply_diversity_filter(candidates, max_per_company=5, max_total=10)
        assert len(result) == 3

    def test_max_per_company_of_one(self) -> None:
        """Strict dedup: max_per_company=1 keeps only the top-weighted per company."""
        candidates = [
            _candidate(company="A", weight=0.9),
            _candidate(company="A", weight=0.8),
            _candidate(company="B", weight=0.7),
            _candidate(company="B", weight=0.6),
        ]
        result = apply_diversity_filter(candidates, max_per_company=1, max_total=10)
        assert len(result) == 2
        assert result[0].company_name == "A"
        assert result[1].company_name == "B"


# Ordering preservation


class TestOrderPreservation:
    """Verify output preserves weight-descending order."""

    def test_preserves_weight_descending_order(self) -> None:
        """Filtered results maintain the original weight-descending order."""
        candidates = [
            _candidate(company="X", weight=0.95),
            _candidate(company="Y", weight=0.90),
            _candidate(company="X", weight=0.85),
            _candidate(company="Z", weight=0.80),
            _candidate(company="Y", weight=0.75),
        ]
        result = apply_diversity_filter(candidates, max_per_company=2, max_total=10)
        weights = [c.weight for c in result]
        assert weights == sorted(weights, reverse=True)


# Early termination


class TestEarlyTermination:
    """Verify max_total cap halts iteration."""

    def test_stops_at_max_total(self) -> None:
        """With many candidates, output length is exactly max_total."""
        candidates = [_candidate(company=f"Company-{i}", weight=1.0 - i * 0.01) for i in range(50)]
        result = apply_diversity_filter(candidates, max_per_company=5, max_total=10)
        assert len(result) == 10

    def test_max_total_one(self) -> None:
        """max_total=1 → exactly one result (the highest weight)."""
        candidates = [
            _candidate(company="A", weight=0.9),
            _candidate(company="B", weight=0.8),
        ]
        result = apply_diversity_filter(candidates, max_per_company=5, max_total=1)
        assert len(result) == 1
        assert result[0].weight == pytest.approx(0.9)
