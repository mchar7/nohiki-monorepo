# Job Ingest Schedule Service

Tracks when each configured search query was last executed and dispatches scrape requests for
queries that are overdue. On every `SYS_SCHEDULE_TICK` event, this service queries its
`ingestion_schedules` table for active rows where `next_run_at <= now`, publishes a
`JOB_INGEST_DISCOVERY_REQUESTED` command for each, then advances `last_run_at` and `next_run_at`
forward by the query's configured frequency. Kafka-only, stateful with PostgreSQL and Redis.

## Role in the System

This service owns the "when to scrape" concern. It sits between the job query composition layer
and the job discovery layer: the job-query-composition-service defines which searches to run,
this service decides when to run them, and the job-ingest-discovery-service executes them.
No other service in the pipeline has visibility into scheduling state.

The trigger mechanism is a Kubernetes CronJob (`sys-tick-job`) that runs on a configured
schedule (typically every few minutes) and publishes a single `SYS_SCHEDULE_TICK` event to
`sys.fct.schedule-tick.v1`. This service consumes that tick and evaluates all registered
queries. There is no background async timer, no polling loop; the service is entirely
event-driven and sleeps between ticks.

When the job-query-composition-service creates or modifies a search query, this service receives
the corresponding `JOB_QUERY_CREATED` or `JOB_QUERY_UPDATED` CDC event, upserts the schedule
row with the denormalized query parameters, and (if the query is active) immediately dispatches
a first scrape rather than waiting for the next tick.

## Event-Driven Integration

### Events Consumed

- **`SYS_SCHEDULE_TICK`** (`sys.fct.schedule-tick.v1`, `ScheduleTick`): The heartbeat that
  drives all scheduling. On receipt, the handler calls `process_due_schedules`, which selects
  active rows with `next_run_at <= now` using `SELECT … FOR UPDATE SKIP LOCKED` (safe for
  concurrent consumers), publishes a `JOB_INGEST_DISCOVERY_REQUESTED` event for each, then
  updates `last_run_at` and advances `next_run_at` by the row's `frequency` interval. The tick
  event carries an optional `batch_limit` that overrides the service-level default (100); a
  value of `0` falls back to the default. Consumer group: `{consumer_group}-ticks`.

- **`JOB_QUERY_CREATED`** (`job-query.cdc.query-created.v1`, `IngestionQueryChanged`): Signals
  that the job-query-composition-service has composed a new search query. The handler creates a
  new `ingestion_schedules` row, denormalizing search keywords, locations, work arrangements,
  sources, and frequency from the event payload. If the query is active at creation, it
  immediately publishes a `JOB_INGEST_DISCOVERY_REQUESTED` event (the first scrape does not wait
  for the next tick). Idempotent: skips creation if a row with the same `query_id` already
  exists. Consumer group: `{consumer_group}`.

- **`JOB_QUERY_UPDATED`** (`job-query.cdc.query-updated.v1`, `IngestionQueryChanged`): Signals
  that an existing query's parameters or activation state changed. The handler updates all
  denormalized fields on the existing schedule row. If a query transitions from inactive to
  active and has no `next_run_at`, the handler sets it to `now` so the query runs on the next
  tick. If no row exists for the `query_id`, the handler creates one (covers out-of-order event
  delivery). Consumer group: `{consumer_group}`.

- **`JOB_QUERY_DELETED`** (`job-query.cdc.query-deleted.v1`, `IngestionQueryDeleted`): Signals
  that a query has been removed. The handler deletes the corresponding `ingestion_schedules` row.
  Idempotent: a missing row is treated as already deleted. Consumer group: `{consumer_group}`.

### Events Published

- **`JOB_INGEST_DISCOVERY_REQUESTED`** (`job-ingest.cmd.discovery-requested.v1`,
  `IngestionTriggered`): Published directly to Kafka before the schedule timestamps advance. Each
  run uses a deterministic UUID derived from `query_id` and its scheduled timestamp as the event
  ID, correlation ID, and Kafka key. The event carries the complete profile-agnostic
  `IngestionQuery` snapshot and no `user_id` or `pref_id`.

### Key Design Patterns

#### Tick-Driven Scheduling

The `sys-tick-job` is a one-shot Kubernetes CronJob. Each execution publishes exactly one
`ScheduleTick` event to `sys.fct.schedule-tick.v1`, then exits. The tick carries a
`batch_limit` field (defaults to `0`, meaning "use the service default") that caps how many
overdue schedules are processed per tick, preventing a large backlog from overwhelming the
discovery layer in a single burst.

#### `SELECT FOR UPDATE SKIP LOCKED`

`process_due_schedules` acquires a row-level lock on each due schedule before publishing its
command and updating it. `SKIP LOCKED` gives concurrent consumers non-overlapping schedule sets.
If direct Kafka publication fails, the exception propagates before either schedule timestamp changes.

#### Immediate Dispatch on Query Activation

When a new active query arrives, this service publishes a discovery request immediately and sets
its next run one frequency interval ahead.

## State & Persistence

### Database

Schema `job_schedule_schema` holds one `ingestion_schedules` row per registered query and
`processed_events` for consumer idempotency. It has no transactional outbox table.

See [DATABASE.md](./DATABASE.md) for complete schema documentation.

### Redis

Redis provides circuit breaker state for the Kafka client via `nohiki-redis-utils` (included
through `RedisMixin`). No application-level caching or locking uses Redis directly in this
service.

## Configuration

Settings use `NohikiBaseSettings` with `DatabaseMixin`, `RedisMixin`, and `KafkaMixin`. The
env prefix is `JOB_INGEST_SCHEDULE_`.

**Service-specific settings** (`JOB_INGEST_SCHEDULE_SCHEDULER__*`):

| Variable | Default | Description |
| ---------- | --------- | ------------- |
| `SCHEDULER__DEFAULT_HOURS_OLD` | `72` | How many hours back scrapers search for listings |
| `SCHEDULER__DEFAULT_RESULTS_WANTED` | `50` | Target result count per scrape run |
| `SCHEDULER__BATCH_LIMIT` | `100` | Maximum schedules processed per tick (overridden by tick event if non-zero) |

**Kafka concurrency**: `max_concurrent_handlers` is set to `5`. Tick handling is I/O-bound
(PostgreSQL query + Kafka publish per due schedule), so a low concurrency limit is appropriate
given the CronJob-driven arrival rate.

## Development

### Local Setup

```bash
uv sync
cd backend/services/job-ingest-schedule-service
alembic upgrade head
```

### Testing

```bash
just test job-ingest-schedule-service
just test-cov job-ingest-schedule-service
```

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise backend/services/job-ingest-schedule-service/
uv run ty check
```

Requires a running PostgreSQL instance with the `job_schedule_schema` schema applied and a
reachable Kafka broker. Use `just infra-up` to start the local infrastructure stack.
