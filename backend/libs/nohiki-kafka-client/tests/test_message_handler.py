"""Tests for message_handler decorator with required group_id."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import betterproto2
import pytest

if TYPE_CHECKING:
    from nohiki_kafka_client.handlers import MessageContext


@dataclass
class MockMessage(betterproto2.Message):
    """Mock betterproto2 message for testing."""

    value: str = ""


class TestMessageHandlerGroupIdRequired:
    """Test that message_handler requires explicit group_id."""

    def test_message_handler_requires_group_id_keyword(self) -> None:
        """Test that message_handler raises TypeError when group_id is missing."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(
                bootstrap_servers="kafka:29092",
            ),
            is_testing=True,
        )
        unsafe_client = cast("Any", client)

        # Attempting to use message_handler without group_id should raise TypeError
        with pytest.raises(TypeError, match="group_id"):

            @unsafe_client.message_handler("test.topic.v1", MockMessage)
            async def handler(message: MockMessage, context: MessageContext) -> None:
                assert message is not None
                assert context is not None

    def test_message_handler_accepts_explicit_group_id(self) -> None:
        """Test that message_handler works with explicit group_id."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(
                bootstrap_servers="kafka:29092",
            ),
            is_testing=True,
        )

        # Should work with explicit group_id
        @client.message_handler("test.topic.v1", MockMessage, group_id="test-service-primary")
        async def handler(message: MockMessage, context: MessageContext) -> None:
            pass

        # Verify handler was registered with correct group_id
        assert len(client._handlers) == 1
        handler_key = next(iter(client._handlers.keys()))
        assert "test-service-primary" in handler_key
        registration = client._handlers[handler_key]
        assert registration.group_id == "test-service-primary"

    def test_message_handler_group_id_must_be_keyword_only(self) -> None:
        """Test that group_id must be passed as keyword argument."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(
                bootstrap_servers="kafka:29092",
            ),
            is_testing=True,
        )

        # Attempting to pass group_id as positional should raise TypeError
        with pytest.raises(TypeError):

            @cast("Any", client).message_handler("test.topic.v1", MockMessage, "test-group")
            async def handler(message: MockMessage, context: MessageContext) -> None:
                assert message is not None
                assert context is not None


class TestConsumerGroupNamingConvention:
    """Test consumer group naming convention enforcement."""

    def test_valid_group_id_patterns(self) -> None:
        """Test that valid group_id patterns are accepted."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(
                bootstrap_servers="kafka:29092",
            ),
            is_testing=True,
        )

        valid_group_ids = [
            "job-store-primary",
            "job-matcher-cache",
            "notification-lifecycle",
            "doc-tailor-primary",
            "user-service-cache",
        ]

        for i, group_id in enumerate(valid_group_ids):

            @client.message_handler(f"test.topic.{i}.v1", MockMessage, group_id=group_id)
            async def handler(message: MockMessage, context: MessageContext) -> None:
                assert message is not None
                assert context is not None

        assert len(client._handlers) == len(valid_group_ids)

    def test_handlers_with_same_group_id_share_partition_assignment(self) -> None:
        """Test that handlers with same group_id are registered correctly."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(
                bootstrap_servers="kafka:29092",
            ),
            is_testing=True,
        )

        # Two handlers with same group_id (intentionally sharing partition assignment)
        @client.message_handler("topic.a.v1", MockMessage, group_id="service-primary")
        async def handler_a(message: MockMessage, context: MessageContext) -> None:
            assert message is not None
            assert context is not None

        @client.message_handler("topic.b.v1", MockMessage, group_id="service-primary")
        async def handler_b(message: MockMessage, context: MessageContext) -> None:
            assert message is not None
            assert context is not None

        # Both should be registered
        assert len(client._handlers) == 2

        # Both should have the same group_id
        for registration in client._handlers.values():
            assert registration.group_id == "service-primary"

    def test_handlers_with_different_group_ids_are_independent(self) -> None:
        """Test that handlers with different group_ids are independent."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(
                bootstrap_servers="kafka:29092",
            ),
            is_testing=True,
        )

        @client.message_handler("job.created.v1", MockMessage, group_id="service-primary")
        async def handler_primary(message: MockMessage, context: MessageContext) -> None:
            assert message is not None
            assert context is not None

        @client.message_handler("cache.invalidate.v1", MockMessage, group_id="service-cache")
        async def handler_cache(message: MockMessage, context: MessageContext) -> None:
            assert message is not None
            assert context is not None

        assert len(client._handlers) == 2

        group_ids = {reg.group_id for reg in client._handlers.values()}
        assert group_ids == {"service-primary", "service-cache"}
