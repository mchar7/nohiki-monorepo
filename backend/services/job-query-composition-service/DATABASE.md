# Job Query Composition Service Database Schema

Schema `job_query_schema` stores the deduplicated scrape queries produced by clustering user
search preferences, along with the contributor records that map individual preferences to each
query.

## Entity Overview

| Table | Purpose |
| ------- | --------- |
| `ingestion_queries` | Deduplicated scrape queries, keyed by normalized keywords + canonical locations |
| `query_contributors` | Maps individual user preferences (`pref_id`) to their parent `IngestionQuery` |
| `outbox` | Transactional outbox for CDC event delivery via Debezium |

`ingestion_queries` is the canonical record of what the scraping pipeline will fetch.
`query_contributors` records every user preference that caused a given query to exist, storing
that preference's individual parameters so aggregates on `ingestion_queries` can be recomputed
from first principles whenever any contributor changes. The outbox table captures query lifecycle
events (`created`, `updated`, `deleted`) atomically with domain writes, guaranteeing exactly-once
delivery to `job-ingest-schedule-service` via Debezium CDC.

## Table Details

### `ingestion_queries`

#### Purpose

Represents one deduplicated job scrape query: a unique combination of normalized search keywords
and canonical target locations. All user preferences that share the same deduplication key
contribute to a single row here rather than generating separate scrape runs.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key, generated server-side via `uuidv7()`. Encodes creation
  timestamp.
- **`search_keywords`** (`VARCHAR[]`): Normalized keyword array (lowercased, stripped, sorted).
  Forms the first half of the deduplication key. Queried with exact array equality.
- **`locations`** (`JSONB`): Canonical location array: the second half of the deduplication key.
  Each element is `{"country": int, "location_type": int, "state_province": str, "city": str}`
  with validated, lowercased, sorted values. Queried with JSONB equality for deduplication lookups.
- **`work_arrangements`** (`work_arrangement_enum[]`): Union of all active contributors'
  work arrangement preferences. Values: `UNSPECIFIED`, `ON_SITE`, `HYBRID`, `REMOTE`. Stored as
  PostgreSQL enum strings; the ORM model exposes them as `WorkArrangement` proto enums via
  property accessors that filter out `UNSPECIFIED`.
- **`remote_preferences`** (`VARCHAR[]`): Derived remote preference labels aggregated from active
  contributors. Each element is one of `remote`, `onsite`, `hybrid`, or `any`.
- **`sources`** (`job_board_source_enum[]`): Union of all active contributors' target job boards.
  Values: `UNSPECIFIED`, `INDEED`, `LINKEDIN`, `ZIPRECRUITER`, `GOOGLE`, `GLASSDOOR`, `BAYT`,
  `NAUKRI`, `COMPANY_WEBSITE`. ORM exposes as `JobBoardSource` proto enums via property accessors.
- **`frequency`** (`INTERVAL`): Minimum scrape frequency across all active contributors. Set to
  `1 day` by default; upgraded to `1 hour` if any active contributor is on the `pro` or
  `enterprise` entitlement tier. The schedule service reads `frequency_seconds` from the CDC event
  payload derived from this column.
- **`is_active`** (`BOOLEAN`): `true` when at least one contributor is active. The schedule
  service only issues discovery commands for active queries.
- **`active_contributor_count`** (`INTEGER`): Count of contributors with `is_active = true`.
  Recomputed on every aggregate recomputation.
- **`total_contributor_count`** (`INTEGER`): Count of all contributors (active and inactive).
  Used to determine whether to delete the query when a contributor is removed (`total = 0` →
  delete).
- **`last_recomputed_at`** (`TIMESTAMPTZ`): Timestamp of the latest aggregate recomputation,
  retained for operational visibility. Material updates recompute eagerly for correctness.

#### Indexes

- **`idx_queries_active`** (`is_active`): Supports filtering to active queries only, useful for
  operational queries during schedule tick processing.
- Primary key on `id` provides O(1) lookup by query ID, used by all aggregate recomputation paths.

#### Constraints & Invariants

- **CHECK `chk_locations_json_array`** (`locations IS JSON ARRAY`): Rejects bare objects,
  scalars, and JSON null so persisted proto locations always remain a repeated-value array.
- There is no UNIQUE constraint on `(search_keywords, locations)` at the database level; the
  service enforces deduplication via `find_or_create_query` which performs a SELECT before INSERT.
  This keeps the migration simple while relying on the service-layer upsert logic and the
  outbox-serialized commit to prevent races.

#### Data Lifecycle

- **Created** when `USER_PREF_CREATED` is consumed and `find_or_create_query` finds no existing
  query matching the normalized keyword + location key.
- **Updated (aggregates)** after any `USER_PREF_CREATED`, `USER_PREF_UPDATED`,
  `USER_PREF_DELETED`, `USER_ENTITLEMENT_CHANGED`, or `USER_AUTH_ACTIVITY` event causes
  `recompute_query_aggregates` to run.
- **Deleted** when `USER_PREF_DELETED` or `USER_AUTH_ACCOUNT_DELETED` removes the last
  contributor (`total_contributor_count` drops to 0). The `JOB_QUERY_DELETED` outbox event is
  written before the row is removed so Debezium captures the deletion intent.

---

### `query_contributors`

#### Purpose

Records one user preference's contribution to a parent `IngestionQuery`. The table is the source
of truth for recomputing query aggregates: whenever any contributor row changes, the service
re-derives `work_arrangements`, `sources`, `frequency`, and `is_active` on the parent query by
reading all contributors for that query.

#### Key Columns

- **`query_id`** (`UUID`): Part of the composite primary key. References
  `job_query_schema.ingestion_queries.id` with a real `FOREIGN KEY ... ON DELETE CASCADE`
  constraint (same schema, so FK is valid here). Cascade ensures contributor rows are cleaned up
  if the parent query is deleted directly.
- **`pref_id`** (`UUID`): Part of the composite primary key. References
  `user_pref_schema.search_prefs.id` (no FK constraint because this is a cross-schema reference by UUID). The
  composite `(query_id, pref_id)` PK enforces one contributor row per preference per query.
- **`user_id`** (`UUID`): References `user_auth_schema.users.id` (no FK constraint because this is cross-schema).
  Indexed to support bulk operations by user (account deletion, entitlement change, activity
  reactivation) without full-table scans.
- **`work_arrangements`** (`work_arrangement_enum[]`): This contributor's work arrangement
  preferences. Stored as PostgreSQL enum strings, exposed as `WorkArrangement` proto enums via
  ORM property accessors.
- **`remote_preference`** (`VARCHAR(20)`): Derived from the contributor's location list:
  `remote`, `onsite`, `hybrid`, or `any`. Computed by `extract_remote_pref` from the location
  type fields in the preference snapshot.
- **`sources`** (`job_board_source_enum[]`): This contributor's target job boards. Stored as
  PostgreSQL enum strings, exposed as `JobBoardSource` proto enums.
- **`frequency_tier`** (`VARCHAR(10)`): The contributor's scrape frequency tier, derived from
  their entitlement: `free` → `daily`, `pro`/`enterprise` → `hourly`. Maps to a `timedelta` via
  `TIER_FREQUENCIES` for aggregate computation. Values: `hourly`, `6h`, `daily`, `weekly`.
- **`is_active`** (`BOOLEAN`): `true` by default. Set to `false` when the user goes inactive
  (detected via `USER_AUTH_ACTIVITY` absence); restored to `true` on the next activity event.
  Only active contributors are included when computing `ingestion_queries.work_arrangements`,
  `sources`, `frequency`, and `active_contributor_count`.

#### Indexes

- **`idx_contributors_user`** (`user_id`): Supports bulk operations scoped to a user --
  `update_contributor_frequency`, `set_user_inactive`, `set_user_active`, and
  `delete_user_contributions` all filter by `user_id`.
- **`idx_contributors_pref`** (`pref_id`): Supports O(1) lookup by preference ID, used by
  `delete_contributor` when handling `USER_PREF_DELETED`.
- Composite primary key `(query_id, pref_id)` serves as the idempotency key for
  `create_or_update_contributor` -- the handler performs a SELECT then INSERT-or-UPDATE rather
  than an UPSERT, relying on this PK to prevent duplicates.

#### Constraints & Invariants

- **PRIMARY KEY** `(query_id, pref_id)`: Enforces one contributor row per preference per query.
  A preference can appear in at most one query at a time (keywords + locations define the query
  identity).
- **FOREIGN KEY** `(query_id) → ingestion_queries.id ON DELETE CASCADE`: If a query is deleted
  directly (e.g., via a manual cleanup), its contributor rows are removed automatically. In normal
  operation, the service always deletes contributors first and removes the query last.

#### Data Lifecycle

- **Created** when `USER_PREF_CREATED` is consumed and `create_or_update_contributor` finds no
  existing row for `(query_id, pref_id)`.
- **Updated** when `USER_PREF_UPDATED` changes work arrangements, sources, or location; or when
  `USER_ENTITLEMENT_CHANGED` changes `frequency_tier`; or when `USER_AUTH_ACTIVITY` sets
  `is_active = true`.
- **Deleted** when `USER_PREF_DELETED` removes the row for a specific `pref_id`, or when
  `USER_AUTH_ACCOUNT_DELETED` bulk-deletes all rows for a `user_id`.

---

## Outbox Table

The service uses the transactional outbox pattern for guaranteed event delivery. All three query
CDC events are written to `job_query_schema.outbox` within the same database transaction as the
domain data change, ensuring that no query lifecycle event is lost even if the service crashes
between the domain write and the Kafka publish.

Debezium's PostgreSQL connector with the Outbox Event Router SMT reads this table from the
PostgreSQL WAL and publishes events to Kafka. See
`infra/kafka-connect/connectors/` for the connector configuration.

**Events published via outbox:**

- **`JOB_QUERY_CREATED`** (`job-query.cdc.query-created.v1`): Published when a new
  `IngestionQuery` is inserted. `aggregate_type`: `ingestion_query`.
- **`JOB_QUERY_UPDATED`** (`job-query.cdc.query-updated.v1`): Published when an existing query's
  aggregated parameters change. `aggregate_type`: `ingestion_query`.
- **`JOB_QUERY_DELETED`** (`job-query.cdc.query-deleted.v1`): Published immediately before the
  `IngestionQuery` row is deleted. `aggregate_type`: `ingestion_query`.

The outbox `payload` column stores a serialized `IngestionQueryChanged` or `IngestionQueryDeleted`
protobuf message (betterproto2 binary encoding).

## Migration Strategy

Nohiki uses **clean-cut deployment**: all services are stopped, schemas are dropped and recreated,
and the single `001_` migration is applied fresh. The migration file is edited in place rather
than creating incremental migrations.

This is possible because Nohiki is pre-release with zero production data. There are no data
migrations or backward compatibility concerns.

```bash
# Apply migration
alembic upgrade head

# Generate updated migration after model changes
alembic revision --autogenerate -m "description"

# View current state
alembic current
```
