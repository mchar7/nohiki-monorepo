# Job Storage Service Database Schema

Schema `job_storage_schema` stores the canonical job listing records for the Nohiki platform,
including enriched listing data, pre-computed embeddings, two deduplication keys, and a full
version history of every listing mutation.

## Entity Overview

| Table | Purpose |
|-------|---------|
| `listings` | Canonical job listing records: one row per unique real-world job posting |
| `listing_versions` | Immutable JSONB snapshots of listing state captured before each overwrite |
| `outbox` | Transactional outbox for CDC and fact event publishing via Debezium |
| `processed_events` | Idempotency guard tracking already-processed Kafka message IDs |

The `listings` table is the primary entity. Each row represents a single unique real-world job
posting, regardless of how many sources scraped it or how many times it was re-scraped. The
`listing_versions` table has a many-to-one relationship with `listings` via `listing_id` (with a
real foreign key and `ON DELETE CASCADE`), preserving a point-in-time snapshot each time an
enriched listing is overwritten. The `outbox` and `processed_events` tables are owned by
`nohiki-db-utils` and managed by Debezium.

## Table Details

### `listings`

#### Purpose

The single source of truth for every accepted job listing. A row is created when a discovered
listing passes pre-enrichment deduplication, then updated in-place when its LLM-enriched version
arrives. The row carries both the raw scraped fields and the fully structured enrichment output,
including dense embedding vectors for semantic matching.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key, generated server-side via `uuidv7()`. Encodes creation
  timestamp; sortable by insertion order without a secondary index.
- **`listing_url`** (`TEXT`): The canonical URL of the job posting on its source board. The
  primary same-source deduplication key -- `UNIQUE` constraint prevents two rows for the same URL.
- **`dedup_hash`** (`VARCHAR(64)`): SHA-256 of `lower(title) | lower(company_name) | date(posted_at)`.
  Cross-source deduplication key: the same job posted on LinkedIn and Indeed resolves to the same
  hash and therefore the same row. `UNIQUE` constraint enforces one canonical record per real-world
  job posting.
- **`raw_content_hash`** (`VARCHAR(64)`): SHA-256 of the raw scraped listing body. Used at discovery
  time to detect whether a re-scrape brought new content. If the hash matches the stored value and
  embeddings are already present, the listing is a content-identical duplicate and enrichment is
  skipped.
- **`job_board_source`** (`job_board_source_enum`): Source board -- `INDEED`, `LINKEDIN`,
  `ZIPRECRUITER`, `GOOGLE`, `GLASSDOOR`, `BAYT`, `NAUKRI`, or `COMPANY_WEBSITE`.
- **`status`** (`listing_status_enum`): Lifecycle state -- `ACTIVE`, `STALE`, or `EXPIRED`. State
  machine transitions are enforced by `StateMachineMixin`: `ACTIVE → STALE → EXPIRED` (one-way,
  no resurrection from `EXPIRED`).
- **`version`** (`INTEGER`): Monotonically increasing counter incremented on every enrichment
  update. Included in the `ListingSnapshot` carried by CDC events so consumers can detect
  out-of-order delivery.
- **`skills_embedding`** (`FLOAT8[]`): Dense embedding vector for the listing's skill set,
  computed by job-ingest-enrichment-service. Stored here so backfill callbacks can include
  embeddings without an extra ML round-trip.
- **`title_embedding`** (`FLOAT8[]`): Dense embedding vector for the listing title. Same purpose
  as `skills_embedding`. Both vectors must be present before the service will publish a
  `duplicate-detected` event or serve a listing in a backfill response.
- **`collection_version`** (`VARCHAR(10)`): The Qdrant collection version string (e.g., `v1`)
  from the ML manifest at the time embeddings were computed. Consumers use this together with the
  content hash to detect embedding staleness.
- **`canonical_skill_ids`** (`TEXT[]`): UUIDs of normalised canonical skills from
  `skill-graph-service`, resolved during enrichment. References `skill_graph_schema` records
  with no FK constraint because this is a cross-schema UUID reference.
- **`required_skills`** (`TEXT[]`): Raw skill name strings from the enrichment output, parallel
  to `canonical_skill_ids`. Used for FTS ranking (weighted `B` in the search trigger) and for
  array containment queries.
- **`compensation`** (`JSONB`): Raw compensation data from the enrichment output, structured as
  `{"items": [{"min": int, "max": int, "currency": str, "frequency": str}]}`. Converted to the
  typed `Compensation` proto by `publishers.py` when building the `ListingSnapshot` for events.
- **`location`** (`JSONB`): Structured location from enrichment: `{"city": str, "state": str,
  "country": str}`. The `CHECK` constraint rejects non-JSON values. Country must be a recognisable
  three-letter code (`USA`, `CAN`, `GBR`) to be included in the event snapshot's `Location` proto.
- **`search_vector`** (`TSVECTOR`): Populated automatically by the `trg_listings_search_vector_update`
  trigger on every insert and update. Combines title (weight `A`), company name (weight `B`),
  required skills (weight `B`), and description (weight `C`). Powers the FTS queries used by
  `JobStoreService.search_jobs_fts` with prefix-aware `to_tsquery`.
- **`discovered_at`** (`TIMESTAMPTZ`): When the scraper first saw this URL. Set at discovery time
  and preserved through enrichment updates, so it does not change on re-scrapes.
- **`processed_at`** (`TIMESTAMPTZ`): Set to `now()` when the enriched listing is banked. `NULL`
  means the listing was accepted for enrichment but enrichment has not yet completed. The backfill
  query filters on `processed_at IS NOT NULL` to avoid serving unenriched records.

#### Indexes

- **`ix_listings_url_unique`** (`listing_url`) `UNIQUE`: Same-source deduplication and the primary
  lookup path for the discovery handler (`_get_job_by_url`).
- **`ix_listings_dedup`** (`dedup_hash`) `UNIQUE`: Cross-source deduplication. Also the lookup
  path for the enrichment handler (`_get_job_by_dedup_hash`).
- **`ix_listings_search_vector`** GIN (`search_vector`): Enables `@@ to_tsquery(...)` full-text
  search. Used by `search_jobs_fts` to power the BFF's `/api/v1/listings?q=...` endpoint.
- **`ix_listings_skills_gin`** GIN (`required_skills`): Supports array containment (`@>`) and
  overlap (`&&`) queries used by `search_jobs_by_skills`. Allows the BFF to filter listings by
  specific skill sets without scanning all rows.
- **`ix_listings_location_gin`** GIN (`location jsonb_path_ops`): Supports JSONB containment
  queries on the location field used by `get_jobs_by_location`.
- **`ix_listings_active`** (`created_at DESC`) partial where `status = 'ACTIVE'`: Covers the
  most common query pattern: recent active listings. The partial condition keeps the index small
  by excluding stale and expired rows.
- **`ix_listings_discovered_at_brin`** BRIN (`discovered_at`): Time-series data is naturally
  correlated with physical page order, so a BRIN index is 100× smaller than a B-tree while still
  serving the backfill query's `discovered_at >= cutoff` filter.
- **`ix_listings_created_at_brin`** BRIN (`created_at`): Same rationale as `discovered_at`.
- **`ix_listings_source_hash`** HASH (`job_board_source`): Equality-only lookup by source board;
  hash indexes are more space-efficient than B-tree for low-cardinality enum columns.
- **`ix_listings_content_hash`** (`raw_content_hash`) partial where `raw_content_hash IS NOT NULL`:
  Supports change-detection lookups by content hash during the discovery dedup flow.
- **`ix_listings_company_name`** B-tree (`company_name`): Supports company-scoped queries.
- **`ix_listings_work_arrangement`** B-tree (`work_arrangement`): Supports remote/hybrid/on-site
  filter queries.

#### Constraints & Invariants

- **`UNIQUE` on `listing_url`**: One canonical record per URL. Acts as the idempotency key for
  the `JOB_INGEST_LISTING_DISCOVERED` handler: duplicate inserts for the same URL raise
  `IntegrityError` and are silently discarded.
- **`UNIQUE` on `dedup_hash`**: One canonical record per real-world job posting. Acts as the
  idempotency key for the `JOB_INGEST_ENRICHMENT_COMPLETED` handler when cross-source duplicates
  arrive.
- **`chk_experience_range`**: Requires `min_experience_years <= max_experience_years` when both
  are non-null, preventing obviously invalid enrichment output from being stored.
- **`chk_location_json`** / **`chk_compensation_json`**: Reject malformed JSONB by requiring
  `IS NULL OR IS JSON`.

#### Data Lifecycle

- **Created** (skeleton row) when `JOB_INGEST_LISTING_DISCOVERED` is consumed and the URL is not
  yet known. Fields populated at this stage: URL, source, title, company, description, location
  raw, `raw_content_hash`, `dedup_hash`, `discovered_at`. Classification fields default to
  `UNSPECIFIED`; embeddings are `NULL`.
- **Updated** (fully enriched) when `JOB_INGEST_ENRICHMENT_COMPLETED` is consumed. All structured
  fields, embeddings, `collection_version`, and `processed_at` are written. `version` increments.
  A `ListingVersion` snapshot is written before the update if embeddings were already present.
- **Updated again** on subsequent re-scrapes where `raw_content_hash` changes, triggering
  re-enrichment and a further version increment.
- **Status transitioned** (`ACTIVE → STALE → EXPIRED`) by external operators or scheduled jobs
  (not handled by this service's Kafka handlers directly).
- **Deleted** via `delete_job` in `JobStoreService`, which writes a `listing-deleted` outbox event
  atomically. Cascade delete propagates to `listing_versions`.

---

### `listing_versions`

#### Purpose

An immutable audit trail of listing state, capturing a full JSONB snapshot of the listing before
each overwrite. Enables forensic analysis of how a listing's content, skills, or compensation
changed across successive enrichment runs.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key, generated server-side.
- **`listing_id`** (`UUID`): References `job_storage_schema.listings.id` via a real foreign key
  with `ON DELETE CASCADE`. When a listing is deleted, all its version history is deleted too.
- **`version`** (`INTEGER`): The `listings.version` value at the moment this snapshot was taken --
  i.e., the version number of the listing state captured here, before it was incremented.
- **`raw_content_hash`** (`VARCHAR(64)`): The `raw_content_hash` of the listing at the time of
  this version, allowing callers to identify what content produced each snapshot.
- **`snapshot`** (`JSONB`): A serialised `ListingSnapshot` proto (via `.to_dict()`) representing
  the complete listing state at this version. Contains all enriched fields, embeddings, and
  metadata.
- **`change_type`** (`VARCHAR(20)`): One of `created`, `updated`, or `enriched`. Constrained by
  `chk_change_type`. Currently only `enriched` is written (the snapshot is captured before
  overwriting an already-enriched row).
- **`correlation_id`** (`VARCHAR(255)`): Propagated from the enrichment event for distributed
  tracing across the ingest pipeline.

#### Indexes

- **`ix_listing_versions_listing_id`** (`listing_id`): Supports fetching all versions for a given
  listing.
- **`ix_listing_versions_listing_version`** (`listing_id`, `version DESC`): Supports fetching the
  most recent version for a listing efficiently, and ordered version history browsing.
- **`ix_listing_versions_created_at_brin`** BRIN (`created_at`): Supports time-range queries over
  version history (e.g., all changes in the last 7 days).

#### Constraints & Invariants

- **Foreign key** `listing_id → listings.id ON DELETE CASCADE`: Version history is owned by its
  parent listing; deletion is automatic and consistent.
- **`chk_change_type`**: Restricts `change_type` to `('created', 'updated', 'enriched')`.
- **`chk_version_positive`**: Requires `version > 0`.

#### Data Lifecycle

- **Created** by `JobStoreService._store_version_history` immediately before an enriched listing
  is overwritten, but only if the listing already has embeddings present. This ensures only
  meaningful state transitions (enrichment → re-enrichment) are captured, not skeleton-row
  overwrites.
- **Never updated** -- rows are immutable by design.
- **Deleted** automatically when the parent `listings` row is deleted (cascade).

---

### `outbox`

#### Purpose

Standard transactional outbox table managed by `nohiki-db-utils`. Every CDC and fact event
published by this service is first written here in the same transaction as the domain change.
Debezium's PostgreSQL connector reads the WAL and forwards each row to Kafka, then marks it
processed.

#### Events Published via Outbox

- `job-listing.fct.accepted.v1` -- New or content-changed listing accepted for enrichment
- `job-listing.fct.duplicate-detected.v1` -- Incoming listing identified as a known duplicate
- `job-listing.cdc.listing-created.v1` -- Enriched listing banked (new or updated)
- `job-listing.cdc.listing-updated.v1` -- Enriched listing overwrote an existing record
- `job-listing.cdc.listing-deleted.v1` -- Listing deleted from the bank

The outbox table schema and Debezium connector configuration are managed by `nohiki-db-utils`.
See `infra/kafka-connect/connectors/` for the Debezium connector descriptor.

---

### `processed_events`

#### Purpose

Idempotency guard table managed by `nohiki-db-utils`. Records the Kafka message IDs of events
that have already been processed. Handlers that need strict once-only semantics check this table
before executing business logic.

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
