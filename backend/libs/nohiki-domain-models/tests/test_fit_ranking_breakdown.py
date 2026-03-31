"""Round-trip tests for the public fit-ranking explanation contract."""

from nohiki.job.correlation.v1 import (
    CorrelationEvaluated,
    FitFactor,
    FitFactorContribution,
    FitRankingBreakdown,
)


def test_fit_ranking_breakdown_round_trips_without_legacy_metadata() -> None:
    event = CorrelationEvaluated(
        correlation_id="5bb6f7b7-63db-42f9-9617-a0abfc7793fa",
        fit_score=80,
        correlation_metadata={},
        fit_ranking_breakdown=FitRankingBreakdown(
            method_version="deterministic-fit-v1",
            factors=[
                FitFactorContribution(
                    factor=FitFactor.ROLE_RELEVANCE,
                    compatibility_score=81.5,
                    importance=100,
                    contribution_points=0.0,
                ),
                FitFactorContribution(
                    factor=FitFactor.SKILLS,
                    compatibility_score=92.0,
                    importance=75,
                    contribution_points=1.75,
                ),
                FitFactorContribution(
                    factor=FitFactor.LOCATION,
                    compatibility_score=25.0,
                    importance=50,
                    contribution_points=-3.25,
                ),
            ],
        ),
    )

    restored = CorrelationEvaluated().parse(bytes(event))

    assert restored.fit_score == 80
    assert dict(restored.correlation_metadata) == {}
    assert restored.fit_ranking_breakdown is not None
    assert restored.fit_ranking_breakdown.method_version == "deterministic-fit-v1"
    assert [factor.factor for factor in restored.fit_ranking_breakdown.factors] == [
        FitFactor.ROLE_RELEVANCE,
        FitFactor.SKILLS,
        FitFactor.LOCATION,
    ]
    assert [factor.contribution_points for factor in restored.fit_ranking_breakdown.factors] == [
        0.0,
        1.75,
        -3.25,
    ]
    assert 100 * 0.815 + 1.75 - 3.25 == 80.0
