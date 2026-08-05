# Job Ingest Schedule Service Database Design

Schema `job_schedule_schema` stores the materialized scheduling state for all registered search
queries: their configuration, activation status, and next/last execution timestamps. This schema
is a projection of events from the job-query-composition-service; it does not own the query
definitions, only the scheduling metadata derived from them.

`ingestion_schedules` is the sole domain table. Each row corresponds to a query owned by
`job_query_schema`, referenced by `query_id` (no cross-schema FK). Discovery commands are
published directly to Kafka; this schema has no outbox table.

## `ingestion_schedules`

### Purpose

Represents the scheduling state for a single search query. Stores the full set of search
parameters denormalized from the job-query-composition-service's CDC events alongside
the scheduling fields (`frequency`, `is_active`, `next_run_at`, `last_run_at`) that the
tick handler uses to determine which queries are due for execution.

### Field Semantics

- **`query_id`**: Carries the `query_id` from the `job-query-composition-service`. Not generated
  here: it is sourced directly from the `JOB_QUERY_CREATED` / `JOB_QUERY_UPDATED` event payload.
  Enforces one schedule row per query. Also serves as the idempotency key for
  `JOB_QUERY_CREATED` handlers: the handler checks for an existing row before inserting.
- **`work_arrangements`**: The `UNSPECIFIED` variant is filtered out on write. Python property
  accessors convert between string names and proto enum instances at the ORM boundary.
- **`sources`**: Job board platforms to scrape. `UNSPECIFIED` is filtered out on write.
- **`hours_old`**: How many hours back the scraper should search for listings. Not sourced from
  the event payload.
- **`results_wanted`**: Target number of results per scrape run. Not sourced from the event
  payload.
- **`frequency`**: How often this query runs. Sourced from `frequency_seconds` in the event
  payload (converted to `timedelta`).
- **`is_active`**: Whether the scheduler should dispatch this query on ticks. Inactive queries
  are skipped entirely by the due-schedule query.
- **`next_run_at`**: The next time the scheduler should dispatch this query. `NULL` for inactive
  queries. On activation it is set one frequency interval after the immediate dispatch
  timestamp; the scheduler advances it by `frequency` after each successful dispatch.
- **`last_run_at`**: The timestamp of the most recent successful dispatch. `NULL` until the first
  tick processes this query. Updated alongside `next_run_at` after each dispatch.

### Access Patterns

The tick handler uses an access path over `next_run_at` restricted to active rows with a scheduled
run. `process_due_schedules` filters on `is_active = true` and `next_run_at <= now()`; the
restriction covers both predicates while keeping inactive rows out entirely.

A BRIN access path supports time-range queries on creation time. BRIN is appropriate because rows
are largely append-ordered and its storage overhead is minimal.

### Data Lifecycle

- **Created** when `JOB_QUERY_CREATED` (`job-query.cdc.query-created.v1`) is consumed. The
  handler also creates a row when `JOB_QUERY_UPDATED` arrives for a `query_id` that has no
  existing row (out-of-order delivery guard).
- **Updated** when `JOB_QUERY_UPDATED` (`job-query.cdc.query-updated.v1`) is consumed
  (query parameters or activation state changed), or when `SYS_SCHEDULE_TICK` processing
  advances `last_run_at` and `next_run_at` after a successful dispatch.
- **Deleted** when `JOB_QUERY_DELETED` (`job-query.cdc.query-deleted.v1`) is consumed.
  The handler is idempotent: a missing row is treated as already deleted.

## `processed_events`

Consumer-side idempotency store provided by `nohiki-db-utils`. The baseline revision provisions
the table, but no handler in this service calls `check_and_mark_processed`, so nothing writes to
it; redelivery is absorbed by the row-existence checks in the query handlers.

## Source of Truth

- Models: `src/job_ingest_schedule_service/db/models.py`
- Baseline revision: `alembic/versions/001_initial_migration.py`
- Migration commands and workflow: [root README](../../../README.md#database-migration-workflow)
