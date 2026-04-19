# Job Storage Service

The canonical store for all job listings in Nohiki. This service sits at the centre of the job
domain: it receives scraped listings from the ingest pipeline, deduplicates them across sources and
re-scrapes, persists the enriched record with pre-computed embeddings, and publishes CDC events that
drive both the user-facing job feed (via BFF projections) and the ML scoring pipeline (via
job-correlation-evaluation-service). Kafka-only, stateful with PostgreSQL.

## Role in the System

Job Storage occupies the boundary between the ingest pipeline and the rest of the platform. The
ingest pipeline (discovery → enrichment) produces raw and enriched listing data. Job Storage is
the first service that decides whether a listing is genuinely new, a content update to something
already stored, or a cross-source duplicate of a listing already in the bank, and acts accordingly.
No other service makes this determination.

After accepting and storing an enriched listing, Job Storage publishes `job-listing.cdc.listing-created.v1`
and (on updates) `job-listing.cdc.listing-updated.v1` via the transactional outbox. These CDC events
carry the full `ListingSnapshot` -- title, company, location, skills, pre-computed embeddings, and
compensation, so downstream consumers never need to query back. The BFF consumes these events to
maintain its projection tables for the `/api/v1/listings` endpoint, and job-correlation-evaluation-service
consumes them to score each new or updated listing against every stored user preference.

Job Storage also serves as the listing data provider for profile backfill. When job-correlation-evaluation-service
creates a new user preference and needs to score it against existing listings, it publishes a
`job-listing.cmd.backfill-requested.v1` command. Job Storage queries active, enriched listings
from the last N days and streams them back in batches via the callback topic.

## Event-Driven Integration

### Events Consumed

- **`JOB_INGEST_LISTING_DISCOVERED`** (`job-ingest.fct.listing-discovered.v1`, `ListingDiscovered`):
  The first signal from the ingest pipeline. The handler extracts the URL and `content_hash` from
  the raw scraped data and runs pre-enrichment deduplication: if the URL is new, it inserts a
  skeleton record and publishes `job-listing.fct.accepted.v1` to trigger LLM enrichment; if the
  URL exists but the content hash changed, it updates the hash and re-triggers enrichment; if the
  URL exists with the same hash and embeddings are present, it publishes
  `job-listing.fct.duplicate-detected.v1` and stops. Consumer group: `settings.kafka.consumer_group`
  (default, configured via `KAFKA__CONSUMER_GROUP`). Idempotent via `UNIQUE` constraint on
  `listing_url` -- concurrent inserts for the same URL raise `IntegrityError` and are safely
  discarded.

- **`JOB_INGEST_ENRICHMENT_COMPLETED`** (`job-ingest.fct.enrichment-completed.v1`, `EnrichmentCompleted`):
  Carries the LLM-enriched `StoredListing` proto: structured skills, seniority, work arrangement,
  compensation, location, and pre-computed dense embeddings (skills and title vectors). The handler
  runs cross-source deduplication using `dedup_hash` (SHA-256 of normalised title + company +
  posted date), then either inserts or updates the canonical listing row, stores a version snapshot,
  and publishes `job-listing.cdc.listing-created.v1` (and `listing-updated.v1` on updates) via the
  outbox. Consumer group: same as above; idempotent via `UNIQUE` constraint on `dedup_hash`.

- **`JOB_LISTING_BACKFILL_REQUESTED`** (`job-listing.cmd.backfill-requested.v1`, `BackfillRequested`):
  A command from job-correlation-evaluation-service requesting a batch of recent listings for a
  specific user preference. The handler queries active, enriched listings (those with `processed_at`
  set) from the last `since_days` days, up to `max_listings`, and streams them as `BackfillCallback`
  messages in configurable batch sizes to the `callback_topic` embedded in the command header.
  Consumer group: `{base_group}-backfill`. The handler uses `preserve_partition_order=False` to
  allow parallel processing of concurrent backfill requests.

### Events Published

- **`job-listing.fct.accepted.v1`** (`ListingAccepted`): Published via the transactional outbox
  when a discovered listing passes pre-enrichment deduplication: either because it is genuinely
  new or its content changed. This event is consumed by job-ingest-enrichment-service to trigger
  LLM enrichment of the listing.

- **`job-listing.fct.duplicate-detected.v1`** (`DuplicateDetected`): Published via the transactional
  outbox when an incoming discovered listing matches an already-stored, already-enriched record
  (same URL, same `raw_content_hash`, embeddings present). Carries the existing `ListingSnapshot`
  so downstream consumers can reference the canonical record without re-querying.

- **`job-listing.cdc.listing-created.v1`** (`ListingCreated`): Published via the transactional
  outbox after an enriched listing is banked (whether new or updated, the `was_updated` flag
  distinguishes). Carries the full `ListingSnapshot` including pre-computed embeddings and
  `retrieval_embeddings`. Consumed by bff-service (for the listings projection table) and
  job-correlation-evaluation-service (to trigger scoring against all user preferences).

- **`job-listing.cdc.listing-updated.v1`** (`ListingUpdated`): Published alongside `listing-created`
  when an enriched listing overwrites an existing record. Carries the updated snapshot. Consumed by
  the same downstream services as `listing-created`.

- **`job-listing.cdc.listing-deleted.v1`** (`ListingDeleted`): Published via the transactional
  outbox when a listing is deleted from the bank. Consumed by downstream services to purge
  projections and correlations.

- **`BackfillCallback`** (to the requester's `callback_topic`): Published directly (not via outbox)
  in response to `JOB_LISTING_BACKFILL_REQUESTED`. Delivered in batches; each message includes
  `batch_number`, `total_batches`, and `is_final_batch` so the correlation service can detect
  completion without a saga coordinator.

### Notable Patterns

**Transactional outbox**: All CDC and fact events (`listing-accepted`, `duplicate-detected`,
`listing-created`, `listing-updated`, `listing-deleted`) are written to the `outbox` table in the
same database transaction as the domain row change. Debezium's PostgreSQL connector reads the WAL
and publishes to Kafka. This guarantees exactly-once delivery even if the service crashes after
committing.

**Two-phase deduplication**: Deduplication runs at two distinct stages. At discovery time, the
service deduplicates by `listing_url` (same-source re-scrape detection) and by `raw_content_hash`
(unchanged content detection). At enrichment time, it deduplicates by `dedup_hash` (cross-source
detection: the same real-world job posted on both LinkedIn and Indeed resolves to the same canonical
row). A cross-source match takes precedence over a URL match.

**Backfill callback pattern**: The backfill handler streams results in configurable batches
(default 50 per message, up to 500 listings total, looking back up to 30 days) to avoid producing
Kafka messages that exceed size limits. `preserve_partition_order=False` lets multiple concurrent
backfill requests proceed in parallel rather than serialising behind a single partition.

**Version history**: Before overwriting an enriched listing, the service snapshots the current row
into `listing_versions` as a JSONB blob. This gives an immutable audit trail of how a listing's
content evolved through successive scrapes and enrichments.

## State & Persistence

### Database

Schema `job_storage_schema` stores two domain tables (`listings`, `listing_versions`) plus the
standard `outbox` and `processed_events` tables. The `listings` table is the canonical record for
every accepted job listing, storing the full enriched state alongside pre-computed embeddings and
two deduplication keys. The `listing_versions` table preserves a JSONB snapshot of each listing
state at the moment it was overwritten.

See [DATABASE.md](./DATABASE.md) for complete schema documentation.

## Key Design Patterns

**ECST snapshot in CDC events**: Every `ListingCreated` and `ListingUpdated` event carries the
full `ListingSnapshot` protobuf, including pre-computed dense embeddings. Downstream consumers
(BFF, correlation service) never query job-storage-service directly, so all data they need arrives
in the event. The embeddings stored in `listings.skills_embedding` and `listings.title_embedding`
are also embedded in the snapshot so correlation evaluation starts immediately upon receiving the
CDC event.

**`dedup_hash` for cross-source canonicalization**: The hash is computed as
`SHA-256(lower(title) | lower(company_name) | date(posted_at))`. This normalises away source-specific
formatting differences and catches the same job posted on multiple boards. The `UNIQUE` constraint
on `dedup_hash` doubles as an idempotency guard: a duplicate enrichment event for the same real-world
job silently updates rather than inserting a second row.

## Configuration

The service uses `DatabaseMixin` and `KafkaMixin` from `nohiki-core-settings`.

Key settings (prefix `JOB_STORAGE_`):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE__URL` | -- | PostgreSQL DSN (required) |
| `KAFKA__DSN` | `kafka://localhost:29092` | Kafka bootstrap server |
| `KAFKA__CONSUMER_GROUP` | `default-group` | Base consumer group for ingest handlers |
| `KAFKA__CONSUMER__MAX_CONCURRENT_HANDLERS` | `15` | I/O-bound workload: concurrent handler limit |
| `JOB_STORAGE_BACKFILL__DEFAULT_MAX_LISTINGS` | `500` | Max listings returned per backfill request |
| `JOB_STORAGE_BACKFILL__DEFAULT_SINCE_DAYS` | `30` | Lookback window for backfill queries |
| `JOB_STORAGE_BACKFILL__BATCH_SIZE` | `50` | Listings per `BackfillCallback` message |

The backfill settings cap the blast radius of a single backfill request: a new user with many
stored profiles could otherwise trigger queries returning tens of thousands of rows.

## Development

### Local Setup

```bash
uv sync
alembic upgrade head
```

### Testing

```bash
just test job-storage-service
just test-cov job-storage-service
```

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise
uv run ty check
```

Requires a running PostgreSQL instance with the `job_storage_schema` schema applied. The service
also requires a reachable Kafka broker, because the lifespan startup calls `ensure_kafka_ready` and will
not complete until the broker responds.
