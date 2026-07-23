"""Auto-managing Kafka client with internal lifecycle management."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Self, cast

import betterproto2
from nohiki_observability import get_logger

from nohiki_kafka_client.config import KafkaClientConfig
from nohiki_kafka_client.consumer import KafkaConsumer
from nohiki_kafka_client.consumer import RetryConsumer as _RetryConsumer
from nohiki_kafka_client.dlq import DLQHandler
from nohiki_kafka_client.exceptions import KafkaClientError
from nohiki_kafka_client.handlers import (
    DLQStrategy,
    HandlerRegistration,
    HandlerRegistryMixin,
    MessageContext,
    MessageHandlerFunc,
    _HandlerMetadata,
)
from nohiki_kafka_client.middleware.db_session import execute_with_db_session
from nohiki_kafka_client.middleware.protocol import execute_middleware_chain
from nohiki_kafka_client.observability.metrics import KafkaMetrics, get_kafka_metrics
from nohiki_kafka_client.producer import KafkaProducer, MessageMetadata
from nohiki_kafka_client.supervision.lifecycle import get_lifecycle_manager
from nohiki_kafka_client.supervision.supervisor import (
    ConsumerSupervisor,
    SupervisorConfig,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)

PRODUCER_NOT_INITIALIZED_MSG = "Producer not initialized"

_global_instance: list[AutoKafkaClient | None] = [None]


def _get_global_instance() -> AutoKafkaClient | None:
    """Return the current global AutoKafkaClient instance (or None)."""
    return _global_instance[0]


def _set_global_instance(instance: AutoKafkaClient) -> None:
    """Set the global AutoKafkaClient singleton instance."""
    _global_instance[0] = instance


class AutoKafkaClient(HandlerRegistryMixin):
    """Self-managing Kafka client that handles lifecycle automatically.

    Inherits decorator-based handler registration from ``HandlerRegistryMixin``.
    """

    _config: KafkaClientConfig
    _is_testing: bool
    _handlers: dict[str, HandlerRegistration]
    _handler_metadata: dict[int, _HandlerMetadata]
    _producer: KafkaProducer | None
    _consumers: dict[str, KafkaConsumer]
    _metrics: KafkaMetrics
    _initialized: bool
    _consumers_started: bool
    _consumers_ready: bool
    _consumer_tasks: list[asyncio.Task[None]]
    _consumer_owner_task: asyncio.Task[None] | None
    _consumer_failure: BaseException | None
    _shutdown_requested: bool
    _needs_producer: bool
    _needs_consumers: bool
    _producer_lock: asyncio.Lock
    _producer_ready: bool
    _supervisor: ConsumerSupervisor

    def __init__(self, config: KafkaClientConfig, *, is_testing: bool = False) -> None:
        """Initialize AutoKafkaClient with the given configuration.

        Args:
            config: Kafka client configuration.
            is_testing: If True, publish operations are no-ops.

        """
        self._config = config
        self._is_testing = is_testing
        self._handlers: dict[str, HandlerRegistration] = {}
        self._handler_metadata: dict[int, _HandlerMetadata] = {}
        self._producer: KafkaProducer | None = None
        self._consumers: dict[str, KafkaConsumer] = {}
        self._metrics = get_kafka_metrics()
        self._initialized = False
        self._consumers_started = False
        self._consumers_ready = False
        self._consumer_tasks: list[asyncio.Task[None]] = []
        self._consumer_owner_task: asyncio.Task[None] | None = None
        self._consumer_failure: BaseException | None = None
        self._shutdown_requested = False
        self._needs_producer = False
        self._needs_consumers = False
        self._producer_lock = asyncio.Lock()
        self._producer_ready = False
        self._db_session_factory: async_sessionmaker[AsyncSession] | None = None
        self._retry_consumers: dict[str, _RetryConsumer] = {}
        self._supervisor = ConsumerSupervisor(SupervisorConfig())

    @property
    def kafka_client(self) -> Self:
        """Access the AutoKafkaClient instance itself."""
        return self

    #: HandlerRegistryMixin hooks --

    def _on_handler_registered(self, _registration: HandlerRegistration) -> None:
        """Trigger auto-start after handler registration."""
        self._needs_consumers = True
        self._maybe_auto_start()

    def set_db_session_factory(self, factory: async_sessionmaker[AsyncSession]) -> None:
        """Register a database session factory for ``with_db_session`` handlers.

        Args:
            factory: SQLAlchemy async session factory.

        """
        self._db_session_factory = factory

    def _ensure_initialized(self) -> None:
        """Ensure client core components are initialized."""
        if not self._initialized:
            self._initialized = True
            logger.debug("Kafka client core components ready")

    async def _ensure_producer(self) -> None:
        """Lazy-initialize producer only when needed."""
        # Check if producer exists AND its internal producer is ready
        if self._producer_ready and self._producer and self._producer.is_ready():
            return

        async with self._producer_lock:
            # Double-check after acquiring lock
            if self._producer_ready and self._producer and self._producer.is_ready():
                return

            # Reset state if producer exists but internal producer is None
            if self._producer and not self._producer.is_ready():
                logger.warning("Producer exists but internal producer is None, restarting")
                self._producer = None
                self._producer_ready = False

            if self._producer is None and self._needs_producer:
                self._ensure_initialized()

                self._producer = KafkaProducer(config=self._config)
                await self._producer.__aenter__()
                self._producer_ready = True
                logger.info("Kafka producer ready")

    def _auto_start_consumers(self) -> asyncio.Task[None] | None:
        """Schedule and return the task that owns the consumer generation."""
        if not self._handlers or self._consumers_started or not self._needs_consumers:
            return self._consumer_owner_task

        self._ensure_initialized()
        handlers_by_group: defaultdict[str, list[HandlerRegistration]] = defaultdict(list)
        for registration in self._handlers.values():
            handlers_by_group[registration.group_id].append(registration)

        self._consumer_failure = None
        task = asyncio.create_task(
            self._initialize_all_consumers(handlers_by_group),
            name=f"{self._config.auto_client.consumer_task_prefix}-orchestrator",
        )
        self._consumer_owner_task = task
        self._consumer_tasks.append(task)
        task.add_done_callback(self._consumer_owner_finished)
        self._consumers_started = True
        self._sync_lifecycle_consumer_state()
        logger.info(
            "Kafka consumer startup scheduled",
            handler_count=len(self._handlers),
            group_count=len(handlers_by_group),
        )
        return task

    async def _initialize_all_consumers(self, handlers_by_group: dict[str, list[HandlerRegistration]]) -> None:
        """Start and own every supervised/retry task as one consumer generation."""
        generation_tasks: list[asyncio.Task[None]] = []
        try:
            for group_id, registrations in handlers_by_group.items():
                task_count = len(self._consumer_tasks)
                await self._start_consumer_for_group(group_id, registrations)
                generation_tasks.extend(self._consumer_tasks[task_count:])
                logger.info("Consumer group started", group_id=group_id)

            self._consumers_ready = True
            self._sync_lifecycle_consumer_state()
            logger.info(
                "All consumer groups initialized",
                active_groups=len(handlers_by_group),
                total_groups=len(handlers_by_group),
            )
            await self._monitor_consumer_generation(generation_tasks)
        except asyncio.CancelledError:
            self._consumers_ready = False
            await self._cancel_consumer_generation(generation_tasks)
            raise
        except Exception as error:
            self._record_consumer_failure(error)
            logger.exception("Kafka consumer generation failed", error=str(error))
            await self._cancel_consumer_generation(generation_tasks)
            raise

    async def _monitor_consumer_generation(self, tasks: list[asyncio.Task[None]]) -> None:
        """Surface the first child exit after retrieving every completed result."""
        if not tasks:
            message = "Kafka consumer generation started without child tasks"
            raise KafkaClientError(message)
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        failure: BaseException | None = None
        finished_task: asyncio.Task[None] | None = None
        for task in tasks:
            if task not in done:
                continue
            finished_task = task
            if not task.cancelled() and (error := task.exception()) is not None and failure is None:
                failure = error
        if failure is not None:
            raise failure
        task_name = finished_task.get_name() if finished_task is not None else "unknown"
        message = f"Kafka consumer task {task_name!r} stopped unexpectedly"
        raise KafkaClientError(message)

    @staticmethod
    async def _cancel_consumer_generation(tasks: list[asyncio.Task[None]]) -> None:
        """Cancel and retrieve every child result in the consumer generation."""
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _record_consumer_failure(self, error: BaseException) -> None:
        """Publish the first fatal consumer failure into client health state."""
        self._consumers_ready = False
        if self._consumer_failure is None:
            self._consumer_failure = error
        self._sync_lifecycle_consumer_state()

    def _sync_lifecycle_consumer_state(self) -> None:
        """Publish current consumer readiness to the shared health probe state."""
        try:
            manager = get_lifecycle_manager()
        except RuntimeError:
            return
        active_tasks = sum(1 for task in self._consumer_tasks if not task.done())
        handlers_registered = len(self._handlers)
        consumers_ready = handlers_registered == 0 or (
            self._consumers_started and self._consumers_ready and active_tasks > 0 and not self._shutdown_requested
        )
        manager.update_consumer_state(
            consumers_ready=consumers_ready,
            handlers_registered=handlers_registered,
            consumers_active=len(self._consumers),
            consumer_tasks_running=active_tasks,
        )

    def _consumer_owner_finished(self, task: asyncio.Task[None]) -> None:
        """Retrieve an unawaited owner failure while keeping it awaitable by callers."""
        if task.cancelled():
            return
        if (error := task.exception()) is not None:
            self._record_consumer_failure(error)

    def start_consumers(self) -> asyncio.Task[None] | None:
        """Synchronously schedule consumers and return their owner task."""
        return self._auto_start_consumers()

    async def wait_for_consumers(self) -> None:
        """Wait for the consumer generation to stop and propagate its exact failure."""
        if self._consumer_owner_task is not None:
            await asyncio.shield(self._consumer_owner_task)
        elif self._consumer_failure is not None:
            raise self._consumer_failure

    @asynccontextmanager
    async def supervise_consumer_failures(self) -> AsyncIterator[None]:
        """Cancel the surrounding lifespan when the consumer generation fails."""
        owner_task = self._consumer_owner_task
        if owner_task is None:
            message = "Kafka consumers must be started before they can be supervised"
            raise KafkaClientError(message)

        async with asyncio.TaskGroup() as task_group:
            monitor_task = task_group.create_task(
                self.wait_for_consumers(),
                name=f"{self._config.auto_client.consumer_task_prefix}-failure-monitor",
            )
            try:
                yield
            finally:
                owner_failed = owner_task.done() and not owner_task.cancelled() and owner_task.exception() is not None
                if not owner_failed:
                    monitor_task.cancel()

    async def wait_for_consumer_catchup(self, group_id: str, timeout_seconds: float) -> None:
        """Wait until a consumer group reaches a single startup offset snapshot."""
        if timeout_seconds <= 0:
            msg = "timeout_seconds must be greater than zero"
            raise ValueError(msg)
        if not any(registration.group_id == group_id for registration in self._handlers.values()):
            msg = f"No consumer handlers registered for group {group_id!r}"
            raise KafkaClientError(msg)
        if self._shutdown_requested or not self._consumers_started:
            msg = f"Kafka consumers are stopped; cannot wait for group {group_id!r}"
            raise KafkaClientError(msg)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        snapshot: dict[tuple[str, int], int] | None = None
        while loop.time() < deadline:
            if self._shutdown_requested or not self._consumers_started:
                msg = f"Kafka consumers stopped while waiting for group {group_id!r}"
                raise KafkaClientError(msg)
            if (consumer := self._consumers.get(group_id)) is not None:
                if snapshot is None:
                    snapshot = await consumer.snapshot_end_offsets()
                if snapshot is not None and await consumer.has_reached_offsets(snapshot):
                    return
            await asyncio.sleep(min(0.05, max(0.0, deadline - loop.time())))

        msg = f"Consumer group {group_id!r} did not reach its startup offset snapshot within {timeout_seconds} seconds"
        raise KafkaClientError(msg)

    async def ensure_producer_ready(self) -> None:
        """Initialize the Kafka producer if not already initialized."""
        self._needs_producer = True
        await self._ensure_producer()

    def is_producer_ready(self) -> bool:
        """Check if producer is initialized and ready to publish."""
        return self._producer is not None and self._initialized

    def get_health_state(self) -> dict[str, object]:
        """Get health state for readiness checks.

        Returns dict with:
        - consumers_ready: True if all registered consumers are running
        - handlers_registered: Number of registered message handlers
        - consumers_active: Number of active consumers
        - consumer_tasks_running: Number of consumer tasks not done
        - shutdown_requested: True if shutdown has been initiated
        - supervisor: Per-consumer health summary from ConsumerSupervisor
        """
        self._sync_lifecycle_consumer_state()
        active_tasks = sum(1 for t in self._consumer_tasks if not t.done())
        handlers_registered = len(self._handlers)

        # Service is ready only if:
        # 1. No handlers registered (producer-only), OR
        # 2. Consumers are started AND ready AND tasks are running
        if handlers_registered == 0:
            consumers_ready = True  # No consumers needed
        else:
            consumers_ready = (
                self._consumers_started and self._consumers_ready and active_tasks > 0 and not self._shutdown_requested
            )

        return {
            "consumers_ready": consumers_ready,
            "handlers_registered": handlers_registered,
            "consumers_active": len(self._consumers),
            "consumer_tasks_running": active_tasks,
            "shutdown_requested": self._shutdown_requested,
            "consumer_failure": str(self._consumer_failure) if self._consumer_failure is not None else None,
            "consumer_failure_type": type(self._consumer_failure).__name__
            if self._consumer_failure is not None
            else None,
            "needs_consumers": self._needs_consumers,
            "supervisor": self._supervisor.get_health_summary(),
        }

    async def _cleanup_consumer_for_group(self, group_id: str) -> None:
        """Clean up a consumer for a specific group."""
        if group_id not in self._consumers:
            return
        consumer = self._consumers.pop(group_id)
        try:
            await consumer.__aexit__(None, None, None)
        except Exception:
            logger.exception("Failed to cleanup consumer", group_id=group_id)

    def _wrap_handler_with_middleware(self, registration: HandlerRegistration) -> HandlerRegistration:
        """Wrap a handler's function with configured middleware chain.

        Applies middleware in order, creating an "onion" where each middleware
        wraps the next, with the handler at the center.
        """
        if not registration.middleware:
            return registration

        original_func = registration.handler_func
        middleware_stack = registration.middleware

        async def wrapped(message: betterproto2.Message, context: MessageContext) -> None:
            await execute_middleware_chain(middleware_stack, original_func, message, context)

        wrapped.__name__ = original_func.__name__
        wrapped.__module__ = original_func.__module__
        return HandlerRegistration(
            topic=registration.topic,
            message_type=registration.message_type,
            handler_func=cast("MessageHandlerFunc[betterproto2.Message]", wrapped),
            group_id=registration.group_id,
            middleware=[],  # Middleware already applied
            is_transactional=registration.is_transactional,
            resilience_config=registration.resilience_config,
            db_session_config=registration.db_session_config,
            preserve_partition_order=registration.preserve_partition_order,
        )

    def _wrap_handler_with_db_session(self, registration: HandlerRegistration) -> HandlerRegistration:
        """Wrap a handler's function with DB session middleware if configured."""
        db_config = registration.db_session_config
        if not db_config:
            return registration

        if not self._db_session_factory:
            msg = (
                f"Handler '{registration.handler_func.__name__}' uses @with_db_session "
                "but no db session factory was registered. "
                "Call kafka_client.set_db_session_factory() before start_consumers()."
            )
            raise KafkaClientError(msg)

        original_func = registration.handler_func
        factory = self._db_session_factory

        async def wrapped(message: betterproto2.Message, context: MessageContext) -> None:
            await execute_with_db_session(original_func, message, context, db_config, factory)

        wrapped.__name__ = original_func.__name__
        wrapped.__module__ = original_func.__module__
        return HandlerRegistration(
            topic=registration.topic,
            message_type=registration.message_type,
            handler_func=cast("MessageHandlerFunc[betterproto2.Message]", wrapped),
            group_id=registration.group_id,
            middleware=registration.middleware,
            is_transactional=registration.is_transactional,
            resilience_config=registration.resilience_config,
            db_session_config=registration.db_session_config,
            preserve_partition_order=registration.preserve_partition_order,
        )

    async def _start_consumer_for_group(
        self,
        group_id: str,
        registrations: list[HandlerRegistration],
    ) -> tuple[asyncio.Task[None], asyncio.Task[None]]:
        """Start a supervised consumer group with automatic restart on transient failures.

        Registers one ``HandlerRegistration`` sentinel with the ``ConsumerSupervisor``
        to represent the group, then spawns the supervisor loop as a long-running task.
        The supervisor's factory creates a fresh ``KafkaConsumer`` on every attempt
        (initial start + each supervised restart) to guarantee a clean connection state.

        Also starts a ``RetryConsumer`` for non-blocking retry processing on
        ``{group_id}.retry``.
        """
        # Apply middleware chain first, then db_session wrapper
        # Order: middleware → db_session → handler
        wrapped_registrations = [
            self._wrap_handler_with_db_session(self._wrap_handler_with_middleware(r)) for r in registrations
        ]
        topics = [r.topic for r in wrapped_registrations]
        handler_map = {r.topic: r for r in wrapped_registrations}

        # Producer needed for REPUBLISH strategy (DLQ + retry) or when
        # max_retries > 0 (retry publishing even with LOG_ONLY DLQ)
        if self._config.dlq.strategy == DLQStrategy.REPUBLISH or self._config.dlq.max_retries > 0:
            self._needs_producer = True
            await self._ensure_producer()

        # Use the first registration as the supervisor sentinel for this group.
        # The factory receives it but we capture the full handler_map via closure.
        sentinel_registration = wrapped_registrations[0]
        supervised = self._supervisor.register(sentinel_registration)

        async def _consumer_factory(_registration: HandlerRegistration) -> None:
            """Create a fresh consumer and run it for this group attempt."""
            dlq_handler = DLQHandler(
                config=self._config.dlq,
                metrics=self._metrics,
                consumer_group=group_id,
            )
            if self._producer:
                dlq_handler.set_producer(self._producer)

            consumer = KafkaConsumer(
                config=self._config,
                dlq_handler=dlq_handler,
                group_id=group_id,
            )
            async with consumer:
                self._consumers[group_id] = consumer
                try:
                    await consumer.consume_multi(
                        topics=topics,
                        handler_map=handler_map,
                        kafka_client=self,
                    )
                except asyncio.CancelledError:
                    logger.info("Consumer task cancelled", group_id=group_id, topics=topics)
                    raise
                finally:
                    self._consumers.pop(group_id, None)

        retry_consumer = _RetryConsumer(
            consumer_group=group_id,
            handler_map=handler_map,
            config=self._config,
            producer=self._producer,
        )
        self._retry_consumers[group_id] = retry_consumer

        supervised_task = asyncio.create_task(
            self._supervisor.start_consumer(supervised, _consumer_factory),
            name=f"{self._config.auto_client.consumer_task_prefix}-{group_id}",
        )
        supervised.task = supervised_task
        self._consumer_tasks.append(supervised_task)

        retry_task = asyncio.create_task(
            retry_consumer.start(),
            name=f"{self._config.auto_client.consumer_task_prefix}-{group_id}-retry",
        )
        self._consumer_tasks.append(retry_task)
        return supervised_task, retry_task

    def _maybe_auto_start(self) -> None:
        """Try to auto-start consumers if event loop is running and handlers exist."""
        if not self._config.auto_client.auto_start_consumers:
            return  # Auto-start disabled - wait for explicit start_consumers() call
        if self._handlers and not self._consumers_started and self._needs_consumers and not self._is_testing:
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(self._schedule_auto_start)
            except RuntimeError:
                pass

    def _schedule_auto_start(self) -> None:
        """Schedule auto-start in the background without blocking."""
        self._auto_start_consumers()

    def _mock_metadata(
        self,
        topic: str,
        key: str | None,
        *,
        size_bytes: int | None = None,
        serialization_time_ms: float | None = None,
    ) -> MessageMetadata:
        """Build mock MessageMetadata for testing mode."""
        ac = self._config.auto_client
        return MessageMetadata(
            topic=topic,
            partition=ac.mock_partition,
            offset=ac.mock_offset,
            timestamp=ac.mock_timestamp,
            key=key or ac.mock_key_default,
            size_bytes=size_bytes or ac.mock_message_size_bytes,
            serialization_time_ms=serialization_time_ms
            if serialization_time_ms is not None
            else ac.mock_serialization_time_ms,
            publish_time_ms=ac.mock_publish_time_ms,
        )

    async def _require_producer(self) -> KafkaProducer:
        """Ensure producer is ready and return it, or raise."""
        self._needs_producer = True
        await self._ensure_producer()
        if self._producer is None:
            raise KafkaClientError(PRODUCER_NOT_INITIALIZED_MSG)
        return self._producer

    async def publish(
        self,
        topic: str,
        message: betterproto2.Message,
        key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> MessageMetadata:
        """Publish a message to Kafka with automatic producer initialization."""
        if self._is_testing:
            logger.debug("Skipping Kafka publish in test mode", topic=topic)
            return self._mock_metadata(topic, key)

        producer = await self._require_producer()
        return await producer.publish(topic=topic, message=message, key=key, headers=headers)

    async def publish_raw(
        self,
        topic: str,
        value: bytes,
        key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> MessageMetadata:
        """Publish raw bytes to Kafka (used by outbox/DLQ)."""
        if self._is_testing:
            logger.debug("Skipping Kafka raw publish in test mode", topic=topic)
            return self._mock_metadata(topic, key, size_bytes=len(value), serialization_time_ms=0.0)

        producer = await self._require_producer()
        return await producer.publish_raw(topic=topic, key=key, value=value, headers=headers)

    async def publish_json(
        self,
        topic: str,
        value: dict,
        key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> MessageMetadata:
        """Publish JSON message for sink connectors.

        Designed for use with Kafka Connect sink connectors (e.g., Qdrant sink)
        that expect JSON payloads rather than Protobuf.

        Args:
            topic: Target Kafka topic.
            value: Dictionary to serialize as JSON.
            key: Optional message key.
            headers: Optional message headers.

        Returns:
            MessageMetadata with publish details.

        """
        if self._is_testing:
            logger.debug("Skipping Kafka JSON publish in test mode", topic=topic)
            return self._mock_metadata(topic, key, size_bytes=len(json.dumps(value)), serialization_time_ms=0.0)

        producer = await self._require_producer()
        return await producer.publish_json(topic=topic, value=value, key=key, headers=headers)

    def serialize(self, topic: str, message: betterproto2.Message) -> bytes:
        """Serialize betterproto2 message to wire format."""
        _ = topic  # Topic not needed for betterproto2 serialization
        return bytes(message)

    async def flush(self) -> None:
        """Flush any pending messages."""
        if self._producer:
            await self._producer.flush()

    async def stop_consumers(self, drain_timeout_seconds: float = 30.0) -> None:
        """Stop consumers gracefully via two-phase task cancellation.

        Phase 1: Immediate cancel:
            Sets shutdown events, then cancels all consumer tasks.  This
            breaks blocked ``async for`` iterators instantly via
            ``CancelledError``.  Each consume loop catches the error,
            calls ``uncancel()``, drains in-flight handlers, commits
            final offsets, then exits normally.

        Phase 2: Timeout guard:
            Waits up to ``drain_timeout_seconds`` for the graceful drain
            to finish.  Tasks still running after the timeout are
            force-cancelled a second time (hard stop).

        The drain timeout should align with Kubernetes'
        ``terminationGracePeriodSeconds`` (default 30s).

        Args:
            drain_timeout_seconds: Maximum time to wait for in-flight
                messages before force-cancelling.  Defaults to 30s.

        """
        if not self._consumers and not self._consumer_tasks:
            return

        logger.info("Stopping Kafka consumers - initiating graceful shutdown")
        self._consumers_ready = False
        self._sync_lifecycle_consumer_state()
        owner_task = self._consumer_owner_task
        if owner_task is not None and not owner_task.done():
            owner_task.cancel()
            with suppress(asyncio.CancelledError):
                await owner_task

        # Signal supervisor to stop all supervised consumers (sets shutdown events
        # and cancels their tasks). This prevents the supervisor from restarting
        # consumers that exit during shutdown.
        await self._supervisor.stop_all()

        # Signal shutdown events for remaining components that check them directly
        for consumer in self._consumers.values():
            consumer.stop()

        for retry_consumer in self._retry_consumers.values():
            retry_consumer.stop()

        # Phase 1: Cancel tasks to break blocked async iterators.
        # The consume loop handles CancelledError gracefully:
        # uncancel() → drain in-flight → final commit → exit normally.
        for task in self._consumer_tasks:
            if not task.done():
                task.cancel()

        # Phase 2: Wait for graceful drain to complete
        active_tasks = [t for t in self._consumer_tasks if not t.done()]
        if active_tasks:
            done, pending = await asyncio.wait(active_tasks, timeout=drain_timeout_seconds)

            if pending:
                # Drain timeout exceeded: hard stop remaining tasks
                for task in pending:
                    logger.warning(
                        "Force-cancelling consumer task after drain timeout",
                        task_name=task.get_name(),
                    )
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

            logger.info(
                "Consumer shutdown complete",
                drained=len(done),
                force_cancelled=len(pending),
            )

        self._consumer_tasks.clear()
        self._consumers.clear()
        self._retry_consumers.clear()
        self._consumers_started = False
        self._consumer_owner_task = None

        self._sync_lifecycle_consumer_state()
        logger.info("Kafka consumers stopped")

    async def close(self, drain_timeout_seconds: float = 30.0) -> None:
        """Close all Kafka client resources gracefully.

        This method should be called from the FastAPI lifespan shutdown phase.
        It stops all consumers and closes producer connections.

        Safe to call multiple times - subsequent calls are no-ops.

        Args:
            drain_timeout_seconds: Maximum time to wait for in-flight
                messages before force-cancelling. Defaults to 30s to align
                with Kubernetes' ``terminationGracePeriodSeconds``.
        """
        if self._shutdown_requested:
            return

        self._shutdown_requested = True
        logger.info("Starting Kafka client cleanup")

        await self.stop_consumers(drain_timeout_seconds=drain_timeout_seconds)

        if self._producer is not None:
            try:
                await self._producer.__aexit__(None, None, None)
            except (KafkaClientError, asyncio.CancelledError) as e:
                logger.exception("Error cleaning up producer", error=str(e))
            finally:
                self._producer = None
                self._producer_ready = False

        logger.info("Kafka client cleanup complete")
