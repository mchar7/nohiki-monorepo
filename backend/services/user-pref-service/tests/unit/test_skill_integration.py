"""Unit tests for skill_integration module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from user_pref_service.core.embedding import PrefEmbeddingState
from user_pref_service.services.skill_integration import request_skill_normalization


class TestRequestSkillNormalization:
    """Tests for request_skill_normalization function."""

    @pytest.mark.asyncio
    async def test_publishes_normalization_request(self) -> None:
        """Publishes SkillNormalizationRequested with CommandHeader caller_context."""
        profile_id = uuid4()

        with patch("user_pref_service.services.skill_integration.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()

            result = await request_skill_normalization(
                canonical_skill_ids=["2c17f3a0-6240-4f53-9d0d-6284cf7e47b7", "6da17a56-5d95-4c0e-b1fd-eb32ba648b41"],
                profile_id=profile_id,
                correlation_id="corr-1",
            )

            assert isinstance(result, str)
            mock_kafka.publish.assert_awaited_once()
            published_msg = mock_kafka.publish.call_args.args[1]
            assert list(published_msg.canonical_skill_ids) == [
                "2c17f3a0-6240-4f53-9d0d-6284cf7e47b7",
                "6da17a56-5d95-4c0e-b1fd-eb32ba648b41",
            ]
            assert list(published_msg.raw_skills) == []

    @pytest.mark.asyncio
    async def test_caller_context_carries_pref_id_and_action(self) -> None:
        """CommandHeader.caller_context carries PrefEmbeddingState with pref_id and action."""
        profile_id = uuid4()

        with patch("user_pref_service.services.skill_integration.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()

            await request_skill_normalization(
                canonical_skill_ids=["2c17f3a0-6240-4f53-9d0d-6284cf7e47b7"],
                profile_id=profile_id,
                correlation_id="corr-1",
                action="update",
            )

            published_msg = mock_kafka.publish.call_args.args[1]
            state = PrefEmbeddingState.from_bytes(published_msg.command.caller_context)
            assert state.pref_id == str(profile_id)
            assert state.action == "update"

    @pytest.mark.asyncio
    async def test_default_action_is_create(self) -> None:
        """Default action in caller_context is 'create'."""
        with patch("user_pref_service.services.skill_integration.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()

            await request_skill_normalization(
                canonical_skill_ids=["2c17f3a0-6240-4f53-9d0d-6284cf7e47b7"],
                profile_id=uuid4(),
                correlation_id="corr-1",
            )

            published_msg = mock_kafka.publish.call_args.args[1]
            state = PrefEmbeddingState.from_bytes(published_msg.command.caller_context)
            assert state.action == "create"

    @pytest.mark.asyncio
    async def test_callback_topic_is_user_pref_skill_callback(self) -> None:
        """CommandHeader.callback_topic is USER_PREF_SKILL_CALLBACK."""
        from nohiki_kafka_client import Topics

        with patch("user_pref_service.services.skill_integration.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()

            await request_skill_normalization(
                canonical_skill_ids=["2c17f3a0-6240-4f53-9d0d-6284cf7e47b7"],
                profile_id=uuid4(),
                correlation_id="corr-1",
            )

            published_msg = mock_kafka.publish.call_args.args[1]
            assert published_msg.command.callback_topic == Topics.USER_PREF_SKILL_CALLBACK

    @pytest.mark.asyncio
    async def test_returns_operation_id_string(self) -> None:
        """Returns a non-empty operation_id string."""
        with patch("user_pref_service.services.skill_integration.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()

            result = await request_skill_normalization(
                canonical_skill_ids=["2c17f3a0-6240-4f53-9d0d-6284cf7e47b7"],
                profile_id=uuid4(),
                correlation_id="corr-2",
            )

            assert isinstance(result, str)
            assert result
