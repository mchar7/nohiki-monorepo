"""Tests for the request-correlated preference enrichment failure fact."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from nohiki.user.pref.v1 import PrefEnrichmentFailedFailureReason
from nohiki_kafka_client import Topics
from user_pref_service.events.publishers import publish_pref_enrichment_failed


@pytest.mark.asyncio
async def test_failure_fact_carries_request_and_saga_identity() -> None:
    saga = MagicMock(
        id=uuid4(),
        pref_id=uuid4(),
        user_id=uuid4(),
        request_id=uuid4(),
        correlation_id="corr-1",
    )
    outbox = MagicMock(write_event=AsyncMock())
    db = MagicMock()

    await publish_pref_enrichment_failed(
        db,
        outbox,
        saga,
        reason=PrefEnrichmentFailedFailureReason.EMBEDDING_FAILED,
        error_message="permanent failure",
    )

    kwargs = outbox.write_event.await_args.kwargs
    assert kwargs["params"].event_type == Topics.USER_PREF_ENRICHMENT_FAILED
    assert kwargs["event"].request_id == str(saga.request_id)
    assert kwargs["event"].saga_id == str(saga.id)
    assert kwargs["event"].user_id == str(saga.user_id)
    assert kwargs["event"].reason == PrefEnrichmentFailedFailureReason.EMBEDDING_FAILED
