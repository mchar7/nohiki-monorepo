# Job Ingest Schedule Service Database Schema

Schema `job_schedule_schema` stores the materialized scheduling state for all registered search
queries: their configuration, activation status, and next/last execution timestamps. This schema
is a projection of events from the job-query-composition-service; it does not own the query
definitions, only the scheduling metadata derived from them.

## Entity Overview

| Table | Purpose |
|-------|---------|
| `ingestion_schedules` | One row per registered search query; tracks scheduling state and denormalized query parameters |
| `processed_events` | Consumer-side idempotency log; prevents duplicate processing of Kafka messages |

`ingestion_schedules` is the sole domain table. Each row corresponds to a query owned by
`job_query_schema`, referenced by `query_id` (UUID, no cross-schema FK). `processed_events`
guards consumed Kafka messages against at-least-once redelivery. Discovery commands are
published directly to Kafka; this schema has no outbox table.

## Table Details

### `ingestion_schedules`

#### Purpose

Represents the scheduling state for a single search query. Stores the full set of search
parameters denormalized from the job-query-composition-service's CDC events alongside
the scheduling fields (`frequency`, `is_active`, `next_run_at`, `last_run_at`) that the
tick handler uses to determine which queries are due for execution.

#### Key Columns

- **`query_id`** (`UUID`): Primary key. Carries the `query_id` from the
  `job-query-composition-service`. Not generated here: it is sourced directly from the
  `JOB_QUERY_CREATED` / `JOB_QUERY_UPDATED` event payload. Acts as the cross-schema
  reference to `job_query_composition_schema.queries.id`.
- **`search_keywords`** (`VARCHAR[]`): Array of keyword strings for the scrape query,
  e.g., `["software engineer", "python"]`.
- **`locations`** (`JSONB`): Array of location objects, each with integer-encoded `country`
  (proto `CountryCode` enum value), `location_type` (proto `LocationType` enum value),
  and optional string fields `city` and `state_province`. Validated by the
  `chk_locations_json_array` check constraint.
- **`work_arrangements`** (`work_arrangement_enum[]`): PostgreSQL enum array. Values are the
  string names of the proto `WorkArrangement` enum: `ON_SITE`, `HYBRID`, `REMOTE`. The
  `UNSPECIFIED` variant is filtered out on write. Python property accessors convert between
  string names and proto enum instances at the ORM boundary.
- **`sources`** (`job_board_source_enum[]`): PostgreSQL enum array of job board platforms to
  scrape: `INDEED`, `LINKEDIN`, `ZIPRECRUITER`, `GOOGLE`, `GLASSDOOR`, `BAYT`, `NAUKRI`,
  `COMPANY_WEBSITE`. `UNSPECIFIED` is filtered out on write.
- **`hours_old`** (`INTEGER`): How many hours back the scraper should search for listings.
  Defaults to `72`. Set by service configuration, not from the event payload.
- **`results_wanted`** (`INTEGER`): Target number of results per scrape run. Defaults to `50`.
  Set by service configuration, not from the event payload.
- **`frequency`** (`INTERVAL`): How often this query runs, stored as a PostgreSQL interval.
  Sourced from `frequency_seconds` in the event payload (converted to `timedelta`). Defaults
  to `1 day`.
- **`is_active`** (`BOOLEAN`): Whether the scheduler should dispatch this query on ticks.
  Inactive queries are skipped entirely by the due-schedule query. Defaults to `false`.
- **`next_run_at`** (`TIMESTAMPTZ`): The next time the scheduler should dispatch this query.
  `NULL` for inactive queries. On activation it is set one frequency interval after the immediate
  dispatch timestamp; the scheduler advances it by `frequency` after each successful dispatch.
- **`last_run_at`** (`TIMESTAMPTZ`): The timestamp of the most recent successful dispatch.
  `NULL` until the first tick processes this query. Updated alongside `next_run_at` after
  each dispatch.
- **`created_at`** / **`updated_at`** (`TIMESTAMPTZ`): Standard audit timestamps, both
  defaulting to `now()` at row creation.

#### Indexes

- **`idx_schedules_due`** (partial B-tree on `next_run_at` WHERE `is_active = true AND next_run_at IS NOT NULL`):
  The primary read path for the tick handler. The `process_due_schedules` query filters on
  `is_active = true` and `next_run_at <= now()`; this partial index covers both predicates and
  eliminates inactive rows from the index entirely, keeping it compact.
- **`idx_schedules_active_hash`** (HASH on `is_active`): Supports equality lookups on
  `is_active`. Hash indexes are smaller and faster than B-tree for single-value equality
  predicates on low-cardinality boolean columns.
- **`idx_schedules_created_at_brin`** (BRIN on `created_at`, `pages_per_range = 32`):
  Supports time-range queries on creation timestamp. BRIN is appropriate here because rows are
  largely append-ordered and the index has minimal storage overhead.

#### Constraints

- **PRIMARY KEY** on `query_id`: Enforces one schedule row per query. Also serves as the
  idempotency key for `JOB_QUERY_CREATED` handlers: the handler checks for an existing row
  before inserting.
- **CHECK `chk_locations_json_array`** (`locations IS JSON ARRAY`): Database-level validation
  that the `locations` JSONB column always contains a JSON array, not a bare object or scalar.

- **CHECK `ck_schedule_frequency_positive`** (`frequency > INTERVAL '0 seconds'`): Rejects
  invalid non-positive schedule intervals even if an application boundary is bypassed.

#### Data Lifecycle

- **Created** when `JOB_QUERY_CREATED` (`job-query.cdc.query-created.v1`) is consumed. The
  handler also creates a row when `JOB_QUERY_UPDATED` arrives for a `query_id` that has no
  existing row (out-of-order delivery guard).
- **Updated** when `JOB_QUERY_UPDATED` (`job-query.cdc.query-updated.v1`) is consumed
  (query parameters or activation state changed), or when `SYS_SCHEDULE_TICK` processing
  advances `last_run_at` and `next_run_at` after a successful dispatch.
- **Deleted** when `JOB_QUERY_DELETED` (`job-query.cdc.query-deleted.v1`) is consumed.
  The handler is idempotent: a missing row is treated as already deleted.

### `processed_events`

#### Purpose

Consumer-side idempotency store provided by `nohiki-db-utils`. Kafka delivers messages
at-least-once; this table records processed message IDs so handlers can skip redeliveries.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key, generated server-side.
- **`event_id`** (`VARCHAR`): The Kafka message offset or correlation ID used as the
  deduplication key.
- **`processed_at`** (`TIMESTAMPTZ`): When the event was first processed successfully.

#### Data Lifecycle

- **Created** on first successful processing of any Kafka message.
- **Never updated or deleted** -- the table grows monotonically as a deduplication log.

## Migration Strategy

Migrations are applied incrementally through Alembic. Revision `001` creates the scheduling and
consumer-idempotency tables, including the positive-frequency constraint. The schema has no
outbox table.

**Commands:**

```bash
# Apply migration
alembic upgrade head

# Generate updated migration after model changes
alembic revision --autogenerate -m "description"

# View current state
alembic current
```
