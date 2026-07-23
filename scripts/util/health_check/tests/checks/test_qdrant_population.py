"""Behavior tests for cross-store Qdrant population invariants."""

from __future__ import annotations

import json
from collections.abc import Generator
from unittest.mock import patch

import pytest
from health_check.checks.vectors.qdrant_population import (
    JobVectorPopulationCheck,
    ProfileVectorPopulationCheck,
)
from health_check.core.models import CheckStatus

from .._helpers import MockPlatform


class _Manifest:
    def get_collection_name(self, entity: str) -> str:
        return {"jobs": "jobs_v1", "profiles": "profiles_v1"}[entity]


@pytest.fixture(autouse=True)
def _manifest() -> Generator[None]:
    with patch(
        "health_check.checks.vectors.qdrant_population.ManifestCache.get",
        return_value=_Manifest(),
    ):
        yield


def _platform(*, entities: int, points: int) -> MockPlatform:
    return MockPlatform(
        _psql_result=(0, str(entities), ""),
        _curl_result=(0, json.dumps({"result": {"points_count": points}}), ""),
    )


@pytest.mark.parametrize(
    ("check", "collection", "entity"),
    [
        (JobVectorPopulationCheck(), "jobs_v1", "jobs"),
        (ProfileVectorPopulationCheck(), "profiles_v1", "profiles"),
    ],
)
async def test_embedded_entities_with_zero_points_are_actionable(
    check: JobVectorPopulationCheck | ProfileVectorPopulationCheck,
    collection: str,
    entity: str,
) -> None:
    result = await check.execute(_platform(entities=7, points=0))

    assert result.status == CheckStatus.FAILED
    assert collection in result.summary
    assert "zero points" in result.summary
    assert f"canonical_{entity}=7" in result.details
    assert f"{collection}.points=0" in result.details
    assert result.remediation_hint is not None
    assert "replay" in result.remediation_hint.lower()


@pytest.mark.parametrize("check", [JobVectorPopulationCheck(), ProfileVectorPopulationCheck()])
async def test_fresh_empty_population_is_not_a_false_failure(
    check: JobVectorPopulationCheck | ProfileVectorPopulationCheck,
) -> None:
    result = await check.execute(_platform(entities=0, points=0))

    assert result.status == CheckStatus.SKIPPED
    assert "Fresh empty" in result.summary
    assert result.remediation_hint is None
    assert any(detail.endswith("=0") for detail in result.details)


@pytest.mark.parametrize("check", [JobVectorPopulationCheck(), ProfileVectorPopulationCheck()])
async def test_populated_both_sides_reports_observed_counts(
    check: JobVectorPopulationCheck | ProfileVectorPopulationCheck,
) -> None:
    result = await check.execute(_platform(entities=7, points=5))

    assert result.status == CheckStatus.PASSED
    assert any(detail.endswith("=7") for detail in result.details)
    assert any(detail.endswith("=5") for detail in result.details)


def test_profile_population_counts_completed_canonical_profiles() -> None:
    assert "is_enrichment_complete" in ProfileVectorPopulationCheck.sql
    assert "embedding IS NOT NULL" not in ProfileVectorPopulationCheck.sql


async def test_orphan_points_are_actionable() -> None:
    result = await JobVectorPopulationCheck().execute(_platform(entities=0, points=3))

    assert result.status == CheckStatus.FAILED
    assert "Orphan" in result.summary
    assert result.details == ("canonical_jobs=0", "jobs_v1.points=3")
    assert result.remediation_hint is not None
