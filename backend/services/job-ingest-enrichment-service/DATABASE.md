# Job Ingest Enrichment Service Database Schema

Schema `job_ingest_enrichment_schema` stores the saga state rows that coordinate multi-callback
convergence during job enrichment, plus the standard outbox and processed-events tables shared
by all stateful services.

## Entity Overview

| Table | Purpose |
| ------- | --------- |
| `enrichment_embedding_saga` | Tracks convergence of parallel embedding callbacks per enrichment job |
| `outbox` | Transactional outbox for `JOB_INGEST_ENRICHMENT_COMPLETED` publication via Debezium |
| `processed_events` | Idempotency log preventing duplicate handler execution |

The `enrichment_embedding_saga` table is the primary domain artifact of this service. It holds
all state required to reconstruct a `StoredListing` once every asynchronous callback has arrived.
Each saga row is created when the skill normalization callback arrives and accumulates embedding
results as they arrive from `ml-gateway-service`. The `outbox` table captures the final
`JOB_INGEST_ENRICHMENT_COMPLETED` event in the same transaction as the saga COMPLETED state
transition, guaranteeing that the event is never published without a completed saga and is
never lost if the process crashes after the state update.

## Table Details

### `enrichment_embedding_saga`

#### Purpose

Each row represents one in-flight enrichment job: the window between skill normalization
completing and all embedding computations converging. The row carries the full serialized
`EnrichmentContext` (the LLM extraction result plus geocoded coordinates) and accumulates
the base64-encoded embedding bytes from `ml-gateway-service` as each callback arrives.
When the last callback fills the final embedding column, the handler reading that message
completes the saga and writes the enrichment event to the outbox, all in one transaction.

#### Key Columns

**From `SagaBaseMixin` (provided by `nohiki-db-utils`):**

- **`id`** (`UUID`): UUIDv7 primary key, generated server-side via `uuidv7()`. The value is
  embedded in every `ML_EMBEDDING_REQUESTED` `caller_context` payload so callbacks can locate
  their saga row.
- **`status`** (`VARCHAR(20)`): Saga lifecycle state. Constrained to `PENDING`, `COMPLETED`,
  `FAILED`, `EXPIRED`. All rows start as `PENDING`; terminal states (`COMPLETED`, `FAILED`,
  `EXPIRED`) are irreversible.
- **`expected_callbacks`** (`INTEGER`): The number of embedding callbacks this saga waits for.
  Normally 2 (retrieval + title), but can be 1 if only one of the two text fields is non-empty.
  Set at saga creation time and never updated.
- **`received_callbacks`** (`INTEGER`): Incremented by 1 each time an `EmbeddingCallback`
  handler successfully stores its result. When `received_callbacks >= expected_callbacks`, the
  saga is complete. Starts at 0.
- **`expires_at`** (`TIMESTAMPTZ`): `created_at + 30 minutes`. The `StaleSagaDetector` uses
  this to transition stuck PENDING sagas to EXPIRED during periodic cleanup.
- **`version`** (`INTEGER`): Optimistic lock counter. Incremented on every callback recording.
  The `record_callback` method issues a `SELECT ... FOR UPDATE` on the saga row before
  incrementing, serialising concurrent callbacks that arrive on different consumer threads or
  pod replicas.

**Domain-specific columns:**

- **`listing_id`** (`VARCHAR(36)`): References `job_storage_schema.listings.id` (no FK
  constraint: cross-schema reference by UUID string). Indexed for operational queries
  (e.g., "is there a PENDING saga for this listing?").
- **`enrichment_data_json`** (`TEXT`): JSON document carrying all state needed to build the
  final `StoredListing` proto once embeddings arrive. Structure:

  ```json
  {
    "enrichment_ctx": { "listing_id": "...", "listing_url": "...", "cleaned_title": "...",
                        "cleaned_company": "...", "cleaned_description": "...",
                        "geocoded_lat": 37.7749, "geocoded_lon": -122.4194,
                        "seniority": "...", "work_arrangement": "...",
                        "discovered_json": "<base64-proto-bytes>",
                        "correlation_id": "..." },
    "skill_requirements": [{ "skill_id": "...", "skill_name": "...",
                             "proficiency_level": 2, "is_required": true }],
    "skills_b64": "<base64-encoded EmbeddingVector proto | null>"
  }
  ```

  This column makes the saga row self-contained: no other database read is needed to produce
  the enrichment event when the callbacks arrive.
- **`retrieval_embedding_b64`** (`TEXT`, nullable): Base64-encoded serialised `EmbeddingResult`
  proto containing MUVERA, ColBERT, and Sparse vectors for the full listing text. Written by
  the `JOB_INGEST_ENRICHMENT_EMBEDDING_CALLBACK` handler when `embedding_type = "retrieval"`.
  NULL until that callback arrives.
- **`title_embedding_b64`** (`TEXT`, nullable): Base64-encoded serialised `EmbeddingResult`
  proto containing a single Dense vector for the listing title. Written when
  `embedding_type = "title"`. NULL until that callback arrives.

#### Indexes

- **`ix_enrichment_saga_listing_id`** (`listing_id`): Supports lookups by listing to check
  whether enrichment is in progress for a given listing (used in operational monitoring and
  deduplication logic).
- **`ix_enrichment_saga_status_pending`** (`status`) WHERE `status = 'PENDING'`: Partial index
  covering only in-flight sagas. The vast majority of queries against this table filter on
  `status = 'PENDING'`; this index keeps those queries fast without scanning completed or
  expired rows.
- **`ix_enrichment_saga_expires`** (`expires_at`) WHERE `status = 'PENDING'`: Supports the
  `StaleSagaDetector` query that finds `PENDING` rows with `expires_at < now()`. Without this
  index, stale detection would scan all PENDING rows ordered by expiry time.
- **`ix_enrichment_saga_created_at_brin`** BRIN (`created_at`, pages_per_range=32): Supports
  time-range queries on append-heavy data without the overhead of a B-tree. Saga rows are
  inserted in roughly creation-time order, making BRIN efficient for range scans used by
  time-windowed monitoring queries.

#### Constraints

- **CHECK** `status IN ('PENDING', 'COMPLETED', 'FAILED', 'EXPIRED')`: Enforces the state
  machine at the database level, preventing invalid transitions from code bugs or direct SQL.
- **CHECK** `expected_callbacks >= 1`: A saga with zero expected callbacks is nonsensical and
  would immediately appear complete; this constraint makes the impossible state unrepresentable.
- **CHECK** `received_callbacks >= 0`: Guards against negative counter values from concurrent
  decrements (which should never occur but are guarded at the DB layer for safety).
- **CHECK** `version >= 1`: Versions start at 1; zero or negative values indicate a corrupted
  row.

#### Saga Completion and Concurrency

Each embedding callback handler calls `SagaRepository.record_callback()`, which executes
`SELECT ... FOR UPDATE` on the saga row before mutating it. This row-level lock serialises two
concurrent callbacks that arrive in the same instant. The second callback blocks until the
first transaction commits, then re-reads the updated `received_callbacks` value. The handler
that increments `received_callbacks` to `expected_callbacks` detects `is_complete = True` and
proceeds to call `_converge_and_publish`: it transitions `status` to `COMPLETED`, writes the
`JOB_INGEST_ENRICHMENT_COMPLETED` message to the `outbox` table, and commits in the same
transaction. Any subsequent duplicate callback for an already-COMPLETED saga raises
`InvalidTransitionError` (the state machine rejects transitions out of terminal states), and
the callback is safely discarded.

#### Data Lifecycle

- **Created** when `JOB_INGEST_SKILL_CALLBACK` arrives and there is at least one non-empty text
  field to embed. The row is inserted and committed before the `ML_EMBEDDING_REQUESTED` commands
  are published, ensuring the saga exists before any callback can arrive.
- **Updated** (twice, once per embedding callback) when each `JOB_INGEST_ENRICHMENT_EMBEDDING_CALLBACK`
  message is processed. Each update writes one of the two embedding columns and increments
  `received_callbacks` and `version`.
- **Completed** when the final callback arrives: `status` transitions to `COMPLETED` in the
  same transaction that writes the outbox event. The row is retained after completion for audit
  purposes; no TTL-based deletion runs on completed rows.
- **Failed** when an embedding callback arrives carrying an error result. `status` transitions
  to `FAILED`. No enrichment event is published. The listing remains in `job-storage-service`
  in its raw accepted state without enrichment data.
- **Expired** when `StaleSagaDetector` runs its periodic sweep and finds rows with
  `expires_at < now()` that are still `PENDING`. This handles the case where an embedding
  callback is never delivered (e.g., `ml-gateway-service` outage, lost Kafka message). The
  30-minute TTL is set at row creation via `expires_at = created_at + timedelta(minutes=30)`.

---

### `outbox`

#### Purpose

The outbox table provides Debezium with the events it needs to publish to Kafka. Writing an
enrichment event here in the same transaction as the saga COMPLETED transition means the event
is published if and only if the saga is completed, with no gap where a process crash could
leave the saga completed but the event unpublished.

#### Key Columns

- **`id`** (`UUID`): Random UUID primary key (`gen_random_uuid()`), not UUIDv7 -- this is a
  Debezium infrastructure table, not a domain entity.
- **`aggregatetype`** (`VARCHAR(255)`): The domain entity type, e.g. `"EnrichmentCompleted"`.
  Debezium's Outbox Event Router SMT uses this to route events to the correct Kafka topic.
- **`aggregateid`** (`VARCHAR(255)`): The aggregate root's identifier (listing ID). Used by
  Debezium as the Kafka message key, ensuring ordering per listing.
- **`type`** (`VARCHAR(255)`): The event type name, e.g. `"JOB_INGEST_ENRICHMENT_COMPLETED"`.
- **`payload`** (`BYTEA`): Serialised betterproto2 protobuf bytes of the `EnrichmentCompleted`
  message.
- **`timestamp`** (`TIMESTAMPTZ`): Write time. Indexed for Debezium's incremental snapshot and
  for operational monitoring queries.
- **`tracingspancontext`** (`VARCHAR(256)`): OpenTelemetry trace context propagated into Kafka.

#### Indexes

- **`ix_job_ingest_enrichment_schema_outbox_timestamp`** (`timestamp`): Debezium's incremental
  snapshot connector reads outbox rows ordered by timestamp when catching up after a restart.

#### Events Published via Outbox

- **`JOB_INGEST_ENRICHMENT_COMPLETED`** (`EnrichmentCompleted`, topic
  `job-ingest.fct.enrichment-completed.v1`): Published in the same transaction as the saga
  COMPLETED state transition. Carries the fully populated `StoredListing` proto.

#### Data Lifecycle

- **Created** in the same database transaction as each saga COMPLETED transition: one outbox
  row per enrichment job. Debezium captures the insert from the PostgreSQL WAL and publishes the
  event to Kafka, then deletes the row (the Outbox Event Router SMT deletes after publish).
  Rows are short-lived under normal operation; accumulation indicates a Debezium connector
  outage.

---

### `processed_events`

#### Purpose

The processed-events table prevents a Kafka handler from processing the same message twice if
the consumer restarts mid-execution. Each handler records `(event_id, handler_name)` before
committing its database work. On redelivery, the handler checks this table first and skips
processing if the pair already exists.

#### Key Columns

- **`event_id`** (`UUID`): The Kafka message's event ID from `EventMetadata`.
- **`handler_name`** (`VARCHAR(255)`): The handler function name that processed the event.
  The composite `(event_id, handler_name)` primary key allows the same event to be processed
  by different handlers without conflict.
- **`processed_at`** (`TIMESTAMPTZ`): Insertion timestamp. Used by periodic cleanup jobs to
  expire records older than the Kafka retention window (default: 7 days).

#### Indexes

- **`idx_job_ingest_enrichment_schema_processed_events_processed_at`** (`processed_at`):
  Supports time-bounded DELETE queries during TTL cleanup.

#### Data Lifecycle

- **Created** once per successfully processed Kafka message per handler. The insert and the
  handler's database work commit atomically, so a crash before commit means neither the
  processed-events record nor the domain change are persisted, and the message is redelivered.
- **Deleted** by periodic cleanup after 7 days (configurable via
  `get_cleanup_processed_events_sql`). Deletion is safe because Kafka's retention window
  guarantees the message will not be redelivered after 7 days.

## Migration Strategy

Nohiki uses **clean-cut deployment**: all services stop, schemas drop and recreate, and the
single `001_` migration applies fresh. The migration file is edited in place rather than
accumulating incremental revisions.

This is viable because Nohiki is pre-release with no production data. There are no data
migrations or backward compatibility constraints.

```bash
# Apply migration
alembic upgrade head

# Generate updated migration after model changes
alembic revision --autogenerate -m "description"

# View current state
alembic current
```
