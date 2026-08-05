# Job Ingest Enrichment Service Database Design

Schema `job_ingest_enrichment_schema` stores the saga state rows that coordinate multi-callback
convergence during job enrichment, plus the standard outbox and processed-events tables shared
by all stateful services.

The `enrichment_embedding_saga` table is the primary domain artifact of this service. It holds
all state required to reconstruct a `StoredListing` once every asynchronous callback has arrived.
Each saga row is created when the skill normalization callback arrives and accumulates embedding
results as they arrive from `ml-gateway-service`. The `outbox` table captures the final
`JOB_INGEST_ENRICHMENT_COMPLETED` event in the same transaction as the saga COMPLETED state
transition, guaranteeing that the event is never published without a completed saga and is
never lost if the process crashes after the state update.

## `enrichment_embedding_saga`

### Purpose

Each row represents one in-flight enrichment job: the window between skill normalization
completing and all embedding computations converging. The row carries the full serialized
`EnrichmentContext` (the LLM extraction result plus geocoded coordinates) and accumulates
the base64-encoded embedding bytes from `ml-gateway-service` as each callback arrives.
When the last callback fills the final embedding column, the handler reading that message
completes the saga and writes the enrichment event to the outbox, all in one transaction.

The `enrichment_data_json` column makes the saga row self-contained: no other database read is
needed to produce the enrichment event when the callbacks arrive.

The saga row identifier is embedded in every `ML_EMBEDDING_REQUESTED` `caller_context` payload
so callbacks can locate their saga row. `listing_id` references
`job_storage_schema.listings.id` with no foreign key constraint because it is a cross-schema
reference by UUID string.

Operational lookups by listing can check whether enrichment is in progress. The in-flight
access path covers queries that filter on `status = 'PENDING'` without scanning completed or
expired rows. The expiry access path supports the periodic sweep for `PENDING` rows with
`expires_at < now()` ordered by expiry time. Saga rows are inserted in roughly creation-time
order, making time-windowed range scans efficient.

### Saga Completion and Concurrency

`expected_callbacks` is set at saga creation time and never updated, with one expected callback
per non-empty retrieval, title, or skills field. `received_callbacks` starts at 0 and reaches
`expected_callbacks` to complete the saga.

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

### Data Lifecycle

- **Created** when `JOB_INGEST_SKILL_CALLBACK` arrives and there is at least one non-empty text
  field to embed. The row is inserted and committed before the `ML_EMBEDDING_REQUESTED` commands
  are published, ensuring the saga exists before any callback can arrive.
- **Updated** when each `JOB_INGEST_ENRICHMENT_EMBEDDING_CALLBACK` message is processed. Each
  update writes one of the embedding columns and increments `received_callbacks` and `version`.
- **Completed** when the final callback arrives: `status` transitions to `COMPLETED` in the
  same transaction that writes the outbox event. The row is retained after completion for audit
  purposes; no TTL-based deletion runs on completed rows.
- **Failed** when an embedding callback arrives carrying an error result. `status` transitions
  to `FAILED` and a terminal failed outcome is enqueued in the outbox in the same transaction.
  `job-storage-service` consumes the failed outcome and marks the in-flight ingest saga `FAILED`;
  no canonical listing row is created for this enrichment attempt.
- **Expired** when the service's periodic sweep (`expire_stale_embedding_sagas`, driven from the
  application lifespan) finds rows with `expires_at < now()` that are still `PENDING`, and
  enqueues one failed outcome per expired saga. This handles the case where an embedding
  callback is never delivered (e.g., `ml-gateway-service` outage, lost Kafka message). The
  30-minute TTL is set at row creation via `expires_at = created_at + timedelta(minutes=30)`.

## `outbox`

### Purpose

The outbox table provides Debezium with the events it needs to publish to Kafka. Writing an
enrichment event here in the same transaction as the saga COMPLETED transition means the event
is published if and only if the saga is completed, with no gap where a process crash could
leave the saga completed but the event unpublished.

### Events Published via Outbox

- **`JOB_INGEST_ENRICHMENT_COMPLETED`** (`EnrichmentCompleted`, topic
  `job-ingest.fct.enrichment-completed.v1`): Published in the same transaction as the saga
  COMPLETED state transition. Carries the fully populated `StoredListing` proto. The same event
  type carries terminal failure outcomes written when a saga fails or expires.
  The listing ID is used by Debezium as the Kafka message key, ensuring ordering per listing.

### Data Lifecycle

- **Created** in the same database transaction as each saga terminal transition: one outbox
  row per enrichment job. Debezium captures the insert from the PostgreSQL WAL and publishes the
  event to Kafka. The connector does not delete published rows, and no cleanup job removes them,
  so this table grows monotonically.

## `processed_events`

### Purpose

The processed-events table prevents a Kafka handler from processing the same message twice if
the consumer restarts mid-execution. A handler that opts in records `(event_id, handler_name)`
before committing its database work, and on redelivery checks this table first and skips
processing if the pair already exists. No handler in this service currently claims events this
way; the table is created by the migration but unused here. Duplicate embedding callbacks are
instead rejected by the saga row itself, which is locked `FOR UPDATE` and refuses a second write
to an already-populated embedding column or a transition out of a terminal state.

### Data Lifecycle

- **Created** once per successfully processed Kafka message per handler that claims events. The
  insert and the handler's database work commit atomically, so a crash before commit means
  neither the processed-events record nor the domain change are persisted, and the message is
  redelivered.
- Nothing deletes rows from this table today: `get_cleanup_processed_events_sql` exists in
  `nohiki-db-utils` but has no caller.

## Source of Truth

- Models: `src/job_ingest_enrichment_service/db/models.py`
- Baseline revision: `alembic/versions/001_initial_migration.py`
- Migration workflow: [`../../../README.md#database-migration-workflow`](../../../README.md#database-migration-workflow)
