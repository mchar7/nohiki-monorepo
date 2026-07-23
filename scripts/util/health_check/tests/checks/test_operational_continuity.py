"""Behavior tests for schedule continuity and model readiness."""

import json

import pytest
from health_check.checks.application.model_readiness import ModelReadinessCheck
from health_check.checks.messaging.schedule_ticks import ScheduleTickContinuityCheck
from health_check.core.models import CheckStatus

from .._helpers import MockPlatform


async def test_due_schedules_without_dispatch_progress_fail_actionably() -> None:
    result = await ScheduleTickContinuityCheck().execute(MockPlatform(_psql_result=(0, "4|2|-1", "")))

    assert result.status == CheckStatus.FAILED
    assert "stalled" in result.summary
    assert result.details == (
        "active_schedules=4",
        "due_schedules=2",
        "latest_dispatch_age_seconds=-1",
    )
    assert result.remediation_hint is not None
    assert "Kafka publication" in result.remediation_hint
    assert "consumer membership" in result.remediation_hint


async def test_inactive_schedules_do_not_mask_active_overdue_schedule() -> None:
    result = await ScheduleTickContinuityCheck().execute(MockPlatform(_psql_result=(0, "2|1|-1", "")))

    assert result.status == CheckStatus.FAILED
    assert result.summary == "Schedule tick publication is stalled"
    assert result.remediation_hint is not None


async def test_fresh_empty_schedules_are_not_a_false_failure() -> None:
    result = await ScheduleTickContinuityCheck().execute(MockPlatform(_psql_result=(0, "0|0|-1", "")))

    assert result.status == CheckStatus.SKIPPED
    assert "not required" in result.summary
    assert "active_schedules=0" in result.details


async def test_recent_dispatch_progress_passes_with_age_evidence() -> None:
    result = await ScheduleTickContinuityCheck().execute(MockPlatform(_psql_result=(0, "4|2|15", "")))

    assert result.status == CheckStatus.PASSED
    assert "latest_dispatch_age_seconds=15" in result.details


async def test_missing_model_readiness_is_actionable() -> None:
    result = await ModelReadinessCheck().execute(MockPlatform(_curl_result=(22, "", "HTTP 503")))

    assert result.status == CheckStatus.FAILED
    assert result.summary == "ML inference models are not ready"
    assert result.details == ("ml-compute-service readiness probe failed",)
    assert result.remediation_hint is not None
    assert "model cache" in result.remediation_hint


@pytest.mark.parametrize(
    ("response", "summary", "detail"),
    [
        (
            "",
            "ML readiness response is empty",
            "ml-compute-service returned an empty readiness response",
        ),
        (
            "not-json",
            "ML readiness response is invalid JSON",
            "ml-compute-service returned invalid readiness data",
        ),
        (
            "[]",
            "ML readiness state is missing or invalid",
            "ml-compute-service readiness state is missing",
        ),
        (
            "{}",
            "ML readiness state is missing or invalid",
            "ml-compute-service readiness state is missing",
        ),
    ],
    ids=("empty", "malformed-json", "non-object", "missing-state"),
)
async def test_model_readiness_rejects_empty_malformed_non_object_and_missing_state(
    response: str, summary: str, detail: str
) -> None:
    result = await ModelReadinessCheck().execute(MockPlatform(_curl_result=(0, response, "")))

    assert result.status == CheckStatus.FAILED
    assert result.summary == summary
    assert result.details == (detail,)
    assert result.remediation_hint is not None


async def test_warming_model_state_fails_without_private_probe_content() -> None:
    result = await ModelReadinessCheck().execute(MockPlatform(_curl_result=(0, json.dumps({"state": "warming"}), "")))

    assert result.status == CheckStatus.FAILED
    assert result.summary == "ML readiness state is not ready"
    assert result.details == ("ml-compute-service reported a non-ready state",)
    assert "warming" not in result.summary
    assert all("warming" not in detail for detail in result.details)
    assert result.remediation_hint == "Inspect ml-compute model warm-up failures"


async def test_ready_model_passes() -> None:
    result = await ModelReadinessCheck().execute(MockPlatform(_curl_result=(0, json.dumps({"status": "ready"}), "")))

    assert result.status == CheckStatus.PASSED
    assert "state=ready" in result.summary
