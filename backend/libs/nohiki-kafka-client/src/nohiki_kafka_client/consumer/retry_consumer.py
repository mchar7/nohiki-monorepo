"""Dedicated retry consumer for reprocessing failed messages after backoff.

Each service auto-registers a ``RetryConsumer`` alongside its main consumers.
The retry consumer subscribes to ``{consumer_group}.retry`` using consumer
group ``{consumer_group}.retry-cg``.  Retry state (count, backoff, original
topic) lives entirely in Kafka headers: no external state required.

In multi-pod deployments, Kafka distributes retry topic partitions across all
pods running the same service.  Any pod can process any retry message; this is
intentional so that pod-specific failures can be recovered by a different pod.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiokafka import (
    AIOKafkaConsumer,
    ConsumerRebalanceListener,
    ConsumerRecord,
    TopicPartition,
)
from aiokafka.errors import KafkaError
from nohiki_observability import get_logger

from nohiki_kafka_client.config import KafkaClientConfig, get_aiokafka_consumer_config
from nohiki_kafka_client.dlq import DLQHandler
from nohiki_kafka_client.dlq.models import ConsumedMessage, ProcessingContext
from nohiki_kafka_client.exceptions import DLQPublishError
from nohiki_kafka_client.handlers import HandlerRegistration, MessageContext
from nohiki_kafka_client.observability.metrics import get_kafka_metrics

if TYPE_CHECKING:
    from nohiki_kafka_client.producer import KafkaProducer

logger = get_logger(__name__)

INITIAL_RESTART_BACKOFF_SECONDS = 0.5
MAX_RESTART_BACKOFF_SECONDS = 30.0
MAX_RESTART_BACKOFF_EXPONENT = 6
MAX_KAFKA_TOPIC_NAME_LENGTH = 249


def _decode_headers(raw_headers: Sequence[tuple[str, bytes]] | None) -> dict[str, str]:
    """Decode Kafka record headers from bytes to strings."""
    if not raw_headers:
        return {}
    return {k: v.decode("utf-8", errors="replace") for k, v in raw_headers}


def _decode_key(raw_key: bytes | None) -> str | None:
    """Decode Kafka record key from bytes to string."""
    if raw_key is None:
        return None
    return raw_key.decode("utf-8", errors="replace")


def _parse_retry_count(headers: dict[str, str]) -> int:
    """Extract integer retry count from decoded headers."""
    raw = headers.get("x-retry-count", "0")
    try:
        return int(raw)
    except ValueError, TypeError:
        return 0


def _parse_next_retry_at(headers: dict[str, str]) -> float:
    """Extract float retry-at timestamp from decoded headers."""
    raw = headers.get("x-next-retry-at", "0.0")
    try:
        return float(raw)
    except ValueError, TypeError:
        return 0.0


@dataclass(frozen=True, slots=True)
class _RetryFailure:
    """Inputs required to route a failed retry through the DLQ policy."""

    record: ConsumerRecord
    error: Exception
    headers: dict[str, str]
    registration: HandlerRegistration | None
    source_topic: str | None = None


class RetryConsumer:
    """Dedicated consumer for retry topic: applies backoff, re-routes to handler.

    The retry consumer's sole job is reprocessing messages after their backoff
    period elapses.  The ``asyncio.sleep()`` here is architecturally correct --
    this consumer's sole purpose is handling retries, so sleeping does not
    impact main consumer throughput.
    """

    def __init__(
        self,
        consumer_group: str,
        handler_map: Mapping[str, HandlerRegistration],
        config: KafkaClientConfig,
        *,
        producer: KafkaProducer | None = None,
    ) -> None:
        """Initialize the retry consumer.

        Args:
            consumer_group: The main consumer group this retry consumer serves.
            handler_map: Topic-to-handler mapping from the main consumer.
            config: Full Kafka client configuration.
            producer: Optional Kafka producer for DLQ escalation.

        """
        self._consumer_group = consumer_group
        self._retry_topic = f"{consumer_group}.retry"
        self._retry_consumer_group = f"{consumer_group}.retry-cg"
        self._handler_map = handler_map
        self._config = config
        self._shutdown_event = asyncio.Event()
        self._metrics = get_kafka_metrics()
        self._consumer: AIOKafkaConsumer | None = None
        self._supervisor_task: asyncio.Task[None] | None = None
        self._partition_tails: dict[TopicPartition, asyncio.Future[None]] = {}
        self._blocked_offsets: dict[TopicPartition, int] = {}
        self._inflight_tasks: set[asyncio.Task[None]] = set()
        self._generation_failure: asyncio.Future[BaseException] | None = None
        self._partition_tasks: dict[TopicPartition, set[asyncio.Task[None]]] = {}
        self._revoked_partitions: set[TopicPartition] = set()
        self._admission = asyncio.Semaphore(config.consumer.max_concurrent_handlers)

        self._dlq_handler = DLQHandler(
            config=config.dlq,
            metrics=self._metrics,
            consumer_group=consumer_group,
        )
        if producer:
            self._dlq_handler.set_producer(producer)

    def stop(self) -> None:
        """Signal shutdown and interrupt the owned supervisor task."""
        self._shutdown_event.set()
        task = self._supervisor_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    async def start(self) -> None:
        """Run retry-consumer generations until explicit shutdown.

        A fresh Kafka consumer is created for every generation. Startup and
        polling failures restart after capped exponential backoff. Cancellation
        propagates only after the active generation has cancelled its record
        tasks and stopped its Kafka consumer.
        """
        self._supervisor_task = asyncio.current_task()
        failure_count = 0
        try:
            while not self._shutdown_event.is_set():
                try:
                    await self._run_generation()
                except asyncio.CancelledError:
                    logger.info(
                        "Retry consumer shutdown initiated",
                        retry_topic=self._retry_topic,
                    )
                    raise
                except KafkaError as error:
                    if self._shutdown_event.is_set():
                        return
                    failure_count += 1
                    backoff = _restart_backoff(failure_count)
                    logger.warning(
                        "Retry consumer generation failed; restarting",
                        retry_topic=self._retry_topic,
                        attempt=failure_count,
                        backoff_seconds=backoff,
                        error=str(error),
                    )
                    if await self._wait_for_restart(backoff):
                        return
                except Exception:
                    logger.exception(
                        "Retry consumer stopped after an unexpected failure",
                        retry_topic=self._retry_topic,
                    )
                    raise
        finally:
            self._supervisor_task = None

    async def _run_generation(self) -> None:
        """Own one Kafka consumer generation and all of its record tasks."""
        consumer_kwargs = get_aiokafka_consumer_config(self._config, self._retry_consumer_group)
        consumer_kwargs["enable_auto_commit"] = False
        consumer_kwargs["auto_offset_reset"] = "earliest"

        consumer = AIOKafkaConsumer(**consumer_kwargs)
        try:
            consumer.subscribe(
                [self._retry_topic],
                listener=_RetryRebalanceListener(
                    self._on_partitions_assigned,
                    self._on_partitions_revoked,
                ),
            )
            await consumer.start()
            self._consumer = consumer
            logger.info(
                "Retry consumer started",
                retry_topic=self._retry_topic,
                group=self._retry_consumer_group,
            )
            await self._consume_loop(consumer)
        finally:
            try:
                await self._cancel_inflight_tasks()
            finally:
                try:
                    await consumer.stop()
                finally:
                    self._consumer = None
                    logger.info("Retry consumer stopped", retry_topic=self._retry_topic)

    async def _consume_loop(self, consumer: AIOKafkaConsumer) -> None:
        """Poll until shutdown, propagating record and broker failures to the owner."""
        failure = asyncio.get_running_loop().create_future()
        self._generation_failure = failure
        poll_task = asyncio.create_task(
            self._consume_attempt(consumer),
            name=f"retry-poll-{self._retry_consumer_group}",
        )
        try:
            done, _ = await asyncio.wait(
                (poll_task, failure),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if failure in done:
                poll_task.cancel()
                await asyncio.gather(poll_task, return_exceptions=True)
                raise failure.result()

            await poll_task
            if failure.done():
                raise failure.result()
            if not self._shutdown_event.is_set():
                msg = "Retry consumer poll exited unexpectedly"
                raise KafkaError(msg)
        finally:
            self._generation_failure = None
            if not failure.done():
                failure.cancel()
            if not poll_task.done():
                poll_task.cancel()
                await asyncio.gather(poll_task, return_exceptions=True)

    async def _wait_for_restart(self, backoff: float) -> bool:
        """Wait for restart backoff; return true when shutdown interrupts it."""
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=backoff)
        except TimeoutError:
            return False
        return True

    async def _consume_attempt(self, consumer: AIOKafkaConsumer) -> None:
        """Poll one generation and admit a bounded number of record tasks."""
        async for record in consumer:
            if self._shutdown_event.is_set():
                return

            tp = TopicPartition(record.topic, record.partition)
            await self._admission.acquire()
            if self._shutdown_event.is_set():
                self._admission.release()
                return
            if tp in self._revoked_partitions:
                self._admission.release()
                continue

            task = asyncio.create_task(
                self._process_retry_record(record, consumer),
                name=f"retry-{record.topic}-{record.partition}-{record.offset}",
            )
            self._inflight_tasks.add(task)
            self._partition_tasks.setdefault(tp, set()).add(task)
            task.add_done_callback(lambda done, partition=tp: self._task_finished(partition, done))

    async def _cancel_inflight_tasks(self) -> None:
        """Cancel and observe every scheduled record before the consumer closes."""
        tasks = tuple(self._inflight_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight_tasks.clear()
        self._partition_tasks.clear()
        self._partition_tails.clear()
        self._blocked_offsets.clear()

    def _task_finished(
        self,
        tp: TopicPartition,
        task: asyncio.Task[None],
    ) -> None:
        """Release admission and observe a scheduled task exactly once."""
        self._admission.release()
        self._inflight_tasks.discard(task)
        if partition_tasks := self._partition_tasks.get(tp):
            partition_tasks.discard(task)
            if not partition_tasks:
                self._partition_tasks.pop(tp, None)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error(
                "Scheduled retry task failed",
                retry_topic=self._retry_topic,
                error=str(error),
            )
            if self._generation_failure is not None and not self._generation_failure.done():
                self._generation_failure.set_result(error)

    def _on_partitions_assigned(self, assigned: set[TopicPartition]) -> None:
        """Allow newly assigned partitions to admit records."""
        self._revoked_partitions.difference_update(assigned)
        logger.info(
            "Retry partitions assigned",
            partitions=[str(tp) for tp in assigned],
            count=len(assigned),
        )

    async def _on_partitions_revoked(
        self,
        revoked: set[TopicPartition],
    ) -> None:
        """Cancel revoked work before forgetting all partition-local state."""
        if not revoked:
            return

        self._revoked_partitions.update(revoked)
        tasks = tuple(task for tp in revoked for task in self._partition_tasks.get(tp, ()))
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        for tp in revoked:
            self._blocked_offsets.pop(tp, None)
            self._partition_tails.pop(tp, None)
            self._partition_tasks.pop(tp, None)
        logger.info(
            "Retry partitions revoked",
            partitions=[str(tp) for tp in revoked],
            count=len(revoked),
        )

    async def _process_retry_record(
        self,
        record: ConsumerRecord,
        consumer: AIOKafkaConsumer,
    ) -> None:
        """Serialize records per partition while polling remains non-blocking."""
        tp = TopicPartition(record.topic, record.partition)
        if tp in self._revoked_partitions:
            return
        previous = self._partition_tails.get(tp)
        completion = asyncio.get_running_loop().create_future()
        self._partition_tails[tp] = completion
        try:
            if previous is not None:
                await previous
            if tp in self._revoked_partitions:
                return
            await self._process_retry_record_once(record, consumer, tp)
        finally:
            if not completion.done():
                completion.set_result(None)
            if self._partition_tails.get(tp) is completion:
                self._partition_tails.pop(tp, None)

    async def _process_retry_record_once(
        self,
        record: ConsumerRecord,
        consumer: AIOKafkaConsumer,
        tp: TopicPartition,
    ) -> None:
        """Process one partition-ordered record with scheduled backoff."""
        blocked_offset = self._blocked_offsets.get(tp)
        if blocked_offset is not None and blocked_offset != record.offset:
            logger.warning(
                "Skipping record behind an uncommittable retry offset",
                retry_topic=self._retry_topic,
                partition=record.partition,
                offset=record.offset,
                blocked_offset=blocked_offset,
            )
            return

        headers = _decode_headers(record.headers)
        original_topic = headers.get("x-original-topic")
        topic_is_valid = (
            original_topic is not None
            and bool(original_topic)
            and len(original_topic) <= MAX_KAFKA_TOPIC_NAME_LENGTH
            and all(character.isascii() and (character.isalnum() or character in "._-") for character in original_topic)
        )
        paused = False
        try:
            if _parse_next_retry_at(headers) > time.time():
                if tp in consumer.assignment():
                    consumer.pause(tp)
                    paused = True
                await _apply_backoff(_parse_next_retry_at(headers))

            registration = self._handler_map.get(original_topic) if topic_is_valid else None
            if not topic_is_valid or registration is None:
                reason = (
                    "Retry message has missing or invalid x-original-topic"
                    if not topic_is_valid
                    else "Retry message has no registered handler"
                )
                if not await self._route_poison_record(
                    record,
                    consumer,
                    tp,
                    headers,
                    ValueError(reason),
                ):
                    return
                await self._commit_retry_offset(record, consumer, tp)
                return

            if not await self._dispatch_or_route(record, consumer, tp, headers, registration):
                return
            await self._commit_retry_offset(record, consumer, tp)
        finally:
            if paused and tp in consumer.assignment():
                consumer.resume(tp)

    async def _route_poison_record(
        self,
        record: ConsumerRecord,
        consumer: AIOKafkaConsumer,
        tp: TopicPartition,
        headers: dict[str, str],
        error: ValueError,
    ) -> bool:
        """Publish an unroutable retry record to a safe DLQ topic."""
        try:
            await self._handle_retry_failure(
                _RetryFailure(
                    record=record,
                    error=error,
                    headers=headers,
                    registration=None,
                    source_topic=self._retry_topic,
                )
            )
        except DLQPublishError:
            logger.exception(
                "Poison retry record DLQ publish failed; offset not committed",
                retry_topic=self._retry_topic,
                partition=record.partition,
                offset=record.offset,
            )
            await self._seek_blocked_offset(consumer, tp, record.offset)
            return False
        return True

    async def _dispatch_or_route(
        self,
        record: ConsumerRecord,
        consumer: AIOKafkaConsumer,
        tp: TopicPartition,
        headers: dict[str, str],
        registration: HandlerRegistration,
    ) -> bool:
        """Dispatch a retry and return false when its offset must be retried."""
        original_topic = headers.get("x-original-topic", "")
        try:
            await _dispatch_to_handler(record, registration, headers)
        except asyncio.CancelledError:
            raise
        except DLQPublishError:
            logger.exception(
                "DLQ publish failed during retry, offset not committed",
                retry_topic=self._retry_topic,
                original_topic=original_topic,
                offset=record.offset,
            )
            await self._seek_blocked_offset(consumer, tp, record.offset)
            return False
        except Exception as retry_error:  # noqa: BLE001  # route handler failures to DLQ/retry
            try:
                await self._handle_retry_failure(
                    _RetryFailure(
                        record=record,
                        error=retry_error,
                        headers=headers,
                        registration=registration,
                    )
                )
            except DLQPublishError:
                logger.exception(
                    "DLQ publish failed during retry escalation, offset not committed",
                    retry_topic=self._retry_topic,
                    original_topic=original_topic,
                    offset=record.offset,
                )
                await self._seek_blocked_offset(consumer, tp, record.offset)
                return False
        return True

    async def _commit_retry_offset(
        self,
        record: ConsumerRecord,
        consumer: AIOKafkaConsumer,
        tp: TopicPartition,
    ) -> None:
        """Commit only this record and seek whenever the commit is unconfirmed."""
        try:
            await consumer.commit({tp: record.offset + 1})
        except KafkaError:
            logger.exception(
                "Retry offset commit failed; seeking uncommittable record",
                retry_topic=self._retry_topic,
                partition=record.partition,
                offset=record.offset,
            )
            await self._seek_blocked_offset(consumer, tp, record.offset)
            return
        self._blocked_offsets.pop(tp, None)

    async def _seek_blocked_offset(self, consumer: AIOKafkaConsumer, tp: TopicPartition, offset: int) -> None:
        """Keep a failed offset as the partition barrier and rewind Kafka."""
        self._blocked_offsets[tp] = offset
        try:
            consumer.seek(tp, offset)
        except KafkaError:
            logger.warning(
                "Retry offset could not be sought after partition transition",
                retry_topic=self._retry_topic,
                partition=tp.partition,
                offset=offset,
            )

    async def _handle_retry_failure(self, failure: _RetryFailure) -> None:
        """Route a failed retry through the configured DLQ policy."""
        record = failure.record
        headers = failure.headers
        retry_count = _parse_retry_count(headers)
        original_topic = failure.source_topic or headers.get("x-original-topic", record.topic)

        consumed_message = ConsumedMessage(
            topic=original_topic,
            partition=record.partition,
            offset=record.offset,
            timestamp=record.timestamp or 0,
            headers=headers,
            key=_decode_key(record.key),
            raw_value=record.value or b"",
        )
        processing_context = ProcessingContext(
            consumer_group=self._consumer_group,
            handler_name=f"retry:{original_topic}",
            processing_start_time=time.time(),
        )

        result = await self._dlq_handler.handle_failure(
            consumed_message,
            failure.error,
            processing_context,
            failure.registration.resilience_config if failure.registration is not None else None,
        )
        if not result.success:
            logger.error(
                "Retry failure escalation failed",
                original_topic=original_topic,
                retry_count=retry_count,
                error=str(failure.error),
                dlq_error=str(result.error),
            )
            msg = "Retry failure escalation failed"
            raise DLQPublishError(
                msg,
                details={
                    "topic": original_topic,
                    "retry_count": retry_count,
                    "error": str(result.error or failure.error),
                },
            )


class _RetryRebalanceListener(ConsumerRebalanceListener):
    """Bridge aiokafka rebalances to callbacks supplied by the owner."""

    __slots__ = ("_on_assigned", "_on_revoked")

    def __init__(
        self,
        on_assigned: Callable[[set[TopicPartition]], None],
        on_revoked: Callable[[set[TopicPartition]], Awaitable[None]],
    ) -> None:
        self._on_assigned = on_assigned
        self._on_revoked = on_revoked

    def on_partitions_assigned(self, assigned: set[TopicPartition]) -> None:
        self._on_assigned(assigned)

    async def on_partitions_revoked(self, revoked: set[TopicPartition]) -> None:
        await self._on_revoked(revoked)


def _restart_backoff(failure_count: int) -> float:
    """Return capped exponential backoff for a consecutive generation failure."""
    exponent = min(max(0, failure_count - 1), MAX_RESTART_BACKOFF_EXPONENT)
    return min(
        INITIAL_RESTART_BACKOFF_SECONDS * (2**exponent),
        MAX_RESTART_BACKOFF_SECONDS,
    )


async def _apply_backoff(next_retry_at: float) -> None:
    """Sleep until the scheduled retry time, if in the future.

    Args:
        next_retry_at: Unix timestamp when retry should execute.

    """
    if (remaining := next_retry_at - time.time()) > 0:
        await asyncio.sleep(remaining)


async def _dispatch_to_handler(
    record: ConsumerRecord,
    registration: HandlerRegistration,
    headers: dict[str, str],
) -> None:
    """Deserialize and dispatch the retry message to the original handler.

    Args:
        record: The raw Kafka record.
        registration: The handler registration for the original topic.
        headers: Decoded message headers.

    """
    raw_value = record.value or b""
    message = registration.message_type().parse(raw_value)
    context = MessageContext(
        topic=headers.get("x-original-topic", record.topic),
        partition=record.partition,
        offset=record.offset,
        timestamp=record.timestamp or 0,
        headers=headers,
        key=_decode_key(record.key),
        retry_count=_parse_retry_count(headers),
    )
    await registration.handler_func(message, context)
