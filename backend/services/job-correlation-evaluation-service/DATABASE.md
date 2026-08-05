# Job Correlation Evaluation Database Design

The service persists one scoring record for each evaluated job-listing and user-preference pair. These records combine
the calibrated match result, the raw 32-feature learning-to-rank input, user interaction state, and feedback needed for
later model training. Separate feedback records capture more granular score-quality signals and explicit score
corrections.

The listing belongs to `job-storage-service`, and the preference belongs to `user-pref-service`. Those references cross
service ownership boundaries and are reconciled through events rather than synchronous database relationships.

## Scoring Records

A scoring record represents the result of evaluating one listing against one search preference. A record is meaningful
even when its score is zero. The calibrated score is produced from the LightGBM raw score through isotonic calibration,
scaling to the 0-100 display range, and rounding. Pending records do not yet have a completed score or evaluation time.

The records support the BFF's job-match display, notification delivery, and learning-to-rank training export. They
retain:

- the raw 32-feature vector passed to the model, ordered by `FeatureIndex` from `nohiki-ml-manifest` (with
  `nohiki-l2r-core` as the architectural target owner), so historical examples can be trained on without re-scoring;
- explicit user feedback as a learning signal;
- whether the user viewed, saved, applied to, or dismissed a match, allowing downstream behavior and BFF filtering to
  follow the interaction lifecycle; and
- the evaluation time used to order actionable results.

A record created with a zero score because of disqualification can omit the feature vector.

The database does not persist an `ml_explanation` or human-readable attribution. Raw model inputs remain in the feature
vector for internal evaluation. When publishing `CorrelationEvaluated`, the service leaves the legacy
`correlation_metadata` map empty and constructs a versioned, deterministic `fit_ranking_breakdown` from role relevance
and each fit factor's compatibility, user importance, and signed contribution points.

### Identity and concurrency

At most one score is retained for a given preference and listing pair. That pair is also the event-handler idempotency
key: a redelivered listing-created event attempts the same write and is skipped rather than creating another score.
Kafka event processing is additionally tracked in a local deduplication log.

Time-ordered identifiers keep records inserted in scoring bursts physically close together. For example, the records
produced when one new job is evaluated against many profiles tend to be colocated.

### Denormalization and access patterns

The user's identity is copied from the preference snapshot at scoring time so user-scoped queries do not need the
preference projection. The listing URL is copied so consumers of `CorrelationEvaluated` can render a link without
querying `job-storage-service`.

The storage layout is optimized around the service's actual access patterns:

- score-ordered access lets the BFF fetch a preference's top 50 matches without sorting the full history;
- an access path limited to pending or evaluated, non-dismissed records keeps the actionable working set small as
  retained history grows and returns the newest evaluations first;
- targeted access supports dismissing every match for a deleted listing, user-scoped administration, and status-based
  cleanup; and
- low-overhead time-range access supports training exports without imposing the cost of a fully ordered structure on the
  complete history.

### State transitions

| State       | Meaning                            | Valid next states                          |
| ----------- | ---------------------------------- | ------------------------------------------ |
| `pending`   | Created but not yet scored         | `evaluated`                                |
| `evaluated` | Scored and visible to the user     | `viewed`, `dismissed`, `expired`           |
| `viewed`    | The user opened the listing detail | `saved`, `applied`, `dismissed`, `expired` |
| `saved`     | The user bookmarked the listing    | `applied`, `dismissed`, `expired`          |
| `applied`   | The user applied for the job       | `expired`                                  |
| `dismissed` | The user dismissed the listing     | -- terminal                                |
| `expired`   | The job posting expired            | -- terminal                                |

Only pending or evaluated records that have not been dismissed are actionable.

### Lifecycle and retention

A scoring record is created when a `JOB_LISTING_CREATED` or `JOB_CORRELATION_BACKFILL_LISTINGS` event identifies a new
listing-preference pair. The record and its publication work are committed in the same asynchronous database
transaction.

BFF interaction events advance the view, save, application, and dismissal state. A `JOB_CORRELATION_FEEDBACK_RECORDED`
event updates the record's explicit user feedback.

When `JOB_LISTING_DELETED` is consumed, every score for that listing is moved to `dismissed` so it is no longer
actionable. The service does not hard-delete scoring records when listings or preferences disappear; they remain
available as historical training data.

## Preference Projection

The service keeps a local ECST projection of user search preferences from `user-pref-service` CDC events. The scoring
path reads this projection rather than making a cross-service HTTP request.

Each projection contains the complete `SearchPrefSnapshot`, including the precomputed MUVERA, ColBERT, and sparse query
encodings, required skills, disallowed keywords, location, salary expectations, and experience requirements. This is
everything `FeatureComposer` needs to construct the 32-feature model input and lets the Qdrant path reconstruct its
`QueryEncoding` without asking `ml-gateway-service` for embeddings.

Preference-created and preference-updated events use the same full-snapshot upsert, so either event can be reprocessed
safely. An update replaces the prior snapshot, including embeddings changed with the profile text. Inactive profiles are
excluded from scoring; profiles are currently active, but this boundary allows a projection to be disabled without
deleting it.

The projection's read paths support user-scoped administrative counts and the active-profile scan run for every
listing-created event. Limiting that scoring access path to active profiles keeps it fast regardless of the total
projection count.

A preference-deleted event hard-deletes the local projection. Historical scoring records for that preference remain
retained.

## Feedback and Audit Records

### Score-quality feedback

Asymmetric feedback records whether a score was calibrated correctly or was directionally too high or too low. This is
more useful than a simple like/dislike signal because it evaluates the score itself, and it feeds calibration analysis
during model retraining.

The user identity is copied into the feedback record for user-scoped analysis. The feedback representation remains
decoupled from the correlation lifecycle representation. A record is created when `FEEDBACK_SCORE_FEEDBACK_REQUESTED` is
consumed, then remains immutable as audit data.

### Manual adjustments

A manual adjustment captures the exact score a user believes is correct and their free-text explanation. It also
snapshots the original calibrated score from the scoring record at the time of the request. These are high-signal
training examples because the user has explicitly stated the desired outcome.

An adjustment is created when `FEEDBACK_SCORE_ADJUSTMENT_REQUESTED` is consumed, but only if the referenced scoring
record exists. It is never updated or deleted and remains immutable audit data. The user identity is copied into the
record for user-scoped analysis.

## Transactional WAL Publication

Every `CorrelationEvaluated` event is emitted as a transactional PostgreSQL logical message in the same `AsyncSession`
transaction as its scoring record. PostgreSQL commits the record and logical message together, so Debezium cannot
observe either side independently.

The dedicated `job-correlation-evaluation-service-wal` connector captures these logical messages and routes them through
`NohikiWalRouterSmt` to Kafka. Its narrowly filtered publication includes only the processed-event ledger needed by the
connector, and the SMT drops those publication row records. Successfully scored correlations are published on
`job-correlation.cdc.correlation-evaluated.v1`.

The schema itself is defined by the service's SQLAlchemy models in `src/job_correlation_evaluation_service/db/models.py`
and `src/job_correlation_evaluation_service/db/feedback_models.py` and Alembic revision
`alembic/versions/001_initial_migration.py`.
