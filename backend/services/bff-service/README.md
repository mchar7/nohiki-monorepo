# BFF Service

The Backend-for-Frontend service is the sole HTTP API gateway between the browser frontend and
Nohiki's event-driven backend. Every piece of data the frontend displays comes from a local
PostgreSQL projection table that this service populates by consuming Kafka CDC and fact events from
ten upstream services. Every user-initiated write action is dispatched as a Kafka command event and
returns `202 Accepted` with a `request_id` -- no write ever touches an upstream domain service
directly. The BFF is stateful (PostgreSQL `bff_schema`), HTTP-exposed via Traefik, and is the
highest Kafka topic consumer in the monorepo at 17 subscribed topics, with 12 command topics it
publishes to.

## Role in the System

The BFF owns no authoritative domain state. Its database schema is entirely composed of
denormalized read models (projections) written by Kafka event handlers and read by API routers.
This means the BFF is the single integration point where event-driven eventual consistency meets
synchronous HTTP: a `GET /api/v1/listings` is answered from a locally cached projection, while
a `POST /api/v1/profiles` publishes `USER_PREF_CREATE_REQUESTED` to Kafka and immediately
returns a `request_id` the frontend can poll.

Upstream services that feed the BFF via CDC events: `user-auth-service` (account state),
`user-pref-service` (search profiles and settings), `user-upload-service` (document attachments),
`job-storage-service` (listing metadata), `job-correlation-evaluation-service` (match scores),
`doc-template-service` (Jinja2 HTML templates and render results), and `skill-graph-service`
(canonical skill catalogue). Every command the BFF publishes is consumed by one of:
`user-pref-service`, `user-upload-service`, `job-correlation-evaluation-service`,
`doc-template-service`, or `doc-content-service`.

The BFF is on the critical path for every user-facing feature: job discovery, match scoring
display, profile management, attachment uploads, template browsing, and document generation all
run through its API surface. It shares HTTP-exposure status only with `user-auth-service`
(login/registration). All other 16 services are Kafka-only.

## Event-Driven Integration

### Events Consumed

All projection handlers share a single consumer group derived at startup:
`{kafka.consumer_group}-projections` (e.g., `bff-service-projections`). Concurrency is set to
`max_concurrent_handlers=20`, appropriate for the I/O-bound projection upsert workload. All
handlers use `preserve_partition_order=False` for maximum throughput.

- **`USER_AUTH_ACCOUNT_UPDATED`** (`AccountUpdated`): Upserts the `account_projections` row from
  the ECST `AccountSnapshot` embedded in the event. Before upserting, it deletes any stale rows
  sharing the same email with a different `id` -- handling the edge case where a user re-registers
  with the same email after account deletion. Consumer group: `bff-service-projections`. Idempotent
  via `ON CONFLICT (id) DO UPDATE`.

- **`USER_AUTH_ACCOUNT_DELETED`** (`AccountDeleted`): Deletes the `account_projections` row for
  the given `user_id`. Consumer group: `bff-service-projections`.

- **`USER_PREF_CREATED`** (`PrefCreated`): Creates a `profile_projections` row from the
  `SearchPrefSnapshot`. Converts `notification_config.threshold` from a 0-100 integer percentage
  to a 0.0-1.0 float, and serializes `commute_preferences` to JSONB. Idempotent via
  `ON CONFLICT DO NOTHING`. Consumer group: `bff-service-projections`.

- **`USER_PREF_UPDATED`** (`PrefUpdated`): Upserts `profile_projections` with the same snapshot
  mapping. Idempotent via `ON CONFLICT (id) DO UPDATE`. Consumer group: `bff-service-projections`.

- **`USER_PREF_DELETED`** (`PrefDeleted`): Deletes the `profile_projections` row by `pref_id`.
  Consumer group: `bff-service-projections`.

- **`USER_PREF_SETTINGS_CREATED`** (`UserPrefSettingsCreated`): Creates a
  `user_pref_settings_projections` row containing the user's default L2R feature importance
  weights (serialized as JSONB with keys `skill_match_importance`, `location_importance`,
  `work_arrangement_importance`, `experience_importance`, `salary_importance`,
  `recency_importance`). Idempotent via `ON CONFLICT DO NOTHING`. Consumer group:
  `bff-service-projections`.

- **`USER_PREF_SETTINGS_UPDATED`** (`UserPrefSettingsUpdated`): Upserts
  `user_pref_settings_projections` with the same JSONB structure. Idempotent via
  `ON CONFLICT (user_id) DO UPDATE`. Consumer group: `bff-service-projections`.

- **`USER_UPLOAD_CREATED`** (`UploadCreated`): Creates an `attachment_projections` row from the
  `UploadSnapshot`. This fires after `user-upload-service` has verified the file in S3 and published
  its CDC event. The BFF can then surface the attachment in `GET /api/v1/attachments`. Idempotent
  via `ON CONFLICT DO NOTHING`. Consumer group: `bff-service-projections`.

- **`USER_UPLOAD_DELETED`** (`UploadDeleted`): Deletes the `attachment_projections` row by
  `upload_id`. Consumer group: `bff-service-projections`.

- **`JOB_LISTING_CREATED`** (`ListingCreated`): Upserts `job_listing_projections` from the
  `ListingSnapshot`. A PostgreSQL trigger fires on every insert/update to compute the
  `search_vector` TSVECTOR column (title weight A, company + required_skills weight B, description
  weight C), enabling full-text search via the GIN index. Idempotent via `ON CONFLICT (id) DO
  UPDATE`. Consumer group: `bff-service-projections`.

- **`JOB_LISTING_UPDATED`** (`ListingUpdated`): Applies the same upsert logic with the new
  snapshot version. Consumer group: `bff-service-projections`.

- **`JOB_LISTING_DELETED`** (`ListingDeleted`): Deletes the `job_listing_projections` row by
  `listing_id`. Consumer group: `bff-service-projections`.

- **`JOB_CORRELATION_EVALUATED`** (`CorrelationEvaluated`): Upserts `job_correlation_projections`
  with the fit score, status, and score breakdown from `job-correlation-evaluation-service`. The
  event carries both `ListingSnapshot` and `SearchPrefSnapshot` so the BFF can denormalize listing
  metadata (`listing_title`, `listing_company`, `listing_url`, `listing_location`) directly into
  the correlation row, eliminating any join at query time. Idempotent via `ON CONFLICT ON
  CONSTRAINT uq_correlation_pref_listing DO UPDATE`. Consumer group: `bff-service-projections`.

- **`DOC_TEMPLATE_CREATED`** (`TemplateCreated`): Upserts `template_projections` from the ECST
  `TemplateSnapshot` and its `VersionSnapshot`. Parses `content_schema_json` from the version
  snapshot to store the variable schema as JSONB. Idempotent via `ON CONFLICT (id) DO UPDATE`.
  Consumer group: `bff-service-projections`.

- **`DOC_TEMPLATE_UPDATED`** (`TemplateUpdated`): Same upsert logic as create. Consumer group:
  `bff-service-projections`.

- **`DOC_TEMPLATE_DELETED`** (`TemplateDeleted`): Deletes the `template_projections` row. Consumer
  group: `bff-service-projections`.

- **`DOC_TEMPLATE_RENDER_COMPLETED`** (`DocumentRenderCompleted`): Updates the
  `document_generation_status` row matched by `metadata.correlation_id` (= the `request_id`
  assigned at generation time). Sets `status` to `completed` or `failed`, and on success records
  `storage_key`, `file_size`, and `content_hash`. This is how an asynchronous render initiated via
  `POST /api/v1/documents/generate` becomes visible on `GET /api/v1/documents/{request_id}/status`.
  Consumer group: `bff-service-projections`.

- **`SKILL_CREATED`** (`SkillCreated`): Upserts `skill_projections` from the `SkillSnapshot`. A
  PostgreSQL trigger maintains the `search_vector` column (normalized_text + display_name weight A,
  category weight B, description weight C). Idempotent via `ON CONFLICT (id) DO UPDATE`. Consumer
  group: `bff-service-projections`.

### Events Published

The BFF publishes commands directly via `kafka_client.publish()` (no transactional outbox). Each
published event carries a UUIDv7 `request_id` used for correlation and idempotency tracking.

- **`USER_PREF_CREATE_REQUESTED`** (`PrefCreateRequested`): Published by `POST /api/v1/profiles`.
  Consumed by `user-pref-service`, which creates the preference and publishes
  `USER_PREF_CREATED` back to the BFF for projection. Keyed by `request_id`.

- **`USER_PREF_UPDATE_REQUESTED`** (`PrefUpdateRequested`): Published by
  `PATCH /api/v1/profiles/{pref_id}`. Consumed by `user-pref-service`. Carries an `updated_fields`
  list so the consumer applies only the changed fields. Keyed by `request_id`.

- **`USER_PREF_DELETE_REQUESTED`** (`PrefDeleteRequested`): Published by
  `DELETE /api/v1/profiles/{pref_id}`. Consumed by `user-pref-service`. Keyed by `request_id`.

- **`USER_PREF_ATTACH_UPLOAD_REQUESTED`** (`PrefAttachUploadRequested`): Published by
  `POST /api/v1/profiles/{pref_id}/attachments/{upload_id}`. Links an uploaded document to a
  search preference. Consumed by `user-pref-service`. Keyed by `request_id`.

- **`USER_PREF_DETACH_UPLOAD_REQUESTED`** (`PrefDetachUploadRequested`): Published by
  `DELETE /api/v1/profiles/{pref_id}/attachments/{upload_id}`. Consumed by `user-pref-service`.
  Keyed by `request_id`.

- **`USER_PREF_SETTINGS_UPDATE_REQUESTED`** (`UserPrefSettingsUpdateRequested`): Published by
  `PUT /api/v1/profiles/settings/feature-importance`. Updates user-level L2R feature importance
  defaults that apply across all search preferences. Consumed by `user-pref-service`. Keyed by
  `request_id`.

- **`USER_PREF_FEATURE_IMPORTANCE_UPDATE_REQUESTED`** (`PrefFeatureImportanceUpdateRequested`):
  Published by `PUT /api/v1/profiles/{pref_id}/feature-importance`. Overrides importance weights
  for a single search preference, taking precedence over user-level defaults. Consumed by
  `user-pref-service`. Keyed by `request_id`.

- **`USER_UPLOAD_CREATE_REQUESTED`** (`UploadCreateRequested`): Published by
  `POST /api/v1/attachments/{upload_id}/complete`. Carries the BFF-computed SHA-256 content hash
  (never accepted from the client). Consumed by `user-upload-service`. Keyed by `upload_id`.

- **`USER_UPLOAD_DELETE_REQUESTED`** (`UploadDeleteRequested`): Published by
  `DELETE /api/v1/attachments/{upload_id}`. Consumed by `user-upload-service`. Keyed by
  `request_id`.

- **`JOB_CORRELATION_FEEDBACK_RECORDED`** (`FeedbackRecorded`): Published by
  `POST /api/v1/correlations/{correlation_id}/feedback`. Carries the qualitative feedback type
  (viewed, saved, applied, dismissed, liked, disliked). Consumed by
  `job-correlation-evaluation-service` for L2R training signal collection. Keyed by `request_id`.

- **`FEEDBACK_SCORE_FEEDBACK_REQUESTED`** (`ScoreFeedbackRequested`): Published by
  `POST /api/v1/correlations/{correlation_id}/score-feedback`. Carries asymmetric score assessment
  (GOOD, TOO_HIGH, TOO_LOW). Consumed by `job-correlation-evaluation-service`. Keyed by
  `request_id`.

- **`FEEDBACK_SCORE_ADJUSTMENT_REQUESTED`** (`ScoreAdjustmentRequested`): Published by
  `POST /api/v1/correlations/{correlation_id}/adjust-score`. Carries the user's explicit corrected
  score (0.0-1.0) and a freeform reasoning string. Consumed by
  `job-correlation-evaluation-service`. Keyed by `request_id`.

- **`DOC_TEMPLATE_CREATE_REQUESTED`** (`TemplateCreateRequested`): Published by
  `POST /api/v1/template-families`. Carries the full Jinja2 HTML content after local validation
  (balanced block tags, `<!DOCTYPE html>` structure). Consumed by `doc-template-service`. Keyed by
  `request_id`.

- **`DOC_TEMPLATE_VERSION_ADD_REQUESTED`** (`TemplateVersionAddRequested`): Published by
  `POST /api/v1/template-families/{family_id}/versions`. Consumed by `doc-template-service`. Keyed
  by `request_id`.

- **`DOC_TEMPLATE_DELETE_REQUESTED`** (`TemplateDeleteRequested`): Published by
  `DELETE /api/v1/template-families/{family_id}`. Consumed by `doc-template-service`. Keyed by
  `request_id`.

- **`DOC_TEMPLATE_RENDER_REQUESTED`** (`DocumentRenderRequested`): Published by
  `POST /api/v1/documents/generate`. Carries the full template content embedded in the event (ECST
  pattern -- `doc-template-service` does not need to look it up). The `metadata.correlation_id`
  is set to the `request_id` so the BFF can match the `DOC_TEMPLATE_RENDER_COMPLETED` callback.
  Consumed by `doc-template-service`, which renders the PDF/HTML via Gotenberg. Keyed by
  `request_id`.

### Notable Patterns

**CQRS with Projections**: The BFF implements CQRS more explicitly than any other service in the
monorepo. Each API resource has two completely separate code paths: a read path (GET endpoints
query `bff_schema` projection tables directly) and a write path (POST/PATCH/DELETE endpoints call
`kafka_client.publish()` and return `202 Accepted`). No write endpoint queries the database. No
read endpoint touches Kafka. A developer new to the codebase must understand that a `POST /profiles`
will not be immediately visible on `GET /profiles` -- there is an eventual consistency window while
`user-pref-service` processes the command and the resulting `USER_PREF_CREATED` event propagates
back through the BFF's own Kafka consumer.

**Document Generation Render Callback**: The document flow uses an implicit callback pattern. The
BFF publishes `DOC_TEMPLATE_RENDER_REQUESTED` with `metadata.correlation_id = request_id`, inserts
a `document_generation_status` row with `status = pending`, and returns immediately. When
`doc-template-service` completes rendering, it publishes `DOC_TEMPLATE_RENDER_COMPLETED` with the
same `correlation_id`. The BFF's `handle_render_completed` handler matches on `correlation_id` and
updates the status row to `completed` or `failed`. The frontend polls
`GET /api/v1/documents/{request_id}/status` or subscribes to the SSE endpoint
`GET /api/v1/documents/{request_id}/events`.

## State & Persistence

### Database

Schema `bff_schema` contains thirteen tables, all of which are projections. No table in this schema
represents authoritative domain state: all data originates from upstream services and arrives via
Kafka events. The projections cover four domains: user data (`account_projections`,
`profile_projections`, `user_pref_settings_projections`, `attachment_projections`), job data
(`job_listing_projections`, `job_correlation_projections`), document data
(`schema_family_projections`, `schema_version_projections`, `template_projections`,
`document_generation_status`), and skills (`skill_projections`). Two tables are operational rather
than projections: `command_requests` for command idempotency tracking, and the standard outbox and
processed_events tables created by shared migration helpers.

See [DATABASE.md](./DATABASE.md) for semantic database design and lifecycle documentation.

### Object Storage

The BFF uses RustFS (S3-compatible) exclusively for presigned URL generation and server-side file
verification during the upload completion flow. It does not store objects itself -- `user-upload-service`
owns the authoritative copy. The storage key pattern for user uploads is
`user-uploads/{user_id}/{upload_id}/{filename}`. On upload completion, the BFF retrieves the object
to compute SHA-256 rather than trusting any hash from the client.

### Redis

Redis serves two roles:

- **Rate limiting**: `nohiki-fastapi-utils` `setup_rate_limiting` middleware applies per-user
  limits (authenticated: 120 req/min, 3000 req/hour in production; anonymous: 30 req/min,
  300 req/hour). Development defaults are much higher for convenience.

- **Result caching**: Skill searches are cached for 5 minutes, skill-by-ID batch lookups for
  10 minutes, and skill category lists for 30 minutes. Job listing full-text search results are
  cached for 2 minutes (configurable via `BFF_CACHING__SEARCH_RESULTS_TTL`). Cache keys are
  keyed by query parameters and pagination state.

## Key Design Patterns

### CQRS Write Path: Command + Idempotency Tracking

Every mutating endpoint generates a UUIDv7 `request_id`, publishes a Kafka command event with that
ID embedded in `EventMetadata.correlation_id`, and records a `command_requests` row with
`status = pending`. The `request_id` is returned to the caller in a `CommandAcceptedResponse`.
If the same request is submitted again with the same `request_id`, the Kafka consumer on the
receiving service uses its own idempotency mechanism to skip reprocessing. The `command_requests`
table is not the primary idempotency guard. Upstream services own that, and the table enables
frontend to poll command status.

The document generation flow is an exception: it does not record into `command_requests` but
instead uses `document_generation_status` as its tracking table, keyed by `request_id`, because
it has richer state transitions (`pending → in_progress → completed/failed`) and needs to carry
the S3 `storage_key`, `file_size`, and `content_hash` on completion.

### JWKS Token Verification

The BFF validates JWTs using the JWKS endpoint published by `user-auth-service` at
`/.well-known/jwks.json`. On startup, `init_jwks_verifier` fetches and caches the public key set.
Every authenticated endpoint calls `get_current_user_id_from_cookie` (or `get_current_user_claims`
for the session endpoint), which validates the `nohiki_at` HttpOnly cookie using RS256 signature
verification against the cached JWKS. The BFF does not share a symmetric secret with
`user-auth-service`. In production, the cookie carries the `__Host-` prefix to require HTTPS
and block cross-site access.

### Full-Text Search via PostgreSQL TSVECTOR Triggers

Job listings and skills use PostgreSQL FTS rather than a separate search engine. The migration
installs two trigger functions (`job_listing_search_trigger` and `skill_search_trigger`) that fire
`BEFORE INSERT OR UPDATE` and populate the `search_vector` TSVECTOR column with weighted tokens.
For listings: title (weight A), company name and required skills (weight B), description (weight C).
For skills: normalized text and display name (weight A), category (weight B), description (weight C).
The GIN index on `search_vector` makes ranked FTS queries efficient. Listing queries use
`build_prefix_tsquery` from `nohiki-db-utils` for incremental/partial-word matching during typing.
Results are ranked by `ts_rank_cd` and cached in Redis.

### Feature Importance Resolution

The profile endpoints implement a three-tier resolution hierarchy for L2R feature importance
weights. When `GET /api/v1/profiles/{pref_id}/resolved-importance` is called,
`ProfileService.get_resolved_importance` checks in order: (1) the search preference's own
`feature_importance` JSONB (set via `PUT /api/v1/profiles/{pref_id}/feature-importance`), (2) the
user's default `default_feature_importance` in `user_pref_settings_projections` (set via
`PUT /api/v1/profiles/settings/feature-importance`), (3) neutral defaults of 50 for all six
dimensions. This resolution runs entirely against local projection data. There is no upstream lookup.

### Upload Security: Server-Side Hash Computation

The attachment upload flow uses client-side S3 PUT (presigned URL) but never trusts the client's
claimed file hash. After the client calls `POST /api/v1/attachments/{upload_id}/complete`, the BFF
downloads the file from S3 via the internal endpoint, verifies the byte count matches the declared
`file_size`, computes SHA-256, and embeds the BFF-computed hash in the `USER_UPLOAD_CREATE_REQUESTED`
command. `user-upload-service` receives a hash it can trust.

## Configuration

The BFF uses `DatabaseMixin`, `RedisMixin`, `KafkaMixin`, `S3Mixin`, and `NohikiBaseSettings`.
All environment variables are prefixed with `BFF_`.

Key non-obvious settings:

- **`BFF_JWT__JWKS_URL`**: URL to `user-auth-service`'s JWKS endpoint (e.g.,
  `https://auth.nohiki.com/.well-known/jwks.json`). Required at startup; the service will not
  initialize the JWKS verifier without it.
- **`BFF_JWT__ISSUER`** / **`BFF_JWT__AUDIENCE`**: Expected JWT claims. Defaults to
  `https://api.nohiki.com` / `https://app.nohiki.com`.
- **`BFF_COOKIE__ACCESS_TOKEN_NAME`**: Cookie name for the JWT access token. In production,
  automatically prefixed with `__Host-` to enforce HTTPS and exact-domain binding.
- **`BFF_ORIGINS__CORS_ORIGINS`** / **`BFF_ORIGINS__CSRF_ORIGINS`**: Comma-separated lists of
  allowed origins for CORS and CSRF protection respectively.
- **`BFF_KAFKA__CONSUMER__MAX_CONCURRENT_HANDLERS`**: Defaults to 20. Higher than other services
  because all handlers are I/O-bound DB upserts with no blocking computation.
- **`BFF_CACHING__SEARCH_RESULTS_TTL`**: Redis TTL in seconds for job listing search results.
  Defaults to 120 (2 minutes).
- **`BFF_CACHING__BFF_RATE_LIMIT__AUTH_REQUESTS_PER_MINUTE`** etc.: Per-tier rate limits.
  Production defaults (120/min authenticated, 30/min anonymous) are applied automatically when
  `BFF_ENVIRONMENT` is not `development`.

## Development

### Local Setup

```bash
uv sync
alembic upgrade head
```

Requires PostgreSQL (`bff_schema` will be created by the migration), Redis, and a reachable Kafka
broker. In Compose, the JWKS URL is `http://nohiki-svc-user-auth:8000/.well-known/jwks.json`.
For separately launched host processes, use the host and port where `user-auth-service` is listening.

In development mode (`BFF_ENVIRONMENT=development`), the `__Host-` cookie prefix is suppressed
automatically, rate limits are raised to 10,000 req/min, and the CSRF middleware operates with
relaxed origins.

### Testing

```bash
just test bff-service
just test-cov bff-service
```

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise
uv run ty check
```
