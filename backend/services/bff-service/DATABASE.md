# BFF Service Database Design

Schema `bff_schema` is a read-model database for the Backend-for-Frontend service. Most tables
in this schema are **projections**: denormalized, eventually consistent copies of data owned by
upstream services and delivered via Kafka CDC or fact events. The BFF writes projection tables
only from its Kafka event handlers; API routers read from them. The two non-projection tables,
`document_generation_status` and `command_requests`, are written directly by API routers.

The migration also creates standard `outbox` and `processed_events` tables via shared migration
helpers from `nohiki-db-utils`. No BFF code reads or writes either table: the BFF does not use a
transactional outbox for its command publishing, and its handlers do not claim events through
`processed_events`.

All user and job projection tables reference other services' data by UUID only: there are no
foreign key constraints across schema boundaries. A `profile_projections.user_id` references
`user_auth_schema.accounts.id` by convention, not by database constraint.

## Table Details

### `account_projections`

#### Purpose

A projection of user account state, populated from `USER_AUTH_ACCOUNT_UPDATED` events published
by `user-auth-service`. The BFF uses this table to resolve user identity in the `/api/v1/session`
adjacent workflows where account metadata is needed beyond what the JWT carries.

#### Notes

- **`id`**: Value is the canonical user ID from `user_auth_schema.accounts`;
  not BFF-generated. Carries the UUIDv7 encoding from the originating service.
- **`email`**: The handler deletes stale rows with the same
  email but a different `id` before upserting. This handles re-registration with the same email address.
- **`updated_at`**: Replicated from the upstream snapshot; reflects the timestamp
  of the last mutation in `user-auth-service`, not the projection update time.

The table is accessed only by `id` (from JWT `sub` claim) in production usage.

#### Constraints & Invariants

- **Unique `email`**: The handler explicitly cleans up email
  conflicts before upserting to maintain this invariant.

#### Data Lifecycle

- **Created/Updated** when `USER_AUTH_ACCOUNT_UPDATED` is consumed. `ON CONFLICT (id) DO UPDATE`
  applies the snapshot fields.
- **Deleted** when `USER_AUTH_ACCOUNT_DELETED` is consumed.

---

### `profile_projections`

#### Purpose

A projection of job search preference profiles from `user-pref-service`. Each row represents one
`SearchPref` entity, containing the keywords, work arrangement preferences, notification thresholds,
and commute settings that drive job matching and notifications. The BFF uses this table for
`GET /api/v1/profiles` and feature importance resolution.

#### Notes

- **`id`**: Value is the `pref_id` from `user-pref-service`.
- **`user_id`**: References `user_auth_schema.accounts.id` (no FK constraint --
  cross-schema).
- **`search_keywords`**: Keyword strings used for job query
  composition by `job-query-composition-service`.
- **`disallowed_keywords`**: Keywords that disqualify a listing from matching.
- **`notification_threshold`**: Stored as a 0.0-1.0 ratio. The upstream source is a
  0-100 integer from `SearchPrefSnapshot.notification_config.threshold`; the handler converts it
  with `percent_to_ratio`.
- **`auto_tailor_threshold`**: Score compared against by `doc-content-service`, also a 0.0-1.0
  ratio converted from the upstream integer percentage. Reaching it starts nothing: the
  auto-generation trigger is intentionally unimplemented.
- **`feature_importance`**: Per-profile L2R feature importance overrides set
  via `PUT /api/v1/profiles/{pref_id}/feature-importance`.
- **`commute_preferences`**: Serialized from `CommutePreferences` proto.

The primary read pattern for this table is `SELECT ... WHERE user_id = $1` in
`ProfileService.list_profiles`.

#### Constraints & Invariants

- **`ON CONFLICT (id) DO NOTHING`** on `USER_PREF_CREATED` (create is idempotent by skipping
  duplicates).
- **`ON CONFLICT (id) DO UPDATE`** on `USER_PREF_UPDATED` (replaces all mutable fields).

#### Data Lifecycle

- **Created** when `USER_PREF_CREATED` is consumed.
- **Updated** when `USER_PREF_UPDATED` is consumed with the new snapshot.
- **Deleted** when `USER_PREF_DELETED` is consumed.

---

### `user_pref_settings_projections`

#### Purpose

A projection of per-user preference settings from `user-pref-service`, specifically the global
default feature importance weights. There is at most one row per user. The BFF uses this table
in the feature importance resolution hierarchy: if a profile has no per-profile `feature_importance`,
these user-level defaults are applied instead.

#### Notes

- **`user_id`**: References `user_auth_schema.accounts.id` (no FK constraint).
  Each user has exactly one settings row.
- **`default_feature_importance`**: Six-dimensional importance weights at the
  user level. Same structure as `profile_projections.feature_importance`. `null` means "use system
  defaults (50 for all dimensions)".

The single-row lookup happens in `ProfileService.get_resolved_importance`.

#### Data Lifecycle

- **Created** when `USER_PREF_SETTINGS_CREATED` is consumed. `ON CONFLICT DO NOTHING`.
- **Updated** when `USER_PREF_SETTINGS_UPDATED` is consumed. `ON CONFLICT (user_id) DO UPDATE`.

---

### `attachment_projections`

#### Purpose

A projection of uploaded document metadata from `user-upload-service`. The BFF heads the S3 object
and computes its content hash before publishing the upload command; `user-upload-service` then
validates the declared content type and size, records the supplied hash, and publishes
`USER_UPLOAD_CREATED`, which creates the row. The BFF uses this table to list and retrieve
attachment metadata for the `/api/v1/attachments` endpoints.

#### Notes

- **`id`**: Value is the `upload_id` generated by the BFF at upload
  initiation time (UUIDv7 from `uuid_utils`).
- **`user_id`**: References the owner.
- **`file_size`**: Capped at 10 MB by the API layer.
- **`storage_key`**: S3 object key: `user-uploads/{user_id}/{upload_id}/{filename}`.
  This key is deterministic and reproducible from the upload metadata. Download URLs are generated
  on demand via presigned GET URLs, not stored here.

Reads are paginated listing by user.

#### Data Lifecycle

- **Created** when `USER_UPLOAD_CREATED` is consumed. `ON CONFLICT DO NOTHING`.
- **Deleted** when `USER_UPLOAD_DELETED` is consumed.

---

### `job_listing_projections`

#### Purpose

A projection of job listing metadata from `job-storage-service` CDC events. This table is the
data source for the job discovery experience: browsing, filtering, and full-text searching listings.
It includes a computed `search_vector` TSVECTOR column for FTS, maintained by a PostgreSQL trigger.

#### Notes

- **`id`**: Value is the canonical `listing_id` from `job-storage-service`.
- **`required_skills`**: Skill names extracted by `job-ingest-enrichment-service`
  and stored in the snapshot.
- **`version`**: Snapshot version counter from `job-storage-service`. Monotonically
  increasing. The BFF does not enforce ordering. The last writer wins.
- **`raw_content_hash`**: SHA-256 of the raw scraped content. Used by
  `job-storage-service` for deduplication; stored here for observability.
- **`search_vector`**: Computed by the `job_listing_search_trigger` on every INSERT
  or UPDATE. Weighted: title (A), company + required_skills (B), description (C). Never written
  directly by application code.

Full-text search backs `GET /api/v1/listings?q=...`; chronological order is the default when no
search query is present, and `company=` filters the listings endpoint.

#### Data Lifecycle

- **Created** when `JOB_LISTING_CREATED` is consumed. `ON CONFLICT (id) DO UPDATE` (upsert with
  mutable fields).
- **Updated** when `JOB_LISTING_UPDATED` is consumed. Same upsert logic.
- **Deleted** when `JOB_LISTING_DELETED` is consumed.

---

### `job_correlation_projections`

#### Purpose

A projection of job-user match results from `job-correlation-evaluation-service`. Each row
represents a scored correlation between one search preference and one job listing, carrying both
the fit score and denormalized listing metadata to avoid joins at query time. The frontend uses
this table to display "My Matches" ranked by fit score.

#### Notes

- **`id`**: Value is the `correlation_id` from
  `job-correlation-evaluation-service`.
- **`user_id`**: Denormalized from `pref_snapshot.user_id` in the event. Not derivable from
  `pref_id` without a cross-table lookup, hence denormalized.
- **`pref_id`**: References `profile_projections.id` (no FK constraint).
- **`listing_id`**: References `job_listing_projections.id` (no FK constraint).
- **`score_breakdown`**: Retained for compatibility but always written as an empty object.
- **`fit_ranking_breakdown`**: Carries the deterministic per-factor explanation from
  `CorrelationEvaluated.fit_ranking_breakdown`.
- **`listing_title`**, **`listing_company`**, **`listing_url`**, **`listing_location`**: Denormalized
  from the `ListingSnapshot` embedded in the `CorrelationEvaluated` event. Allows
  `GET /api/v1/listings/correlations/mine` to return complete match cards without joining
  `job_listing_projections`.

Read paths filter all matches for a user, filter matches by profile (`?pref_id=...`), and order by
fit score on the "My Matches" listing.

#### Constraints & Invariants

- **Unique `(pref_id, listing_id)`**: Enforces exactly one
  correlation per preference-listing pair. Also serves as the idempotency key for the upsert.

#### Data Lifecycle

- **Created or updated** when `JOB_CORRELATION_EVALUATED` is consumed. Upsert via the unique
  constraint. The `fit_score`, `status`, `score_breakdown`, and `fit_ranking_breakdown` are
  overwritten on each evaluation (re-scoring after model updates or feedback incorporation).

---

### `schema_family_projections`

#### Purpose

A projection of document schema families. Schema families group related JSON schemas by
namespace (e.g., a `resume` namespace containing schemas for different resume content structures).
This table is populated by a doc-schema-service that is not yet fully wired in the monorepo;
rows are currently seeded or managed manually.

#### Notes

- **`namespace`**: Logical grouping for the schema family.
- **`is_active`**: Soft-delete flag.

---

### `schema_version_projections`

#### Purpose

Individual versioned JSON schemas associated with a `schema_family_projections` row. The BFF
uses these to present the schema for template variable validation and document content generation
requests. The API uses `DISTINCT ON (family_id) ORDER BY version DESC`
to serve the latest version efficiently.

#### Notes

- **`family_id`**: References `schema_family_projections.id` (no FK constraint).
- **`version`**: A plain integer. Nothing in the BFF writes this table, and no uniqueness or
  ordering guard exists on it; routers order by it descending and also select an exact version
  by equality.
- **`schema_content`**: The full JSON Schema document. Used to validate template data
  before publishing `DOC_CONTENT_GENERATION_REQUESTED`.

---

### `template_projections`

#### Purpose

A projection of Jinja2 HTML document templates from `doc-template-service`. Uses single-table
design: each row is a complete template version, identified by `(namespace, name, version)`.
Multiple rows with the same `(namespace, name)` exist when a template has multiple versions.
The BFF uses this table both to display available templates and to embed template content in
`DOC_TEMPLATE_RENDER_REQUESTED` events (ECST -- `doc-template-service` does not need to look up
the content separately).

#### Notes

- **`id`**: Value is the template version ID from `doc-template-service`.
- **`namespace`**: Template domain grouping (e.g., `resume`, `cover_letter`).
  Validated by the API to match `^[a-z][a-z0-9_-]{0,62}$`.
- **`name`**: Template name within namespace. Must be lowercase alphanumeric.
- **`version`**: Semantic version string (e.g., `1.2.0`). Validated by the API
  against `^\d+\.\d+\.\d+` before publish.
- **`template_content`**: Full Jinja2 HTML source. Stored and forwarded to
  `doc-template-service` in render commands. Maximum 1 MB enforced at the API layer.
- **`content_schema`**: JSON Schema defining the variables the template accepts.
  Parsed from `VersionSnapshot.content_schema_json` at projection time. `null` if the template
  version was created without a schema.
- **`access_scope`**: `PRIVATE` templates are associated with an `owner_id`.
- **`owner_id`**: User who owns a `PRIVATE` template. `null` for system and
  public templates.

Reads use the family listing query (`DISTINCT ON (namespace, name)`) and lookup by namespace+name,
with `created_at` as the secondary ordering key in the latest-version query
(`ORDER BY created_at DESC`).

#### Data Lifecycle

- **Created** when `DOC_TEMPLATE_CREATED` is consumed. `ON CONFLICT (id) DO UPDATE`.
- **Updated** when `DOC_TEMPLATE_UPDATED` is consumed. Same upsert.
- **Deleted** when `DOC_TEMPLATE_DELETED` is consumed. Hard delete.

---

### `document_generation_status`

#### Purpose

Tracks the lifecycle of async document render requests. This is one of the two tables in `bff_schema`
that is not a projection from an upstream service and is written by the BFF API layer
(on `POST /api/v1/documents/generate`): it is updated by the Kafka handlers for
`DOC_CONTENT_GENERATION_COMPLETED`, `DOC_CONTENT_GENERATION_FAILED`, and
`DOC_TEMPLATE_RENDER_COMPLETED`. Correlation-scoped requests, meaning rows whose
`job_correlation_id` is set, move `pending` to `in_progress` on content generation; render
completion moves any non-terminal row to `completed` or `failed`.

#### Notes

- **`request_id`**: UUIDv7 generated at request time. Also used as
  `metadata.correlation_id` in the `DOC_TEMPLATE_RENDER_REQUESTED` event so the completion
  callback can be matched back to this row.
- **`user_id`**: Owner. Used to scope status queries to the requesting user.
- **`template_version_id`**: References `template_projections.id` (no FK constraint).
  Records which template version was used, for observability.
- **`storage_key`**: S3 object key of the rendered document. Populated
  from `DOC_TEMPLATE_RENDER_COMPLETED.storage_key` on success. `null` while pending or on failure.
- **`content_hash`**: SHA-256 of the rendered file. Set on success.
- **`error_message`**: Error detail from `DOC_TEMPLATE_RENDER_COMPLETED.result.error`
  on failure.
- **`completed_at`**: Timestamp of the terminal state transition.

Reads support `GET /api/v1/documents` (list user's documents ordered by `created_at DESC`).

#### Data Lifecycle

- **Created** by `POST /api/v1/documents/generate` synchronously before publishing the Kafka
  command. Initial `status = pending`.
- **Moved to `in_progress`** when `DOC_CONTENT_GENERATION_COMPLETED` is consumed for a row whose
  `job_correlation_id` is set.
- **Moved to `failed`** when `DOC_CONTENT_GENERATION_FAILED` is consumed for a row whose
  `job_correlation_id` is set and whose status is `pending` or `in_progress`.
- **Moved to `completed` or `failed`** when `DOC_TEMPLATE_RENDER_COMPLETED` is consumed, matched
  by `request_id = metadata.correlation_id`, unless the row is already terminal.

---

### `command_requests`

#### Purpose

Records each Kafka command published by the BFF, enabling the frontend to poll for async
completion. This is not a projection. Rows are written synchronously by the API layer before
the command is published to Kafka.
The table implements a state machine with valid transitions from `pending` to `in_progress`,
`completed`, or `failed`, and from `in_progress` to `completed` or `failed`. `completed` and
`failed` are terminal.

Not every command type uses this table: profile operations (`USER_PREF_*`) and template
operations (`DOC_TEMPLATE_*`) record here, but upload operations and feedback commands do not.
Document generation uses `document_generation_status` instead.

#### Notes

- **`request_id`**: The same UUIDv7 embedded in the published Kafka event's
  `metadata.correlation_id`. Enables the frontend to correlate a `202 Accepted` response to a
  later status check.
- **`user_id`**: Owner.
- **`command_type`**: Identifies the command category. Profile commands are tracked via
  `ProfileService._track_command`.
- **`completed_at`**: Populated when the command reaches a terminal
  state.
- **`error_message`**: Failure detail when `status = failed`.

Reads support per-user command history and `ProfileService.get_command_status`.

#### Data Lifecycle

- **Created** synchronously by the API layer immediately before `kafka_client.publish()`. This
  ensures a row exists even if the Kafka publish fails.
- **Updated** when the corresponding upstream event is consumed: template handlers call
  `mark_command_completed`, which only completes rows still in `pending`, while preference
  handlers complete or fail rows in `pending` or `in_progress` directly.

## Source of Truth

- Models: `src/bff_service/db/models/base.py`, `command_tracking.py`, `doc_projections.py`,
  `job_projections.py`, `skill_projections.py`, `user_projections.py`, `auth_revocation.py`
- Migration: `alembic/versions/001_initial_migration.py`
- Migration workflow: [`README.md`](../../../README.md#database-migration-workflow)
