# Job Storage Service Database Design

Schema `job_storage_schema` stores the canonical job listing records for the Nohiki platform,
including enriched listing data, pre-computed embeddings, two deduplication keys, and a full
version history of every listing mutation.

The `listings` table is the primary entity. Each row represents a single unique real-world job
posting, regardless of how many sources scraped it or how many times it was re-scraped. The
`listing_versions` table has a many-to-one relationship with `listings` via `listing_id`,
preserving a point-in-time snapshot each time an enriched listing is overwritten. The `outbox` and
`processed_events` tables are owned by `nohiki-db-utils`.

## `listings`

### Purpose

The single source of truth for every accepted job listing. A row is created when the enrichment
result for an accepted listing is banked, not at discovery: discovery records the in-flight
`listing_ingest_saga` row instead. The row carries both the raw scraped fields and the fully
structured enrichment output, including dense embedding vectors for semantic matching.

### Semantics

- `listing_url`: The canonical URL of the job posting on its source board. The primary same-source
  deduplication key.
- `dedup_hash`: SHA-256 of `lower(title) | lower(company_name) | date(posted_at)`. Cross-source
  deduplication key: the same job posted on LinkedIn and Indeed resolves to the same hash and
  therefore the same row.
- `raw_content_hash`: SHA-256 of the raw scraped listing body. Discovery compares the incoming
  content hash against the pending saga row for the same URL rather than against this column: an
  equal hash is an idempotent redelivery and no second `ListingAccepted` is published.
- `status`: Lifecycle state. The transition map declared on the model allows `ACTIVE` to `STALE` or
  `EXPIRED`, and `STALE` back to `ACTIVE` or on to `EXPIRED`; no code in this service performs a
  listing status transition, so rows stay in the `ACTIVE` state written at banking time. Read paths
  filter on `status = 'ACTIVE'`.
- `version`: Monotonically increasing counter incremented on every enrichment update. Included in
  the `ListingSnapshot` carried by CDC events so consumers can detect out-of-order delivery.
- `skills_embedding` / `title_embedding`: Dense embedding vectors for the listing's skill set and
  title, computed by job-ingest-enrichment-service. Stored here so backfill callbacks can include
  embeddings without an extra ML round-trip. Both vectors must be present before the service will
  serve a listing in a backfill response.
- `collection_version`: The Qdrant collection version string from the ML manifest at the time
  embeddings were computed. Consumers use this together with the content hash to detect embedding
  staleness.
- `canonical_skill_ids`: UUIDs of normalised canonical skills from `skill-graph-service`, resolved
  during enrichment. References `skill_graph_schema` records with no FK constraint because this is
  a cross-schema UUID reference.
- `required_skills`: Raw skill name strings from the enrichment output, parallel to
  `canonical_skill_ids`. Used for FTS ranking (weighted `B` in the search trigger) and for
  array containment queries.
- `compensation`: Raw compensation data from the enrichment output. Converted to the typed
  `Compensation` proto by `publishers.py` when building the `ListingSnapshot` for events.
- `location`: Structured location from enrichment. Country must be a recognisable three-letter code
  (`USA`, `CAN`, `GBR`) to be included in the event snapshot's `Location` proto.
- `search_vector`: Populated automatically by a database trigger on every insert and update.
  Combines title (weight `A`), company name (weight `B`), required skills (weight `B`), and
  description (weight `C`). Powers the FTS queries used by `JobStoreService.search_jobs_fts` with
  prefix-aware `to_tsquery`.
- `discovered_at`: When the scraper first saw this URL. Set at discovery time and preserved through
  enrichment updates, so it does not change on re-scrapes.
- `processed_at`: Set to `now()` when the enriched listing is banked. `NULL` means the listing was
  accepted for enrichment but enrichment has not yet completed. The backfill query filters on
  `processed_at IS NOT NULL` to avoid serving unenriched records.

### Access Patterns

- Enables `@@ to_tsquery(...)` full-text search. Used by `search_jobs_fts` to power the BFF's
  `/api/v1/listings?q=...` endpoint.
- Supports array containment (`@>`) and overlap (`&&`) queries used by
  `search_jobs_by_skills`. Allows the BFF to filter listings by specific skill sets without
  scanning all rows.
- Supports JSONB containment queries on the location field used by `get_jobs_by_location`.
- Covers the most common query pattern: recent active listings. The partial condition keeps the
  access path small by excluding stale and expired rows.
- Time-series data is naturally correlated with physical page order, so the BRIN access path is
  100× smaller than a B-tree while still serving the backfill query's `discovered_at >= cutoff`
  filter.

### Data Lifecycle

- **Created** when `JOB_INGEST_ENRICHMENT_COMPLETED` is consumed for a URL with no existing
  canonical row; the new row takes the accepting saga's UUID as its `id`.
- **Updated** (fully enriched) when `JOB_INGEST_ENRICHMENT_COMPLETED` is consumed and a row already
  exists for the `dedup_hash` or the URL. All structured fields, embeddings, `collection_version`,
  and `processed_at` are written. `version` increments. A `ListingVersion` snapshot is written
  before the update if embeddings were already present.
- **Updated again** on subsequent re-scrapes where `raw_content_hash` changes, triggering
  re-enrichment and a further version increment.
- **Deleted** via `delete_job` in `JobStoreService`, which writes a `listing-deleted` outbox event
  atomically. Cascade delete propagates to `listing_versions`.

## `listing_versions`

### Purpose

An immutable audit trail of listing state, capturing a full JSONB snapshot of the listing before
each overwrite. Enables forensic analysis of how a listing's content, skills, or compensation
changed across successive enrichment runs.

### Semantics

- `version`: The `listings.version` value at the moment this snapshot was taken, i.e., the version
  number of the listing state captured here, before it was incremented.
- `raw_content_hash`: The `raw_content_hash` of the listing at the time of this version, allowing
  callers to identify what content produced each snapshot.
- `snapshot`: A serialised `ListingSnapshot` proto (via `.to_dict()`) representing the complete
  listing state at this version. Contains all enriched fields, embeddings, and metadata.
- `change_type`: Currently only `enriched` is written (the snapshot is captured before overwriting
  an already-enriched row).
- `correlation_id`: Propagated from the enrichment event for distributed tracing across the ingest
  pipeline.

### Access Patterns

- Supports fetching all versions for a given listing.
- Supports fetching the most recent version for a listing efficiently, and ordered version history
  browsing.
- Supports time-range queries over version history (e.g., all changes in the last 7 days).

### Data Lifecycle

- **Created** by `JobStoreService._store_version_history` immediately before an enriched listing
  is overwritten, but only if the listing already has embeddings present. This ensures only
  meaningful state transitions (enrichment to re-enrichment) are captured, not skeleton-row
  overwrites.
- **Never updated**: rows are immutable by design.
- **Deleted** automatically when the parent `listings` row is deleted (cascade).

## `outbox`

### Purpose

Standard transactional outbox table managed by `nohiki-db-utils`. Every CDC and fact event
published by this service is first written here in the same transaction as the domain change.
Debezium's PostgreSQL connector reads the WAL and forwards each row to Kafka; it does not mark or
delete the rows it has read.

### Events Published via Outbox

- `job-listing.fct.accepted.v1` -- New or content-changed listing accepted for enrichment
- `job-listing.cdc.listing-created.v1` -- Enriched listing banked (new or updated)
- `job-listing.cdc.listing-updated.v1` -- Enriched listing overwrote an existing record, or a
  snapshot refresh was requested
- `job-listing.cdc.listing-deleted.v1` -- Listing deleted from the bank

The outbox table schema and Debezium connector configuration are managed by `nohiki-db-utils`.
See `infra/k8s/kafka-connect/connectors/` for the Debezium connector descriptor.

## `processed_events`

### Purpose

Idempotency guard table managed by `nohiki-db-utils`, created for this schema by the baseline
migration. Records the Kafka message IDs of events that have already been processed.
`handle_job_raw_found` checks and marks this table before executing business logic; the enrichment,
backfill, and refresh handlers do not claim events here.

## Source of Truth

- Models: `backend/services/job-storage-service/src/job_storage_service/db/models.py`
- Baseline revision: `backend/services/job-storage-service/alembic/versions/001_initial_migration.py`
- Migration workflow: [`../../../README.md#database-migration-workflow`](../../../README.md#database-migration-workflow)
