# Job Storage Database Design

The `job_storage_schema` is the canonical store for accepted job listings. It owns the raw discovery data, structured
enrichment output, pre-computed embeddings, canonicalization state, and the retained history of enriched overwrites.
Each canonical listing represents one real-world posting regardless of how many sources scraped it or how often it was
re-scraped.

## Ownership and data boundaries

The canonical listing begins as a discovery skeleton after a `JOB_INGEST_LISTING_DISCOVERED` event passes pre-enrichment
deduplication. The same record is updated in place when `JOB_INGEST_ENRICHMENT_COMPLETED` supplies structured enrichment
and dense skill and title embeddings. Keeping raw and enriched states together lets the service decide whether later
scrapes are unchanged, changed, or cross-source duplicates without consulting another service.

Canonical skill identities are resolved during enrichment from `skill-graph-service`; the listing retains those
identities alongside the raw skill names. Embeddings are computed by `job-ingest-enrichment-service` and stored here so
CDC snapshots and backfill callbacks can reuse them without another ML round trip. The embedding collection version is
retained with the content fingerprint so consumers can detect stale embeddings.

Compensation remains in the enrichment representation and is converted to the typed `Compensation` message when an event
snapshot is built. Structured locations are likewise converted for event snapshots; only recognized three-letter country
codes are included in the typed `Location` message.

Canonical identifiers are time-sortable, preserving insertion order without an auxiliary ordering structure.

## Deduplication, idempotency, and ordering

Deduplication combines canonical identity with content-change detection:

- The canonical listing URL identifies repeated observations from the same source. Concurrent attempts to create the
  same URL cannot create two canonical records; the losing insert is treated as an already-handled discovery.
- A SHA-256 fingerprint of normalized title, company name, and posting date identifies the same real-world job across
  different sources. It also makes repeated enrichment completion events idempotent instead of creating another
  canonical record.
- A separate fingerprint of the raw scraped body detects content changes. When that fingerprint is unchanged and
  embeddings already exist, enrichment is skipped and the incoming observation is treated as a duplicate. A changed
  fingerprint causes another enrichment pass.

Handlers that require strict once-only processing check the shared `processed_events` store before executing business
logic and record consumed Kafka message identities there. `nohiki-db-utils` supplies this idempotency store.

Each enrichment update advances a monotonically increasing listing version. That version is included in CDC
`ListingSnapshot` messages so consumers can identify out-of-order delivery.

## Listing and audit lifecycle

A newly accepted discovery contains the scraped identity and content needed for deduplication, but is not yet enriched.
Backfill excludes that incomplete state. When enrichment completes, the service writes the structured fields,
embeddings, embedding provenance, and completion marker, then advances the listing version.

If a listing already has embeddings, the service captures its current `ListingSnapshot` immediately before an enrichment
overwrite. These serialized snapshots form an immutable audit trail for forensic comparison of content, skills,
compensation, and metadata across re-enrichments. Audit entries retain the listing version and content fingerprint that
produced the snapshot, and propagate the enrichment event's correlation identity for distributed tracing. They currently
represent enrichment overwrites rather than the initial discovery-to-enrichment transition.

Audit history belongs to its canonical listing: it is never updated and is removed when the listing is deleted. Listing
deletion also writes the `listing-deleted` outbox event in the same transaction.

Discovery time records when the scraper first saw the URL and survives later enrichment updates and re-scrapes. The
enrichment completion marker distinguishes listings safe to return in backfill from accepted discoveries still awaiting
enrichment.

Listing status moves in one direction from active to stale to expired. An expired listing cannot be resurrected.
Operators or scheduled jobs perform these transitions; the service's Kafka handlers do not.

## Query design

Exact URL and cross-source fingerprint lookups serve the two deduplication stages. Content-fingerprint lookups cover
records eligible for content-change detection. Company and work-arrangement access paths support their corresponding
scoped filters.

Full-text search weights title most strongly, company and required skills next, and description last. Search access
supports weighted full-text queries, skill containment and overlap, and structured-location filtering. These paths power
the BFF's `/api/v1/listings?q=...` search and skill and location filters.

Storage is optimized for recent active browsing, append-correlated time-window and backfill scans, and equality
filtering by source.

Audit access paths support ordered history for one listing, efficient retrieval of its latest version, and time-range
analysis such as reviewing recent changes.

Backfill queries return only active, fully enriched listings observed within the requested time window. Both dense
embeddings must be present before a listing is returned in backfill or used to publish a `duplicate-detected` snapshot.

## Event atomicity and operations

The service writes its CDC and fact events to the shared transactional outbox in the same database transaction as the
corresponding listing change. This covers:

- `job-listing.fct.accepted.v1` for a new or content-changed discovery accepted for enrichment
- `job-listing.fct.duplicate-detected.v1` for a known, already-enriched duplicate
- `job-listing.cdc.listing-created.v1` whenever an enriched listing is banked, including updates
- `job-listing.cdc.listing-updated.v1` when enrichment overwrites an existing listing
- `job-listing.cdc.listing-deleted.v1` when a listing is deleted

The outbox implementation and Debezium connector configuration are managed by `nohiki-db-utils`. The PostgreSQL
connector reads committed outbox records from the WAL, forwards them to Kafka, and marks them processed. The database
mutation and outbox record are atomic; Kafka publication still depends on that connector completing the WAL relay. Its
descriptor is maintained under `infra/k8s/kafka-connect/connectors/`.

The schema itself is defined by the service's SQLAlchemy models at
`backend/services/job-storage-service/src/job_storage_service/db/models.py` and Alembic revision at
`backend/services/job-storage-service/alembic/versions/001_initial_migration.py`.
