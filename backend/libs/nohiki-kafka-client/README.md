# Nohiki Kafka Client

The backbone of all inter-service communication in Nohiki. Every one of the 18 backend services
depends on this library. It wraps `aiokafka` with a decorator-based handler registration system,
automatic consumer lifecycle tied to FastAPI's lifespan, a non-blocking retry-via-Kafka-topic
mechanism, dead letter queue routing, consumer supervision with exponential backoff reconnection,
and the canonical `Topics` enum listing all 100+ topic names across every domain. Without it, each
service would implement its own Kafka connection management, retry logic, and error classification --
which is precisely the duplication this library eliminates.

## Quick Start

The canonical pattern used by all 18 services: create one `kafka_client` singleton, decorate
handlers, wire the lifespan.

**`core/kafka.py`** -- one per service, always two lines:

```python
from nohiki_kafka_client import create_kafka_client
from my_service.core.config import get_settings

kafka_client = create_kafka_client(get_settings())
```

**`events/handlers.py`** -- register handlers with the decorator:

```python
from nohiki.job.listing.v1 import ListingCreated
from nohiki_kafka_client import MessageContext, Topics

from my_service.core.config import get_settings
from my_service.core.kafka import kafka_client

settings = get_settings()

@kafka_client.message_handler(
    Topics.JOB_LISTING_CREATED,
    ListingCreated,
    group_id=f"{settings.kafka.consumer_group}-primary",
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_listing_created(message: ListingCreated, context: MessageContext) -> None:
    db = context.require_db_session()
    await process_listing(db, message.listing_snapshot)
```

**`main.py`** -- import handlers to trigger registration, then wire lifespan:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from nohiki_db_utils import get_async_sessionmaker, initialize_database
from nohiki_kafka_client import ensure_kafka_ready

from my_service.core.kafka import kafka_client
from my_service.events import handlers  # import triggers @decorator registration

@asynccontextmanager
async def lifespan(_: FastAPI):
    await initialize_database(settings)
    await ensure_kafka_ready(bootstrap_servers=settings.kafka.bootstrap_servers)
    kafka_client.set_db_session_factory(get_async_sessionmaker(settings.database))
    kafka_client.start_consumers()  # boots all registered consumers

    yield

    await kafka_client.stop_consumers()
    await kafka_client.close()

app = FastAPI(lifespan=lifespan)
```

## Core Concepts

### The `kafka_client` singleton

Each service creates exactly one `AutoKafkaClient` instance via `create_kafka_client(settings)`,
conventionally in `core/kafka.py`. This singleton is what `@kafka_client.message_handler` is
called on. Python evaluates the decorator at module import time, so the singleton must exist
before handler modules are imported.

`create_kafka_client()` defaults to `auto_start_consumers=False`. This is intentional: consumers
should not start until after database migrations, JWKS initialization, and other startup tasks
complete. Services call `kafka_client.start_consumers()` explicitly, at the right point in their
lifespan.

The singleton is also accessible globally via `get_kafka_client()` after creation, but direct
import of the module-level `kafka_client` variable is the idiomatic pattern.

### `@kafka_client.message_handler()`

The primary API. Calling the decorator at module import time registers a handler function into
the client's internal `_handlers` dict. When `start_consumers()` is later called, the client
groups all registered handlers by `group_id`, then starts one `KafkaConsumer` per group --
meaning handlers sharing a `group_id` are multiplexed onto the same underlying aiokafka consumer
and therefore share partition assignments.

`group_id` is **required** and must be explicit. The naming convention is
`{service-short}-{responsibility}-{priority}`, e.g.:

- `job-correlation-primary` -- main processing group
- `job-correlation-projection` -- snapshot projection group
- `bff-projections-primary` -- BFF read model projection group

Setting distinct `group_id` values on different handlers is what gives each handler its own
independent consumer group offset, so one handler's lag does not block another's.

### `MessageContext`

The second argument to every handler function. It carries the Kafka message metadata (topic,
partition, offset, timestamp, headers, key, retry count) and, depending on decorators applied,
database sessions and publishing capability.

```python
# context.kafka_client is set automatically. Use context.publish() to emit events
await context.publish(Topics.JOB_CORRELATION_EVALUATED, event, key=listing_id)

# context.db_session is only available when @with_db_session is applied
db = context.require_db_session()  # raises RuntimeError if not decorated

# context.outbox is only available when @with_db_session(schema=...) is applied
outbox = context.require_outbox()
```

Convention: name the parameter `_context` (underscore prefix) when the handler does not use it --
this signals to readers and linters that the context is intentionally unused.

### Auto-lifecycle and consumer supervision

Registering a handler with `@kafka_client.message_handler()` does not start any consumer. It
adds the `HandlerRegistration` to the client's internal registry. `start_consumers()` triggers
the actual boot sequence:

1. Handlers are grouped by `group_id`.
2. For each group, a `ConsumerSupervisor` registers a `SupervisedConsumer` sentinel.
3. A long-running task starts the `KafkaConsumer` via a factory function. The factory creates a
   fresh `KafkaConsumer` on every attempt, including the initial start and each supervised restart, guaranteeing
   a clean aiokafka connection state.
4. A dedicated `RetryConsumer` also starts for each group, subscribed to `{group_id}.retry`.
5. The startup task remains the owner of every supervised and retry child task. If any child
   fails or exits unexpectedly, the owner marks the generation unready, cancels and awaits all
   siblings, records the fatal error for health reporting, and propagates the original exception.

The `ConsumerSupervisor` classifies failures by type:

| Error category | Examples | Action |
| ---------------- | ---------- | -------- |
| `TRANSIENT` | `KafkaConnectionError`, `OSError`, `TimeoutError` | Restart with exponential backoff |
| `COORDINATOR` | `NodeNotReadyError`, `CommitFailedError`, `UnknownMemberIdError` | Restart with exponential backoff |
| `AUTH` | `GroupAuthorizationFailedError` | Stop (non-recoverable) |
| `FATAL` | `ConsumerStoppedError`, unrecognized `KafkaError` | Stop (non-recoverable) |

Backoff starts at 1 second, doubles per attempt (with ±20% jitter), caps at 60 seconds. After 10
consecutive failures, the supervisor marks the consumer `FAILED` and stops retrying.

`start_consumers()` remains a synchronous scheduling call and returns the generation owner task.
Callers that need direct failure supervision can retain that task or await `wait_for_consumers()`;
callers that do neither still expose the failure through consumer readiness and the health fields.

Shutdown is two-phase. `stop_consumers()` first cancels all consumer tasks (which breaks blocked
`async for` iterators via `CancelledError`). Each consume loop catches `CancelledError`, calls
`uncancel()`, drains in-flight handlers, commits final offsets, then exits normally. A 30-second
drain timeout matches Kubernetes' `terminationGracePeriodSeconds`; tasks still running after
the timeout are force-cancelled.

### Retry and DLQ

All retry state lives in Kafka message headers. The client uses no Redis or in-memory state. When a handler
raises an exception, `DLQHandler.handle_failure()` classifies it:

**Retryable errors** (`DataNotAvailableError`, `ExternalServiceError`, `RateLimitedError`,
`StaleDataError`, `asyncio.TimeoutError`, `OSError`): the message is published to the
`{group_id}.retry` topic with headers encoding the retry count, next-retry timestamp, original
topic, and error type. The main consumer commits the offset immediately.
It never sleeps or blocks for retry backoff. The `RetryConsumer` (subscribed to `{group_id}.retry`) picks up the
message, waits until the `x-next-retry-at` timestamp, then dispatches it back to the original
handler.

**Non-retryable errors** (`DataNotFoundError`, `ValidationError`, `SchemaVersionMismatchError`,
`SerializationError`, `ValueError`, `TypeError`, `KeyError`, `AttributeError`), or retryable
errors that have exhausted `max_retries`: the message is sent to the DLQ.

DLQ behavior is controlled by `strategy`:

- **`republish`** (default): publishes the original message plus structured error metadata
  (type, message, stacktrace, timestamps, retry count) to `dlq.{original-topic}`. The DLQ
  topic is separate from the retry topic and is intended for human inspection or offline replay.
- **`log_only`**: logs the failure at `WARNING` level and discards the message. No Kafka publish
  occurs, so no producer is needed.

If publishing to the retry or DLQ topic fails, the source offset is not committed. The failure
stops that consumer generation and is classified as transient by the supervisor, which restarts
with backoff so Kafka redelivers the source record instead of letting the live iterator advance
indefinitely behind an in-memory offset gap.

Backoff for retries uses exponential increase: `backoff_ms * 2^retry_count`, capped at
`max_backoff_ms`. Per-handler overrides via `@kafka_client.with_resilience()` take precedence
over service-level defaults.

### `Topics` enum

All topic names in the monorepo live in `nohiki_kafka_client.Topics` as `Final[str]` class
attributes. Every service imports `Topics` and references topics symbolically.
String literals for topic names never appear in service code.

Topic naming convention: `{scope-subdomain}.{classification}.{event-name}.v{version}`

| Classification | Meaning | Example |
| ---------------- | --------- | --------- |
| `cdc` | Change Data Capture: entity state change with ECST snapshot | `user-pref.cdc.pref-created.v1` |
| `cmd` | Command: request to perform an action, expects a state change | `user-pref.cmd.create-requested.v1` |
| `fct` | Fact: immutable event recording that something happened | `job-ingest.fct.listing-discovered.v1` |
| `sys` | System/internal: callbacks, routing, not for external consumers | `job-correlation.sys.embedding-callback.v1` |

```python
from nohiki_kafka_client import Topics

# Consumer registration
@kafka_client.message_handler(Topics.JOB_LISTING_CREATED, ListingCreated, group_id="...")

# Direct publish
await kafka_client.publish(Topics.JOB_CORRELATION_EVALUATED, event, key=listing_id)

# Outbox serialization (user-auth-service pattern)
payload = kafka_client.serialize(Topics.USER_AUTH_ACCOUNT_UPDATED, event)
```

### `@kafka_client.with_db_session()`

Injects a SQLAlchemy `AsyncSession` into `context.db_session` before the handler runs and
auto-commits on success. On exception, rolls back and re-raises. The session factory must be
registered before `start_consumers()` is called:

```python
kafka_client.set_db_session_factory(get_async_sessionmaker(settings.database))
```

When `schema` is provided, an `OutboxWriter` is also created and injected into `context.outbox`,
enabling handlers to write CDC events atomically within the same transaction:

```python
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_command(message: MyCommand, context: MessageContext) -> None:
    db = context.require_db_session()
    outbox = context.require_outbox()
    entity = await create_entity(db, message)
    await outbox.write_event(db, OutboxEventParams(...), event)
    # session auto-commits, Debezium captures from WAL
```

### `@kafka_client.with_resilience()`

Overrides service-level retry/DLQ settings for one handler. Fields left as `None` inherit the
global `ResilienceSettings` from the service's `KafkaSettings`. Only specify what differs:

```python
@kafka_client.message_handler(Topics.ML_EMBEDDING_REQUESTED, EmbeddingRequested, group_id="...")
@kafka_client.with_resilience(max_retries=5, retry_backoff_ms=2000, max_backoff_ms=60000)
async def handle_embedding_requested(message: EmbeddingRequested, _context: MessageContext) -> None:
    ...
```

### `@kafka_client.transactional`

Marks a handler as transactional, which sets `preserve_partition_order=False` and
`is_transactional=True` on the registration. Currently a metadata marker. In practice, it signals
to readers that the handler is order-independent, and it may be used by future
infrastructure to enable Kafka transactions on the producer side.

### `max_concurrent_handlers`

Controls how many handler coroutines may run simultaneously within one consumer group. Default
is 10. Valid range: 1-200. Tune per workload:

| Workload type | Setting | Rationale |
| --------------- | --------- | ----------- |
| CPU-bound (ML compute, heavy inference) | 1-2 | Avoid thrashing; one task saturates the CPU |
| I/O-bound (DB projection updates, pure routing) | 15-20 | Overlap I/O wait across messages |
| Mixed (LLM calls with DB writes) | 5-10 | Balance I/O overlap with connection pool pressure |

Set via environment variable: `KAFKA__CONSUMER__MAX_CONCURRENT_HANDLERS=20`

## API Reference

### Factory

- **`create_kafka_client(settings, *, auto_start_consumers=False) -> AutoKafkaClient`** --
  Creates the `AutoKafkaClient` singleton from a settings object that satisfies `HasKafkaSettings`
  (i.e., has `.service_name`, `.kafka: KafkaSettings`, and `.observability`). Stores the instance
  globally so `get_kafka_client()` works anywhere afterward. `auto_start_consumers=False` is
  correct for all services. Consumers start explicitly in the lifespan after other setup completes.

- **`get_kafka_client() -> AutoKafkaClient`** -- Returns the singleton. Raises `RuntimeError` if
  `create_kafka_client()` has not been called.

- **`ensure_kafka_ready(bootstrap_servers) -> None`** -- Checks broker connectivity before
  starting consumers. Call in lifespan after database init, before `start_consumers()`.

### `AutoKafkaClient` methods

- **`message_handler(topic, message_type, *, group_id, middleware=None, preserve_partition_order=True)`** --
  Decorator. Registers a handler for `topic`, deserializing incoming messages as `message_type`
  (a betterproto2 class). `group_id` is required. `preserve_partition_order=True` (default) means
  messages within the same partition are processed sequentially; set `False` for fully
  idempotent, order-independent handlers to allow full concurrency across all partitions.

- **`with_db_session(schema=None, *, auto_commit=True)`** -- Decorator. Injects an
  `AsyncSession` into `context.db_session`. When `schema` is provided, also injects an
  `OutboxWriter` into `context.outbox`. Requires `set_db_session_factory()` to have been called.

- **`with_resilience(*, max_retries, retry_backoff_ms, max_backoff_ms, strategy)`** -- Decorator.
  Per-handler override of service-level resilience defaults. All parameters are optional; omitted
  parameters inherit from `KafkaSettings.resilience`.

- **`transactional`** -- Decorator (no arguments). Marks the handler as order-independent.

- **`set_db_session_factory(factory)`** -- Registers the SQLAlchemy `async_sessionmaker` used by
  `@with_db_session`. Must be called before `start_consumers()`.

- **`start_consumers() -> asyncio.Task[None] | None`** -- Boots all registered handlers and returns
  the task that owns the complete consumer generation. Groups handlers by `group_id`, creating
  one supervised `KafkaConsumer` plus one `RetryConsumer` per group. Existing callers may ignore
  the return value when health-based supervision is sufficient.

- **`wait_for_consumers()`** -- Awaits the active generation owner. It blocks while consumers are
  healthy and propagates the exact startup or child-task exception if the generation fails.

- **`supervise_consumer_failures()`** -- Async context manager for service lifespans. Enter it
  after `start_consumers()` and place the lifespan `yield` inside it. A fatal owner failure
  cancels the code inside the context and propagates through its `TaskGroup` to the ASGI process
  supervisor. Normal context exit cancels only the monitor, not the healthy consumer generation.
  Entering before consumers are started raises `KafkaClientError`.

- **`stop_consumers(drain_timeout_seconds=30.0)`** -- Two-phase graceful shutdown. Signals
  supervisor to stop, cancels tasks, waits for in-flight handlers to finish, force-cancels
  anything still running after `drain_timeout_seconds`.

- **`close()`** -- Stops consumers and closes the producer. Safe to call multiple times. Call
  after `stop_consumers()` in lifespan shutdown.

- **`publish(topic, message, key=None, headers=None) -> MessageMetadata`** -- Publishes a
  betterproto2 message. Lazy-initializes the producer on first call.

- **`publish_raw(topic, value, key=None, headers=None) -> MessageMetadata`** -- Publishes raw
  bytes. Used internally by the outbox pattern and DLQ handler.

- **`publish_json(topic, value, key=None, headers=None) -> MessageMetadata`** -- Publishes a
  `dict` as JSON. Used by `ml-compute-service` to publish to the Qdrant Kafka Sink Connector
  via `ml.fct.embedding-completed-json.v1`. Application-data Qdrant mutations belong to
  entity lifecycle owners via `nohiki-qdrant-client`; do not add new callers of `publish_json`.

- **`serialize(topic, message) -> bytes`** -- Serializes a betterproto2 message to wire bytes
  without publishing. Used by services that write to the transactional outbox directly
  (e.g., `user-auth-service`).

- **`ensure_producer_ready()`** -- Explicitly initializes the producer. Call in lifespan startup
  for services that publish before handling any consumed message (e.g., BFF command handlers).

- **`get_health_state() -> dict`** -- Returns consumer readiness for K8s health probes:
  `consumers_ready`, `handlers_registered`, `consumers_active`, `consumer_tasks_running`,
  `consumer_failure`, `consumer_failure_type`, `shutdown_requested`, and a per-consumer health
  summary from the supervisor. Fatal generation state is also synchronized to the shared
  `KafkaLifecycleManager` consumed by `KafkaHealthProbe`.

### `MessageContext`

```python
@dataclass(slots=True)
class MessageContext:
    topic: str
    partition: int
    offset: int
    timestamp: int
    headers: dict[str, str]
    key: str | None
    retry_count: int = 0
    correlation_id: str | None = None
    kafka_client: KafkaPublisher | None = None
    db_session: AsyncSession | None = None      # set by @with_db_session
    outbox: OutboxWriter | None = None          # set by @with_db_session(schema=...)
    session_factory: async_sessionmaker | None = None  # set by @with_db_session

    async def publish(topic, message, key=None, headers=None) -> MessageMetadata
    def require_db_session() -> AsyncSession       # raises if not @with_db_session
    def require_session_factory() -> async_sessionmaker
    def require_outbox() -> OutboxWriter           # raises if schema not provided
```

### Event metadata

- **`create_event_metadata(source_service, correlation_id=None, *, causation_id=None, version="v1") -> EventMetadata`**
  -- Creates the standard `nohiki.common.v1.EventMetadata` envelope with a new UUIDv7 event ID and
  UTC timestamp. All services use this when constructing outgoing events:

  ```python
  from nohiki_kafka_client import create_event_metadata, Topics

  event = ListingCreated(
      metadata=create_event_metadata(settings.service_name, correlation_id=str(listing_id)),
      listing_snapshot=snapshot,
  )
  ```

### Callback state

- **`CallbackStateMixin`** -- Mixin for frozen dataclasses that need to survive round-trips
  through Kafka headers as `caller_context` bytes in the callback pattern. Provides `to_bytes()`
  (JSON serialize) and `from_bytes()` (JSON deserialize with unknown-field filtering for safe
  schema evolution):

  ```python
  @dataclass(frozen=True, slots=True)
  class PrefEmbeddingState(CallbackStateMixin):
      pref_id: str
      action: str   # "create" or "update"

  # Encode into the command's caller_context field
  state = PrefEmbeddingState(pref_id=str(pref.id), action="create")
  command = EmbeddingRequested(caller_context=state.to_bytes(), ...)

  # Recover in the callback handler
  state = PrefEmbeddingState.from_bytes(callback.caller_context)
  ```

### `KafkaAdmin`

```python
from nohiki_kafka_client import KafkaAdmin, TopicSpec

admin = KafkaAdmin(bootstrap_servers="localhost:29092")
result = await admin.ensure_topics([
    TopicSpec(name="my-topic.v1", num_partitions=3, replication_factor=1),
])
```

Used in integration tests and service init scripts to create topics if they do not exist.
`ensure_topics()` is idempotent. It ignores `TopicAlreadyExistsError`.

### `KafkaHealthProbe`

```python
from nohiki_kafka_client import KafkaCapability, KafkaHealthProbe

probe = KafkaHealthProbe(
    bootstrap_servers=settings.kafka.bootstrap_servers,
    capabilities=[KafkaCapability.PRODUCE, KafkaCapability.CONSUME],
)
is_healthy = await probe.check()
```

Used by `nohiki-fastapi-utils` health router for K8s readiness checks.

## Configuration

### `KafkaMixin`

Add `KafkaMixin` to the service's `Settings` class to declare a `kafka` field:

```python
from nohiki_core_settings import NohikiBaseSettings
from nohiki_kafka_client import KafkaMixin

class Settings(KafkaMixin, NohikiBaseSettings):
    model_config = SettingsConfigDict(env_prefix="MY_SERVICE_", env_nested_delimiter="__")
```

`KafkaMixin` enforces SSL in non-development environments via a `model_validator`.

### Environment variables

All Kafka settings use nested env var format with `KAFKA__` prefix (after the service's own
prefix). With `env_nested_delimiter="__"`:

| Variable | Default | Description |
| ---------- | --------- | ------------- |
| `KAFKA__DSN` | `kafka://localhost:29092` | Broker connection string |
| `KAFKA__CONSUMER_GROUP` | `default-group` | Base consumer group ID |
| `KAFKA__USE_SSL` | `false` | Enable TLS (required in production) |
| `KAFKA__CONSUMER__MAX_POLL_RECORDS` | `500` | Records per poll cycle |
| `KAFKA__CONSUMER__MAX_POLL_INTERVAL_MS` | `300000` | Max time between polls before broker removes consumer from group |
| `KAFKA__CONSUMER__SESSION_TIMEOUT_MS` | `30000` | Heartbeat timeout before broker marks consumer dead |
| `KAFKA__CONSUMER__HEARTBEAT_INTERVAL_MS` | `3000` | Heartbeat frequency |
| `KAFKA__CONSUMER__MAX_CONCURRENT_HANDLERS` | `10` | Concurrent handlers per group (1-200) |
| `KAFKA__RESILIENCE__MAX_RETRIES` | `3` | Retry attempts before DLQ |
| `KAFKA__RESILIENCE__RETRY_BACKOFF_MS` | `1000` | Base backoff between retries |
| `KAFKA__RESILIENCE__MAX_BACKOFF_MS` | `30000` | Backoff cap |
| `KAFKA__RESILIENCE__STRATEGY` | `republish` | DLQ strategy: `republish` or `log_only` |
| `KAFKA__RESILIENCE__TOPIC_PREFIX` | `dlq` | Prefix for DLQ topics |

## Testing

### Unit tests: testing mode

Pass `is_testing=True` directly to `AutoKafkaClient`, or use the test fixture from
`nohiki-test-utils`. In testing mode, `publish()`, `publish_raw()`, and `publish_json()` are
no-ops that return mock `MessageMetadata` -- no broker connection is made.

To test a handler directly, construct a `MessageContext` and call the handler function:

```python
import pytest
from unittest.mock import AsyncMock
from nohiki_kafka_client import MessageContext
from my_service.events.handlers import handle_listing_created

@pytest.mark.asyncio
async def test_handle_listing_created(mock_db_session):
    message = ListingCreated(listing_snapshot=make_snapshot())
    context = MessageContext(
        topic=Topics.JOB_LISTING_CREATED,
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key="listing-id",
    )
    context.db_session = mock_db_session
    context.kafka_client = AsyncMock()

    await handle_listing_created(message, context)

    mock_db_session.execute.assert_called_once()
```

Do not assert on `context.publish()` calls via the `kafka_client` field directly.
Mock `context.kafka_client` with `AsyncMock()` and assert on `.publish`.

### Integration tests -- `kafka_container` fixture

The library ships a session-scoped `kafka_container` pytest fixture in
`nohiki_kafka_client.testing`. Import it explicitly in integration test conftest files.
It is not auto-loaded:

```python
# tests/integration/conftest.py
from nohiki_kafka_client.testing import kafka_container  # noqa: F401 -- fixture registration

@pytest.fixture
def kafka_bootstrap(kafka_container: str) -> str:
    return kafka_container
```

The fixture uses `testcontainers` to spin up `confluentinc/cp-kafka:8.0.1` in KRaft mode
(no ZooKeeper). It skips automatically if Docker is unavailable. One container is created per
test session. Mark integration tests `@pytest.mark.requires_docker`.

Integration tests require the `[testing]` extra:

```toml
dependencies = [
    "nohiki-kafka-client[testing]==0.1.0",
]
```

## Design Decisions

**Why `auto_start_consumers=False` by default**: Services need to complete database migrations,
JWKS setup, and broker connectivity checks before accepting Kafka messages. If consumers started
automatically on handler decoration (which happens at import time, before any lifespan code
runs), handlers would receive messages before their dependencies are ready. Explicit
`start_consumers()` in the lifespan gives each service control over initialization order.

**Why retry state lives in Kafka headers**: Encoding retry count and next-retry timestamp as
message headers avoids all external state. The library uses no Redis or database table.
The main consumer never sleeps waiting for a retry delay; it publishes to the retry topic and commits immediately,
keeping its throughput independent of retry backoff times. The dedicated `RetryConsumer` handles
the sleeping, in a consumer whose sole purpose is to do exactly that.

**Why one `KafkaConsumer` per `group_id`**: Kafka requires all topics in one consumer's
subscription to be served by one group. Handlers with different `group_id` values need
independent offset tracking. A projection handler must not share an offset with a command
handler even if they consume the same topic. Each group gets its own supervised consumer,
which means failures in one group do not affect others.

**Why `preserve_partition_order=True` is the default**: Kafka's ordering guarantee is per-partition.
Processing messages from partition N concurrently with partition M is safe. Processing two
messages from the same partition N concurrently is not safe for stateful handlers because a
later message could be processed before an earlier one, causing incorrect state. Setting
`preserve_partition_order=False` is appropriate only for fully idempotent handlers (e.g.,
BFF projection upserts with `ON CONFLICT DO NOTHING`).
