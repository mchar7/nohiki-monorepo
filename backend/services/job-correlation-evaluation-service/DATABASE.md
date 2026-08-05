# Job Correlation Evaluation Service Database Schema

Schema `job_correlation_schema` stores one correlation record per job-profile pair, including
the integer match score, the raw 32-dimensional L2R feature vector, interaction lifecycle
flags, and user feedback signals used to train future model iterations. A second schema,
`feedback`, holds granular score quality signals in two separate tables. Uses clean-cut
deployment: the single `001_` migration is edited in place and the schemas are dropped and
recreated on each deployment.

## Entity Overview

| Table | Schema | Purpose |
| ------- | -------- | --------- |
| `correlations` | `job_correlation_schema` | One row per job-listing × user-preference pair with match score, feature vector, and interaction lifecycle state |
| `profile_projections` | `job_correlation_schema` | ECST projection of user search preferences received from `user-pref-service` CDC events |
| `processed_events` | `job_correlation_schema` | Idempotency log for Kafka event deduplication |
| `asymmetric_feedback` | `feedback` | Score quality signals (GOOD / TOO_HIGH / TOO_LOW) from users |
| `manual_adjustments` | `feedback` | User-provided score overrides with free-text reasoning |

The `correlations` table is the central domain entity. Each row links a `listing_id` (owned by
`job-storage-service`) to a `pref_id` (owned by `user-pref-service`) via a UNIQUE constraint
that enforces one score per pair and serves as the idempotency key for event handlers.
`profile_projections` provides the local replica of all active preferences that the scoring
pipeline reads at runtime without querying `user-pref-service`. Transactional logical messages
ensure `CorrelationEvaluated` events commit atomically with correlation writes;
`asymmetric_feedback` and `manual_adjustments` capture user signals that flow back into the L2R
training pipeline.

## Table Details

### `correlations`

**Purpose:**

Stores the result of evaluating a single job listing against a single user search preference.
A row exists for every pair the service has scored, regardless of the resulting score value --
a 0% correlation is still a correlation. The table drives the BFF's job match display, the
notification pipeline, and the L2R training data export.

**Key columns:**

- **`id`** (`UUID`): UUIDv7 primary key, generated server-side via `uuidv7()`. The time-ordered
  nature means rows inserted in burst (e.g., a new job scored against 50 profiles) are
  physically adjacent on disk.
- **`pref_id`** (`UUID`): References `user-pref-service`'s preference record by UUID. No
  foreign key constraint: cross-schema references are resolved via events per EDA principles.
- **`listing_id`** (`UUID`): References `job-storage-service`'s listing record by UUID. No
  foreign key constraint. Listing deletions are handled by consuming
  `job-listing.cdc.listing-deleted.v1` events.
- **`user_id`** (`UUID`): Denormalized from the profile snapshot at scoring time. Enables
  user-scoped queries without joining to `profile_projections`.
- **`listing_url`** (`TEXT`): Denormalized listing URL, stored so downstream consumers of
  `CorrelationEvaluated` events can render links without querying `job-storage-service`.
- **`correlation_score`** (`INTEGER`): The final calibrated match score as an integer in
  `[0, 100]`. Derived from the LightGBM raw score → isotonic calibration → multiply by 100 →
  round. `NULL` on rows that are `PENDING` (created but not yet scored).
- **`correlation_reasoning`** (`JSONB`): Score breakdown map. Contains `ml_score`,
  `ml_confidence`, `ml_explanation` (SHAP-derived human-readable string), `scoring_method`,
  and a nested `feature_importances` map of the 32 raw feature values keyed by feature name.
- **`correlation_status`** (`correlation_status_enum`): State machine field. Valid values and
  transitions are defined below. Default: `pending`.
- **`user_feedback`** (`user_feedback_enum`): Optional explicit feedback from the user.
  Values: `liked`, `disliked`, `saved`, `interested`. Used as a training signal for the L2R
  model.
- **`is_viewed`**, **`is_applied`**, **`is_dismissed`** (`BOOLEAN`): Interaction flags set by
  the BFF when the user takes action. Used by downstream services and the BFF query to filter
  the job list.
- **`is_actionable`** (`BOOLEAN GENERATED ALWAYS AS ... STORED`): Computed column:
  `correlation_status IN ('evaluated', 'pending') AND is_dismissed = false`. Stored (not
  virtual) because PostgreSQL 18 does not support virtual generated columns on tables using
  user-defined enum types. Drives the partial index used by the BFF's actionable matches query.
- **`feature_vector`** (`FLOAT[]`): The raw 32-element feature array passed to the LightGBM
  model, indexed by `FeatureIndex` (defined in `nohiki-ml-manifest`; architectural target
  owner is `nohiki-l2r-core`). Stored alongside the score so that historical rows can be
  exported as training samples without re-scoring.
  `NULL` when the row was created with a zero score due to disqualification.
- **`evaluated_at`** (`TIMESTAMPTZ`): Timestamp when scoring completed. `NULL` for `PENDING`
  rows. Used in the partial `idx_correlations_actionable` index ordering.

**Correlation status state machine:**

| Status | Meaning | Valid next states |
| -------- | --------- | ------------------ |
| `pending` | Created but not yet scored | `evaluated` |
| `evaluated` | Scored and visible to user | `viewed`, `dismissed`, `expired` |
| `viewed` | User opened the listing detail | `saved`, `applied`, `dismissed`, `expired` |
| `saved` | User bookmarked the listing | `applied`, `dismissed`, `expired` |
| `applied` | User applied for the job | `expired` |
| `dismissed` | User dismissed the listing | -- (terminal) |
| `expired` | Job posting expired | -- (terminal) |

**Indexes:**

- **`uq_correlation_pref_listing`** UNIQUE on `(pref_id, listing_id)`: Enforces one score per
  pair. The event handler uses `ON CONFLICT DO NOTHING` against this constraint for idempotency --
  if the same `ListingCreated` event is redelivered, the insert is silently skipped.
- **`idx_correlations_pref_score`** on `(pref_id, correlation_score DESC NULLS LAST)`: Serves
  the BFF's "top matches for user" query. The descending score order means PostgreSQL can
  satisfy `ORDER BY score DESC LIMIT 50` with an index scan rather than a sort.
- **`idx_correlations_actionable`** partial on `(pref_id, evaluated_at DESC)` WHERE
  `correlation_status IN ('evaluated', 'pending') AND is_dismissed = false`: Serves the BFF's
  actionable matches endpoint. The partial condition filters to only the rows the BFF ever
  queries, keeping the index small even as the total row count grows.
- **`idx_correlations_listing_id`** on `listing_id`: Used by `dismiss_matches_for_deleted_job`
  when a `ListingDeleted` event arrives and all correlations for that listing must be located.
- **`idx_correlations_user_id`** on `user_id`: Supports user-scoped administrative queries.
- **`idx_correlations_status_hash`** HASH on `correlation_status`: Serves equality lookups
  on status (e.g., finding all `expired` rows for cleanup).
- **`idx_correlations_created_at_brin`** BRIN on `created_at`: Low-overhead time-range scan
  for training data export queries that filter by date range.

**Constraints:**

- **UNIQUE** on `(pref_id, listing_id)`: One correlation per job-profile pair.
- **CHECK** `correlation_score IS NULL OR (correlation_score >= 0 AND correlation_score <= 100)`:
  Ensures the integer score stays within the calibrated probability range.

**Lifecycle:**

- **Created** when a `JOB_LISTING_CREATED` or `JOB_CORRELATION_BACKFILL_LISTINGS` event is
  processed and a new job-profile pair is identified. The row and the outbox entry are written
  in a single `AsyncSession` transaction.
- **Updated** when the user views, saves, applies to, or dismisses the listing (BFF events),
  or when a `JOB_CORRELATION_FEEDBACK_RECORDED` event updates `user_feedback`.
- **Soft-deleted** (status → `dismissed`) when `JOB_LISTING_DELETED` is consumed, marking all
  correlations for that listing as non-actionable without deleting historical data.
- **Not hard-deleted**: Rows are retained as training data even after the listing or preference
  is removed.

---

### `profile_projections`

**Purpose:**

A local ECST projection of user search preferences, populated by consuming `user-pref-service`
CDC events. The scoring pipeline reads from this table at runtime to avoid any cross-service
HTTP calls. Every `SearchPrefSnapshot` -- including the profile's pre-computed MUVERA, ColBERT,
and sparse query encodings: the full snapshot is stored here as JSONB so the service can reconstruct a
`QueryEncoding` for the Qdrant pipeline without requesting embeddings from `ml-gateway-service`.

**Key columns:**

- **`id`** (`UUID`): The `pref_id` from `user-pref-service`. Not UUIDv7 (set explicitly from
  the event, not generated here). Serves as the primary key and the join key to `correlations`.
- **`user_id`** (`UUID`): Denormalized from the event for user-scoped lookups.
- **`profile_name`** (`VARCHAR(255)`): Human-readable profile name for logging.
- **`is_active`** (`BOOLEAN`): When `false`, the profile is excluded from the `get_active_profiles`
  query. Currently all profiles are active; this flag exists to support future soft-disabling
  without deleting projections.
- **`snapshot_data`** (`JSONB`): The serialized `SearchPrefSnapshot` protobuf, stored via
  `betterproto2`'s `.to_dict()`. Re-hydrated via `.from_dict()` when needed. Contains the full
  preference payload including `query_retrieval_embeddings` (MUVERA + ColBERT + sparse vectors),
  `required_skills`, `disallowed_keywords`, location data, salary expectations, and experience
  requirements: everything the `FeatureComposer` needs to extract the 32-feature vector.

**Indexes:**

- **`ix_profile_projections_user_id`** on `user_id`: Supports user-scoped administrative
  queries (e.g., "how many profiles does this user have?").
- **`ix_profile_projections_is_active`** partial on `is_active` WHERE `is_active = true`:
  Used by `get_active_profiles()`, which is called on every `JOB_LISTING_CREATED` event.
  The partial index makes this a near-instant scan regardless of total profile count.

**Lifecycle:**

- **Created** (upserted) when `USER_PREF_CREATED` is consumed. The same `upsert_profile()`
  call is used for both create and update paths so events can be reprocessed safely.
- **Updated** (upserted) when `USER_PREF_UPDATED` is consumed. The full snapshot, including
  new embeddings if the profile text changed, replaces the previous row.
- **Deleted** when `USER_PREF_DELETED` is consumed. The row is hard-deleted; any existing
  `correlations` rows referencing this `pref_id` remain as historical data.

---

### `feedback.asymmetric_feedback`

**Purpose:**

Captures score quality feedback from users indicating whether a given correlation score is
accurate (GOOD), too high (TOO_HIGH), or too low (TOO_LOW). This "asymmetric" feedback is
more granular than binary thumbs up/down: it tells the model not just whether the user liked
or disliked a job, but whether the *score itself* was calibrated correctly. These records feed
into calibration analysis during model retraining.

**Key columns:**

- **`id`** (`UUID`): UUIDv7 primary key.
- **`correlation_id`** (`UUID`): References `job_correlation_schema.correlations.id`. No FK
  constraint.
- **`user_id`** (`UUID`): Denormalized from the request for user-scoped queries.
- **`feedback_type`** (`SMALLINT`): `1 = GOOD`, `2 = TOO_HIGH`, `3 = TOO_LOW`. Stored as a
  smallint with a CHECK constraint rather than an enum to keep the feedback schema decoupled
  from the correlation schema's enum types.

**Lifecycle:**

- **Created** when `FEEDBACK_SCORE_FEEDBACK_REQUESTED` is consumed.
- **Never updated or deleted**: Feedback records are immutable audit data.

---

### `feedback.manual_adjustments`

**Purpose:**

Stores user-provided score overrides where the user specifies an exact score they believe is
correct, plus a free-text explanation. Captures both the original model score (fetched from
the `correlations` row at the time of adjustment) and the adjusted score. These records provide
high-signal training examples where the user has explicitly expressed the desired outcome.

**Key columns:**

- **`id`** (`UUID`): UUIDv7 primary key.
- **`correlation_id`** (`UUID`): References `job_correlation_schema.correlations.id`. No FK
  constraint.
- **`user_id`** (`UUID`): Denormalized from the request.
- **`original_score`** (`DOUBLE PRECISION`): The calibrated probability (`0.0–1.0`) at the
  time the adjustment was made. Fetched from `correlations.correlation_score / 100.0`.
- **`adjusted_score`** (`DOUBLE PRECISION`): The user-provided calibrated probability
  (`0.0–1.0`).
- **`reasoning`** (`TEXT`): Free-text explanation of why the score should differ.

**Lifecycle:**

- **Created** when `FEEDBACK_SCORE_ADJUSTMENT_REQUESTED` is consumed, if the referenced
  correlation row exists.
- **Never updated or deleted**: Immutable audit data.

## Transactional WAL Messages

Every `CorrelationEvaluated` event is emitted with `pg_logical_emit_message(..., true, ...)`
inside the same `AsyncSession` transaction as the `correlations` insert. PostgreSQL commits the
row and logical message together, so Debezium cannot observe either side independently.

The dedicated `job-correlation-evaluation-service-wal` connector captures logical messages and
routes them through `NohikiWalRouterSmt` to Kafka. Its minimal filtered publication contains only
`job_correlation_schema.processed_events`; the SMT drops all publication row records.

**Events published via transactional WAL:**

- **`job-correlation.cdc.correlation-evaluated.v1`** (`CorrelationEvaluated`): Published for
  every successfully scored correlation.

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

# View current migration state
alembic current
```

The `001_initial_migration.py` creates both `job_correlation_schema` and the `feedback` schema.
The `downgrade()` function drops both schemas with `CASCADE`, removing all tables, indexes,
enum types, and processed-event state in a single operation.
