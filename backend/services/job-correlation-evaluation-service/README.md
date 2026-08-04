# Job Correlation Evaluation Service

Evaluates job-user fit by running a deterministic scoring pipeline against every job-profile
pair in the system. The pipeline combines MUVERA ANN retrieval, ColBERT MaxSim
late-interaction reranking, optional LLM reranking, and evidence-backed human fit factors to
produce a 0-100 fit ranking index. Kafka-only, stateful with PostgreSQL, Qdrant, and Redis.

## Role in the System

This service sits at the centre of the job recommendation pipeline. Every time a new job listing
appears (via `job-listing.cdc.listing-created.v1`) or a user updates their preferences (via
`user-pref.cdc.pref-created.v1` or `user-pref.cdc.pref-updated.v1`), this service scores the
new entity against every counterpart it holds in its local projection ledger and writes one
`correlations` row per pair. The resulting `job-correlation.cdc.correlation-evaluated.v1` events
drive the notification pipeline (`notification-service`) and the document generation pipeline
(`doc-content-service`).

No other service performs this cross-domain matching. `job-storage-service` owns the canonical
job data; `user-pref-service` owns user preferences. This service consumes CDC snapshots from
both and maintains its own local copy of each, so it can evaluate any new listing against all
known profiles and any new profile against all recent listings without cross-service queries.

The correlation scores stored here are the primary read path for the BFF's job listings
endpoint (`/api/v1/correlations`), which presents ranked matches to the user.

## Event-Driven Integration

### Events Consumed

- **`job-listing.cdc.listing-created.v1`** (`ListingCreated`): The primary trigger for
  real-time scoring. When `job-storage-service` publishes a new listing, this service extracts
  the `ListingSnapshot` (which carries inline ColBERT multi-vector embeddings) and scores it
  against every profile in its `profile_projections` ledger. Scoring uses inline embeddings from
  the snapshot for the MaxSim step, so no Qdrant lookup is needed for real-time job events.
  Results are batch-inserted and published via outbox in a single atomic transaction.
  Consumer group: `job-correlation-eval-primary`. Idempotent via `ON CONFLICT (pref_id,
  listing_id) DO NOTHING` -- if the correlation already exists, the event is skipped.

- **`job-listing.cdc.listing-deleted.v1`** (`ListingDeleted`): Soft-deletes all correlations
  for the removed listing by setting `correlation_status = 'dismissed'`. This is the
  event-driven substitute for a cross-schema `ON DELETE CASCADE` -- Nohiki enforces
  referential integrity via events, not database constraints. Consumer group:
  `job-correlation-eval-primary`.

- **`user-pref.cdc.pref-created.v1`** (`PrefCreated`): Stores the full `SearchPrefSnapshot`
  in the `profile_projections` ledger, then publishes a `job-listing.cmd.backfill-requested.v1`
  command to `job-storage-service` requesting the most recent listings (up to `max_listings`,
  within `since_days`). The backfill response arrives via the callback pattern documented below.
  Consumer group: `job-correlation-eval-projection`.

- **`user-pref.cdc.pref-updated.v1`** (`PrefUpdated`): Updates the local profile projection
  with the new snapshot, then triggers the same backfill flow as `pref-created` to re-score
  all recent listings against the updated preferences. Consumer group:
  `job-correlation-eval-projection`.

- **`user-pref.cdc.pref-deleted.v1`** (`PrefDeleted`): Removes the profile from the local
  ledger. Existing correlations for that profile remain in the database as historical records
  (they are no longer actionable since `is_actionable` is a generated column dependent on
  status, not profile existence). Consumer group: `job-correlation-eval-projection`.

- **`job-correlation.sys.backfill-listings.v1`** (`BackfillCallback`): The callback from
  `job-storage-service` in response to a `backfill-requested` command. The response carries a
  batch of `ListingSnapshot` objects. This service scores each listing against the profile that
  triggered the backfill. For backfill scoring, Qdrant is queried for real MUVERA/MaxSim scores
  (unlike real-time scoring, which uses inline embeddings from the event). Batches arrive
  sequentially until `is_final_batch = true`. Consumer group:
  `job-correlation-eval-backfill-callback`.

- **`job-correlation.cmd.feedback-recorded.v1`** (`FeedbackRecorded`): Records viewed,
  saved, applied, dismissed, liked, and disliked interactions on a correlation. Interaction
  actions update their corresponding flags; saved and liked persist `positive` while disliked
  persists `negative` in `user_feedback`. Consumer group: `job-correlation-eval-feedback`.

- **`job-correlation.cmd.training-export-requested.v1`** (`TrainingExportRequested`): Exports
  all correlations with feedback signals as `TrainingSample` protobuf objects and publishes
  them to the caller's `callback_topic`. Used by the `train_l2r_model.py` operational script
  to collect training data for the next model iteration. Consumer group:
  `job-correlation-eval-export`.

- **`feedback.cmd.score-feedback-requested.v1`** (`ScoreFeedbackRequested`): Records asymmetric
  score quality feedback (GOOD / TOO_HIGH / TOO_LOW) in the `feedback.asymmetric_feedback`
  table. Provides more granular signal than binary thumbs feedback, enabling calibration
  improvement. Consumer group: `job-correlation-eval-score-feedback`.

- **`feedback.cmd.score-adjustment-requested.v1`** (`ScoreAdjustmentRequested`): Records a
  user-provided manual score override with free-text reasoning in
  `feedback.manual_adjustments`. The original score is fetched from the `correlations` row.
  Consumer group: `job-correlation-eval-score-feedback`.

### Events Published

- **`job-correlation.cdc.correlation-evaluated.v1`** (`CorrelationEvaluated`): Published for
  every successfully scored job-profile pair. Carries the `correlation_id`, `fit_score` (0-100
  integer), `correlation_status` (`EVALUATED`), a `correlation_metadata` map containing the
  score breakdown, a minimal `ListingNotificationSnapshot` for downstream rendering, the full
  `SearchPrefSnapshot`, and the user's upload references. Emitted as a transactional PostgreSQL
  logical message in the same database transaction as the `correlations` row, so the row and
  event commit atomically. Consumed by `notification-service` and `doc-content-service`, and
  projected into the BFF's correlation table.

- **`job-listing.cmd.backfill-requested.v1`** (`BackfillRequested`): Published when a new or
  updated profile is received, requesting `job-storage-service` to send its most recent
  listings (configurable `max_listings` and `since_days`). The `callback_topic` is set to
  `job-correlation.sys.backfill-listings.v1` so responses route back to this service. Published
  directly (not via outbox) since it is a command, not a CDC event.

### Notable Patterns

#### Backfill Request/Callback

When a new profile arrives, this service cannot immediately score all existing listings because
they are not in memory. Instead it publishes `job-listing.cmd.backfill-requested.v1` to
`job-storage-service` (a Kafka command), which responds with paginated
`BackfillCallback` messages on `job-correlation.sys.backfill-listings.v1`. Each callback batch
is processed independently, with Qdrant queried for real embedding similarity scores. The
is_final_batch` flag marks the last batch; there is no saga coordinator: each batch is fully
self-contained.

#### Transactional WAL Publication

Every `CorrelationEvaluated` event is emitted with transactional
`pg_logical_emit_message` in the same `AsyncSession` transaction as the `correlations` insert.
The dedicated Debezium connector and `NohikiWalRouterSmt` publish the raw protobuf payload to
Kafka only after PostgreSQL commits, guaranteeing the database row and event are never observed
independently.

See `infra/k8s/kafka-connect/connectors/wal-connector-template.json` for the connector configuration.

## State & Persistence

### Database

Schema `job_correlation_schema` stores the primary domain data: one `correlations` row per
job-profile pair with the integer match score, 32-dimensional feature vector (stored as
`FLOAT[]`), interaction flags, and a state machine for the correlation lifecycle
(pending → evaluated → viewed → saved/applied/dismissed/expired). The `profile_projections`
table holds ECST snapshots of all active user preferences, serialized as JSONB. A separate
`feedback` schema holds `asymmetric_feedback` and `manual_adjustments` tables for granular
score quality signals.

See [DATABASE.md](./DATABASE.md) for complete schema documentation.

### Object Storage

The `scripts/` directory contains offline tooling that reads raw text and ColBERT token artifacts
from S3 for future real-label model evaluation and training data export. These tools and their
artifacts are not loaded by the production service.

### Vector Store

This service reads from a Qdrant collection containing job listing embeddings. The collection
name is resolved at startup from the `SemanticRepresentationManifest` via the `nohiki-ml-manifest`
library using `manifest.get_collection_name(EntityType.JOB)`. The collection holds three
vector types per listing:

- **MUVERA FDE** (dense): Used for Stage 1 ANN retrieval: fast approximate nearest-neighbour
  search over all listings
- **ColBERT multi-vector**: Used for Stage 2 MaxSim reranking: late-interaction similarity
  computed natively by Qdrant's SIMD-optimized multi-vector support
- **Sparse**: Used for hybrid lexical boosting in the Stage 1+2 combined query

For backfill scoring, this service queries Qdrant by entity ID to retrieve real embedding
similarity scores for specific listings. For real-time scoring of new listings, the inline
ColBERT multi-vector embedded in the `ListingCreated` event is used instead, avoiding a
Qdrant round-trip.

### Redis

Redis serves two purposes in this service:

- **Profile cache**: Active `SearchPrefSnapshot` objects deserialized from
  `profile_projections.snapshot_data` are cached for 5 minutes (`active_profiles_ttl: 300s`)
  to reduce database load during high-throughput job bursts.
- **Skill relationship cache**: Skill graph relationships fetched from `skill-graph-service`
  (via its published events, not direct calls) are cached for 1 hour
  (`skill_relationships_ttl: 3600s`) and shared across pods for the skill feature group.
- **Circuit breaker state**: The LLM reranker (Stage 3) uses a circuit breaker whose open/closed
  state is stored in Redis, with a 30-second recovery window
  (`PIPELINE_CIRCUIT_RECOVERY_SECONDS`). This prevents cascading failures if the reranker is
  unavailable; Stage 3 is bypassed and Stage 4 runs with `rerank_score = 0.0`.

## Key Design Patterns

### 4-Stage Scoring Pipeline

The core of this service is a four-stage pipeline executed for every job-profile pair:

#### Stage 1+2: Native MUVERA + ColBERT MaxSim via Qdrant

The first two stages are merged into a single Qdrant multi-stage query. Qdrant first performs
an ANN search using the profile's MUVERA FDE vector (prefetching up to 200 candidates), then
re-ranks those candidates using its native multi-vector MaxSim implementation over the ColBERT
tokens. This produces approximately 150 candidates with real late-interaction similarity scores.
A sparse vector is included in the hybrid query for lexical signal. The MaxSim score is then
normalised using per-token mean/std parameters from the `SemanticRepresentationManifest` to
produce a score comparable across queries of different lengths.

For real-time scoring of new listings (where the listing's ColBERT tokens come from the event
payload rather than Qdrant), the MaxSim is computed locally using the same normalisation
parameters.

#### Stage 3: LLM Reranker (optional)

An optional LLM reranker endpoint (`PIPELINE_RERANKER_ENDPOINT_URL`) re-scores the top 50
candidates from Stage 2 using text-based relevance. Disabled by default
(`PIPELINE_STAGE3_ENABLED=false`). When the circuit breaker is open (5 consecutive failures),
Stage 3 is bypassed entirely and `rerank_score = 0.0` is passed to Stage 4.

#### Stage 4: Deterministic Fit Ranking

Stage 4 combines normalized semantic relevance with available evidence-backed fit factors.
Missing factors are omitted rather than guessed. The resulting integer `correlation_score` is a
0-100 fit ranking index, not a probability.

### ECST Snapshot Ledger

This service never queries `user-pref-service` or `job-storage-service` at runtime. Instead,
it maintains a local `profile_projections` table populated by consuming CDC events from
`user-pref-service`. When a `ListingCreated` event arrives, the service loads all active
profiles from `profile_projections` (Redis-cached), extracts the `QueryEncoding` from the
profile's `query_retrieval_embeddings` field (which `user-pref-service` embeds in the
snapshot), and scores the listing against every profile entirely within this service.

This is Event-Carried State Transfer: every `PrefCreated` / `PrefUpdated` event carries the
full `SearchPrefSnapshot`, including the profile's pre-computed MUVERA, ColBERT, and sparse
query encodings. There is no lookup step.

### Disqualification Before Scoring

Before running the 4-stage pipeline, `MLScoringService._check_disqualification()` scans the
job's text (title + description + company name + skills) for any keywords in the profile's
`disallowed_keywords` list. A single compiled regex pattern (cached by `@lru_cache`) performs
the scan in O(n) rather than O(k×n) per-keyword loops. Disqualified listings receive score 0
and are not inserted into the database.

### Fit Explanation

Each result carries a typed, human-readable breakdown anchored by role relevance and the
available fit factors. It reports compatibility, resolved user importance, and signed
contribution points without exposing technical feature keys or probability claims.

## ML Operational Scripts

Four scripts in `scripts/` are manual operational tools for the model training lifecycle. They
are run by operators and are not invoked by the service at runtime.

- **`generate_training_data.py`**: Generates synthetic labelled training samples for
  bootstrapping before real feedback is available.
- **`train_l2r_model.py`**: Trains a new LightGBM LambdaMART model from exported feedback
  data. Pipeline: export → prepare → train (with early stopping) → calibrate → evaluate
  (NDCG@10) → save versioned files.
- **`evaluate_model.py`**: Evaluates a candidate model version against held-out validation
  data and prints NDCG metrics and per-feature importance tables.
- **`deploy_model.py`**: Manages model version metadata (`model_metadata.json`), copies model
  files to the deployment location, and supports rollback to the previous version.

## Configuration

Settings are loaded via `pydantic-settings` with the `JOB_CORRELATION_EVAL_` prefix. The
service composes the following mixins:

| Mixin | Purpose |
| ------- | --------- |
| `DatabaseMixin` | PostgreSQL async engine + Alembic migrations |
| `KafkaMixin` | Kafka consumer/producer with `max_concurrent_handlers=5` |
| `RedisMixin` | Cache + circuit breaker state |
| `S3Mixin` | RustFS (S3-compatible) for ML artifact access |
| `QdrantMixin` | Qdrant async client for embedding similarity |
| `LLMMixin` | LLM client for optional Stage 3 reranking |
| `ManifestMixin` | `SemanticRepresentationManifest` for collection/normalization params |

Key service-specific settings:

- **`JOB_CORRELATION_EVAL_BACKFILL__ENABLED`**: Toggle backfill on new/updated profiles
  (default: `true`).
- **`JOB_CORRELATION_EVAL_BACKFILL__MAX_LISTINGS`**: Maximum listings to request per backfill
  (default: `500`, max: `1000`).
- **`JOB_CORRELATION_EVAL_BACKFILL__SINCE_DAYS`**: How many days back to backfill
  (default: `30`).
- **`PIPELINE_STAGE3_ENABLED`**: Enable LLM reranking (default: `false`).
- **`PIPELINE_STAGE2_CANDIDATE_LIMIT`**: MaxSim output limit (default: `150`).
- **`PIPELINE_STAGE1_CANDIDATE_LIMIT`**: MUVERA ANN retrieval limit (default: `1000`).

## Development

### Local Setup

```bash
uv sync
alembic upgrade head
```

The service requires PostgreSQL with `uuidv7()` extension, Qdrant (with a populated job
collection), and Kafka. Run `just infra-up` to start PostgreSQL, Redis, Kafka, and
Schema Registry. Qdrant must be running on `localhost:6333`. The Qdrant collection name and
normalization parameters are loaded from the manifest file: ensure
`JOB_CORRELATION_EVAL_MANIFEST_PATH` points to a valid `manifest.json`.

The L2R model files must exist at the configured paths before starting the service. Use
`scripts/generate_training_data.py` and `scripts/train_l2r_model.py` to create an initial
model for development.

### Testing

```bash
# Run unit tests only (integration tests are excluded by default)
just test job-correlation-evaluation-service

# Run with coverage
just test-cov job-correlation-evaluation-service

# Run a single test file
uv run --package job-correlation-evaluation-service pytest backend/services/job-correlation-evaluation-service/tests/test_feature_composer.py -v --tb=short

# Run integration tests (requires Docker + testcontainers)
uv run --package job-correlation-evaluation-service pytest backend/services/job-correlation-evaluation-service/tests/ -m integration
```

### Linting and Type Checking

```bash
just lint-service job-correlation-evaluation-service
just typecheck job-correlation-evaluation-service
```
