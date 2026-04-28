# User Pref Service

Manages user job target profiles: the structured representation of what jobs a user is looking
for. Each profile specifies desired job titles and keywords, locations, work arrangements, salary
ranges, seniority levels, required and preferred skills, and document tailoring parameters.
Kafka-only, stateful with PostgreSQL and Redis. Publishes enriched preference snapshots to
downstream consumers via transactional outbox.

## Role in the System

This service is the authoritative owner of user search preferences in the Nohiki domain. BFF
publishes command events for every preference lifecycle operation (create, update, delete,
attach/detach uploads, update settings), and this service executes them against its PostgreSQL
schema. No other service modifies preference data.

The preferences this service produces drive job matching. `job-correlation-evaluation-service`
consumes `user-pref.cdc.pref-created` and `user-pref.cdc.pref-updated` to score every stored job
listing against a new or changed preference. `job-query-composition-service` consumes these same
events to maintain the query parameters used during job discovery. `bff-service` maintains
projection tables from CDC events to serve the preferences API. Because every CDC event carries
the full `SearchPrefSnapshot` (including embeddings), none of these consumers need to query back
to this service.

A preference is not published until it is fully enriched. When BFF creates a preference with
skills listed, this service must first resolve those skills to canonical IDs via
`skill-graph-service`, then compute MUVERA/SPARSE/COLBERT query embeddings via
`ml-gateway-service`. Only after both callbacks arrive does this service mark enrichment complete
and publish the CDC event. This enrichment gate keeps the ECST snapshot clean: downstream
consumers always receive fully resolved skill IDs and retrieval-ready embedding vectors.

## Event-Driven Integration

### Events Consumed

- **`user-pref.cmd.create-requested`** (`PrefCreateRequested`): Received from `bff-service` when
  a user creates a new job target profile. The handler persists the raw profile to PostgreSQL
  (idempotent via `request_id` unique index), then determines the enrichment path: if the command
  includes skills, it publishes to `skill.cmd.normalization-requested`; if it includes only search
  keywords (no skills), it publishes directly to `ml.cmd.embedding-requested`; if neither, it
  marks enrichment complete immediately and publishes the created CDC event. Consumer group:
  `user-pref-service-commands`.

- **`user-pref.cmd.update-requested`** (`PrefUpdateRequested`): Received from `bff-service` when
  a user edits a preference. The handler resets `is_enrichment_complete` to `false`, applies
  field-level updates (only fields listed in `updated_fields` are written), then follows the same
  skill/keyword/empty enrichment decision tree as create. Consumer group:
  `user-pref-service-commands`.

- **`user-pref.cmd.delete-requested`** (`PrefDeleteRequested`): Deletes the named preference.
  The handler is idempotent: if the preference is already absent, it returns without error.
  Consumer group: `user-pref-service-commands`.

- **`user-pref.cmd.attach-upload.v1`** (`PrefAttachUploadRequested`): Associates an uploaded
  document (resume, portfolio, etc.) with a preference. After the association is written to
  `search_pref_uploads`, the handler republishes a `user-pref.cdc.pref-updated` event so
  downstream services see the new attachment list. Consumer group: `user-pref-service-commands`.

- **`user-pref.cmd.detach-upload.v1`** (`PrefDetachUploadRequested`): Removes a document
  association from a preference. Same update-and-republish pattern as attach. Consumer group:
  `user-pref-service-commands`.

- **`user-pref.cmd.settings-update-requested`** (`UserPrefSettingsUpdateRequested`): Upserts
  user-level preference defaults (timezone, locale, default feature importance weights). Publishes
  `user-pref.cdc.settings-created` or `user-pref.cdc.settings-updated` via outbox depending on
  whether the row is new. Consumer group: `user-pref-service-commands`.

- **`user-pref.cmd.pref-importance-update-requested`** (`PrefFeatureImportanceUpdateRequested`):
  Updates the L2R feature importance weights on a specific preference (how much the user wants
  skill match vs. location vs. salary weighted). Publishes `user-pref.cdc.pref-updated` via
  outbox. Consumer group: `user-pref-service-commands`.

- **`user-pref.sys.skill-callback.v1`** (`SkillNormalizationCallback`): Callback from
  `skill-graph-service` after skill normalization completes. On success, the handler persists the
  full `SkillNormalizationResult` to the profile row (`user_skill_ids`, `user_skills_data`,
  `user_skills_embedding`), then either requests query embedding (if the profile has query text)
  or publishes the lifecycle event immediately. On error, the handler records the downstream-
  declared failure and acknowledges the callback. Consumer group: `user-pref-skill-completed-primary`.

- **`user-pref.sys.embedding-callback.v1`** (`EmbeddingCallback`): Callback from
  `ml-gateway-service` after query embedding completes. On success, the handler persists the DENSE
  vector to `query_embedding` and all other retrieval vectors (MUVERA, SPARSE, COLBERT) to
  `query_artifacts_data`, marks `is_enrichment_complete = true`, loads the user skills previously
  persisted by the skill callback, and publishes the lifecycle event. Consumer group:
  `user-pref-embedding-callback-primary`.

- **`user-auth.cdc.account-deleted.v1`** (`AccountDeleted`): Published by `user-auth-service`
  when a user account is deleted. This service bulk-deletes all preferences and user-level
  settings for that user. Consumer group: `user-pref-service`.

- **`user-upload.cdc.upload-deleted.v1`** (`UploadDeleted`): Published by `user-upload-service`
  when a document is deleted. This service removes the corresponding rows from
  `search_pref_uploads` across all preferences. Consumer group: `user-pref-service`.

### Events Published

- **`user-pref.cdc.pref-created.v1`** (`PrefCreated`): Published after a preference is fully
  enriched (both skill normalization and query embedding callbacks received, or immediately if no
  skills/keywords are present). Carries the complete `SearchPrefSnapshot` including canonical
  skill IDs, embedding vectors, upload references, and all targeting criteria. Published via
  transactional outbox. Consumed by `job-correlation-evaluation-service`,
  `job-query-composition-service`, and `bff-service`.

- **`user-pref.cdc.pref-updated.v1`** (`PrefUpdated`): Published after a preference update
  completes enrichment, or immediately on attachment changes and feature importance updates.
  Carries the same full `SearchPrefSnapshot`. Published via transactional outbox. Same consumers
  as above.

- **`user-pref.cdc.pref-deleted.v1`** (`PrefDeleted`): Published when a preference is deleted
  (either by explicit user command or account deletion cascade). Carries `pref_id` and `user_id`.
  Published via transactional outbox. Consumed by `job-correlation-evaluation-service` and
  `bff-service` to remove associated data.

- **`user-pref.cdc.settings-created.v1`** (`UserPrefSettingsCreated`): Published when user-level
  preference settings are created for the first time. Published via transactional outbox.
  Consumed by `bff-service`.

- **`user-pref.cdc.settings-updated.v1`** (`UserPrefSettingsUpdated`): Published when user-level
  preference settings are updated. Published via transactional outbox. Consumed by `bff-service`.

- **`skill.cmd.normalization-requested.v1`** (`SkillNormalizationRequested`): Published directly
  (not via outbox) to request skill normalization from `skill-graph-service`. Carries
  `callback_topic=user-pref.sys.skill-callback.v1` and a serialized `PrefEmbeddingState` in
  `caller_context` so the callback handler can identify the target preference without a DB lookup.

- **`ml.cmd.embedding-requested.v1`** (`EmbeddingRequested`): Published directly via
  `EmbeddingPublisher` to request MUVERA/SPARSE/COLBERT embedding computation from
  `ml-gateway-service`. Carries `callback_topic=user-pref.sys.embedding-callback.v1` and the
  same `PrefEmbeddingState` context. Used both after skill normalization completes (to embed the
  combined skill+keyword query text) and directly (when a preference has only search keywords and
  no skills).

### Notable Patterns

#### Two-Stage Sequential Callback (Without Saga)

When a preference has skills, enrichment proceeds in two sequential Kafka round-trips:

1. **Stage 1 -- Skill normalization**: This service publishes to
   `skill.cmd.normalization-requested.v1`. When `skill-graph-service` replies on
   `user-pref.sys.skill-callback.v1`, the callback handler persists the full skill data
   (canonical IDs, skills embedding vector, `UserSkillEntry` list) to the `search_prefs` row,
   then publishes the embedding request.

2. **Stage 2 -- Query embedding**: This service publishes to `ml.cmd.embedding-requested.v1`.
   When `ml-gateway-service` replies on `user-pref.sys.embedding-callback.v1`, the callback
   handler persists the retrieval vectors, loads the skills already written to the DB in Stage 1,
   marks enrichment complete, and publishes the CDC event.

This is sequential chaining, not a saga. A saga collects concurrent, independent callbacks and
merges their results once all arrive. Here the callbacks are intentionally ordered: the skill
normalization result feeds the embedding request's query text (skill names concatenated with
keywords). Running them concurrently would require carrying the full skill list in Kafka message
state; instead, Stage 1 persists to the DB and Stage 2 reads from there. The `PrefEmbeddingState`
carried in `caller_context` stays at ~80 bytes regardless of how many skills the user has.

#### Enrichment Completeness Gate

`is_enrichment_complete` on `search_prefs` gates CDC publication. A preference awaiting callbacks
has `is_enrichment_complete = false`. If the same command is redelivered (Kafka at-least-once),
the handler checks this flag: if `true`, the command is already fully processed and the handler
returns immediately. If `false`, the handler skips DB creation (the row already exists via
`request_id` lookup) and re-enters the enrichment flow from the beginning.

#### Transactional Outbox

All CDC events are written to the `outbox` table in the same database transaction as the domain
write, using `nohiki-db-utils`'s `OutboxWriter`. Debezium's PostgreSQL connector captures outbox
rows from the WAL and routes them to the appropriate Kafka topics. This guarantees that a
preference update and its CDC event are always published atomically, so no in-flight updates are
ever lost to a crash.

#### ECST Snapshots

Every CDC event carries the complete `SearchPrefSnapshot`, not just changed fields. This means
`job-correlation-evaluation-service` always has the full preference state:
embeddings, skills, locations, salary, and work arrangement. It never needs to query this service for additional data.
The snapshot is built by `build_profile_snapshot()`, which assembles the proto from the DB row
after all enrichment data has been flushed.

## State & Persistence

### Database

Schema `user_pref_schema` stores user job target profiles and their enrichment state. The
`search_prefs` table holds the full preference definition alongside skill normalization results
and query embedding vectors. The `search_pref_uploads` junction table tracks which uploaded
documents (resumes, portfolios) are associated with each preference. The `user_pref_settings`
table holds user-level defaults that apply across all preferences.

See [DATABASE.md](./DATABASE.md) for complete schema documentation.

### Redis

Redis backs the geocoding cache from `nohiki-geo-utils`. When a preference includes physical
locations, the service geocodes them using GeoPy Nominatim. Geocoding results are cached in Redis
under `user-pref-service:*` keys with a TTL managed by `nohiki-geo-utils`. This avoids repeated
Nominatim lookups for frequently used cities.

## Key Design Patterns

### Completion-Aware Command Idempotency

The create handler uses `request_id` as the idempotency key. On each delivery, it first queries
`search_prefs` by `request_id`. If no row exists, it creates one. If a row exists with
`is_enrichment_complete = true`, the command is done and the handler returns. If a row exists with
`is_enrichment_complete = false`, enrichment is in progress or failed partway through, so the
handler re-enters the enrichment flow. This pattern handles Kafka redelivery, consumer restarts,
and partial enrichment failures without duplicating preferences or losing events.

### Field-Level Patch Updates

The update handler uses an `updated_fields` set from the command to apply only the fields the BFF
explicitly changed. This prevents overwriting embedding vectors or skill data when only the
preference name was changed, and avoids triggering unnecessary re-enrichment.

## Configuration

Settings use `USER_PREF_` as the environment variable prefix. The service composes
`DatabaseMixin`, `KafkaMixin`, `RedisMixin`, and `ManifestMixin`.

Key non-obvious settings:

- **`USER_PREF_DATABASE__SCHEMA`**: Defaults to `user_pref_schema`. Overriding this changes the
  PostgreSQL schema used for all tables.
- **`USER_PREF_MAX_KEYWORDS`**: Maximum number of search keywords allowed per preference
  (default: 50). Enforced at the service layer.
- **`USER_PREF_MAX_LOCATIONS`**: Maximum number of locations per preference (default: 20).
- **`USER_PREF_SKILL_NORMALIZATION_ENABLED`**: When `false`, the service skips the skill
  normalization request and proceeds directly to embedding or immediate publication. Useful for
  local development without `skill-graph-service` running.
- **`USER_PREF_GEOCODING_ENABLED`**: When `false`, location geocoding is skipped.
- **`USER_PREF_MANIFEST_PATH`**: Path to the `SemanticRepresentationManifest` file used to
  determine the Qdrant collection version for embedding requests. Must match the manifest used
  by `ml-gateway-service` and `ml-compute-service`.
- **`USER_PREF_KAFKA__CONSUMER_GROUP`**: Base consumer group name. Command handlers append
  `-commands` to form `user-pref-service-commands`.

## Development

### Local Setup

```bash
uv sync
alembic upgrade head
```

Requires PostgreSQL with the `uuidv7()` extension installed. Start the full infrastructure stack
before running the service:

```bash
just infra-up
```

`skill-graph-service` and `ml-gateway-service` must be running for end-to-end preference creation
with enrichment. Set `USER_PREF_SKILL_NORMALIZATION_ENABLED=false` and omit skills from commands
to bypass the callback flow during local development.

### Testing

```bash
just test user-pref-service
just test-cov user-pref-service
```

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise
uv run ty check
```
