# BFF Service Database Schema

Schema `bff_schema` is a read-model database for the Backend-for-Frontend service. Every table
in this schema is a **projection** -- a denormalized, eventually consistent copy of data owned by
upstream services and delivered via Kafka CDC or fact events. The BFF writes to these tables only
from its Kafka event handlers; API routers read from them.

## Entity Overview

| Table | Purpose |
|-------|---------|
| `account_projections` | User account state projected from `user-auth-service` |
| `profile_projections` | Job search preference profiles from `user-pref-service` |
| `user_pref_settings_projections` | Per-user default L2R feature importance weights from `user-pref-service` |
| `attachment_projections` | Uploaded document metadata from `user-upload-service` |
| `job_listing_projections` | Job listing metadata with FTS support from `job-storage-service` |
| `job_correlation_projections` | Job-profile match scores from `job-correlation-evaluation-service` |
| `schema_family_projections` | Document schema families (no current upstream source, seeded manually) |
| `schema_version_projections` | Versioned JSON schemas for document content validation |
| `template_projections` | Jinja2 HTML document templates from `doc-template-service` |
| `document_generation_status` | Async render request lifecycle tracking (not a projection) |
| `command_requests` | Published command idempotency tracking (not a projection) |

Note: The migration also creates standard `outbox` and `processed_events` tables via shared
migration helpers from `nohiki-db-utils`. These support the outbox pattern infrastructure but the
BFF does not use a transactional outbox for its command publishing.

All user and job projection tables reference other services' data by UUID only: there are no
foreign key constraints across schema boundaries. A `profile_projections.user_id` references
`user_auth_schema.accounts.id` by convention, not by database constraint.

## Table Details

### `account_projections`

#### Purpose

A projection of user account state, populated from `USER_AUTH_ACCOUNT_UPDATED` events published
by `user-auth-service`. The BFF uses this table to resolve user identity in the `/api/v1/session`
adjacent workflows where account metadata is needed beyond what the JWT carries.

#### Key Columns

- **`id`** (`UUID`): Primary key. Value is the canonical user ID from `user_auth_schema.accounts`;
  not BFF-generated. Carries the UUIDv7 encoding from the originating service.
- **`email`** (`VARCHAR(255)`): UNIQUE constraint. The handler deletes stale rows with the same
  email but a different `id` before upserting. This handles re-registration with the same email address.
- **`is_active`** (`BOOLEAN`): Set from the `AccountSnapshot.is_active` field. Defaults to `true`.
- **`email_verified`** (`BOOLEAN`): Tracks email verification state. Defaults to `false`.
- **`updated_at`** (`TIMESTAMPTZ`): Replicated from the upstream snapshot; reflects the timestamp
  of the last mutation in `user-auth-service`, not the projection update time.

#### Indexes

No additional indexes beyond the primary key and unique email constraint. The table is accessed
only by `id` (from JWT `sub` claim) in production usage.

#### Constraints & Invariants

- **UNIQUE on `email`**: Enforced at the database level. The handler explicitly cleans up email
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

#### Key Columns

- **`id`** (`UUID`): Primary key. Value is the `pref_id` from `user-pref-service`.
- **`user_id`** (`UUID`): References `user_auth_schema.accounts.id` (no FK constraint --
  cross-schema). Indexed for efficient per-user profile queries.
- **`search_keywords`** (`TEXT[]`): PostgreSQL array of keyword strings used for job query
  composition by `job-query-composition-service`.
- **`disallowed_keywords`** (`TEXT[]`): Keywords that disqualify a listing from matching.
- **`work_arrangements`** (`work_arrangement_enum[]`): Array of the `work_arrangement_enum` type
  (`UNSPECIFIED`, `ON_SITE`, `HYBRID`, `REMOTE`). Stored as a native PostgreSQL ENUM array.
- **`notification_threshold`** (`FLOAT`): Stored as a 0.0-1.0 ratio. The upstream source is a
  0-100 integer from `SearchPrefSnapshot.notification_config.threshold`; the handler converts it
  with `percent_to_ratio`.
- **`auto_tailor_threshold`** (`FLOAT`, nullable): Score above which automatic document tailoring
  triggers. Also a 0.0-1.0 ratio converted from the upstream integer percentage.
- **`feature_importance`** (`JSONB`, nullable): Per-profile L2R feature importance overrides set
  via `PUT /api/v1/profiles/{pref_id}/feature-importance`. Keys: `skill_match_importance`,
  `location_importance`, `work_arrangement_importance`, `experience_importance`,
  `salary_importance`, `recency_importance` -- all integers 0-100.
- **`commute_preferences`** (`JSONB`, nullable): Serialized from `CommutePreferences` proto.
  Structure: `{"acceptable_modes": ["DRIVING", "TRANSIT"], "max_commute_minutes": 45, "ideal_commute_minutes": 20}`.
- **`tailoring_schema_id`** (`UUID`, nullable): Migration-only column (not yet used in ORM model).

#### Indexes

- **`ix_profile_projections_user_id`** on `user_id`: Supports `SELECT ... WHERE user_id = $1`
  in `ProfileService.list_profiles` -- the primary read pattern for this table.

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

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key, generated server-side by the BFF migration (`gen_random_uuid()`
  at migration time, `uuidv7()` in production).
- **`user_id`** (`UUID`): UNIQUE. References `user_auth_schema.accounts.id` (no FK constraint).
  Indexed and uniqueness-constrained so each user has exactly one settings row.
- **`default_feature_importance`** (`JSONB`, nullable): Six-dimensional importance weights at the
  user level. Same structure as `profile_projections.feature_importance`. `null` means "use system
  defaults (50 for all dimensions)".
- **`preferred_timezone`** (`VARCHAR(50)`, nullable): IANA timezone string (e.g., `America/New_York`).
- **`preferred_locale`** (`VARCHAR(10)`, nullable): BCP 47 locale code (e.g., `en-US`).

#### Indexes

- **`ix_user_pref_settings_projections_user_id`** on `user_id`: Supports the single-row lookup
  in `ProfileService.get_resolved_importance`.

#### Data Lifecycle

- **Created** when `USER_PREF_SETTINGS_CREATED` is consumed. `ON CONFLICT DO NOTHING`.
- **Updated** when `USER_PREF_SETTINGS_UPDATED` is consumed. `ON CONFLICT (user_id) DO UPDATE`.

---

### `attachment_projections`

#### Purpose

A projection of uploaded document metadata from `user-upload-service`. Rows are created after
`user-upload-service` validates the file (verifies S3 existence, records content hash) and
publishes `USER_UPLOAD_CREATED`. The BFF uses this table to list and retrieve attachment metadata
for the `/api/v1/attachments` endpoints.

#### Key Columns

- **`id`** (`UUID`): Primary key. Value is the `upload_id` generated by the BFF at upload
  initiation time (UUIDv7 from `uuid_utils`).
- **`user_id`** (`UUID`): References the owner. Indexed for per-user queries.
- **`filename`** (`VARCHAR(255)`): Original filename as declared by the client.
- **`content_type`** (`VARCHAR(100)`): MIME type (e.g., `application/pdf`).
- **`file_size`** (`INTEGER`): Byte count. Capped at 10 MB by the API layer.
- **`storage_key`** (`VARCHAR(500)`): S3 object key: `user-uploads/{user_id}/{upload_id}/{filename}`.
  This key is deterministic and reproducible from the upload metadata. Download URLs are generated
  on demand via presigned GET URLs, not stored here.

#### Indexes

- **`ix_attachment_projections_user_id`** on `user_id`: Supports paginated listing by user.

#### Data Lifecycle

- **Created** when `USER_UPLOAD_CREATED` is consumed. `ON CONFLICT DO NOTHING`.
- **Deleted** when `USER_UPLOAD_DELETED` is consumed.

---

### `job_listing_projections`

#### Purpose

A projection of job listing metadata from `job-storage-service` CDC events. This table is the
data source for the job discovery experience: browsing, filtering, and full-text searching listings.
It includes a computed `search_vector` TSVECTOR column for FTS, maintained by a PostgreSQL trigger.

#### Key Columns

- **`id`** (`UUID`): Primary key. Value is the canonical `listing_id` from `job-storage-service`.
- **`listing_url`** (`VARCHAR(2048)`): The canonical URL of the original job posting.
- **`source`** (`VARCHAR(50)`): Scraping source identifier (e.g., `LINKEDIN`, `INDEED`). Stored
  as the enum name string from the `ListingSource` protobuf enum.
- **`title`** (`VARCHAR(500)`): Job title, included in FTS at weight A (highest relevance).
- **`required_skills`** (`TEXT[]`): Array of skill names extracted by `job-ingest-enrichment-service`
  and stored in the snapshot. Included in FTS at weight B.
- **`version`** (`INTEGER`): Snapshot version counter from `job-storage-service`. Monotonically
  increasing. The BFF does not enforce ordering. The last writer wins.
- **`raw_content_hash`** (`VARCHAR(64)`): SHA-256 of the raw scraped content. Used by
  `job-storage-service` for deduplication; stored here for observability.
- **`search_vector`** (`TSVECTOR`): Computed by the `job_listing_search_trigger` on every INSERT
  or UPDATE. Weighted: title (A), company + required_skills (B), description (C). Never written
  directly by application code.

#### Indexes

- **`ix_job_listing_projections_search`** (`search_vector`) using GIN: Supports `search_vector @@ tsquery`
  full-text search. Used by `GET /api/v1/listings?q=...`.
- **`ix_job_listing_projections_created_at`** (`created_at`): Supports chronological default
  listing order when no search query is present.
- **`ix_job_listing_projections_company`** (`company_name`): Supports the `company=` filter
  parameter on the listings endpoint.

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

#### Key Columns

- **`id`** (`UUID`): Primary key. Value is the `correlation_id` from
  `job-correlation-evaluation-service`.
- **`user_id`** (`UUID`): Denormalized from `pref_snapshot.user_id` in the event. Indexed for
  efficient per-user queries. Not derivable from `pref_id` without a cross-table lookup, hence
  denormalized.
- **`pref_id`** (`UUID`): References `profile_projections.id` (no FK constraint).
- **`listing_id`** (`UUID`): References `job_listing_projections.id` (no FK constraint).
- **`fit_score`** (`INTEGER`): Match score 0-100 (integer percentage). Indexed for ordered queries.
- **`status`** (`VARCHAR(30)`): Correlation pipeline status. Values: `pending`, `in_progress`,
  `completed`, `failed`. Defaults to `pending`.
- **`score_breakdown`** (`JSONB`): Per-dimension scoring metadata from `CorrelationEvaluated.correlation_metadata`.
  Structure is defined by `job-correlation-evaluation-service` and surfaced as-is.
- **`listing_title`**, **`listing_company`**, **`listing_url`**, **`listing_location`**: Denormalized
  from the `ListingSnapshot` embedded in the `CorrelationEvaluated` event. Allows
  `GET /api/v1/listings/correlations/mine` to return complete match cards without joining
  `job_listing_projections`.

#### Indexes

- **`ix_job_correlation_projections_user_id`** on `user_id`: Primary read path filter (all matches
  for a user).
- **`ix_job_correlation_projections_pref_id`** on `pref_id`: Supports filtering matches by
  profile (`?pref_id=...`).
- **`ix_job_correlation_projections_fit_score`** on `fit_score`: Supports `ORDER BY fit_score DESC`
  on the "My Matches" listing.

#### Constraints & Invariants

- **UNIQUE `uq_correlation_pref_listing`** on `(pref_id, listing_id)`: Enforces exactly one
  correlation per preference-listing pair. Also serves as the idempotency key for
  `ON CONFLICT ON CONSTRAINT uq_correlation_pref_listing DO UPDATE`.

#### Data Lifecycle

- **Created or updated** when `JOB_CORRELATION_EVALUATED` is consumed. Upsert via the unique
  constraint. The `fit_score`, `status`, and `score_breakdown` are overwritten on each evaluation
  (re-scoring after model updates or feedback incorporation).

---

### `schema_family_projections`

#### Purpose

A projection of document schema families. Schema families group related JSON schemas by
namespace (e.g., a `resume` namespace containing schemas for different resume content structures).
This table is populated by a doc-schema-service that is not yet fully wired in the monorepo;
rows are currently seeded or managed manually.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key.
- **`namespace`** (`VARCHAR(100)`): Logical grouping for the schema family. Indexed for namespace
  filtering. Example: `resume`, `cover_letter`.
- **`name`** (`VARCHAR(255)`): Human-readable name within the namespace.
- **`is_active`** (`BOOLEAN`): Soft-delete flag. Defaults to `true`.

#### Indexes

- **`ix_schema_family_projections_namespace`** on `namespace`: Supports namespace-filtered listing.

---

### `schema_version_projections`

#### Purpose

Individual versioned JSON schemas associated with a `schema_family_projections` row. The BFF
uses these to present the schema for template variable validation and document content generation
requests. Versions are integers (1, 2, 3, and so on). The API uses `DISTINCT ON (family_id) ORDER BY version DESC`
to serve the latest version efficiently.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key.
- **`family_id`** (`UUID`): References `schema_family_projections.id` (no FK constraint). Indexed.
- **`version`** (`INTEGER`): Monotonically increasing version number within the family.
- **`schema_content`** (`JSONB`): The full JSON Schema document. Used to validate template data
  before publishing `DOC_CONTENT_GENERATION_REQUESTED`.
- **`is_active`** (`BOOLEAN`): Defaults to `true`.

#### Indexes

- **`ix_schema_version_projections_family_id`** on `family_id`: Supports per-family version
  listing and the `DISTINCT ON` latest-version query.

---

### `template_projections`

#### Purpose

A projection of Jinja2 HTML document templates from `doc-template-service`. Uses single-table
design: each row is a complete template version, identified by `(namespace, name, version)`.
Multiple rows with the same `(namespace, name)` exist when a template has multiple versions.
The BFF uses this table both to display available templates and to embed template content in
`DOC_TEMPLATE_RENDER_REQUESTED` events (ECST -- `doc-template-service` does not need to look up
the content separately).

#### Key Columns

- **`id`** (`UUID`): Primary key. Value is the template version ID from `doc-template-service`.
- **`namespace`** (`VARCHAR(100)`): Template domain grouping (e.g., `resume`, `cover_letter`).
  Validated by the API to match `^[a-z][a-z0-9_-]{0,62}$`.
- **`name`** (`VARCHAR(255)`): Template name within namespace. Must be lowercase alphanumeric.
- **`version`** (`VARCHAR(50)`): Semantic version string (e.g., `1.2.0`). Validated by the API
  against `^\d+\.\d+\.\d+` before publish.
- **`template_content`** (`TEXT`): Full Jinja2 HTML source. Stored and forwarded to
  `doc-template-service` in render commands. Maximum 1 MB enforced at the API layer.
- **`content_schema`** (`JSONB`, nullable): JSON Schema defining the variables the template accepts.
  Parsed from `VersionSnapshot.content_schema_json` at projection time. `null` if the template
  version was created without a schema.
- **`access_scope`** (`access_scope_enum`): PostgreSQL ENUM (`UNSPECIFIED`, `PUBLIC`, `PRIVATE`,
  `SYSTEM`). Defaults to `PUBLIC`. `PRIVATE` templates are associated with an `owner_id`.
- **`owner_id`** (`UUID`, nullable): User who owns a `PRIVATE` template. `null` for system and
  public templates.
- **`is_active`** (`BOOLEAN`): Defaults to `true`.

#### Indexes

- **`ix_template_projections_namespace_name`** on `(namespace, name)`: Supports the family
  listing query (`DISTINCT ON (namespace, name)`) and lookup by namespace+name.
- **`ix_template_projections_created_at`** on `created_at`: Used as the secondary ordering key
  in the latest-version query (`ORDER BY created_at DESC`).

#### Data Lifecycle

- **Created** when `DOC_TEMPLATE_CREATED` is consumed. `ON CONFLICT (id) DO UPDATE`.
- **Updated** when `DOC_TEMPLATE_UPDATED` is consumed. Same upsert.
- **Deleted** when `DOC_TEMPLATE_DELETED` is consumed. Hard delete.

---

### `document_generation_status`

#### Purpose

Tracks the lifecycle of async document render requests. This is the only table in `bff_schema`
that is not a projection from an upstream service: it is written directly by the BFF API layer
(on `POST /api/v1/documents/generate`) and updated by the Kafka handler for
`DOC_TEMPLATE_RENDER_COMPLETED`. It implements a state machine: `pending → in_progress → completed`
or `pending → in_progress → failed`.

#### Key Columns

- **`request_id`** (`UUID`): Primary key. UUIDv7 generated at request time. Also used as
  `metadata.correlation_id` in the `DOC_TEMPLATE_RENDER_REQUESTED` event so the completion
  callback can be matched back to this row.
- **`user_id`** (`UUID`): Owner. Indexed. Used to scope status queries to the requesting user.
- **`template_version_id`** (`UUID`): References `template_projections.id` (no FK constraint).
  Records which template version was used, for observability.
- **`output_format`** (`VARCHAR(10)`): `pdf`, `html`, or `png`. Set at request time.
- **`status`** (`VARCHAR(20)`): State machine status. Valid transitions:
  `pending → in_progress → completed` or `failed`. Defaults to `pending`.
- **`storage_key`** (`VARCHAR(512)`, nullable): S3 object key of the rendered document. Populated
  from `DOC_TEMPLATE_RENDER_COMPLETED.storage_key` on success. `null` while pending or on failure.
- **`file_size`** (`BIGINT`, nullable): Byte count of the rendered file. Set on success.
- **`content_hash`** (`VARCHAR(64)`, nullable): SHA-256 of the rendered file. Set on success.
- **`error_message`** (`TEXT`, nullable): Error detail from `DOC_TEMPLATE_RENDER_COMPLETED.result.error`
  on failure.
- **`completed_at`** (`TIMESTAMPTZ`, nullable): Timestamp of the terminal state transition.

#### Indexes

- **`ix_document_generation_status_user_id`** on `user_id`: Supports `GET /api/v1/documents`
  (list user's documents ordered by `created_at DESC`).

#### Data Lifecycle

- **Created** by `POST /api/v1/documents/generate` synchronously before publishing the Kafka
  command. Initial `status = pending`.
- **Updated** when `DOC_TEMPLATE_RENDER_COMPLETED` is consumed, matched by
  `request_id = metadata.correlation_id`.

---

### `command_requests`

#### Purpose

Records each Kafka command published by the BFF, enabling the frontend to poll for async
completion. This is not a projection. Rows are written synchronously by the API layer before
the command is published to Kafka. The table implements a state machine with transitions
`pending → in_progress → completed` or `failed`.

Not every command type uses this table: profile operations (`USER_PREF_*`) and template
operations (`DOC_TEMPLATE_*`) record here, but upload operations and feedback commands do not.
Document generation uses `document_generation_status` instead.

#### Key Columns

- **`request_id`** (`UUID`): Primary key. The same UUIDv7 embedded in the published Kafka event's
  `metadata.correlation_id`. Enables the frontend to correlate a `202 Accepted` response to a
  later status check.
- **`user_id`** (`UUID`): Owner. Indexed for per-user command history queries.
- **`command_type`** (`VARCHAR(50)`): Identifies the command category. Values observed in code:
  `template_create`, `template_version_add`, `template_delete`. Profile commands are tracked via
  `ProfileService._track_command`.
- **`status`** (`VARCHAR(20)`): State machine status. Valid transitions:
  `pending → {in_progress, completed, failed}`, `in_progress → {completed, failed}`.
  Defaults to `pending`.
- **`completed_at`** (`TIMESTAMPTZ`, nullable): Populated when the command reaches a terminal
  state.
- **`error_message`** (`TEXT`, nullable): Failure detail when `status = failed`.

#### Indexes

- **`ix_command_requests_user_id`** on `user_id`: Supports per-user command history and
  `ProfileService.get_command_status`.

#### Data Lifecycle

- **Created** synchronously by the API layer immediately before `kafka_client.publish()`. This
  ensures a row exists even if the Kafka publish fails.
- **Updated** when the upstream service publishes a CDC event that the BFF's projection handler
  calls `mark_command_completed` to transition the status.

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

The `001_initial_migration.py` also creates the `outbox` and `processed_events` tables via
helpers from `nohiki-db-utils.outbox_migrations` and `nohiki-db-utils.idempotency_migrations`.
These are infrastructure tables used by the shared Kafka client library, not BFF application tables.
