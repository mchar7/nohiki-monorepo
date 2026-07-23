"""Behavior tests for correlation pipeline viability."""

from __future__ import annotations

import pytest
from health_check.checks.application.correlation_viability import CorrelationViabilityCheck
from health_check.core.models import CheckStatus

from .._helpers import MockPlatform


async def test_vectors_on_both_sides_without_correlations_fails_actionably() -> None:
    result = await CorrelationViabilityCheck().execute(MockPlatform(_psql_result=(0, "12|4|0", "")))

    assert result.status == CheckStatus.FAILED
    assert "Zero correlations" in result.summary
    assert result.details == ("eligible_jobs=12", "eligible_profiles=4", "correlations=0")
    assert result.remediation_hint is not None
    assert "consumer" in result.remediation_hint
    assert "replay" in result.remediation_hint


@pytest.mark.parametrize("counts", ["0|0|0", "8|0|0", "0|3|0"])
async def test_missing_input_population_is_fresh_precondition_not_failure(counts: str) -> None:
    result = await CorrelationViabilityCheck().execute(MockPlatform(_psql_result=(0, counts, "")))

    assert result.status == CheckStatus.SKIPPED
    assert "not both ready" in result.summary
    assert len(result.details) == 3


async def test_correlation_output_passes_with_all_counts() -> None:
    result = await CorrelationViabilityCheck().execute(MockPlatform(_psql_result=(0, "12|4|9", "")))

    assert result.status == CheckStatus.PASSED
    assert result.details == ("eligible_jobs=12", "eligible_profiles=4", "correlations=9")
