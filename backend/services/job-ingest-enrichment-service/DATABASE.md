# Job Ingest Enrichment Database Design

Schema `job_ingest_enrichment_schema` owns the durable coordination state for job enrichment. Its primary domain
artifact is the embedding saga that converges parallel callbacks before producing a completed enrichment. The schema
also owns the transactional outbox used to publish that result and the processed-event log used to make Kafka handlers
idempotent.

The saga is a coordination record rather than a second source of truth for listings. It relates to the listing owned by
`job-storage-service`, but keeps the serialized enrichment context, normalized skill requirements, and callback results
needed to construct the final `StoredListing`. This deliberate denormalization makes convergence self-contained: the
final callback can produce the completed event without another database read.

## Embedding Saga

### Creation and callback convergence

A saga begins when `JOB_INGEST_SKILL_CALLBACK` arrives and at least one supported text field is non-empty. The expected
callback count is fixed at creation and remains unchanged; it is normally two for retrieval and title embeddings, or one
when only one of those text fields is present. The saga is committed before any `ML_EMBEDDING_REQUESTED` commands are
published, ensuring callbacks cannot legitimately arrive before their coordination record exists. Its identifier is
included in each request's caller context so `ml-gateway-service` callbacks can find the correct saga.

Each successful `JOB_INGEST_ENRICHMENT_EMBEDDING_CALLBACK` stores its result, increments the received-callback count,
and advances the saga's optimistic version. Retrieval callbacks carry the full-listing result used for MUVERA, ColBERT,
and sparse retrieval; title callbacks carry the dense title result. The persisted enrichment context also retains the
LLM extraction result, geocoded coordinates, listing and correlation context, discovered-listing data, normalized skill
requirements, and any skill vectors needed to assemble the final message.

Completion is based on the invariant that received callbacks have reached the immutable expected count. The callback
that satisfies that invariant reconstructs the `StoredListing`, transitions the saga to `COMPLETED`, and records
`JOB_INGEST_ENRICHMENT_COMPLETED` in the outbox.

### Concurrency and terminal behavior

Callback recording takes a row-level lock before reading and mutating the saga. Concurrent callbacks arriving on
separate consumer threads or service replicas therefore serialize: a waiter resumes only after the preceding transaction
commits and then sees the updated count. The monotonically advancing version provides an additional concurrency signal.
Only the callback that observes convergence performs completion and outbox publication.

`COMPLETED`, `FAILED`, and `EXPIRED` are irreversible terminal outcomes. A duplicate callback against a completed saga
is rejected by the state machine with `InvalidTransitionError` and safely discarded rather than causing a second
completion. The same terminal-state rule prevents late callbacks from reviving failed or expired work.

### Lifecycle and retention

- A final successful callback moves the saga from `PENDING` to `COMPLETED` in the same transaction that records the
  completed event. Completed saga rows are retained for audit; no TTL cleanup removes them.
- An embedding callback carrying an error moves the saga to `FAILED`. No enrichment-completed event is emitted, and the
  listing remains in `job-storage-service` in its raw accepted state without enrichment data.
- A saga starts with a 30-minute expiry horizon. The periodic `StaleSagaDetector` moves a still-pending saga to
  `EXPIRED` after that horizon, covering missing callbacks caused by conditions such as an `ml-gateway-service` outage
  or a lost Kafka message.

Operational access is biased toward the active coordination set: operators and deduplication logic need efficient
pending-saga lookup by listing, the stale detector needs pending work ordered by expiry, and monitoring needs
time-window scans over append-heavy saga history. Terminal rows are intentionally kept out of the hot pending-search
paths, while creation-time access is optimized for low-overhead range monitoring.

## Transactional Outbox

The outbox closes the failure gap between database state and Kafka publication. The `COMPLETED` transition and the
`JOB_INGEST_ENRICHMENT_COMPLETED` record are committed atomically, so an event is never recorded for an uncompleted saga
and a process crash after the state change cannot leave a completed saga without its event. The event carries the fully
populated `StoredListing`.

Debezium captures the outbox insert from the PostgreSQL WAL and routes it to `job-ingest.fct.enrichment-completed.v1`.
The listing identifier becomes the Kafka message key, preserving per-listing ordering, and OpenTelemetry trace context
is propagated with the message. Write-time ordering supports connector catch-up after a restart and operational
inspection.

Under normal operation, the Debezium Outbox Event Router publishes an outbox row and then deletes it, so rows are
short-lived and there is one record for each completed enrichment. Accumulation is an operational signal that the
Debezium connector is unavailable or not draining the WAL-derived stream.

## Processed-Event Idempotency

Kafka handlers use a durable event-and-handler identity to prevent duplicate execution. A handler checks that identity
before doing work and skips a redelivery that it has already completed. Handler identity is part of the key so different
handlers may legitimately process the same event without conflicting.

The processed-event record and the handler's database changes commit atomically. If the consumer crashes before commit,
neither is retained and Kafka can redeliver the message; after commit, a redelivery is recognized and skipped.

Processed-event records are removed by periodic cleanup after seven days by default, configurable through
`get_cleanup_processed_events_sql`. That horizon is aligned with Kafka retention, so an identity is removed only after
its message can no longer be redelivered. Time-bounded cleanup is an expected operational workload rather than permanent
audit retention.

The schema itself is defined by the service's SQLAlchemy models in
`backend/services/job-ingest-enrichment-service/src/job_ingest_enrichment_service/db/models.py` and Alembic revision in
`backend/services/job-ingest-enrichment-service/alembic/versions/001_initial_migration.py`.
