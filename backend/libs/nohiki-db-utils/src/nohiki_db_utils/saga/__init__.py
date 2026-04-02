"""Convergence-saga primitives for multi-callback event-driven workflows.

This module is the canonical reference for the saga pattern used across the
Nohiki backend. Services that must wait on multiple asynchronous events before
committing a downstream effect (publishing an outbox event, inserting into a
canonical table, etc.) build their saga table on ``SagaBaseMixin`` and drive
it through ``SagaRepository`` plus ``StaleSagaDetector``.

Lifecycle
---------
PENDING → COMPLETED : all expected callbacks recorded, terminal effect applied
PENDING → FAILED    : unrecoverable error from an upstream callback
PENDING → EXPIRED   : ``StaleSagaDetector`` swept the row past ``expires_at``

COMPLETED, FAILED, and EXPIRED are terminal; ``StateMachineMixin`` rejects
further transitions.

Partial-unique-on-PENDING idiom
-------------------------------
Sagas whose business key (e.g. listing URL) must be unique *while in flight* but
whose terminal rows must remain queryable for audit use a PostgreSQL partial
unique index:

    CREATE UNIQUE INDEX uq_listing_ingest_saga_pending_url
        ON job_storage_schema.listing_ingest_saga (listing_url)
        WHERE status = 'PENDING';

This guarantees at most one in-flight saga per key without preventing later
COMPLETED / EXPIRED rows from coexisting on the same key. After a stale saga is
swept to EXPIRED, a fresh discovery of the same URL can insert a new PENDING
row without an ``ON CONFLICT`` clash.

Interaction with the canonical post-completion table
----------------------------------------------------
For sagas whose successful completion populates a canonical table (e.g.
``ListingIngestSaga`` → ``listings``), the saga's UUID is reused as the
canonical row's primary key. This anchors the same identifier across the
entire event chain (``ListingAccepted`` → ``EnrichmentCompleted`` →
``ListingCreated``) and means the canonical table never sees pre-enrichment
placeholder rows: it only receives fully-validated data on ``transition_to(COMPLETED)``.

Concrete users
--------------
- ``ListingIngestSaga`` (``job-storage-service``): tracks discovered listings
  from ``ListingDiscovered`` to the canonical ``listings`` row, with a 24h TTL.
- ``EnrichmentEmbeddingSaga`` (``job-ingest-enrichment-service``): waits for
  retrieval, title, and skills embedding callbacks before publishing
  ``EnrichmentCompleted``, with a 30-minute TTL.

See ``backend/libs/nohiki-db-utils/README.md`` for end-to-end code examples
covering saga creation, callback recording, completion with outbox, and stale
sweep wiring.

Operational runbook
-------------------
Inspect stuck PENDING sagas (job-storage-service):

    SELECT id, listing_url, received_callbacks, expected_callbacks,
           created_at, expires_at, now() - expires_at AS overdue
    FROM job_storage_schema.listing_ingest_saga
    WHERE status = 'PENDING' AND expires_at < now()
    ORDER BY expires_at ASC LIMIT 50;

Inspect stuck PENDING sagas (job-ingest-enrichment-service):

    SELECT id, listing_id, received_callbacks, expected_callbacks,
           created_at, expires_at, now() - expires_at AS overdue
    FROM job_ingest_enrichment_schema.enrichment_embedding_saga
    WHERE status = 'PENDING' AND expires_at < now()
    ORDER BY expires_at ASC LIMIT 50;

Manually expire or fail a saga (e.g. when the upstream worker is permanently lost):

    UPDATE job_storage_schema.listing_ingest_saga
    SET status = 'EXPIRED', version = version + 1
    WHERE id = '<uuid>' AND status = 'PENDING';

The ``WHERE status = 'PENDING'`` guard mirrors the in-code state machine guard
and prevents accidentally re-transitioning a terminal row.

Metrics to watch
----------------
- ``stale_saga_total{model="..."}``: gauge of PENDING sagas past ``expires_at``.
  A non-zero steady-state indicates lost upstream callbacks.
- ``expired_saga_total{model="..."}``: counter of sagas the sweep has
  transitioned to EXPIRED. Sustained growth signals chronic upstream failure
  (ML worker outage, dead-letter queue backlog, etc).

"""

from nohiki_db_utils.saga.models import SagaBaseMixin, SagaStatus
from nohiki_db_utils.saga.repository import SagaRepository
from nohiki_db_utils.saga.stale import StaleSagaDetector

__all__ = [
    "SagaBaseMixin",
    "SagaRepository",
    "SagaStatus",
    "StaleSagaDetector",
]
