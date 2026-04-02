# Nohiki DB Utils

Provides async SQLAlchemy engine management, the transactional outbox writer, distributed Alembic
migration coordination, the multi-callback saga pattern, idempotency deduplication, database health
probes, and a collection of SQLAlchemy model mixins used across all 13 stateful Nohiki services.

## Quick Start

```python
from nohiki_db_utils import (
    DatabaseDependencies,
    OutboxEventParams,
    close_all_engines,
    initialize_database,
)
from fastapi import Depends

# In service lifespan startup
await initialize_database(settings)  # runs Alembic migrations with distributed lock

# Wires up FastAPI Depends() generators for db sessions and outbox writer
db_deps = DatabaseDependencies(settings.database, outbox_schema=settings.database.schema_name)
get_async_db = db_deps.get_async_db
get_outbox = db_deps.get_outbox

# In a FastAPI route or Kafka handler
async def handle_create(db: AsyncSession = Depends(get_async_db), outbox: OutboxWriter = Depends(get_outbox)):
    entity = MyEntity(...)
    db.add(entity)
    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type="job",
            aggregate_id=str(entity.id),
            event_type=Topics.JOB_LISTING_CREATED,
        ),
        event=listing_created_proto,
    )
    await db.commit()  # entity + outbox row committed atomically

# In service lifespan shutdown
await close_all_engines()
```

## Core Concepts

### Engine Management

`get_async_engine()` and `get_async_sessionmaker()` return cached instances keyed by connection
string. The first call creates the engine with a fixed pool configuration (pool size 3, max
overflow 2, 5-minute recycle, pre-ping enabled); subsequent calls return the cached instance.
Services never create engines directly. They go through `DatabaseDependencies` or call
`get_async_sessionmaker(settings.database)` to get a session factory.

`initialize_database(settings)` is the single startup entry point. It runs Alembic migrations
with distributed coordination (see Migrations below) if `DATABASE__MIGRATE_ON_STARTUP` is true,
which defaults to true in development. In production, migration-on-startup is disabled; migrations
run via the `nohiki-db-migrate` CLI or a pre-deploy Kubernetes Job.

`close_all_engines()` disposes all cached engines in parallel using `asyncio.TaskGroup`. Call
this in the FastAPI lifespan shutdown handler after stopping Kafka consumers.

### Transactional Outbox

The outbox pattern solves a fundamental problem in event-driven systems: if a service writes to
its database and then publishes to Kafka as two separate operations, a crash between them produces
either a committed write with no event, or a Kafka message for a rolled-back transaction.

`OutboxWriter` eliminates this by writing the event into an `outbox` table row within the *same
database transaction* as the domain data. Debezium monitors the PostgreSQL WAL and publishes any
new outbox rows to Kafka via the Outbox Event Router SMT. If the transaction rolls back, the
outbox row never appears in the WAL and the event is never published.

Each service has its own outbox table in its own schema. The `OutboxWriter` requires an explicit
`schema` argument because no default exists. A shared schema would create cross-service
coupling. The column names (`aggregatetype`, `aggregateid`, `type`, `payload`,
`tracingspancontext`) match Debezium's expected format exactly.

`write_event()` serializes a betterproto2 message via `bytes()` and inserts the row. For cases
where the service pre-serializes the payload itself (e.g., via `kafka_client.serialize()` for
envelope-aware serialization), use `write_event_raw()` which accepts `bytes` directly.

`OutboxWriter` does **not** commit the transaction. The caller commits, giving them control to
write multiple events or multiple domain records in a single atomic transaction.

### Saga Pattern

The saga pattern addresses a specific problem: a service issues N parallel async requests (e.g.,
two embedding requests to different ML pipelines) and must wait for all N callbacks before
publishing a downstream event. The saga table tracks how many callbacks have arrived and holds
any intermediate data from each callback until convergence.

#### Model Declaration

Define a service-specific SQLAlchemy model extending `SagaBaseMixin`. The mixin provides the
`id`, `status`, `expected_callbacks`, `received_callbacks`, `created_at`, `expires_at`, and
`version` columns. The subclass adds whatever domain data the service needs to carry across
callbacks:

```python
from nohiki_db_utils import SagaBaseMixin
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text

class Base(DeclarativeBase): ...

class EnrichmentEmbeddingSaga(SagaBaseMixin, Base):
    __tablename__ = "enrichment_embedding_saga"
    __table_args__ = {"schema": "job_ingest_enrichment_schema"}

    listing_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    enrichment_data_json: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_embedding_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    title_embedding_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
```

#### Repository Operations

`SagaRepository[T]` is a generic repository instantiated with the concrete model class. One
instance per model type is sufficient. Create it at module level:

```python
_saga_repo: SagaRepository[EnrichmentEmbeddingSaga] = SagaRepository(EnrichmentEmbeddingSaga)
```

#### Creating a Saga

When the service is ready to issue its parallel requests, create the saga first so that incoming
callbacks can reference it by ID:

```python
from datetime import UTC, datetime, timedelta

saga = EnrichmentEmbeddingSaga(
    listing_id=listing_id,
    enrichment_data_json=json.dumps(context_data),
    expected_callbacks=2,            # waiting for retrieval + title embeddings
    expires_at=datetime.now(UTC) + timedelta(minutes=30),
)
saga = await _saga_repo.create(db, saga)
await db.commit()

# Embed saga_id into each callback's caller_context so callbacks can look it up
saga_ctx = json.dumps({"saga_id": str(saga.id)}).encode()
```

#### Recording a Callback

Each callback handler loads the saga by ID, records the callback-specific data, increments the
counter, and checks whether the saga is now complete:

```python
saga_id = UUID(json.loads(message.callback.caller_context)["saga_id"])

def _update(saga: EnrichmentEmbeddingSaga) -> None:
    match embedding_type:
        case "retrieval":
            saga.retrieval_embedding_b64 = embedding_b64
        case "title":
            saga.title_embedding_b64 = embedding_b64

saga, is_complete = await _saga_repo.record_callback(db, saga_id, update_fn=_update)

if not is_complete:
    await db.commit()  # save partial progress; wait for the other callback
    return

# All callbacks received: converge and publish
await _converge_and_publish(db, saga)
```

`record_callback()` uses `SELECT ... FOR UPDATE` to serialize concurrent callback arrivals.
The `version` column provides optimistic locking: if two callbacks arrive simultaneously on
different pods, one will win the row lock and the other will retry from the top of the handler.
The function returns `(saga, is_complete)`. `is_complete` is `True` when
`received_callbacks >= expected_callbacks`.

#### Completing a Saga

When `is_complete` is `True`, write the final outbox event and transition the saga to `COMPLETED`
atomically. `SagaRepository.complete()` handles both in the same flush:

```python
await _saga_repo.complete(
    db,
    saga,
    outbox_writer=outbox,
    outbox_params=OutboxEventParams(
        aggregate_type="job",
        aggregate_id=listing_id,
        event_type=Topics.JOB_INGEST_ENRICHMENT_COMPLETED,
    ),
    outbox_event=enrichment_completed_proto,
)
await db.commit()
```

Alternatively, services that build the event themselves can call `saga.transition_to(SagaStatus.COMPLETED)`
and `publish_enrichment_completed_outbox()` directly before committing, as `job-ingest-enrichment-service`
does in `_converge_and_publish()`.

#### Stale Saga Detection

Sagas that never receive all their callbacks (because an upstream ML worker died) accumulate in
PENDING state indefinitely. `StaleSagaDetector` runs periodically to transition them to EXPIRED:

```python
from nohiki_db_utils import StaleSagaDetector
from datetime import timedelta

detector = StaleSagaDetector(EnrichmentEmbeddingSaga, max_age=timedelta(minutes=30))

# In a periodic background task
async def cleanup_loop():
    while True:
        async with db_sessionmaker() as db:
            await detector.run(db)
            await db.commit()
        await asyncio.sleep(300)
```

`StaleSagaDetector.run()` delegates to `SagaRepository.expire_stale()`, which queries for all
PENDING sagas with `expires_at` before `now() - max_age` and transitions them to EXPIRED.

#### State Transitions

`SagaBaseMixin` inherits from `StateMachineMixin`, which validates state transitions against a
declared transition map. The saga lifecycle is:

```text
PENDING → COMPLETED  (all callbacks received, outbox event written)
PENDING → FAILED     (an embedding or upstream operation reported an error)
PENDING → EXPIRED    (StaleSagaDetector found it past expires_at)
```

COMPLETED, FAILED, and EXPIRED are terminal. No further transitions are permitted.
`saga.transition_to(SagaStatus.FAILED)` raises `InvalidTransitionError` if the saga is not
in PENDING state.

### Migrations

`initialize_database(settings)` coordinates Alembic migrations across multiple pods using
PostgreSQL advisory locks. One pod acquires a lock keyed on `CRC32("migration:{service_name}")`,
runs `alembic upgrade head`, then releases the lock. Other pods poll and wait. If the pod holding
the lock crashes, the remaining pods detect the stale lock via a timeout and attempt to take over.

Migration state (status, current/target revision, timestamps) is tracked in a module-level
singleton accessible via `get_migration_state()`. `DatabaseHealthProbe` queries this singleton
to report migration status on the K8s readiness endpoint.

To create a new migration:

```bash
just migrate-new <service-name> "describe the change"
just migrate <service-name>       # applies: alembic upgrade head
```

Each service's Alembic `env.py` calls `run_online_migrations()` and `configure_offline_context()`
from this library for consistency.

The outbox table itself is created via Alembic migrations using SQL helpers from
`outbox_migrations`:

```python
# In a service's initial Alembic migration
from nohiki_db_utils import get_create_outbox_table_sql, get_create_outbox_indexes_sql

def upgrade() -> None:
    op.execute(get_create_outbox_table_sql("my_service_schema"))
    op.execute(get_create_outbox_indexes_sql("my_service_schema"))
```

### Health Probes

`DatabaseHealthProbe` checks PostgreSQL connectivity by executing `SELECT 1` and optionally
verifying that migration state is `completed`. It returns HEALTHY, DEGRADED (latency above
threshold), or UNHEALTHY:

```python
from nohiki_db_utils import DatabaseHealthProbe, get_async_engine

DatabaseHealthProbe(
    get_async_engine(settings.database),
    timeout_seconds=5.0,
    degraded_threshold_ms=100.0,
    check_migrations=True,
)
```

`ensure_database_ready(engine)` blocks service startup until PostgreSQL responds successfully,
retrying every 2 seconds up to a configurable timeout (default 60s). Services that use it call
it before starting Kafka consumers.

`OutboxHealthProbe` counts rows in the outbox table. A high count indicates that Debezium is
lagging behind the WAL. The service is writing events faster than CDC can publish them.

### Model Mixins

All stateful services inherit these mixins to avoid duplicating common column definitions:

- **`BaseEntity`** -- `UUIDPrimaryKeyMixin` + `AuditMixin` + `RepresentableMixin`. The standard
  base for domain entities. Primary key is a UUIDv7 generated server-side by a PostgreSQL
  function, providing time-sortable keys with index locality.
- **`UserBaseEntity`** -- Same as `BaseEntity` plus `created_by`/`updated_by` UUID columns for
  user-attributed records.
- **`AuditMixin`** -- `created_at` and `updated_at` timestamp columns with server-side defaults.
- **`FreshnessTrackingMixin`** -- `last_used_at` and `usage_count` columns plus `record_usage()`
  and `is_stale` helpers. Used by `doc-template-service` to detect unused templates.
- **`StateMachineMixin`** -- Validates state transitions against a declared transition map.
  Subclasses declare `__transitions__` and call `entity.transition_to(NewStatus)`. Raises
  `InvalidTransitionError` on invalid transitions.

### Idempotency

`check_and_mark_processed(db, schema, event_id, handler_name)` uses `INSERT ... ON CONFLICT DO NOTHING`
to atomically mark a Kafka event as processed. Returns `True` if the event is new, `False` if
it was already processed. The check commits together with the handler's own transaction, so the
mark is durable only if the handler's work commits successfully:

```python
is_new = await check_and_mark_processed(
    db, schema="my_schema", event_id=message.metadata.event_id, handler_name="handle_listing_created"
)
if not is_new:
    return  # duplicate delivery, skip
```

SQL helpers for creating the `processed_events` table and its index are available via
`get_create_processed_events_sql()`, `get_create_processed_events_index_sql()`, and
`get_cleanup_processed_events_sql()` for use in Alembic migrations.

### Full-Text Search

`build_prefix_tsquery(raw_query)` sanitizes user input and builds a PostgreSQL `tsquery` string
with prefix-matching operators. All alphanumeric tokens are extracted, joined with `&` (AND), and
suffixed with `:*` for prefix matching. Used by `bff-service` listing and skill search endpoints:

```python
from nohiki_db_utils import build_prefix_tsquery

tsquery = build_prefix_tsquery("python kube")
# → "python:* & kube:*"
```

### Pagination

`paginate_query(db, query, offset=..., limit=...)` executes a COUNT subquery and a paginated
SELECT in sequence, returning a `PaginationResult[T]` with `items` and `total`. Used by BFF
list endpoints to avoid duplicating offset/limit/count boilerplate:

```python
from nohiki_db_utils import PaginationResult, paginate_query

result: PaginationResult[ListingRow] = await paginate_query(
    db, base_query, offset=page * page_size, limit=page_size
)
return {"items": result.items, "total": result.total}
```

### Distributed Seeding

`run_seeding_with_coordination(config, seed_function)` mirrors the migration coordinator pattern
for initial data seeding. One pod acquires an advisory lock, runs the seed function, and records
the seed version. Other pods wait, then verify the version is applied and skip. Used by
`doc-template-service` to seed default document templates on first deployment.

### Event Metadata

`create_event_metadata(source_service, correlation_id)` builds a standard `EventMetadata`
protobuf with a new UUIDv7 `event_id` and current UTC timestamp. Services use this when
constructing events for the outbox rather than duplicating metadata creation:

```python
from nohiki_db_utils import create_event_metadata

event = ListingCreated(
    metadata=create_event_metadata(settings.service_name, ctx.correlation_id),
    listing_snapshot=snapshot,
)
```

## API Reference

### Engine and Session

- **`initialize_database(settings)`** -- Runs Alembic migrations with distributed advisory lock
  coordination. Call once in FastAPI lifespan startup. Reads `settings.database.migrate_on_startup`.
- **`get_async_engine(db_settings)`** -- Returns or creates the cached async engine for the given
  settings. Engine parameters: pool_size=3, max_overflow=2, pool_timeout=10, pool_recycle=300,
  pool_pre_ping=True.
- **`get_async_sessionmaker(db_settings)`** -- Returns or creates the cached async sessionmaker.
  Sessions are created with `expire_on_commit=False`.
- **`DatabaseDependencies(db_settings, outbox_schema)`** -- Container for FastAPI `Depends()`
  generators. Provides `get_async_db` and `get_outbox` async generators for injection into
  route handlers and Kafka handlers.
- **`db_session(db_settings)`** -- Returns a bare async session context manager. Useful for
  Kafka handlers that don't use FastAPI dependency injection.
- **`close_all_engines()`** -- Disposes all cached engines in parallel. Call in lifespan shutdown.
- **`reset_db(engine, base_metadata)`** -- Drops and recreates all tables. Test utility only.

### Outbox

- **`OutboxWriter(schema, db=None)`** -- Writes events to the outbox table. Requires `schema`.
  Can be bound to a session at construction or receive one per `write_event()` call.
- **`OutboxWriter.write_event(db, params, event)`** -- Serializes `event` via `bytes()` and
  inserts an outbox row. Returns the UUID of the new row.
- **`OutboxWriter.write_event_raw(db, params, payload)`** -- Inserts pre-serialized bytes.
  Used when the service handles serialization itself (e.g., with Kafka envelope headers).
- **`OutboxEventParams`** -- Frozen dataclass: `aggregate_type`, `aggregate_id`, `event_type`,
  `correlation_id` (optional).
- **`OutboxEntry`** -- Frozen dataclass representing an outbox row (returned/used in tests).
- **`get_create_outbox_table_sql(schema)`** -- SQL for the outbox table Alembic migration.
- **`get_create_outbox_indexes_sql(schema)`** -- SQL for the outbox table timestamp index.

### Saga

- **`SagaBaseMixin`** -- SQLAlchemy mixin providing `id`, `status`, `expected_callbacks`,
  `received_callbacks`, `created_at`, `expires_at`, `version`, and `is_complete` property.
  Also inherits `StateMachineMixin` with predefined transitions.
- **`SagaRepository[T](model_cls)`** -- Generic repository for a concrete saga model.
  - **`create(db, saga)`** -- Inserts the saga row and returns it with server-generated defaults.
  - **`load(db, saga_id)`** -- Loads by ID. Returns `None` if not found.
  - **`record_callback(db, saga_id, *, update_fn)`** → `tuple[T, bool]` -- Increments
    `received_callbacks`, calls `update_fn(saga)`, bumps version. Returns `(saga, is_complete)`.
    Raises `NoResultFound` if saga not found. Raises `InvalidTransitionError` if not PENDING.
  - **`complete(db, saga, *, outbox_writer, outbox_params, outbox_event)`** -- Transitions to
    COMPLETED and writes the outbox event atomically.
  - **`fail(db, saga_id, *, reason)`** -- Transitions to FAILED.
  - **`find_stale(db, *, cutoff)`** -- Returns PENDING sagas with `expires_at < cutoff`.
  - **`expire_stale(db, *, max_age)`** -- Transitions expired sagas to EXPIRED. Returns count.
- **`SagaStatus`** -- StrEnum: `PENDING`, `COMPLETED`, `FAILED`, `EXPIRED`.
- **`StaleSagaDetector[T](model_cls, max_age=timedelta(minutes=30))`** -- Wraps a
  `SagaRepository` for periodic cleanup. Call `await detector.run(db)` in a background task.

### SQLAlchemy Mixins

- **`BaseEntity`** -- UUID PK + `created_at`/`updated_at` + auto-repr. Standard entity base.
- **`UserBaseEntity`** -- Same as `BaseEntity` plus `created_by`/`updated_by`.
- **`AuditMixin`** -- `created_at` + `updated_at` only.
- **`CreatedAtMixin`** -- `created_at` only.
- **`UpdatedAtMixin`** -- `updated_at` only.
- **`UUIDPrimaryKeyMixin`** -- `id` UUID column with `uuidv7()` server default.
- **`UserAuditMixin`** -- Extends `AuditMixin` with `created_by`/`updated_by`.
- **`RepresentableMixin`** -- Auto-generates `__repr__` from `id` and common field names.
- **`FreshnessTrackingMixin`** -- `last_used_at`, `usage_count`, `record_usage()`, `is_stale`.
  Override `__staleness_days__` (default 90).
- **`StateMachineMixin`** -- Declare `__transitions__` and `__status_field__`. Call
  `entity.transition_to(new_state)`. Raises `InvalidTransitionError` on invalid transitions.
- **`SchemaMixin`** -- Base for schema-qualified tables. Override `__table_args__`.
- **`SQL_NOW`** -- `sa.text("now()")` for server-side timestamp defaults.
- **`UUID_DEFAULT`** -- `sa.text("uuidv7()")` for server-side UUIDv7 primary key generation.

### Health

- **`DatabaseHealthProbe(engine, *, timeout_seconds, degraded_threshold_ms, check_migrations)`**
  -- Implements the `HealthProbe` protocol. Returns HEALTHY, DEGRADED, or UNHEALTHY. Pass to
  `build_probe_health_router()` from `nohiki-fastapi-utils`.
- **`ensure_database_ready(engine, *, timeout_seconds, retry_interval_seconds)`** -- Blocks
  startup with retry loop until database accepts connections.
- **`OutboxHealthProbe(session_factory, schema, *, max_backlog)`** -- Returns DEGRADED if the
  outbox row count exceeds `max_backlog` (default 100), indicating CDC lag.

### Migrations (requires `alembic` extra)

- **`initialize_database(settings)`** -- Top-level startup function. Handles migration
  coordination automatically.
- **`run_migrations_with_coordination(service_name, database_url, timeout_seconds, alembic_config_path)`**
  -- Low-level coordinator. Acquires advisory lock, runs Alembic, releases lock.
- **`get_migration_state()`** -- Returns the in-process `MigrationState` singleton.
- **`skip_migrations()`** -- Marks migration state as completed without running anything.
  Used by services with no database (e.g., Kafka-only services using this library only for health).
- **`MigrationState`** -- Dataclass with `status`, `current_revision`, `target_revision`, `error`.

### Other Utilities

- **`check_and_mark_processed(db, schema, event_id, handler_name)`** → `bool` -- Returns `True`
  if the event is new; `False` if already processed.
- **`create_event_metadata(source_service, correlation_id, *, causation_id, version)`** --
  Creates `EventMetadata` proto with a new UUIDv7 event ID and current timestamp.
- **`build_prefix_tsquery(raw_query)`** -- Builds PostgreSQL `tsquery` for prefix FTS matching.
- **`paginate_query(db, query, *, offset, limit)`** → `PaginationResult[T]` -- COUNT + SELECT.
- **`run_seeding_with_coordination(config, seed_function)`** -- Advisory-lock-coordinated seeding.

## Configuration

### `DatabaseMixin`

Add to a service's settings class to declare a required `database` field:

```python
from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin

class Settings(DatabaseMixin, NohikiBaseSettings):
    service_name: str = "my-service"
```

This adds a nested `database: DatabaseSettings` model populated from `DATABASE__*` environment
variables:

| Variable | Default | Description |
|---|---|---|
| `DATABASE__DSN` | required | PostgreSQL connection string (e.g., `postgresql://user:pw@host/db?sslmode=require`) |
| `DATABASE__SCHEMA_NAME` | required | Service-specific schema (e.g., `job_storage_schema`) |
| `DATABASE__POOL_SIZE` | `5` | SQLAlchemy connection pool size |
| `DATABASE__MAX_OVERFLOW` | `10` | Max connections above pool_size |
| `DATABASE__POOL_TIMEOUT` | `30` | Seconds to wait for a pool connection |
| `DATABASE__POOL_RECYCLE` | `1800` | Seconds before a connection is recycled |
| `DATABASE__MIGRATE_ON_STARTUP` | `true` in dev, `false` in prod | Run Alembic on service startup |
| `DATABASE__MIGRATION_TIMEOUT_SECONDS` | `900` | Max time to wait for distributed migration lock |

`DatabaseSettings` handles `sslmode` from the DSN query string. In production, `sslmode=disable`
and `sslmode=prefer` raise `ValueError`. The async engine receives an `ssl.SSLContext` via
`connect_args`; the `sslmode` param is stripped from the URL before passing to asyncpg (which
does not accept it as a URL parameter).

## Testing

The library ships a `testing` module with pytest fixtures for integration tests that need a real
PostgreSQL instance. These fixtures require Docker and are automatically skipped when the Docker
daemon is unavailable.

```python
# conftest.py: import from nohiki_db_utils.testing
from nohiki_db_utils.testing import (
    async_engine,
    async_session,
    async_session_factory,
    postgres_container,
)

# In a test
@pytest.mark.anyio
async def test_outbox_write(async_session: AsyncSession) -> None:
    outbox = OutboxWriter(schema="test_schema")
    params = OutboxEventParams(aggregate_type="test", aggregate_id="1", event_type="test.topic")
    entry_id = await outbox.write_event(async_session, params, my_proto)
    assert entry_id is not None
```

Available fixtures:

- **`postgres_container`** (session-scoped) -- Starts a `postgres:18-alpine` testcontainer.
  Returns the asyncpg connection URL. Skipped if Docker is unavailable.
- **`async_engine`** -- Creates an `AsyncEngine` backed by `postgres_container` with `NullPool`
  (no connection reuse between tests).
- **`async_session_factory`** -- `async_sessionmaker` for the test engine.
- **`async_session`** -- An open `AsyncSession` for a single test.

For unit tests that mock the database layer entirely, construct `AsyncMock` for the session and
use `SagaRepository` directly without a real database. The repository calls are pure
`db.execute()`, `db.add()`, `db.flush()`, and `db.refresh()` -- all easily mockable.

## Design Decisions

**Why per-service outbox schemas instead of a shared table?**
Each service writes to its own schema (e.g., `user_auth_schema.outbox`). This allows Debezium
connectors to be configured per-service, isolates WAL capture to each service's domain, and
prevents a high-write service from creating backlog that affects other services' CDC latency.

**Why UUIDv7 instead of UUIDv4?**
UUIDv7 encodes a millisecond-precision timestamp in the most significant bits. PostgreSQL btree
indexes on UUID primary keys stay compact and sequential because new rows are always appended
near the end of the index, avoiding the page splits that random UUIDv4 values cause under
write-heavy load.

**Why PostgreSQL advisory locks for migration coordination instead of Redis?**
Advisory locks use the same database connection that Alembic needs to run migrations. This means
no additional infrastructure dependency at startup time, and the lock is automatically released
if the connection drops (e.g., pod crash), preventing permanent lock stalls.

**Why does `record_callback` use `SELECT ... FOR UPDATE` rather than optimistic locking?**
Saga callbacks from different embedding types can arrive within milliseconds of each other on
different consumer threads or pods. Optimistic locking (compare-and-swap on version) would cause
retries. `SELECT ... FOR UPDATE` serializes access at the row level, which is acceptable because
the lock is held only for the duration of the increment-and-flush operation, which takes at most a few milliseconds.
