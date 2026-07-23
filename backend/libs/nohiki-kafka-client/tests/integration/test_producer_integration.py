"""Integration tests for Kafka using testcontainers.

All tests use aiokafka via nohiki-kafka-client's testing helpers.
"""

from __future__ import annotations

from dataclasses import dataclass

import betterproto2
import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from nohiki_kafka_client.admin import KafkaAdmin, TopicSpec
from nohiki_kafka_client.config import KafkaClientConfig
from nohiki_kafka_client.observability.health import KafkaCapability, KafkaHealthProbe
from nohiki_kafka_client.testing import get_test_consumer_kwargs, get_test_producer_kwargs

pytestmark = [pytest.mark.requires_docker, pytest.mark.integration]


@dataclass
class SampleMessage(betterproto2.Message):
    """Sample betterproto2 message for integration tests."""

    value: str = ""

    def __bytes__(self) -> bytes:
        """Serialize to bytes."""
        return self.value.encode("utf-8")


class TestKafkaHealthProbeIntegration:
    """Integration tests for KafkaHealthProbe with real Kafka."""

    @pytest.mark.asyncio
    async def test_broker_connectivity_healthy(self, kafka_container: str) -> None:
        """Health probe returns healthy when broker is available."""
        probe = KafkaHealthProbe(
            kafka_container,
            capabilities={KafkaCapability.BROKER_CONNECTIVITY},
            timeout_seconds=10.0,
        )
        result = await probe.check()
        assert result.is_healthy()
        assert result.name == "kafka"
        assert result.details is not None
        assert "capabilities" in result.details
        assert result.details["capabilities"]["broker_connectivity"] is True

    @pytest.mark.asyncio
    async def test_broker_connectivity_unhealthy(self) -> None:
        """Health probe returns unhealthy when broker unavailable."""
        probe = KafkaHealthProbe(
            "invalid-host:9092",
            capabilities={KafkaCapability.BROKER_CONNECTIVITY},
            timeout_seconds=2.0,
        )
        result = await probe.check()
        assert result.status.value == "unhealthy"


class TestKafkaAdminIntegration:
    """Integration tests for KafkaAdmin wrapper."""

    @pytest.mark.asyncio
    async def test_create_topic(self, kafka_container: str) -> None:
        """KafkaAdmin can create topics."""
        config = KafkaClientConfig(bootstrap_servers=kafka_container)
        async with KafkaAdmin(config) as admin:
            spec = TopicSpec(name="test-admin-topic", num_partitions=1)
            created = await admin.create_topics([spec])
            assert "test-admin-topic" in created

    @pytest.mark.asyncio
    async def test_list_topics(self, kafka_container: str) -> None:
        """KafkaAdmin can list topics."""
        config = KafkaClientConfig(bootstrap_servers=kafka_container)
        async with KafkaAdmin(config) as admin:
            topics = await admin.list_topics()
            assert isinstance(topics, tuple)

    @pytest.mark.asyncio
    async def test_ensure_topics_exist(self, kafka_container: str) -> None:
        """KafkaAdmin.ensure_topics_exist is idempotent."""
        config = KafkaClientConfig(bootstrap_servers=kafka_container)
        specs = [
            TopicSpec(name="test-ensure-a", num_partitions=1),
            TopicSpec(name="test-ensure-b", num_partitions=2),
        ]
        async with KafkaAdmin(config) as admin:
            result = await admin.ensure_topics_exist(specs)
            assert len(result.created) == 2

            result2 = await admin.ensure_topics_exist(specs)
            assert len(result2.existing) == 2
            assert len(result2.created) == 0


@pytest.mark.e2e
class TestKafkaProducerConsumerIntegration:
    """Integration tests for aiokafka producer/consumer roundtrip."""

    @pytest.mark.asyncio
    async def test_produce_consume_roundtrip(self, kafka_container: str) -> None:
        """Message produced can be consumed."""
        topic = "test-roundtrip"
        test_value = b"hello-kafka"
        test_key = b"test-key"

        producer_kwargs = get_test_producer_kwargs(kafka_container)
        producer = AIOKafkaProducer(**producer_kwargs)
        await producer.start()
        try:
            await producer.send_and_wait(topic, value=test_value, key=test_key)
        finally:
            await producer.stop()

        consumer_kwargs = get_test_consumer_kwargs(kafka_container, "roundtrip-group")
        consumer = AIOKafkaConsumer(topic, **consumer_kwargs)
        await consumer.start()
        try:
            msg = await consumer.getone()
        finally:
            await consumer.stop()

        assert msg is not None
        assert msg.value == test_value
        assert msg.key == test_key

    @pytest.mark.asyncio
    async def test_produce_with_headers(self, kafka_container: str) -> None:
        """Message with headers can be produced and consumed."""
        topic = "test-headers"
        headers = [("header-key", b"header-value")]

        producer_kwargs = get_test_producer_kwargs(kafka_container)
        producer = AIOKafkaProducer(**producer_kwargs)
        await producer.start()
        try:
            await producer.send_and_wait(
                topic,
                value=b"msg",
                key=b"key",
                headers=headers,
            )
        finally:
            await producer.stop()

        consumer_kwargs = get_test_consumer_kwargs(kafka_container, "headers-group")
        consumer = AIOKafkaConsumer(topic, **consumer_kwargs)
        await consumer.start()
        try:
            msg = await consumer.getone()
        finally:
            await consumer.stop()

        assert msg is not None
        assert msg.headers is not None
        assert ("header-key", b"header-value") in msg.headers
