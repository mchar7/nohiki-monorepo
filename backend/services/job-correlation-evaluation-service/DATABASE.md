# Job Correlation Evaluation Service Database Design

Schema `job_correlation_schema` stores one correlation record per job-profile pair, including
the integer match score, the raw 32-dimensional L2R feature vector, interaction lifecycle
flags, and user feedback signals used to train future model iterations. A second schema,
`feedback`, holds granular score quality signals in two separate tables.

The `correlations` table is the central domain entity. Each row links a `listing_id` (owned by
`job-storage-service`) to a `pref_id` (owned by `user-pref-service`) via a UNIQUE constraint
that enforces one score per pair and serves as the idempotency key for event handlers.
`profile_projections` provides the local replica of all active preferences that the scoring
pipeline reads at runtime without querying `user-pref-service`. Transactional logical messages
ensure `CorrelationEvaluated` events commit atomically with correlation writes;
`asymmetric_feedback` and `manual_adjustments` capture user signals that flow back into the L2R
training pipeline.

## `correlations`

Stores the result of evaluating a single job listing against a single user search preference.
A row exists for every pair the service has scored, regardless of the resulting score value.
A 0% correlation is still a correlation. The table drives the BFF's job match display, the
notification pipeline, and the L2R training data export.

- **`pref_id`:** References `user-pref-service`'s preference record by UUID. No foreign key
  constraint: cross-schema references are resolved via events per EDA principles.
- **`listing_id`:** References `job-storage-service`'s listing record by UUID. No foreign key
  constraint. Listing deletions are handled by consuming
  `job-listing.cdc.listing-deleted.v1` events.
- **`user_id`:** Denormalized from the profile snapshot at scoring time. Enables user-scoped
  queries without joining to `profile_projections`.

The correlation score is either `NULL` until the pair is scored or an integer from 0 through 100.
Rows whose `feature_vector` is `NULL` are excluded from training-sample exports.

`feature_vector` holds the raw feature inputs composed for the model, not a derived or
human-readable explanation. There is no persisted `ml_explanation` column: the human-facing
deterministic ranking explanation is built at publish time as a typed `FitRankingBreakdown`,
and the legacy `CorrelationEvaluated.correlation_metadata` map is left empty.

**`is_actionable`:** Stored (not virtual) because PostgreSQL 18 does not support virtual
generated columns on tables using user-defined enum types. Drives the partial index used by the
BFF's actionable matches query.

**Access patterns and rationale:**

- The event handler uses `ON CONFLICT DO NOTHING` against this constraint for idempotency. If
  the same `ListingCreated` event is redelivered, the insert is silently skipped.
- Serves the BFF's "top matches for user" query. The descending score order means PostgreSQL can
  satisfy `ORDER BY score DESC LIMIT 50` with an index scan rather than a sort.
- Serves the BFF's actionable matches endpoint. The partial condition filters to only the rows
  the BFF ever queries, keeping the index small even as the total row count grows.
- Used by `dismiss_matches_for_deleted_job` when a `ListingDeleted` event arrives and all
  correlations for that listing must be located.
- Supports user-scoped administrative queries.
- Serves equality lookups on status (e.g., finding all `expired` rows for cleanup).
- Low-overhead time-range scan for training data export queries that filter by date range.

**Correlation status state machine:**

| Status | Meaning | Valid next states |
| -------- | --------- | ------------------ |
| `pending` | Created but not yet scored | `evaluated` |
| `evaluated` | Scored and visible to user | `viewed`, `dismissed`, `expired` |
| `viewed` | User opened the listing detail | `saved`, `applied`, `dismissed`, `expired` |
| `saved` | User bookmarked the listing | `applied`, `dismissed`, `expired` |
| `applied` | User applied for the job | `expired` |
| `dismissed` | User dismissed the listing | terminal |
| `expired` | Job posting expired | terminal |

**Lifecycle:**

- **Created** when a `JOB_LISTING_CREATED` or `JOB_CORRELATION_BACKFILL_LISTINGS` event is
  processed and a new job-profile pair is identified. The row and the transactional WAL
  logical message are written in a single `AsyncSession` transaction.
- **Updated** when the user views, saves, applies to, or dismisses the listing (BFF events),
  or when a `JOB_CORRELATION_FEEDBACK_RECORDED` event updates `user_feedback`.
- **Soft-deleted** (status to `dismissed`) when `JOB_LISTING_DELETED` is consumed, marking all
  correlations for that listing as non-actionable without deleting historical data.
- **Not hard-deleted**: Rows are retained as training data even after the listing or preference
  is removed.

## `profile_projections`

A local ECST projection of user search preferences, populated by consuming `user-pref-service`
CDC events. The scoring pipeline reads from this table at runtime to avoid any cross-service
HTTP calls. Every `SearchPrefSnapshot`, including the profile's pre-computed MUVERA, ColBERT,
and sparse query encodings: the full snapshot is stored here as JSONB so the service can reconstruct a
`QueryEncoding` for the Qdrant pipeline without requesting embeddings from `ml-gateway-service`.

**`is_active` and access patterns:**

- **`is_active`:** When `false`, the profile is excluded from the `get_active_profiles` query.
- Used by `get_active_profiles()`, which is called on every `JOB_LISTING_CREATED` event. The
  partial index makes this a near-instant scan regardless of total profile count.
- Supports user-scoped administrative queries on `user_id`.

**Lifecycle:**

- **Created** (upserted) when `USER_PREF_CREATED` is consumed. The same `upsert_profile()`
  call is used for both create and update paths, and it applies a snapshot only when the
  event's source revision is newer than the stored revision, so duplicate or reordered
  deliveries cannot replace newer state.
- **Updated** (upserted) when `USER_PREF_UPDATED` is consumed. The full snapshot, including
  new embeddings if the profile text changed, replaces the previous row when its source
  revision advances.
- **Tombstoned** when `USER_PREF_DELETED` is consumed. The row is retained with `is_active`
  set to false and the deletion revision recorded so delayed CDC cannot resurrect it; any
  existing `correlations` rows referencing this `pref_id` remain as historical data.

## `feedback.asymmetric_feedback`

Captures score quality feedback from users indicating whether a given correlation score is
accurate (GOOD), too high (TOO_HIGH), or too low (TOO_LOW). This "asymmetric" feedback is
more granular than binary thumbs up/down: it tells the model not just whether the user liked
or disliked a job, but whether the *score itself* was calibrated correctly. These records feed
into calibration analysis during model retraining.

**Lifecycle:**

- **Created** when `FEEDBACK_SCORE_FEEDBACK_REQUESTED` is consumed, if the referenced
  correlation row exists.
- **Never updated or deleted**: Feedback records are immutable audit data.

## `feedback.manual_adjustments`

Stores user-provided score overrides where the user specifies an exact score they believe is
correct, plus a free-text explanation. The original model score is snapshotted when the adjustment
is consumed and does not follow later re-scoring: it is converted from the `correlations` table's
0-100 integer to a 0.0-1.0 probability by dividing by 100, and stored as 0.0 when the correlation
is not yet scored. The adjusted score uses the same 0.0-1.0 scale. These records provide
high-signal training examples where the user has explicitly expressed the desired outcome.

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

## Schema Sources

- `src/job_correlation_evaluation_service/db/models.py`
- `src/job_correlation_evaluation_service/db/feedback_models.py`
- `alembic/versions/001_initial_migration.py`

Migration commands and the clean-cut deployment policy live in
[Database Migration Workflow](../../../README.md#database-migration-workflow).
