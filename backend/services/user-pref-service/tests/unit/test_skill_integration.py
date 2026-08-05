"""Unit tests for skill normalization dispatch."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from nohiki_kafka_client import Topics
from user_pref_service.core.embedding import PrefEnrichmentSagaContext
from user_pref_service.services.skill_integration import request_skill_normalization


@pytest.mark.asyncio
async def test_publishes_operation_owned_by_durable_saga() -> None:
    profile_id = uuid4()
    saga_id = str(uuid4())
    with patch("user_pref_service.services.skill_integration.kafka_client") as mock_kafka:
        mock_kafka.publish = AsyncMock()
        operation_id = await request_skill_normalization(
            canonical_skill_ids=["2c17f3a0-6240-4f53-9d0d-6284cf7e47b7"],
            profile_id=profile_id,
            correlation_id="corr-1",
            saga_id=saga_id,
        )

    assert operation_id
    published = mock_kafka.publish.call_args.args[1]
    assert published.command.operation_id == operation_id
    assert published.command.callback_topic == Topics.USER_PREF_SKILL_CALLBACK
    assert list(published.canonical_skill_ids) == ["2c17f3a0-6240-4f53-9d0d-6284cf7e47b7"]
    assert PrefEnrichmentSagaContext.from_bytes(published.command.caller_context).saga_id == saga_id
