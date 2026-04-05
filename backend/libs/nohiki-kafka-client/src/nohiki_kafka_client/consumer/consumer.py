"""Async Kafka consumer using aiokafka.

Uses aiokafka's native async iterator (``async for record in consumer``)
for reactive, push-based message delivery.  aiokafka handles heartbeats,
rebalances, and prefetching in background tasks: no manual polling loop
is needed.  See https://aiokafka.readthedocs.io/en/stable/consumer.html
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

import betterproto2
from aiokafka import (
    AIOKafkaConsumer,
    ConsumerRebalanceListener,
    ConsumerRecord,
    TopicPartition,
)
from aiokafka.errors import KafkaError
from nohiki_observability import get_logger
from opentelemetry import trace

from nohiki_kafka_client.config import KafkaClientConfig, get_aiokafka_consumer_config
from nohiki_kafka_client.consumer.offset_tracker import PartitionOffsetTracker
from nohiki_kafka_client.dlq import DLQHandler
from nohiki_kafka_client.dlq.models import ConsumedMessage, ProcessingContext
from nohiki_kafka_client.exceptions import (
    ConsumerError,
    DLQPublishError,
    SerializationError,
)
from nohiki_kafka_client.handlers import (
    HandlerRegistration,
    KafkaPublisher,
    MessageContext,
    MessageHandlerFunc,
    ResilienceConfig,
)
from nohiki_kafka_client.observability.metrics import get_kafka_metrics
from nohiki_kafka_client.observability.tracing import extract_trace_context

if TYPE_CHECKING:
    import types

logger = get_logger(__name__)

DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS = 5.0
CONSUMER_NOT_INITIALIZED_MSG = "Consumer not initialized"
CONSUMER_LOOP_FAILED_MSG = "Consumer loop failed"


@dataclass(slots=True)
class HealthStatus:
    """Consumer health status."""

    healthy: bool
    details: dict[str, object]
    last_check: float


class KafkaConsumer:
    """Async Kafka consumer using aiokafka for non-blocking operations."""

    def __init__(
        self,
        config: KafkaClientConfig,
        dlq_handler: DLQHandler,
        group_id: str | None = None,
    ) -> None:
        """Initialize Kafka consumer.

        Args:
            config: Kafka client configuration.
            dlq_handler: Handler for dead-letter queue processing.
            group_id: Consumer group override; defaults to ``config.consumer.group_id``.

        """
        self._config = config
        self._group_id = group_id or config.consumer.group_id
        self._dlq_handler = dlq_handler
        self._metrics = get_kafka_metrics()
        self._consumer: AIOKafkaConsumer | None = None
        self._health_status = HealthStatus(healthy=False, details={}, last_check=0.0)
        self._shutdown_event = asyncio.Event()
        self._manual_commit = not config.consumer.enable_auto_commit
        self._tracer = trace.get_tracer(__name__)
        self._offset_tracker = PartitionOffsetTracker()
        self._message_count = 0
        self._semaphore = asyncio.Semaphore(config.consumer.max_concurrent_handlers)
        self._partition_locks: defaultdict[tuple[str, int], asyncio.Lock] = defaultdict(asyncio.Lock)
        self._inflight_tasks: set[asyncio.Task[None]] = set()
        self._generation_failure: asyncio.Future[BaseException] | None = None
        self._subscribed_topics: set[str] = set()

    async def __aenter__(self) -> Self:
        """Initialize consumer as async context manager.

        Returns:
            The initialized and connected consumer instance.

        """
        await self._initialize()
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: types.TracebackType | None,
    ) -> None:
        """Cleanup consumer resources."""
        await self._cleanup()

    def _on_partitions_assigned(self, assigned: set[TopicPartition]) -> None:
        """Handle partition assignment (no async work needed)."""
        logger.info(
            "Partitions assigned",
            partitions=[str(p) for p in assigned],
            count=len(assigned),
        )

    async def _on_partitions_revoked(self, revoked: set[TopicPartition]) -> None:
        """Handle partition revocation: commit tracked offsets and clear state.

        During rebalance, commits contiguous completed offsets for revoked
        partitions and clears the offset tracker so stale offsets from a
        previous assignment cannot cause incorrect commits.
        """
        if not revoked:
            return

        # Rebalance callbacks pause record delivery, so no new work can be
        # dispatched while the current assignment is being drained. Waiting
        # here prevents old-generation tasks from repopulating cleared state.
        if self._inflight_tasks:
            await asyncio.gather(*tuple(self._inflight_tasks), return_exceptions=True)
        if self._consumer and self._manual_commit and self._consumer.assignment():
            committable = await self._offset_tracker.get_committable_offsets()
            revoked_committable = {tp: off for tp, off in committable.items() if tp in revoked}
            if revoked_committable:
                try:
                    await self._consumer.commit(revoked_committable)
                    await self._offset_tracker.clear_committed(revoked_committable)
                except KafkaError as e:
                    logger.warning(
                        "Failed to commit on revoke",
                        error=str(e),
                        revoked_count=len(revoked),
                    )

        await self._offset_tracker.clear_partitions(revoked)
        logger.info(
            "Partitions revoked",
            partitions=[str(p) for p in revoked],
            count=len(revoked),
        )

    @staticmethod
    def _decode_headers(
        raw_headers: Sequence[tuple[str, bytes]] | None,
    ) -> dict[str, str]:
        """Decode raw Kafka headers to a string dict."""
        if not raw_headers:
            return {}
        return {k: v.decode("utf-8") if isinstance(v, bytes) else str(v) for k, v in raw_headers}

    @staticmethod
    def _decode_key(raw_key: bytes | None) -> str | None:
        """Decode raw Kafka key to a string."""
        return raw_key.decode("utf-8") if raw_key else None

    async def _initialize(self) -> None:
        """Initialize the AIOKafkaConsumer."""
        try:
            consumer_config = get_aiokafka_consumer_config(
                config=self._config,
                group_id=self._group_id,
            )

            self._consumer = AIOKafkaConsumer(**consumer_config)
            await self._consumer.start()

            self._health_status = HealthStatus(
                healthy=True,
                details={"initialized": True, "group_id": self._group_id},
                last_check=time.time(),
            )

            logger.info(
                "Kafka consumer initialized",
                group_id=self._group_id,
                max_concurrent=self._config.consumer.max_concurrent_handlers,
            )

        except KafkaError as e:
            msg = "Failed to initialize Kafka consumer"
            raise ConsumerError(msg, details={"error": str(e)}) from e

    async def _cleanup(self) -> None:
        """Cleanup consumer resources."""
        self._shutdown_event.set()

        if self._consumer:
            try:
                await self._consumer.stop()
                logger.info("Kafka consumer cleaned up")
            except KafkaError as e:
                logger.exception("Error during consumer cleanup", error=str(e))
            finally:
                self._consumer = None

    async def _consume_loop(
        self,
        topics: list[str],
        process_record: Callable[[ConsumerRecord], Awaitable[None]],
        *,
        preserve_partition_order: bool = True,
    ) -> None:
        """Subscribe and run one consumer generation until shutdown or failure."""
        consumer = self._consumer
        if consumer is None:
            raise ConsumerError(CONSUMER_NOT_INITIALIZED_MSG)

        periodic_commit_task: asyncio.Task[None] | None = None
        try:
            consumer.subscribe(
                topics,
                listener=_RebalanceListener(
                    on_assign=self._on_partitions_assigned,
                    on_revoke=self._on_partitions_revoked,
                ),
            )
            self._subscribed_topics = set(topics)
            logger.info("Subscribed to topics", topics=topics, group_id=self._group_id)
            periodic_commit_task = self._start_periodic_commit()
            await self._run_consume_generation(
                consumer,
                process_record,
                preserve_partition_order=preserve_partition_order,
            )
        except asyncio.CancelledError:
            await self._drain_cancelled_generation(topics)
            raise
        except KafkaError as error:
            logger.exception(CONSUMER_LOOP_FAILED_MSG, topics=topics, error=str(error))
            raise ConsumerError(
                CONSUMER_LOOP_FAILED_MSG,
                details={"topics": topics, "error": str(error)},
            ) from error
        finally:
            await self._finish_consume_loop(consumer, periodic_commit_task)

    def _start_periodic_commit(self) -> asyncio.Task[None] | None:
        """Start periodic commits when the consumer uses manual offsets."""
        if not self._manual_commit:
            return None
        return asyncio.create_task(
            self._periodic_commit_loop(),
            name=f"periodic-commit-{self._group_id}",
        )

    async def _run_consume_generation(
        self,
        consumer: AIOKafkaConsumer,
        process_record: Callable[[ConsumerRecord], Awaitable[None]],
        *,
        preserve_partition_order: bool,
    ) -> None:
        """Own polling and detached record failures for one generation."""
        failure = asyncio.get_running_loop().create_future()
        self._generation_failure = failure
        poll_task = asyncio.create_task(
            self._poll_records(
                consumer,
                process_record,
                preserve_partition_order=preserve_partition_order,
            ),
            name=f"consumer-poll-{self._group_id}",
        )
        try:
            done, _ = await asyncio.wait(
                (poll_task, failure),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if failure in done:
                poll_task.cancel()
                await asyncio.gather(poll_task, return_exceptions=True)
                await self._cancel_inflight()
                raise failure.result()
            await poll_task
            await self._drain_inflight()
            if failure.done():
                raise failure.result()
        finally:
            self._generation_failure = None
            if not failure.done():
                failure.cancel()
            if not poll_task.done():
                poll_task.cancel()
                await asyncio.gather(poll_task, return_exceptions=True)

    async def _poll_records(
        self,
        consumer: AIOKafkaConsumer,
        process_record: Callable[[ConsumerRecord], Awaitable[None]],
        *,
        preserve_partition_order: bool,
    ) -> None:
        """Poll records and dispatch them until this consumer is stopped."""
        async for record in consumer:
            if self._shutdown_event.is_set():
                return
            await self._dispatch_record(
                record,
                process_record,
                preserve_partition_order=preserve_partition_order,
            )

    async def _drain_cancelled_generation(self, topics: list[str]) -> None:
        """Drain in-flight work while the Kafka consumer is still open."""
        if (current_task := asyncio.current_task()) is not None:
            current_task.uncancel()
        logger.info("Consumer shutdown initiated, draining in-flight work", topics=topics)
        await self._drain_inflight()
        logger.info("Consumer drain complete", topics=topics)

    async def _finish_consume_loop(
        self,
        consumer: AIOKafkaConsumer,
        periodic_commit_task: asyncio.Task[None] | None,
    ) -> None:
        """Stop background commits and unsubscribe before consumer close."""
        if periodic_commit_task is not None and not periodic_commit_task.done():
            periodic_commit_task.cancel()
            with suppress(asyncio.CancelledError):
                await periodic_commit_task
        consumer.unsubscribe()

    async def consume[T: betterproto2.Message](
        self,
        topics: list[str],
        message_type: type[T],
        handler: MessageHandlerFunc[T],
    ) -> None:
        """Start consuming messages with automatic error handling.

        Args:
            topics: Kafka topics to subscribe to.
            message_type: Protobuf message class used for deserialization.
            handler: Async callback invoked for each successfully deserialized message.

        """

        async def _process(record: ConsumerRecord) -> None:
            await self._process_message(record, message_type, handler)

        await self._consume_loop(topics, _process, preserve_partition_order=True)

    async def consume_multi(
        self,
        topics: list[str],
        handler_map: Mapping[str, HandlerRegistration],
        kafka_client: KafkaPublisher,
    ) -> None:
        """Consume from multiple topics with different handlers per topic.

        Args:
            topics: Kafka topics to subscribe to.
            handler_map: Mapping of topic name to its handler registration.
            kafka_client: Publisher instance injected into each handler's processing context.

        """
        any_requires_order = any(r.preserve_partition_order for r in handler_map.values())

        async def _dispatch(record: ConsumerRecord) -> None:
            registration = handler_map.get(record.topic)
            if registration is None:
                logger.warning("No handler for topic", topic=record.topic)
                return

            start_time = time.perf_counter()
            try:
                message, context = self._deserialize_message(record, registration.message_type)
                context.kafka_client = kafka_client
                await self._execute_handler_with_tracing(
                    registration.handler_func,
                    message,
                    context,
                    registration.message_type,
                )
                self._record_processing_metrics(context, start_time, registration.message_type, success=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  # intentional: all non-cancelled errors route to DLQ/retry
                await self._handle_processing_error(record, registration, e, start_time)

        await self._consume_loop(topics, _dispatch, preserve_partition_order=any_requires_order)

    async def _dispatch_record(
        self,
        record: ConsumerRecord,
        process_record: Callable[[ConsumerRecord], Awaitable[None]],
        *,
        preserve_partition_order: bool,
    ) -> None:
        """Dispatch a single record as a bounded concurrent task.

        Registers the offset as in-flight, then spawns a background task
        that acquires the concurrency semaphore (and optionally a
        per-partition lock for ordering) before invoking the callback.

        Completed tasks are automatically reaped from ``_inflight_tasks``.

        Args:
            record: The Kafka record to process.
            process_record: Async callback for a single record.
            preserve_partition_order: If True, acquire a per-partition lock
                so records within the same partition run sequentially.

        """
        tp = TopicPartition(record.topic, record.partition)
        await self._offset_tracker.register_inflight(tp, record.offset)

        async def _run() -> None:
            if preserve_partition_order:
                partition_lock = self._partition_locks[(record.topic, record.partition)]
                async with partition_lock:
                    await self._bounded_process(record, process_record)
            else:
                await self._bounded_process(record, process_record)

        task = asyncio.create_task(_run())
        self._inflight_tasks.add(task)
        task.add_done_callback(self._record_task_finished)

    def _record_task_finished(self, task: asyncio.Task[None]) -> None:
        """Observe a record task and notify the owning consume generation."""
        self._inflight_tasks.discard(task)
        if task.cancelled() or (error := task.exception()) is None:
            return
        if self._generation_failure is not None and not self._generation_failure.done():
            self._generation_failure.set_result(error)

    async def _bounded_process(
        self,
        record: ConsumerRecord,
        process_record: Callable[[ConsumerRecord], Awaitable[None]],
    ) -> None:
        """Process one record and contain only classified delivery outcomes.

        The offset is marked completed on success or when the handler error is
        successfully routed to DLQ/retry. A ``DLQPublishError`` keeps the
        offset pending for redelivery. All other exceptions propagate to the
        owning consume generation.

        Args:
            record: The Kafka record to process.
            process_record: Async callback for a single record.

        """
        tp = TopicPartition(record.topic, record.partition)
        async with self._semaphore:
            try:
                await process_record(record)
            except asyncio.CancelledError:
                raise
            except DLQPublishError:
                # The source offset remains pending. Propagate so the supervisor
                # restarts the generation and Kafka redelivers it immediately.
                logger.exception(
                    "DLQ publish failed, offset not committed (will be redelivered)",
                    topic=record.topic,
                    partition=record.partition,
                    offset=record.offset,
                )
                raise
            await self._offset_tracker.mark_completed(tp, record.offset)

    async def _cancel_inflight(self) -> None:
        """Cancel and await every record task owned by this generation."""
        tasks = tuple(self._inflight_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight_tasks.clear()

    async def _drain_inflight(self) -> None:
        """Drain record tasks, cancelling siblings if one fails unexpectedly."""
        tasks = tuple(self._inflight_tasks)
        if tasks:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            failure: BaseException | None = None
            for task in done:
                if not task.cancelled() and (failure := task.exception()) is not None:
                    break
            if failure is not None:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self._inflight_tasks.clear()
                raise failure
            await asyncio.gather(*pending)
            self._inflight_tasks.clear()

        if self._manual_commit and self._consumer:
            committable = await self._offset_tracker.get_committable_offsets()
            if committable:
                try:
                    await self._consumer.commit(committable)
                    await self._offset_tracker.clear_committed(committable)
                except KafkaError as e:
                    logger.warning("Final commit during drain failed", error=str(e))

    async def _periodic_commit_loop(self) -> None:
        """Periodically commit tracked offsets to reduce re-delivery window.

        Runs as a background task alongside the async iterator loop.  For
        long-running handlers (LLM calls, ML inference), this ensures
        completed records' offsets are committed without waiting for the
        consumer to yield the next record.
        """
        interval = self._config.consumer.periodic_commit_interval_seconds
        while not self._shutdown_event.is_set():
            await asyncio.sleep(interval)
            if self._consumer and self._manual_commit:
                committable = await self._offset_tracker.get_committable_offsets()
                if committable:
                    try:
                        await self._consumer.commit(committable)
                        await self._offset_tracker.clear_committed(committable)
                    except KafkaError as e:
                        logger.warning(
                            "Periodic commit failed",
                            error=str(e),
                            group_id=self._group_id,
                        )

    def _deserialize_message[T: betterproto2.Message](
        self,
        record: ConsumerRecord,
        message_type: type[T],
    ) -> tuple[T, MessageContext]:
        """Deserialize Kafka message and build context."""
        if (raw_bytes := record.value) is None:
            msg = "Message value is None"
            raise SerializationError(msg)
        message = message_type().parse(raw_bytes)

        context = MessageContext(
            topic=record.topic,
            partition=record.partition,
            offset=record.offset,
            timestamp=record.timestamp or 0,
            headers=self._decode_headers(record.headers),
            key=self._decode_key(record.key),
        )

        return message, context

    async def _execute_handler_with_tracing[T: betterproto2.Message](
        self,
        handler: MessageHandlerFunc[T],
        message: T,
        context: MessageContext,
        message_type: type[T],
    ) -> None:
        """Execute message handler within OpenTelemetry span."""
        parent_context = extract_trace_context(context.headers)
        with self._tracer.start_as_current_span(
            f"{context.topic} process",
            context=parent_context,
            kind=trace.SpanKind.CONSUMER,
        ) as span:
            span.set_attribute("messaging.system", "kafka")
            span.set_attribute("messaging.source.name", context.topic)
            span.set_attribute("messaging.kafka.partition", context.partition)
            span.set_attribute("messaging.kafka.offset", context.offset)
            span.set_attribute("messaging.message.type", message_type.__name__)
            if self._group_id:
                span.set_attribute("messaging.kafka.consumer.group", self._group_id)
            await handler(message, context)

    def _record_processing_metrics[T: betterproto2.Message](
        self,
        context: MessageContext,
        start_time: float,
        message_type: type[T],
        *,
        success: bool,
    ) -> None:
        """Record per-message processing metrics (commits handled at batch level)."""
        if success:
            self._message_count += 1

        processing_time = time.perf_counter() - start_time
        self._metrics.record_message_consumed(
            topic=context.topic,
            consumer_group=self._group_id,
            duration_seconds=processing_time,
            success=success,
            handler=message_type.__name__,
        )

    async def _process_message[T: betterproto2.Message](
        self,
        record: ConsumerRecord,
        message_type: type[T],
        handler: MessageHandlerFunc[T],
    ) -> None:
        """Process a single Kafka message through the handler pipeline."""
        start_time = time.perf_counter()

        try:
            message, context = self._deserialize_message(record, message_type)
            await self._execute_handler_with_tracing(handler, message, context, message_type)
            self._record_processing_metrics(context, start_time, message_type, success=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001  # intentional: all non-cancelled errors route to DLQ/retry
            synthetic = HandlerRegistration(
                topic=record.topic,
                message_type=message_type,
                handler_func=handler,
                group_id=self._group_id,
            )
            await self._handle_processing_error(record, synthetic, e, start_time)

    def _build_consumed_message(self, record: ConsumerRecord) -> ConsumedMessage:
        """Build ConsumedMessage from raw Kafka record."""
        return ConsumedMessage(
            topic=record.topic,
            partition=record.partition,
            offset=record.offset,
            timestamp=record.timestamp or 0,
            headers=self._decode_headers(record.headers),
            key=self._decode_key(record.key),
            raw_value=record.value or b"",
        )

    async def _handle_dlq_failure(
        self,
        consumed_message: ConsumedMessage,
        error: Exception,
        processing_context: ProcessingContext,
        handler_resilience: ResilienceConfig | None = None,
    ) -> None:
        """Handle DLQ processing for failed messages.

        Raises:
            DLQPublishError: If DLQ/retry publish fails. Must propagate to
                prevent the offset from being committed (silent data loss).

        """
        try:
            dlq_result = await self._dlq_handler.handle_failure(
                consumed_message,
                error,
                processing_context,
                handler_resilience,
            )
        except DLQPublishError:
            raise  # Must propagate to prevent silent data loss
        except (OSError, ValueError, TypeError) as dlq_error:
            msg = "DLQ handling raised an exception"
            raise DLQPublishError(
                msg,
                details={
                    "topic": consumed_message.topic,
                    "original_error": str(error),
                    "dlq_error": str(dlq_error),
                },
            ) from dlq_error

        if not dlq_result.success:
            msg = "DLQ handling failed"
            raise DLQPublishError(
                msg,
                details={
                    "topic": consumed_message.topic,
                    "error": str(dlq_result.error or error),
                },
            )

    async def _handle_processing_error(
        self,
        record: ConsumerRecord,
        registration: HandlerRegistration,
        error: Exception,
        start_time: float,
    ) -> None:
        """Handle message processing errors."""
        consumed_message = self._build_consumed_message(record)
        handler = registration.handler_func

        processing_context = ProcessingContext(
            consumer_group=self._group_id,
            handler_name=getattr(handler, "__name__", handler.__class__.__name__),
            processing_start_time=start_time,
        )

        await self._handle_dlq_failure(
            consumed_message,
            error,
            processing_context,
            registration.resilience_config,
        )

        processing_time = time.perf_counter() - start_time
        self._metrics.record_message_consumed(
            topic=record.topic,
            consumer_group=self._group_id,
            duration_seconds=processing_time,
            success=False,
            handler=registration.message_type.__name__,
        )

    async def snapshot_end_offsets(self) -> dict[tuple[str, int], int] | None:
        """Snapshot end offsets for every partition in this consumer group subscription.

        Kafka group offsets are shared by all members, so readiness must not be
        limited to this process's assignment during autoscaling.
        """
        consumer = self._consumer
        if consumer is None:
            return None

        assignment = consumer.assignment()
        topics = self._subscribed_topics
        assignment_fallback = not topics
        if assignment_fallback:
            topics = {partition.topic for partition in assignment}
        if not topics:
            return None

        if assignment_fallback:
            partitions = set(assignment)
        else:
            partitions = set()
            for topic in topics:
                result = consumer.partitions_for_topic(topic)
                topic_partitions = await result if inspect.isawaitable(result) else result
                if topic_partitions is None:
                    return None
                partitions.update(TopicPartition(topic, partition) for partition in topic_partitions)

        end_offsets = await consumer.end_offsets(partitions)
        if assignment_fallback and consumer.assignment() != assignment:
            return None
        return {(partition.topic, partition.partition): end_offsets[partition] for partition in partitions}

    async def has_reached_offsets(self, snapshot: Mapping[tuple[str, int], int]) -> bool:
        """Return whether group-committed offsets reached a static snapshot."""
        consumer = self._consumer
        if consumer is None:
            return False

        if not self._subscribed_topics:
            assignment = {(partition.topic, partition.partition) for partition in consumer.assignment()}
            if not snapshot.keys() <= assignment:
                return False
        for (topic, partition), target in snapshot.items():
            try:
                result = consumer.committed(TopicPartition(topic, partition))
                committed = await result if inspect.isawaitable(result) else result
            except KafkaError:
                return False
            if committed is None:
                if target != 0:
                    return False
            elif committed < target:
                return False
        return True

    async def get_consumer_lag(self) -> dict[str, int]:
        """Get consumer lag per topic-partition.

        Lag is calculated as the difference between the latest broker
        offset and the last committed offset for each assigned partition.

        Returns:
            Mapping of ``topic:partition`` keys to lag values.

        """
        if not self._consumer:
            return {}

        lag: dict[str, int] = {}
        for tp in self._consumer.assignment():
            committed = await self._consumer.committed(tp)
            end_offsets = await self._consumer.end_offsets([tp])
            end_offset = end_offsets.get(tp)
            if committed is not None and end_offset is not None:
                lag[f"{tp.topic}:{tp.partition}"] = end_offset - committed
        return lag

    def health_check(self) -> HealthStatus:
        """Check consumer health for readiness probes.

        Returns:
            Current ``HealthStatus`` with partition assignment and message count details.

        """
        now = time.time()
        if not self._consumer:
            return HealthStatus(
                healthy=False,
                details={"error": "Consumer not initialized", "last_error_time": now},
                last_check=now,
            )

        try:
            if (assignment := self._consumer.assignment()) is not None:
                self._health_status = HealthStatus(
                    healthy=True,
                    details={
                        "assigned_partitions": len(assignment),
                        "group_id": self._group_id,
                        "messages_processed": self._message_count,
                        "inflight_tasks": len(self._inflight_tasks),
                        "last_successful_check": now,
                    },
                    last_check=now,
                )
        except KafkaError as e:
            self._health_status = HealthStatus(
                healthy=False,
                details={"error": str(e), "last_error_time": time.time()},
                last_check=time.time(),
            )
        return self._health_status

    def stop(self) -> None:
        """Stop the consumer gracefully."""
        self._shutdown_event.set()


SyncPartitionCallback = Callable[[set[TopicPartition]], None]
AsyncPartitionCallback = Callable[[set[TopicPartition]], Awaitable[None]]


class _RebalanceListener(ConsumerRebalanceListener):
    """Rebalance listener for aiokafka consumer.

    Supports both sync and async callbacks - aiokafka handles both internally.
    Use sync callbacks when no async work is needed (e.g., just logging).
    Use async callbacks when actual async operations are required (e.g., committing).
    """

    __slots__ = ("_on_assign", "_on_revoke")

    def __init__(
        self,
        on_assign: SyncPartitionCallback,
        on_revoke: AsyncPartitionCallback,
    ) -> None:
        """Initialize rebalance listener.

        Args:
            on_assign: Sync callback for partition assignment (typically just logging).
            on_revoke: Async callback for partition revocation (may need to commit offsets).
        """
        self._on_assign = on_assign
        self._on_revoke = on_revoke

    def on_partitions_assigned(self, assigned: set[TopicPartition]) -> None:
        """Called when partitions are assigned (sync)."""
        self._on_assign(assigned)

    async def on_partitions_revoked(self, revoked: set[TopicPartition]) -> None:
        """Called when partitions are revoked (async for offset commit)."""
        await self._on_revoke(revoked)


@dataclass(slots=True)
class ConsumeForeverOptions:
    """Options for the consume_forever convenience function."""

    topics: list[str]
    message_type: type[betterproto2.Message]
    handler: MessageHandlerFunc[betterproto2.Message]
    config: KafkaClientConfig
    group_id: str | None = None
    shutdown_event: asyncio.Event | None = None


async def _run_consumer_with_shutdown[T: betterproto2.Message](
    consumer: KafkaConsumer,
    topics: list[str],
    message_type: type[T],
    handler: MessageHandlerFunc[T],
    shutdown_event: asyncio.Event | None,
) -> None:
    """Run consumer with optional shutdown event monitoring."""
    shutdown_task: asyncio.Task[None] | None = None

    if shutdown_event:

        async def monitor_shutdown() -> None:
            await shutdown_event.wait()
            consumer.stop()

        shutdown_task = asyncio.create_task(monitor_shutdown())

    try:
        await consumer.consume(topics, message_type, handler)
    finally:
        if shutdown_task:
            shutdown_task.cancel()
            with suppress(asyncio.CancelledError):
                await shutdown_task


async def consume_forever(options: ConsumeForeverOptions) -> None:
    """High-level function to consume messages forever.

    Args:
        options: Configuration bundle with consumer config, topics, handler, and shutdown event.

    """
    dlq_handler = DLQHandler(options.config.dlq, get_kafka_metrics(), consumer_group=options.group_id or "")

    async with KafkaConsumer(options.config, dlq_handler, options.group_id) as consumer:
        await _run_consumer_with_shutdown(
            consumer,
            options.topics,
            options.message_type,
            options.handler,
            options.shutdown_event,
        )
