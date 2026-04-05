"""Integration tests for KafkaConsumer using testcontainers.

These tests verify DLQ routing, retry behavior, crash recovery, and concurrent
processing using a real Kafka broker via testcontainers.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from typing import Any

import betterproto2
import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, ConsumerRecord
from nohiki_kafka_client.config import (
    ConsumerConfig,
    GlobalDLQConfig,
    KafkaClientConfig,
)
from nohiki_kafka_client.config.client_config import DLQStrategy
from nohiki_kafka_client.consumer.consumer import KafkaConsumer
from nohiki_kafka_client.dlq import DLQHandler
from nohiki_kafka_client.handlers import HandlerRegistration, MessageContext
from nohiki_kafka_client.observability.metrics import get_kafka_metrics
from nohiki_kafka_client.producer import KafkaProducer
from nohiki_kafka_client.testing import get_test_consumer_kwargs, get_test_producer_kwargs

pytestmark = pytest.mark.requires_docker

# Exception messages for test handlers (extracted to satisfy EM101/TRY003)
_FORCE_DLQ_MSG = "force dlq"
_TRANSIENT_ERROR_MSG = "transient error should retry"


@dataclass
class MockMessage(betterproto2.Message):
    """Sample betterproto2 message for integration tests."""

    value: str = ""

    def __bytes__(self) -> bytes:
        """Serialize to bytes."""
        return self.value.encode("utf-8")

    @classmethod
    def parse(cls, data: bytes) -> MockMessage:
        """Parse from bytes."""
        return cls(value=data.decode("utf-8"))


async def _produce_raw_message(
    kafka_container: str,
    topic: str,
    value: bytes,
    key: bytes | None = None,
    headers: list[tuple[str, bytes]] | None = None,
) -> None:
    """Produce a raw message to a topic."""
    producer_kwargs = get_test_producer_kwargs(kafka_container)
    producer = AIOKafkaProducer(**producer_kwargs)
    await producer.start()
    try:
        await producer.send_and_wait(topic, value=value, key=key, headers=headers or [])
    finally:
        await producer.stop()


async def _consume_all_from_topic(
    kafka_container: str,
    topic: str,
    group_id: str,
    max_messages: int,
    timeout_seconds: float = 10.0,
) -> list[ConsumerRecord]:
    """Consume all messages from a topic up to max_messages."""
    consumer_kwargs = get_test_consumer_kwargs(kafka_container, group_id)
    consumer = AIOKafkaConsumer(topic, **consumer_kwargs)
    messages: list[ConsumerRecord] = []
    await consumer.start()
    try:
        start = time.time()
        while len(messages) < max_messages and (time.time() - start) < timeout_seconds:
            msg = await asyncio.wait_for(consumer.getone(), timeout=1.0)
            messages.append(msg)
    except TimeoutError:
        pass
    finally:
        await consumer.stop()
    return messages


class TestConsumerDlqRoutingE2E:
    """Test A: DLQ routing end-to-end."""

    async def _setup_topics(self, kafka_container: str, source_topic: str, dlq_topic: str) -> KafkaClientConfig:
        """Create topics and return base config."""
        from nohiki_kafka_client.admin import KafkaAdmin, TopicSpec

        config = KafkaClientConfig(bootstrap_servers=kafka_container)
        async with KafkaAdmin(config) as admin:
            await admin.create_topics([TopicSpec(name=source_topic, num_partitions=1)])
            await admin.create_topics([TopicSpec(name=dlq_topic, num_partitions=1)])
        return config

    def _build_dlq_config(self) -> GlobalDLQConfig:
        """Build DLQ config with max_retries=0 for direct DLQ routing."""
        return GlobalDLQConfig(
            strategy=DLQStrategy.REPUBLISH,
            max_retries=0,
            topic_prefix="dlq",
        )

    @pytest.mark.asyncio
    async def test_consumer_dlq_routing_e2e(self, kafka_container: str) -> None:
        """Handler raising ValueError routes message to DLQ topic (REPUBLISH strategy)."""
        source_topic = "test.dlq.source.v1"
        consumer_group = "test-dlq-group"
        dlq_topic = f"dlq.{source_topic}"

        await self._setup_topics(kafka_container, source_topic, dlq_topic)

        dlq_config = self._build_dlq_config()
        config = KafkaClientConfig(
            bootstrap_servers=kafka_container,
            consumer=ConsumerConfig(
                group_id=consumer_group,
                enable_auto_commit=False,
                max_concurrent_handlers=1,
            ),
            dlq=dlq_config,
        )

        producer = KafkaProducer(config)
        await producer.__aenter__()

        try:
            metrics = get_kafka_metrics()
            dlq_handler = DLQHandler(
                config=dlq_config,
                metrics=metrics,
                consumer_group=consumer_group,
            )
            dlq_handler.set_producer(producer)

            # Produce 1 raw message to source_topic
            test_value = b"force-dlq-message"
            await _produce_raw_message(kafka_container, source_topic, test_value)

            # Define failing handler that raises ValueError
            async def failing_handler(_message: MockMessage, _context: MessageContext) -> None:
                raise ValueError(_FORCE_DLQ_MSG)

            registration = HandlerRegistration(
                topic=source_topic,
                message_type=MockMessage,
                handler_func=failing_handler,
                group_id=consumer_group,
                preserve_partition_order=True,
            )

            consumer = KafkaConsumer(config, dlq_handler, group_id=consumer_group)
            await consumer.__aenter__()
            handler_map = {source_topic: registration}

            async def run_consumer() -> None:
                try:
                    await consumer.consume_multi([source_topic], handler_map, producer)
                finally:
                    await consumer.__aexit__(None, None, None)

            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(run_consumer(), timeout=15.0)

            # Wait for DLQ republishing
            await asyncio.sleep(0.5)

            # Read from dlq.{source_topic}
            dlq_messages = await _consume_all_from_topic(
                kafka_container,
                dlq_topic,
                "dlq-verify-group",
                max_messages=1,
                timeout_seconds=5.0,
            )

            # Assert: DLQ has exactly 1 message
            assert len(dlq_messages) == 1

            msg = dlq_messages[0]
            headers_dict = {k: v.decode("utf-8") if isinstance(v, bytes) else v for k, v in (msg.headers or [])}

            # Assert headers
            assert headers_dict.get("dlq-source-topic") == source_topic
            assert headers_dict.get("dlq-error-type") == "ValueError"
            assert headers_dict.get("dlq-retry-count") == "0"

        finally:
            await producer.__aexit__(None, None, None)


class TestConsumerRetryTopicE2E:
    """Test B: Retry topic end-to-end."""

    async def _setup_retry_test(
        self, kafka_container: str, source_topic: str, retry_topic: str
    ) -> tuple[KafkaClientConfig, GlobalDLQConfig]:
        """Setup topics and config for retry test."""
        from nohiki_kafka_client.admin import KafkaAdmin, TopicSpec

        config = KafkaClientConfig(bootstrap_servers=kafka_container)
        async with KafkaAdmin(config) as admin:
            await admin.create_topics([TopicSpec(name=source_topic, num_partitions=1)])
            await admin.create_topics([TopicSpec(name=retry_topic, num_partitions=1)])

        dlq_config = GlobalDLQConfig(
            strategy=DLQStrategy.REPUBLISH,
            max_retries=1,
            retry_backoff_ms=1,
        )
        return config, dlq_config

    @pytest.mark.asyncio
    async def test_consumer_retry_topic_e2e(self, kafka_container: str) -> None:
        """Transient error routes to retry topic with correct headers.

        This test verifies that:
        1. A transient error (OSError) triggers retry publishing
        2. The message is published to the retry topic with correct headers
        3. The retry headers contain x-original-topic, x-retry-count, etc.
        """
        source_topic = "test.retry.source.v1"
        consumer_group = "test-retry-group"
        retry_topic = f"{consumer_group}.retry"

        base_config, dlq_config = await self._setup_retry_test(kafka_container, source_topic, retry_topic)

        config = KafkaClientConfig(
            bootstrap_servers=base_config.bootstrap_servers,
            consumer=ConsumerConfig(
                group_id=consumer_group,
                enable_auto_commit=False,
                max_concurrent_handlers=1,
            ),
            dlq=dlq_config,
        )

        producer = KafkaProducer(config)
        await producer.__aenter__()

        try:
            metrics = get_kafka_metrics()
            dlq_handler = DLQHandler(
                config=dlq_config,
                metrics=metrics,
                consumer_group=consumer_group,
            )
            dlq_handler.set_producer(producer)

            await _produce_raw_message(kafka_container, source_topic, b"retry-test-message")

            handler_called = asyncio.Event()

            async def retry_handler(_message: MockMessage, _context: MessageContext) -> None:
                handler_called.set()
                raise OSError(_TRANSIENT_ERROR_MSG)

            registration = HandlerRegistration(
                topic=source_topic,
                message_type=MockMessage,
                handler_func=retry_handler,
                group_id=consumer_group,
                preserve_partition_order=True,
            )

            handler_map = {source_topic: registration}

            main_consumer = KafkaConsumer(config, dlq_handler, group_id=consumer_group)
            await main_consumer.__aenter__()

            async def run_main() -> None:
                try:
                    await main_consumer.consume_multi([source_topic], handler_map, producer)
                finally:
                    await main_consumer.__aexit__(None, None, None)

            main_task = asyncio.create_task(run_main())

            # Wait for handler to be called and message to be published to retry topic
            await asyncio.wait_for(handler_called.wait(), timeout=10.0)
            await asyncio.sleep(0.5)  # Allow retry publish to complete

            main_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await main_task

            # Verify message was published to retry topic with correct headers
            from aiokafka import AIOKafkaConsumer as RawConsumer

            raw_consumer = RawConsumer(
                retry_topic,
                bootstrap_servers=kafka_container,
                auto_offset_reset="earliest",
                consumer_timeout_ms=5000,
            )
            await raw_consumer.start()

            try:
                record = await asyncio.wait_for(
                    raw_consumer.getone(),
                    timeout=10.0,
                )

                headers = {k: v.decode() for k, v in record.headers}
                assert headers.get("x-original-topic") == source_topic
                assert headers.get("x-retry-count") == "1"
                assert "x-next-retry-at" in headers
                assert headers.get("x-error-type") == "OSError"
            finally:
                await raw_consumer.stop()

        finally:
            await producer.__aexit__(None, None, None)


class TestConsumerCrashRecovery:
    """Test C: Crash recovery with offset commit."""

    async def _setup_crash_test(
        self, kafka_container: str, topic: str
    ) -> tuple[KafkaClientConfig, GlobalDLQConfig, KafkaProducer]:
        """Setup topic, config, and producer for crash recovery test."""
        from nohiki_kafka_client.admin import KafkaAdmin, TopicSpec

        base_config = KafkaClientConfig(bootstrap_servers=kafka_container)
        async with KafkaAdmin(base_config) as admin:
            await admin.create_topics([TopicSpec(name=topic, num_partitions=1)])

        dlq_config = GlobalDLQConfig(strategy=DLQStrategy.REPUBLISH, max_retries=0)
        config = KafkaClientConfig(
            bootstrap_servers=kafka_container,
            consumer=ConsumerConfig(
                group_id="test-crash-group",
                enable_auto_commit=False,
                periodic_commit_interval_seconds=0.1,
                max_concurrent_handlers=1,
            ),
            dlq=dlq_config,
        )
        producer = KafkaProducer(config)
        await producer.__aenter__()
        return config, dlq_config, producer

    def _build_handler_map(
        self,
        topic: str,
        handler: Any,  # noqa: ANN401 - test handler type is intentionally flexible
        group_id: str,
        *,
        preserve_order: bool = True,
    ) -> dict[str, HandlerRegistration]:
        """Build handler map for consume_multi."""
        return {
            topic: HandlerRegistration(
                topic=topic,
                message_type=MockMessage,
                handler_func=handler,
                group_id=group_id,
                preserve_partition_order=preserve_order,
            )
        }

    async def _run_consumer_once(
        self,
        config: KafkaClientConfig,
        dlq_handler: DLQHandler,
        handler_map: dict[str, HandlerRegistration],
        producer: KafkaProducer,
        event: asyncio.Event,
        wait_timeout: float = 10.0,
    ) -> None:
        """Run consumer until event is set or timeout."""
        consumer = KafkaConsumer(config, dlq_handler, group_id=config.consumer.group_id)
        await consumer.__aenter__()
        topic = next(iter(handler_map.keys()))

        async def run() -> None:
            try:
                await consumer.consume_multi([topic], handler_map, producer)
            finally:
                await consumer.__aexit__(None, None, None)

        task = asyncio.create_task(run())
        try:
            await asyncio.wait_for(event.wait(), timeout=wait_timeout)
        except TimeoutError:
            task.cancel()
            raise
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_consumer_crash_recovery(self, kafka_container: str) -> None:
        """After cancellation, restarted consumer picks up from committed offsets."""
        source_topic = "test.crash.topic.v1"
        consumer_group = "test-crash-group"

        config, dlq_config, producer = await self._setup_crash_test(kafka_container, source_topic)
        config.consumer.group_id = consumer_group

        try:
            metrics = get_kafka_metrics()
            dlq_handler = DLQHandler(config=dlq_config, metrics=metrics, consumer_group=consumer_group)
            dlq_handler.set_producer(producer)

            # Produce 5 messages and consume with first consumer
            for i in range(5):
                await _produce_raw_message(kafka_container, source_topic, f"msg-{i}".encode())

            first_received: list[str] = []
            first_event = asyncio.Event()

            async def first_handler(msg: MockMessage, _ctx: MessageContext) -> None:
                first_received.append(msg.value)
                if len(first_received) == 5:
                    first_event.set()

            handler_map1 = self._build_handler_map(source_topic, first_handler, consumer_group)
            await self._run_consumer_once(config, dlq_handler, handler_map1, producer, first_event)
            await asyncio.sleep(0.5)  # Let commit happen

            assert len(first_received) == 5

            # Produce 2 more messages
            for i in range(5, 7):
                await _produce_raw_message(kafka_container, source_topic, f"msg-{i}".encode())

            # Second consumer should only see the 2 new messages
            second_received: list[str] = []
            second_event = asyncio.Event()

            async def second_handler(msg: MockMessage, _ctx: MessageContext) -> None:
                second_received.append(msg.value)
                if len(second_received) == 2:
                    second_event.set()

            dlq_handler2 = DLQHandler(config=dlq_config, metrics=metrics, consumer_group=consumer_group)
            dlq_handler2.set_producer(producer)
            handler_map2 = self._build_handler_map(source_topic, second_handler, consumer_group)
            await self._run_consumer_once(config, dlq_handler2, handler_map2, producer, second_event)

            assert len(second_received) == 2

        finally:
            await producer.__aexit__(None, None, None)


class TestConsumerConcurrentProcessing:
    """Test D: Concurrent processing with max_concurrent_handlers > 1."""

    async def _setup_concurrent_test(
        self, kafka_container: str, topic: str, group_id: str
    ) -> tuple[KafkaClientConfig, GlobalDLQConfig, KafkaProducer, DLQHandler]:
        """Setup topic, config, producer, and DLQ handler for concurrent test."""
        from nohiki_kafka_client.admin import KafkaAdmin, TopicSpec

        base_config = KafkaClientConfig(bootstrap_servers=kafka_container)
        async with KafkaAdmin(base_config) as admin:
            await admin.create_topics([TopicSpec(name=topic, num_partitions=1)])

        dlq_config = GlobalDLQConfig(strategy=DLQStrategy.REPUBLISH, max_retries=0)
        config = KafkaClientConfig(
            bootstrap_servers=kafka_container,
            consumer=ConsumerConfig(
                group_id=group_id,
                enable_auto_commit=False,
                max_concurrent_handlers=5,
            ),
            dlq=dlq_config,
        )

        producer = KafkaProducer(config)
        await producer.__aenter__()

        metrics = get_kafka_metrics()
        dlq_handler = DLQHandler(config=dlq_config, metrics=metrics, consumer_group=group_id)
        dlq_handler.set_producer(producer)

        return config, dlq_config, producer, dlq_handler

    @pytest.mark.asyncio
    async def test_consumer_concurrent_processing(self, kafka_container: str) -> None:
        """max_concurrent_handlers > 1 provides concurrent processing."""
        source_topic = "test.concurrent.topic.v1"
        consumer_group = "test-concurrent-group"

        config, _dlq_config, producer, dlq_handler = await self._setup_concurrent_test(
            kafka_container, source_topic, consumer_group
        )

        try:
            # Produce 5 messages with same key (same partition)
            for i in range(5):
                await _produce_raw_message(kafka_container, source_topic, f"concurrent-{i}".encode(), key=b"same-key")

            processed_count = 0
            processed_event = asyncio.Event()
            processing_times: list[float] = []
            handler_lock = asyncio.Lock()

            async def slow_handler(_msg: MockMessage, _ctx: MessageContext) -> None:
                nonlocal processed_count
                start = time.perf_counter()
                await asyncio.sleep(0.2)
                elapsed = time.perf_counter() - start

                async with handler_lock:
                    processing_times.append(elapsed)
                    processed_count += 1
                    if processed_count == 5:
                        processed_event.set()

            handler_map = {
                source_topic: HandlerRegistration(
                    topic=source_topic,
                    message_type=MockMessage,
                    handler_func=slow_handler,
                    group_id=consumer_group,
                    preserve_partition_order=False,
                )
            }

            consumer = KafkaConsumer(config, dlq_handler, group_id=consumer_group)
            await consumer.__aenter__()

            async def run_consumer() -> None:
                try:
                    await consumer.consume_multi([source_topic], handler_map, producer)
                finally:
                    await consumer.__aexit__(None, None, None)

            start_time = time.perf_counter()
            consumer_task = asyncio.create_task(run_consumer())

            try:
                await asyncio.wait_for(processed_event.wait(), timeout=10.0)
            except TimeoutError:
                consumer_task.cancel()
                pytest.fail("Consumer timeout")
            finally:
                consumer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await consumer_task

            elapsed_total = time.perf_counter() - start_time

            # Assert: elapsed < 5 x 0.2 x 0.7 = 0.7s (concurrent vs sequential)
            assert elapsed_total < 0.7
            assert processed_count == 5

        finally:
            await producer.__aexit__(None, None, None)
