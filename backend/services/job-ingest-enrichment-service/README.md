# Job Ingest Enrichment Service

Transforms raw job listings produced by the discovery service and accepted by the storage service into fully
structured, enriched records ready for matching. For each listing it runs a single LLM call to extract structured
data (cleaned title, company, seniority, work arrangement, compensation, experience requirements, and all skills),
requests skill normalization from `skill-graph-service` and two embedding computations from `ml-gateway-service`
in parallel, then waits for all three callbacks to converge before publishing the enriched listing. This
multi-callback convergence is implemented using the saga pattern from `nohiki-db-utils` -- the only service in the
monorepo that does so. Kafka-only, stateful with PostgreSQL, Redis, and Qdrant.

## Role in the System

This service sits between the job ingestion pipeline and downstream consumers. The ingest pipeline has two
stages before this service: `job-ingest-discovery-service` scrapes raw listings, and `job-storage-service`
deduplicates and accepts them by publishing `JOB_LISTING_ACCEPTED`. This service consumes that event as the
trigger for all enrichment work.

The enrichment it produces is a `JOB_INGEST_ENRICHMENT_COMPLETED` event carrying a fully populated `StoredListing`.
`job-storage-service` consumes this event to create the `JOB_LISTING_CREATED` CDC event that propagates throughout
the platform. Every downstream service (`job-correlation-evaluation-service`, `bff-service` projections,
`notification-service`) ultimately depends on data that originates from this service's enrichment output.
Nothing about a listing beyond its URL and source is considered reliable until this service has processed it.

The service uniquely solves the convergence problem: producing a complete `StoredListing` requires simultaneously
normalized skills (from `skill-graph-service`), dense retrieval embeddings (MUVERA + ColBERT + Sparse from
`ml-gateway-service`), and a title embedding (Dense from `ml-gateway-service`). These three results arrive
asynchronously via separate Kafka callback topics. The saga pattern ensures the enrichment event is only published
once all three have arrived and only in a single atomic transaction with the saga state update.

## Event-Driven Integration

### Events Consumed

- **`JOB_LISTING_ACCEPTED`** (`ListingAccepted`, topic `job-listing.fct.accepted.v1`): The primary trigger.
  `job-storage-service` publishes this after accepting a deduplicated listing. This service extracts the
  `DiscoveredListing` payload, runs the LLM extraction agent, geocodes the location, then publishes a skill
  normalization request. Consumer group: `{service_name}` (from `settings.kafka.consumer_group`). The handler
  applies up to 30 retries with 60-second backoff, allowing up to 10 minutes per poll interval to accommodate
  LLM latency. Rate limiting (configurable via `RATE_LIMIT_*` settings) prevents runaway LLM spend during
  backfill or burst ingestion.

- **`JOB_INGEST_SKILL_CALLBACK`** (`SkillNormalizationCallback`, topic `job-ingest.sys.skill-callback.v1`):
  Callback from `skill-graph-service` carrying normalized `JobSkillRequirement` objects (with canonical skill
  IDs from the skill graph) and an optional skills embedding vector. When the callback arrives, this service
  checks whether any skills require LLM-based clarification (ambiguous candidates). If they do, it runs a
  second LLM call (`skill_clarification` chain) to decide between MATCH, EXPAND, or NEW_SKILL for each
  ambiguous skill, publishes `SKILL_ALIAS_LEARNED` or `SKILL_PROPOSED` events accordingly, then proceeds.
  After clarification (or immediately if no clarification is needed), it creates the embedding saga and
  fires both embedding requests concurrently. Consumer group: `{service_name}-skill-callback`.

- **`JOB_INGEST_ENRICHMENT_EMBEDDING_CALLBACK`** (`EmbeddingCallback`, topic
  `job-ingest-enrichment.sys.embedding-callback.v1`): Callback from `ml-gateway-service` carrying a computed
  embedding vector. Each embedding request tags its callback with an `embedding_type` attribute (`"retrieval"`
  or `"title"`). When a callback arrives, this service loads the saga with a `SELECT FOR UPDATE` lock, stores
  the base64-encoded embedding bytes in the appropriate saga column, increments `received_callbacks`, and
  checks whether all expected callbacks have now arrived. When the last callback arrives and `received_callbacks
  >= expected_callbacks`, the service builds the complete`StoredListing`, transitions the saga to COMPLETED,
  and writes the enrichment event to the outbox in a single transaction. Consumer group:
  `{service_name}-embedding-callback`.

### Events Published

- **`JOB_INGEST_ENRICHMENT_COMPLETED`** (`EnrichmentCompleted`, topic `job-ingest.fct.enrichment-completed.v1`):
  Published via the transactional outbox in the same transaction as the saga COMPLETED state transition. Carries
  a fully populated `StoredListing` (normalized title, company, description, location, seniority, work
  arrangement, employment type, experience requirements, compensation with source attribution, normalized skill
  requirements with proficiency levels, retrieval embeddings, and title embedding) plus geocoded coordinates
  and the LLM model ID used for extraction. `job-storage-service` consumes this to create the final
  `JOB_LISTING_CREATED` CDC event.

- **`SKILL_NORMALIZATION_REQUESTED`** (`SkillNormalizationRequested`, topic
  `skill.cmd.normalization-requested.v1`): Published directly (not via outbox) at the end of LLM extraction,
  before any saga exists. Carries the raw skill names extracted from the posting and the serialized
  `EnrichmentContext` in the `caller_context` field, containing the full LLM extraction result encoded as JSON bytes.
  `skill-graph-service` processes this and replies to `JOB_INGEST_SKILL_CALLBACK`.

- **`ML_EMBEDDING_REQUESTED`** (`EmbeddingRequested`, topic `ml.cmd.embedding-requested.v1`): Published twice
  concurrently (via `asyncio.TaskGroup`) when the embedding saga is created: once for the retrieval embedding
  (MUVERA + ColBERT + Sparse, full listing text) and once for the title embedding (Dense, title text only).
  Each request carries the saga ID in `caller_context` and an `embedding_type` attribute so the callback
  handler can route the result to the correct saga column. `ml-gateway-service` routes these to compute workers
  and publishes results to `JOB_INGEST_ENRICHMENT_EMBEDDING_CALLBACK`.

- **`SKILL_ALIAS_LEARNED`** (`AliasLearned`, topic `skill.fct.alias-learned.v1`): Published during skill
  clarification when the LLM resolves an ambiguous skill to a known canonical skill (MATCH) or to the primary
  skill of an expansion group (EXPAND). `skill-graph-service` uses this to grow its alias index.

- **`SKILL_PROPOSED`** (`SkillProposed`, topic `skill.cmd.skill-proposed.v1`): Published during skill
  clarification when the LLM determines a raw skill has no equivalent in the canonical graph (NEW_SKILL).
  Carries a proposed canonical name, display name, and suggested aliases. `skill-graph-service` evaluates the
  proposal and may add the skill to the graph.

### Notable Patterns

#### Multi-Callback Saga

The defining pattern of this service. Enriching a job listing requires three independent async operations
that produce results over different time horizons and via different Kafka topics. The saga pattern ensures
the enrichment event is only published when all results are available and that publication is atomic with the
saga state update.

The full flow, step by step:

1. `JOB_LISTING_ACCEPTED` arrives. The LLM extraction agent runs (`extraction` chain, `JobExtractionSchema`),
   producing cleaned text fields, seniority, work arrangement, employment term, experience bounds with source
   attribution, compensation bounds with source attribution, and a flat list of raw skill names.

2. Location geocoding runs against the extracted city/state/country (Redis-cached via `nohiki-geo-utils`).

3. The LLM result and geocoded coordinates are packed into an `EnrichmentContext` dataclass, serialized to
   JSON bytes, and carried in the `caller_context` field of `SKILL_NORMALIZATION_REQUESTED`. No database write
  occurs at this point. All intermediate state travels inside the Kafka event.

4. `skill-graph-service` normalizes the raw skills against its canonical graph. If all skills match
   unambiguously, it returns `JobSkillRequirement` objects with canonical IDs and an optional skills embedding
   vector. If some skills are ambiguous (multiple close candidates), it returns clarification requests.

5. `JOB_INGEST_SKILL_CALLBACK` arrives. The `EnrichmentContext` is recovered from `caller_context`. If
   clarification is needed, the `skill_clarification` LLM chain runs to resolve each ambiguous skill via
   MATCH, EXPAND, or NEW_SKILL decisions. Alias and proposal events are published.

6. The embedding saga row is created in PostgreSQL with `expected_callbacks` set to the number of embedding
   requests actually sent (1 or 2 depending on whether retrieval text and title text are both non-empty). Both
   embedding requests are published concurrently. The saga ID is embedded in each request's `caller_context`.

7. Two `JOB_INGEST_ENRICHMENT_EMBEDDING_CALLBACK` messages arrive (order undefined, possibly from different
   consumer threads or pod replicas). Each one loads the saga row with `SELECT FOR UPDATE`, stores its
   embedding bytes in `retrieval_embedding_b64` or `title_embedding_b64`, increments `received_callbacks`,
   and releases the lock. The `version` column increments on each callback, providing optimistic locking.

8. The handler that increments `received_callbacks` to `expected_callbacks` detects saga completion. It builds
   the `StoredListing` proto from the serialized `EnrichmentContext` and both embedding columns, transitions
  the saga to COMPLETED, and writes `JOB_INGEST_ENRICHMENT_COMPLETED` to the outbox in the same
   transaction. Debezium captures the outbox row and publishes to Kafka.

**Saga TTL**: 30 minutes (`_SAGA_TTL`). A `StaleSagaDetector` (from `nohiki-db-utils`) is intended to run
periodically to transition sagas past their `expires_at` to EXPIRED, preventing the table from accumulating
stuck rows if an embedding callback is never delivered.

**Failure handling**: If an embedding callback arrives with an error, `SagaRepository.fail()` transitions the
saga to FAILED and commits. The listing is not enriched; the enrichment event is never published. The original
`JOB_LISTING_ACCEPTED` message is not retried (it has already been processed up to that point), so the
listing remains in `job-storage-service` in its raw accepted state without enrichment.

#### Context-Carried State (No Intermediate Database Row)

Between the LLM extraction step and the skill normalization callback, all state travels inside the Kafka event
in the `caller_context` field, which contains the full `EnrichmentContext` JSON (title, company, description, seniority,
work arrangement, employment term, experience bounds, compensation bounds, location, geocoded coordinates). No
database write happens until the saga is created after the skill normalization callback arrives. This keeps the
stateless window before the saga as cheap as possible.

#### LLM Rate Limiting

A Redis-backed sliding window rate limiter (`nohiki-kafka-client` `RateLimitConfig`) wraps the
`JOB_LISTING_ACCEPTED` handler. Key: `llm:enrichment`. Default: 10 requests per 60-second window. The Kafka
consumer suspends partition consumption while the rate limit is active, resuming automatically when the window
clears. This prevents LLM cost explosions during bulk ingestion or backfill runs.

#### Skill Clarification as LLM Chain

When `skill-graph-service` cannot unambiguously match a skill, it returns `SkillClarificationNeeded` objects
each carrying a list of near-match candidates from the canonical graph. The service runs these through a second
LLM call (`skill_clarification` chain, `SkillClarificationResponse` schema) with the job title and confirmed
skills as context. The LLM decides MATCH (select the correct candidate), EXPAND (the raw skill implies multiple
canonical skills), or NEW_SKILL (no existing candidate fits). LLM decisions are validated against the actual
candidate IDs to detect hallucinations before being applied.

## State & Persistence

### Database

Schema `job_ingest_enrichment_schema` stores the embedding saga rows that track convergence of parallel
embedding callbacks during enrichment. The schema also contains the standard outbox and processed-events
tables used by all stateful services. See [DATABASE.md](./DATABASE.md) for complete schema documentation.

### Vector Store

Retrieval embeddings include MUVERA (multi-vector dense), ColBERT (late-interaction
token-level), and Sparse (keyword-weighted) vectors, supporting the hybrid search used by
`job-correlation-evaluation-service`. The target lifecycle-owner boundary is that this service
publishes vectors in the enrichment result, then `job-storage-service` persists canonical listing
state and writes the jobs Qdrant point. The current tree still contains legacy Kafka-sink indexing
artifacts; do not add new sink usage while that cleanup remains pending. Title embeddings remain
enrichment artifacts for downstream use; they are not written to Qdrant by this service.

### Redis

Redis backs two distinct uses:

- **Location geocoding cache** (`nohiki-geo-utils`): Caches resolved city/state/country → coordinates
  lookups from the Nominatim geocoder. This prevents duplicate external geocoding calls for listings from
  the same city.

- **LLM rate limiting** (`nohiki-kafka-client`): Sliding window counter keyed by `llm:enrichment`. One
  counter tracks both the extraction chain and (when triggered) the skill clarification chain, since both
  ultimately gate on the same per-listing enrichment trigger.

## External Integrations

### OpenRouter (via `nohiki-llm-client`)

Two LLM chains:

- **`extraction`**: The main extraction chain. Runs `JobExtractionSchema` via PydanticAI. Configured in
  `settings.llm.chains["extraction"]`. PydanticAI retries automatically on schema validation failures.
  The agent is cached as a module-level singleton to avoid repeated initialization overhead.

- **`skill_clarification`**: Runs `SkillClarificationResponse` via PydanticAI only when `skill-graph-service`
  returns ambiguous matches. Configured in `settings.llm.chains["skill_clarification"]`. Uses the same
  `LLMClient` infrastructure with retry and cost tracking.

`nohiki-llm-client` provides token usage logging, cost tracking, and circuit breaking on persistent LLM
failures. The `LLMHealthProbe` in `main.py` validates LLM connectivity on startup.

### Nominatim / GeoPy (via `nohiki-geo-utils`)

Geocodes the city/state/country extracted by the LLM into lat/lon coordinates included in the enrichment
event. Results are cached in Redis to avoid repeated lookups for common locations. This is a best-effort
operation. Geocoding failure does not fail enrichment; the enrichment event is published with
`geocoded_coordinates` omitted.

## Key Design Patterns

### Transactional Outbox

`JOB_INGEST_ENRICHMENT_COMPLETED` is written to the `outbox` table in the same transaction as the saga
COMPLETED state transition. This means the event is published if and only if the saga reaches COMPLETED.
If the process crashes between the saga update and the Kafka publish, Debezium will capture the outbox row
on the next WAL read and publish the event. There is no window where the saga is COMPLETED but the event
is lost.

When a listing has no retrieval text and no title (degenerate case), the service bypasses the saga entirely
and publishes `JOB_INGEST_ENRICHMENT_COMPLETED` via a direct Kafka publish (no outbox, no saga row). This
path exists to handle pathologically empty listings without creating unreachable saga rows.

### Kafka Consumer Tuning

The service overrides the default Kafka consumer settings specifically for LLM workloads:

- `max_poll_records=1`: Processes one message at a time. LLM calls can take 5-30 seconds; batching would
  cause consumer lag spikes and potential rebalances.
- `max_poll_interval_ms=600000` (10 minutes): Prevents the broker from considering the consumer dead during
  long LLM calls.
- `max_concurrent_handlers=5`: LLM calls are I/O-bound but slow; 5 concurrent handlers balances throughput
  against LLM API concurrency limits.

## Configuration

Settings inherit from `DatabaseMixin`, `RedisMixin`, `KafkaMixin`, `LLMMixin`, `ManifestMixin`, and
`NohikiBaseSettings`. All environment variables use the `JOB_INGEST_ENRICHMENT_` prefix.

Key non-obvious settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `JOB_INGEST_ENRICHMENT_RATE_LIMIT__ENABLED` | `true` | Enable Redis-backed LLM rate limiting |
| `JOB_INGEST_ENRICHMENT_RATE_LIMIT__REQUESTS_PER_WINDOW` | `10` | Max LLM extractions per window |
| `JOB_INGEST_ENRICHMENT_RATE_LIMIT__WINDOW_SECONDS` | `60` | Rate limit window duration |
| `JOB_INGEST_ENRICHMENT_PROCESSING__MAX_RETRIES` | `3` | Max processing retries |
| `JOB_INGEST_ENRICHMENT_PROCESSING__TIMEOUT_SECONDS` | `120` | Processing timeout |
| `JOB_INGEST_ENRICHMENT_KAFKA__CONSUMER__MAX_POLL_INTERVAL_MS` | `600000` | 10 min poll interval for LLM |
| `JOB_INGEST_ENRICHMENT_MANIFEST_PATH` | -- | Path to `SemanticRepresentationManifest` JSON |

LLM provider and model selection are configured via the `LLMMixin` variables
(`JOB_INGEST_ENRICHMENT_LLM__*`). The `extraction` and `skill_clarification` chains must both be configured;
see `nohiki-llm-client` for the chain configuration schema.

## Development

### Local Setup

```bash
uv sync
cd backend/services/job-ingest-enrichment-service
alembic upgrade head
```

Requires PostgreSQL (schema `job_ingest_enrichment_schema`), Redis, and Kafka with the schema registry
running. Use `just infra-up` from the monorepo root to start all infrastructure.

The LLM chains require `JOB_INGEST_ENRICHMENT_LLM__*` settings pointing to a valid OpenRouter API key.
`skill-graph-service` and `ml-gateway-service` must be reachable on Kafka for the saga path to complete
end-to-end.

### Testing

```bash
# From monorepo root (recommended -- prevents import collisions)
just test job-ingest-enrichment-service


# With coverage
just test-cov job-ingest-enrichment-service
```

### Linting & Type Checking

```bash
just lint-service job-ingest-enrichment-service
just typecheck job-ingest-enrichment-service
```

Or from the service directory:

```bash
uv run ruff check --fix --output-format=concise
uv run ty check
```
