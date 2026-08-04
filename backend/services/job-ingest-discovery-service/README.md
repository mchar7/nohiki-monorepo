# Job Ingest Discovery Service

Scrapes raw job listings from Indeed, LinkedIn, Glassdoor, ZipRecruiter, and Google Jobs using the
[JobSpy](https://github.com/Bunsly/JobSpy) library, triggered exclusively by Kafka command events from
`job-ingest-schedule-service`. Deduplicates scraped results using a Redis content-hash cache before
Kafka-only, stateless: no database, no LLM,
no S3, no outbox.

## Role in the System

This service is the entry point for all job data flowing into Nohiki. The schedule service decides
_when_ to scrape (based on query frequency settings) and emits a `JOB_INGEST_DISCOVERY_REQUESTED`
command carrying a fully-specified `IngestionQuery`. This service wakes up, executes the scrape, and
publishes one `JOB_INGEST_LISTING_DISCOVERED` event per novel result. It never initiates scrapes on
its own schedule. It is purely reactive.

Discovery is profile-agnostic by design. The `IngestionTriggered` message carries no `user_id` or
`pref_id`; the `IngestionQuery` describes _what_ to search (keywords, locations, boards, freshness
window) without knowing _who_ asked for it. Job-user matching is a concern of
`job-correlation-evaluation-service`, not this service.

Downstream, `job-ingest-enrichment-service` consumes every `JOB_INGEST_LISTING_DISCOVERED` event and
runs LLM enrichment (structured extraction of skills, compensation, work arrangement, experience
requirements) before the listing enters permanent storage via `job-storage-service`. This service
publishes raw scraped data only. Enrichment happens entirely downstream.

## Event-Driven Integration

### Events Consumed

- **`JOB_INGEST_DISCOVERY_REQUESTED`** (`job-ingest.cmd.discovery-requested.v1`, message type
  `IngestionTriggered`): The sole trigger for all discovery runs. Emitted by
  `job-ingest-schedule-service` on the cadence configured per query. The message body wraps an
  `IngestionQuery` carrying:
  - `search_keywords` -- one or more job title / skill strings (e.g., `["Senior Python Engineer"]`)
  - `locations` -- list of structured locations (city, state/province, country, `location_type`)
  - `work_arrangements` -- filter set (`REMOTE`, `ON_SITE`, `HYBRID`); empty means all
  - `sources` -- which job boards to target; defaults to Indeed + LinkedIn when absent
  - `hours_old` -- freshness window (only listings posted within this many hours)
  - `results_wanted` -- upper bound on results per source, capped by `discovery.max_results_per_source`
    (3 in development, 25 in production)

  Consumer group: configured via `JOB_INGEST_DISCOVERY__KAFKA__CONSUMER_GROUP` (defaults from
  `NohikiBaseSettings`). `preserve_partition_order=False` is intentional. Discovery runs are
  independent and benefit from concurrent processing.

### Events Published

- **`JOB_INGEST_LISTING_DISCOVERED`** (`job-ingest.fct.listing-discovered.v1`, message type
  `ListingDiscovered`): Published once per novel listing that passes deduplication. The message
  carries:
  - `query_id` -- echoed from the triggering `IngestionQuery` (links discovered listings back to the
    query for debugging and correlation)
  - `listing` -- a `ListingReference` with `listing_url`, `external_listing_id`, and `source` enum
  - `discovered_data` -- a `DiscoveredListing` struct with the full raw payload: title, company name,
    description, raw location string, raw skills list, optional compensation (min/max amounts,
    currency, payment frequency, source), apply URL, company URL, discovery timestamp, posted
    timestamp, and `content_hash`
  - `discovered_at` -- UTC timestamp of the discovery run

  The event is keyed as `{query_id}:{content_hash_prefix}` for Kafka partition affinity. Published
  directly, not via transactional outbox, because this service has no database.

  `job-ingest-enrichment-service` is the primary consumer of this topic.

## Key Design Patterns

### Provider Registry with Priority-Based Fallback

The service uses a pluggable provider architecture. Each `BaseProvider` implementation declares which
job boards it supports and a default priority. Two providers ship currently:

- **`JobSpyProvider`** (priority 50, default enabled): Handles Indeed, LinkedIn, and Glassdoor via
  the `python-jobspy` library. JobSpy is a synchronous scraping library. The provider wraps each
  `jobspy.scrape_jobs()` call in `asyncio.to_thread()` to avoid blocking the event loop.

- **`JSearchProvider`** (priority 100, disabled by default): Calls the JSearch REST API, which
  covers ZipRecruiter and Google Jobs. Requires a valid API key via `JOB_INGEST_DISCOVERY__JSEARCH__API_KEY`.

The `ProviderRegistry` singleton (lazy-initialized on first use) maps each `JobBoardSource` to an
ordered list of providers by priority. When the discovery service processes a multi-board query, it
fans out to each requested source concurrently using `asyncio.gather`. For each source, providers are
tried in priority order; a provider signals fallback (return `None` from `_try_provider`) when:

- It is rate-limited and the `retry_after_seconds` exceeds `fallback.rate_limit_wait_threshold_seconds`
  (default 1,800 seconds)
- It has logged `min_consecutive_errors` (default 3) failures over at least
  `error_duration_threshold_seconds` (default 300 seconds) -- tracked in Redis under
  `provider_fallback:{provider_name}:{source_name}`

Fallback state clears automatically on the next successful scrape from that provider/source pair.

### JobSpy Parameter Expansion

A single `IngestionQuery` can expand into multiple `jobspy.scrape_jobs()` calls. The mapper in
`providers/jobspy/mapper.py` builds one parameter set per keyword × per location (physical or remote).
For example, a query with 2 keywords and 3 physical locations targeting Indeed and LinkedIn produces
up to 8 call sets (2 keywords × (1 remote + 3 physical) = 8). All sets execute concurrently via
`asyncio.gather` with `asyncio.to_thread` wrapping each blocking call. Results from all DataFrames
are concatenated and deduplicated by URL within the provider before being returned to the orchestrator.

JobSpy's stdout/stderr is suppressed (redirected to a `StringIO` buffer) and captured only at
`DEBUG` log level to avoid contaminating structured log output.

### Content-Hash Deduplication via Redis

After all providers return results, the discovery service filters listings already recorded by
`DedupService`, collapses identical keys within the current host run, and publishes the remaining
events concurrently. The deduplication key is `{query_id}:{content_hash}`, where `content_hash` is
derived from title + company + description.

Redis is marked only after Kafka accepts an event. A publication failure therefore leaves no marker,
fails the discovery command transaction, and permits Kafka to redeliver the command. A crash after
publication but before the Redis mark can publish the same stable observation again; this
at-least-once behavior is intentional because job storage is idempotent. A listing whose key was
successfully marked is skipped on later runs until the configurable dedup TTL expires.

Note that the dedup key is scoped to `query_id`. The same job posting discovered by two different
queries (e.g., "Senior Python Engineer" and "Python Backend Engineer") will produce two separate
`JOB_INGEST_LISTING_DISCOVERED` events. Downstream deduplication at the storage layer
(`job-storage-service`) handles true global deduplication by URL.

## State & Persistence

### Redis

Redis serves two distinct purposes:

- **Deduplication cache** (`dedup:hash:{query_id}:{content_hash}` keys): Tracks listings successfully
  published within the rolling TTL window (default 30 days). Marking occurs after publication, so the
  cache cannot suppress an observation Kafka never accepted.

- **Provider fallback state** (`provider_fallback:{provider_name}:{source_name}` keys): Tracks
  consecutive error counts and the timestamp of the first error for each provider/source pair. Used
  by the fallback logic to decide when a degraded provider should be bypassed in favour of a
  lower-priority alternative. TTL is controlled by `caching.ttls.fallback_state` (from
  `nohiki-redis-utils` `CachingSettings`).

## External Integrations

### JobSpy (`python-jobspy`)

JobSpy is a Python scraping library (not an external HTTP service in the traditional sense: it
directly scrapes job board pages). It is invoked synchronously via `jobspy.scrape_jobs()` and returns
a pandas `DataFrame`. The service wraps each call in `asyncio.to_thread()` so scraping does not block
the Kafka consumer's event loop.

JobSpy has no authentication requirement for Indeed, LinkedIn, or Glassdoor. It can be rate-limited
or blocked by job boards; the provider fallback mechanism handles this by tracking error state in Redis
and routing to JSearch when JobSpy degrades.

### JSearch API (`api.openwebninja.com`)

An optional paid REST API for job search covering ZipRecruiter and Google Jobs. Disabled by default.
When enabled, the `JSearchProvider` enforces rate limits configured in `DiscoveryCachingSettings`:
10 requests per minute, 1,000 per hour, 5,000 per day. The JSearch client tracks limit state in Redis
via `nohiki-redis-utils` `ExternalAPIConfig`.

## Configuration

Settings inherit from `RedisMixin`, `KafkaMixin`, and `NohikiBaseSettings`. The env prefix is
`JOB_INGEST_DISCOVERY_` (note: nested settings use double-underscore separators, e.g.
`JOB_INGEST_DISCOVERY__KAFKA__BOOTSTRAP_SERVERS`).

Key settings:

| Setting | Default | Purpose |
| --------- | --------- | --------- |
| `JOB_INGEST_DISCOVERY__REDIS__CONNECTION_STRING` | -- | Redis URL (required) |
| `JOB_INGEST_DISCOVERY__KAFKA__BOOTSTRAP_SERVERS` | -- | Kafka bootstrap (required) |
| `JOB_INGEST_DISCOVERY__KAFKA__CONSUMER__MAX_CONCURRENT_HANDLERS` | `3` | Concurrent discovery runs |
| `JOB_INGEST_DISCOVERY__DISCOVERY__MAX_RESULTS_PER_SOURCE` | `3` (dev) / `25` (prod) | Results cap per keyword/source |
| `JOB_INGEST_DISCOVERY__DISCOVERY__RATE_LIMIT_DELAY_SECONDS` | `1.0` | Delay between provider calls |
| `JOB_INGEST_DISCOVERY__DISCOVERY__TIMEOUT_SECONDS` | `30` | Per-provider timeout |
| `JOB_INGEST_DISCOVERY__CACHING__DEDUP_TTL_SECONDS` | `2592000` (30 days) | Deduplication cache TTL |
| `JOB_INGEST_DISCOVERY__JSEARCH__ENABLED` | `false` | Enable JSearch provider |
| `JOB_INGEST_DISCOVERY__JSEARCH__API_KEY` | -- | JSearch API key (required if enabled) |

`max_concurrent_handlers=3` is deliberately low. Each discovery run spawns multiple concurrent
`asyncio.to_thread` scraping calls; a single `IngestionTriggered` event can already saturate network
I/O. Running more than a few in parallel risks triggering rate limiting across providers.

Provider registry configuration is a list under `JOB_INGEST_DISCOVERY__PROVIDER_REGISTRY__PROVIDERS`,
where each entry specifies `name`, `enabled`, `priority`, and optionally `sources` (to override which
boards a provider handles). If no registry config is provided, the service auto-discovers all
`BaseProvider` subclasses and uses their `default_enabled()` and `default_priority()` defaults.

## Development

### Local Setup

```bash
uv sync
```

This service requires a running Redis instance and a Kafka broker. The full local stack is started
from the monorepo root:

```bash
just infra-up
```

### Running

```bash
uv run python -m job_ingest_discovery_service.main
```

### Testing

```bash
# All tests
just test job-ingest-discovery-service

# With coverage
just test-cov job-ingest-discovery-service

# Single test file
uv run --package job-ingest-discovery-service pytest backend/services/job-ingest-discovery-service/tests/test_dedup_service.py --tb=short
```

Integration tests are marked `@pytest.mark.integration` and `@pytest.mark.requires_docker`. Run
unit tests alone with `-m unit` to skip Docker-dependent tests.

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise
uv run ty check
```

### Development Notes

- **JobSpy in dev vs prod**: `max_results_per_source` defaults to 3 in development (detected via
  `is_development()`) to avoid hammering job boards during local testing. Set
  `JOB_INGEST_DISCOVERY__DISCOVERY__MAX_RESULTS_PER_SOURCE` to override.

- **JSearch disabled by default**: The JSearch provider requires a paid API key and is off unless
  `JOB_INGEST_DISCOVERY__JSEARCH__ENABLED=true` is set explicitly. Omitting it means ZipRecruiter
  and Google Jobs are not scraped.

- **Provider auto-discovery**: `providers/discovery.py` uses `__subclasses__()` to find all
  `BaseProvider` implementations. Adding a new provider requires only creating a subclass in the
  `providers/` package. No registration call is needed.

- **JobSpy stdout suppression**: JobSpy prints scraping progress to stdout. The provider redirects
  both stdout and stderr to a `StringIO` buffer and logs the output at `DEBUG` level only. Do not
  remove this suppression; it prevents JobSpy's print statements from contaminating structured JSON
  log output in production.
