# Job Query Composition Service

Translates user job search preferences into a deduplicated set of canonical scrape queries. When
multiple users share the same search keywords and target locations, this service clusters their
preferences into a single `IngestionQuery` rather than issuing a redundant scrape per user --
reducing N user preferences to M queries where M << N. Kafka-only, stateful with PostgreSQL and
Redis, no HTTP exposure.

## Role in the System

This service sits between the user preference domain and the job ingestion pipeline. It consumes
preference lifecycle events from `user-pref-service` and publishes query lifecycle events
(`job-query.cdc.*`) that `job-ingest-schedule-service` consumes to decide when to trigger each
scrape. The three-service chain: query composition → schedule → discovery means that what a
user saves as a job search preference eventually becomes a timed scrape command sent to
`job-ingest-discovery-service`.

The core problem this service solves is query explosion: without it, 500 users searching for
"software engineer" in Austin would generate 500 separate scrape runs per schedule tick. With it,
those 500 preferences collapse to one `IngestionQuery` keyed on normalized keywords and canonical
locations. The schedule service receives a single `JOB_QUERY_CREATED` event and schedules one
scrape, whose results flow back to all 500 users through the job storage and correlation pipeline.

Query parameters are aggregated across all contributing preferences: the query's `frequency` is
the minimum across all contributors' tiers (so one pro-tier user pulling an `hourly` scrape
upgrades the entire cluster to hourly), `work_arrangements` and `sources` are the union, and
`is_active` follows whether any contributor is active. This means query properties evolve
continuously as contributors are added, updated, or removed.

## Event-Driven Integration

### Events Consumed

- **`USER_PREF_CREATED`** (`PrefCreated`): Triggers query clustering for a new preference. The
  handler normalizes the preference's `search_keywords` (lowercase, sorted) and canonicalizes its
  `locations` (validated enum ints, lowercased city/state, sorted) to form a deduplication key.
  It then calls `find_or_create_query` -- returning an existing query with the same key or
  inserting a new one, and upserts a `QueryContributor` row linking the preference to that
  query. After recomputing aggregates it publishes `JOB_QUERY_CREATED` (new query) or
  `JOB_QUERY_UPDATED` (existing query gained a contributor) via the transactional outbox.
  Consumer group: `settings.kafka_consumer_group`.

- **`USER_PREF_UPDATED`** (`PrefUpdated`): Handles keyword or location changes by re-evaluating
  the deduplication key against the updated snapshot. If the user changed their target city, the
  preference may now match a different `IngestionQuery` (or require a new one). The handler
  upserts the contributor record into the correct query and publishes `JOB_QUERY_UPDATED` if
  enough time has passed since the last recomputation (controlled by
  `JOB_QUERY_COMPOSITION_COMPOSITION__RECOMPUTE_MIN_INTERVAL_SECONDS`, default 300 seconds).

- **`USER_PREF_DELETED`** (`PrefDeleted`): Removes the contributor row for the deleted preference.
  If that contributor was the last one on the query, publishes `JOB_QUERY_DELETED` and then
  deletes the `IngestionQuery`. Otherwise recomputes and publishes `JOB_QUERY_UPDATED` so the
  schedule service knows the aggregate parameters changed.

- **`USER_ENTITLEMENT_CHANGED`** (`EntitlementChanged`): Maps the user's billing tier to a
  frequency tier (`free` → `daily`, `pro`/`enterprise` → `hourly`) and bulk-updates all
  contributor rows for that user. For each affected query where enough time has passed since
  last recomputation, recomputes aggregates and publishes `JOB_QUERY_UPDATED` -- which may change
  the query's scrape frequency if this user was the most frequent contributor.
  `preserve_partition_order=False` because entitlement changes are independent of preference
  partition ordering. Consumer group: `settings.kafka_consumer_group`.

- **`USER_AUTH_ACCOUNT_DELETED`** (`AccountDeleted`): Bulk-deletes all `QueryContributor` rows
  for the deleted user. For each affected query, either publishes `JOB_QUERY_DELETED` and removes
  the `IngestionQuery` (if no contributors remain) or recomputes and publishes `JOB_QUERY_UPDATED`.
  Batch-fetches all affected queries in a single database round-trip.
  `preserve_partition_order=False`. Consumer group: `settings.kafka_consumer_group`.

- **`USER_AUTH_ACTIVITY`** (`UserActivity`): Reactivates any contributor rows that were marked
  inactive for the given user, then recomputes and publishes `JOB_QUERY_UPDATED` for each
  affected query so the schedule service knows those queries are active again.
  `preserve_partition_order=False`. Consumer group: `settings.kafka_consumer_group`.

### Events Published

All events publish via the transactional outbox: they are written to the `outbox` table in the same
database transaction as the domain data change, then delivered to Kafka by Debezium.

- **`JOB_QUERY_CREATED`** (`job-query.cdc.query-created.v1`, `IngestionQueryChanged`): Published
  when a new `IngestionQuery` is created (first contributor for a previously unseen keyword +
  location combination). Carries the full query snapshot: `query_id`, `search_keywords`,
  `locations`, `work_arrangements`, `sources`, `frequency_seconds`, and `is_active`.
  Consumed by `job-ingest-schedule-service` to register the query in its scheduling ledger.

- **`JOB_QUERY_UPDATED`** (`job-query.cdc.query-updated.v1`, `IngestionQueryChanged`): Published
  when an existing query's aggregated parameters change: a new contributor joined, a contributor's
  tier changed, or a contributor was removed without eliminating the query. Same payload structure
  as `JOB_QUERY_CREATED`. Consumed by `job-ingest-schedule-service` to update its local snapshot
  of the query (frequency, active status, search parameters).

- **`JOB_QUERY_DELETED`** (`job-query.cdc.query-deleted.v1`, `IngestionQueryDeleted`): Published
  before the `IngestionQuery` row is deleted (last contributor removed). Carries only `query_id`.
  Consumed by `job-ingest-schedule-service` to remove the query from its scheduling ledger and
  stop issuing discovery commands for it.

### Notable Patterns

#### Transactional Outbox

All three query CDC events go through the `nohiki-db-utils` outbox pattern: `outbox.write_event`
inserts into the `job_query_schema.outbox` table within the same database transaction as the
domain write. Debezium's PostgreSQL connector with the Outbox Event Router SMT reads the outbox
from the WAL and publishes to Kafka. This guarantees that a query deletion is never lost even if
the service crashes between the domain write and the Kafka publish.

#### Eager Aggregate Recomputation

Material preference and entitlement updates always recompute their affected query aggregates in
the same transaction and enqueue complete query snapshots through the transactional outbox. This
avoids leaving a lone update stale when no later event arrives. User-wide changes retain bounded
database round-trips through `recompute_query_aggregates_batch`.

#### Batch Operations

Bulk user-level operations (account deletion, entitlement change, activity reactivation) use
single bulk UPDATE/DELETE SQL statements followed by a single batch SELECT for affected queries,
keeping the database round-trips O(1) regardless of how many preferences a user has. The
`recompute_query_aggregates_batch` function fetches all contributors for a set of queries in one
query, groups them in Python with `defaultdict`, and updates all queries in the ORM session before
flushing once.

## State & Persistence

### Database

Schema `job_query_schema` stores two domain tables. `ingestion_queries` holds the deduplicated
scrape queries with their aggregated search parameters, contributor counts, and scheduling
frequency. `query_contributors` records the many-to-many mapping between `IngestionQuery` rows
and user preferences (`pref_id`), storing each preference's individual parameters so aggregates
can be recomputed from first principles when any contributor changes.

See [DATABASE.md](./DATABASE.md) for complete schema documentation.

### Redis

Redis provides the distributed infrastructure for `nohiki-db-utils` outbox idempotency and the
`nohiki-kafka-client` circuit breaker state. This service does not define its own Redis key
patterns beyond what those libraries manage internally.

## Configuration

The service uses `DatabaseMixin`, `RedisMixin`, and `KafkaMixin` from `nohiki-core-settings`, plus
a service-specific `CompositionSettings` block. All environment variables are prefixed with
`JOB_QUERY_COMPOSITION_`.

| Variable | Default | Purpose |
| ---------- | --------- | --------- |
| `JOB_QUERY_COMPOSITION_COMPOSITION__RECOMPUTE_MIN_INTERVAL_SECONDS` | `300` | Minimum seconds between aggregate recomputations for a given query. Prevents publish storms on burst updates. |
| `JOB_QUERY_COMPOSITION_COMPOSITION__INACTIVITY_THRESHOLD_DAYS` | `30` | Days of inactivity before a user's contributions are considered stale (used by inactivity tick handling). |
| `JOB_QUERY_COMPOSITION_DATABASE__URL` | -- | PostgreSQL connection URL |
| `JOB_QUERY_COMPOSITION_DATABASE__SCHEMA_NAME` | -- | Must be `job_query_schema` |
| `JOB_QUERY_COMPOSITION_KAFKA__BOOTSTRAP_SERVERS` | -- | Kafka broker addresses |
| `JOB_QUERY_COMPOSITION_REDIS__URL` | -- | Redis connection URL |

## Development

### Local Setup

```bash
uv sync
alembic upgrade head
```

### Testing

```bash
just test job-query-composition-service
just test-cov job-query-composition-service
```

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise
uv run ty check
```

Requires PostgreSQL (schema `job_query_schema`), Kafka, and Redis. Run `just infra-up` from the
repo root to start all infrastructure dependencies.
