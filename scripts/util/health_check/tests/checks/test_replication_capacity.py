"""Behavior tests for replication capacity and legacy-slot detection."""

from __future__ import annotations

from health_check.checks.cdc.replication_capacity import ReplicationCapacityCheck
from health_check.core.models import CheckStatus

from tests.conftest import MockPlatform


async def test_legacy_slot_proliferation_reports_counts_and_remediation() -> None:
    result = await ReplicationCapacityCheck().execute(MockPlatform(_psql_result=(0, "7|10|3|10|7", "")))

    assert result.status == CheckStatus.FAILED
    assert "legacy" in result.summary
    assert any("slots=7/10" in detail and "headroom=3" in detail for detail in result.details)
    assert any("nohiki_slots=7" in detail and "expected_at_most=" in detail for detail in result.details)
    assert result.remediation_hint is not None
    assert "Drop" in result.remediation_hint


async def test_exhausted_slot_and_sender_capacity_is_actionable() -> None:
    result = await ReplicationCapacityCheck().execute(MockPlatform(_psql_result=(0, "10|10|10|10|1", "")))

    assert result.status == CheckStatus.FAILED
    assert "max_replication_slots exhausted" in result.summary
    assert "max_wal_senders exhausted" in result.summary
    assert "slots=10/10 headroom=0" in result.details
    assert "wal_senders=10/10 headroom=0" in result.details


async def test_replication_capacity_with_headroom_passes_with_evidence() -> None:
    result = await ReplicationCapacityCheck().execute(MockPlatform(_psql_result=(0, "2|10|2|10|1", "")))

    assert result.status == CheckStatus.PASSED
    assert "headroom" in result.summary
    assert "slots=2/10 headroom=8" in result.details
    assert "wal_senders=2/10 headroom=8" in result.details
