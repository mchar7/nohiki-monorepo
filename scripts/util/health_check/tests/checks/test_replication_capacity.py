"""Behavior tests for replication capacity and unexpected-slot detection."""

from __future__ import annotations

import pytest
from health_check.checks.cdc.replication_capacity import ReplicationCapacityCheck
from health_check.core.models import CheckStatus
from health_check.platform.models import PlatformTarget

from .._helpers import MockPlatform


async def test_superseded_slot_reports_counts_and_bounded_remediation() -> None:
    result = await ReplicationCapacityCheck().execute(
        MockPlatform(_psql_result=(0, "13|16|12|16|nohiki_outbox_slot_user_auth", ""))
    )

    assert result.status == CheckStatus.FAILED
    assert "unexpected" in result.summary
    assert any("slots=13/16" in detail and "headroom=3" in detail for detail in result.details)
    assert "canonical_slots=12/12 unexpected=1" in result.details
    assert result.remediation_hint is not None
    assert "just connect-reconcile-compose-cdc" in result.remediation_hint


async def test_exhausted_slot_and_sender_capacity_is_actionable() -> None:
    result = await ReplicationCapacityCheck().execute(MockPlatform(_psql_result=(0, "16|16|16|16|", "")))

    assert result.status == CheckStatus.FAILED
    assert "max_replication_slots exhausted" in result.summary
    assert "max_wal_senders exhausted" in result.summary
    assert "slots=16/16 headroom=0" in result.details
    assert "wal_senders=16/16 headroom=0" in result.details


async def test_unknown_slot_requires_manual_remediation() -> None:
    result = await ReplicationCapacityCheck().execute(
        MockPlatform(_psql_result=(0, "13|16|12|16|third_party_slot", ""))
    )

    assert result.status == CheckStatus.FAILED
    assert result.remediation_hint is not None
    assert "manually" in result.remediation_hint
    assert "just connect-reconcile-compose-cdc" not in result.remediation_hint


@pytest.mark.parametrize(
    ("target", "expected"),
    [(PlatformTarget.COMPOSE, 12), (PlatformTarget.KUBERNETES, 12)],
)
async def test_replication_capacity_with_headroom_passes_with_evidence(target: PlatformTarget, expected: int) -> None:
    response = f"{expected}|16|{expected}|16|"
    result = await ReplicationCapacityCheck().execute(MockPlatform(target=target, _psql_result=(0, response, "")))

    assert result.status == CheckStatus.PASSED
    assert "headroom" in result.summary
    assert f"slots={expected}/16 headroom={16 - expected}" in result.details
    assert f"canonical_slots={expected}/{expected} unexpected=0" in result.details
