# Job Query Composition Service Database Design

Schema `job_query_schema` stores the deduplicated scrape queries produced by clustering user
search preferences, along with the contributor records that map individual preferences to each
query.

`ingestion_queries` is the canonical record of what the scraping pipeline will fetch.
`query_contributors` records every user preference that caused a given query to exist, storing
that preference's individual parameters so aggregates on `ingestion_queries` can be recomputed
from first principles whenever any contributor changes. The outbox table captures query lifecycle
events (`created`, `updated`, `deleted`) atomically with domain writes for delivery to
`job-ingest-schedule-service` via Debezium CDC.

## Table Details

### `ingestion_queries`

#### Purpose

Represents one deduplicated job scrape query: a unique combination of normalized search keywords
and canonical target locations. All user preferences that share the same deduplication key
contribute to a single row here rather than generating separate scrape runs.

#### Aggregate Semantics

- **`search_keywords`**: Normalized keyword array (lowercased, stripped, sorted). Forms the first
  half of the deduplication key. Queried with exact array equality.
- **`locations`**: Canonicalized, lowercased, and sorted locations form the second half of the
  deduplication key. Queried with JSONB equality for deduplication lookups.
- **`work_arrangements`**: Union of all active contributors' work arrangement preferences.
- **`remote_preferences`**: Derived remote preference labels aggregated from active contributors.
- **`sources`**: Union of all active contributors' target job boards.

`work_arrangements` values are stored as PostgreSQL enum strings; the ORM model exposes them as
`WorkArrangement` proto enums via property accessors that filter out `UNSPECIFIED`. `sources`
values are stored as PostgreSQL enum strings, exposed as `JobBoardSource` proto enums via property
accessors.

- **`frequency`**: Minimum scrape frequency across all active contributors. Upgraded to `1 hour`
  if any active contributor is on the `pro` or `enterprise` entitlement tier. The schedule service
  reads `frequency_seconds` from the CDC event payload derived from this column.
- **`is_active`**: `true` when at least one contributor is active. The schedule service only
  issues discovery commands for active queries.
- **`active_contributor_count`**: Count of contributors with `is_active = true`. Recomputed on
  every aggregate recomputation.
- **`total_contributor_count`**: Used to determine whether to delete the query when a contributor
  is removed (`total = 0` → delete).
- **`last_recomputed_at`**: Timestamp of the latest aggregate recomputation, retained for
  operational visibility. Material updates recompute eagerly for correctness.

#### Constraints & Invariants

- Deduplication on `(search_keywords, locations)` is enforced by the database. `find_or_create_query`
  performs a SELECT before INSERT and, when a concurrent transaction wins the insert, catches the
  resulting integrity error inside its savepoint and re-selects the winning row.

#### Data Lifecycle

- **Created** when `USER_PREF_CREATED` or `USER_PREF_UPDATED` is consumed and
  `find_or_create_query` finds no existing query matching the normalized keyword + location key.
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

#### Contributor Semantics

- **`user_id`**: Indexed to support bulk operations by user (account deletion, entitlement
  change, and activity reactivation) without full-table scans.
- **`remote_preference`**: Derived from the contributor's location list: `remote`, `onsite`,
  `hybrid`, or `any`. Computed by `extract_remote_pref` from the location type fields in the
  preference snapshot.
- **`frequency_tier`**: The contributor's scrape frequency tier, derived from their entitlement:
  `free` → `daily`, `pro`/`enterprise` → `hourly`. Maps to a `timedelta` via `TIER_FREQUENCIES`
  for aggregate computation.
- **`is_active`**: Set from the preference snapshot's active flag whenever a preference event is
  consumed (a preference with no search keywords is stored inactive), and restored to `true` on a
  `USER_AUTH_ACTIVITY` event. Only active contributors are included when computing
  `ingestion_queries.work_arrangements`, `sources`, `frequency`, and `active_contributor_count`.

`work_arrangements` values are stored as PostgreSQL enum strings and exposed as `WorkArrangement`
proto enums via ORM property accessors. `sources` values are stored as PostgreSQL enum strings,
exposed as `JobBoardSource` proto enums. The property accessors filter out `UNSPECIFIED`.

#### Constraints & Invariants

- A preference can appear in at most one query at a time (keywords + locations define the query
  identity). `pref_id` is unique, and `create_or_update_contributor` looks the contributor up by
  `pref_id` alone, reassigning `query_id` in place rather than inserting a second row.
- Cascade ensures contributor rows are cleaned up if the parent query is deleted directly.
- In normal operation, the service always deletes contributors first and removes the query last.

#### Data Lifecycle

- **Created** when `USER_PREF_CREATED` is consumed and `create_or_update_contributor` finds no
  existing row for `pref_id`.
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
`infra/k8s/kafka-connect/connectors/` for the connector configuration.

**Events published via outbox:**

- **`JOB_QUERY_CREATED`** (`job-query.cdc.query-created.v1`): Published when a new
  `IngestionQuery` is inserted. `aggregate_type`: `ingestion_query`.
- **`JOB_QUERY_UPDATED`** (`job-query.cdc.query-updated.v1`): Published when an existing query's
  aggregated parameters change. `aggregate_type`: `ingestion_query`.
- **`JOB_QUERY_DELETED`** (`job-query.cdc.query-deleted.v1`): Published immediately before the
  `IngestionQuery` row is deleted. `aggregate_type`: `ingestion_query`.

The outbox `payload` column stores a serialized `IngestionQueryChanged` or `IngestionQueryDeleted`
protobuf message (betterproto2 binary encoding).

## Source of Truth

- Models: `backend/services/job-query-composition-service/src/job_query_composition_service/db/models.py`
- Baseline revision: `backend/services/job-query-composition-service/alembic/versions/001_initial_migration.py`
- Migration workflow: [root README](../../../README.md#database-migration-workflow)
