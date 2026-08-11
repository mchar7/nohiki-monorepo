# User Pref Service Database Design

Schema `user_pref_schema` stores user job target profiles and their enrichment state, including
raw preference data, normalized skill mappings, query embedding vectors, and document attachment
associations.

`search_prefs` is the central entity. Preference deletion automatically removes all attachment
associations. `user_pref_settings` references a `user_id` owned by another schema:
`user-auth-service` owns the authoritative user record, but this service cleans up
its own data when it receives `user-auth.cdc.account-deleted.v1`. The `outbox` table captures CDC
events transactionally alongside domain writes; Debezium publishes them to Kafka from the
PostgreSQL WAL.

## `search_prefs`

### Purpose

Stores one row per user job target profile. A profile is the complete targeting specification for
a job search: what titles to look for, where, at what seniority and salary, with what required
skills. The row also holds the results of the two-stage enrichment pipeline: canonical skill IDs
and the skills embedding vector from `skill-graph-service`, and query retrieval embedding vectors
from `ml-gateway-service`.

Per-preference feature importance controls how much weight `job-correlation-evaluation-service`
gives each signal for this specific preference. User skill entries are persisted during the skill
callback stage so the embedding callback stage can load them from the DB rather than carrying them
in Kafka state. The collection version recorded at embedding time is used alongside the content
hash to detect stale embeddings when the encoding manifest changes. Inactive preferences are
retained but excluded from correlation scoring.

### Access Patterns

- Supports all per-user listing queries, including the BFF's "list my preferences" read path and
  account-deletion bulk delete.
- Supports the idempotency check in the create handler: looking up an existing preference by the
  BFF's `request_id` before deciding whether to create or re-enter enrichment.
- Supports queries that only need active preferences, avoiding full scans over inactive rows.

### Constraints & Invariants

Uniqueness on `request_id` prevents duplicate preference creation when the BFF command is
redelivered. The create handler uses this to distinguish "first delivery" from "redelivery of
in-progress enrichment".

### Data Lifecycle

- **Created** when `user-pref.cmd.create-requested` is consumed and no row with that `request_id`
  exists
- **Updated** during enrichment (the skill callback stage persists normalized skills, the
  embedding callback stage persists query retrieval vectors)
- **Updated** when `user-pref.cmd.update-requested`, `user-pref.cmd.attach-upload.v1`,
  `user-pref.cmd.detach-upload.v1`, or `user-pref.cmd.pref-importance-update-requested` is
  consumed
- **Deleted** (bulk) when `user-auth.cdc.account-deleted.v1` is consumed: all rows for that
  `user_id` are deleted in a single `DELETE WHERE user_id = ?`
- **Deleted** (single) when `user-pref.cmd.delete-requested` is consumed

---

## `search_pref_uploads`

### Purpose

Junction table linking a search preference to an uploaded document stored in
`user-upload-service`. Tracks whether each upload is an "example" (a resume or work sample used
for tailoring) or "additional_context" (supplementary materials). Upload associations are
automatically removed when the preference is deleted. The upload category determines how
`doc-content-service` uses the document during tailoring.

### Constraints & Invariants

One row per preference-upload pair serves as the idempotency key for the attach handler and
prevents duplicate associations. The attach handler updates the upload type on conflict rather
than failing, so re-categorizing an already-attached upload is idempotent.

### Data Lifecycle

- **Created** when `user-pref.cmd.attach-upload.v1` is consumed
- **Updated** (`upload_type` only) when the same upload is re-attached with a different category
- **Deleted** when `user-pref.cmd.detach-upload.v1` is consumed, or when the parent
  `search_prefs` row is deleted (cascade), or when `user-upload.cdc.upload-deleted.v1` is
  consumed (bulk delete by `upload_id`)

---

## `user_pref_settings`

### Purpose

Stores per-user defaults that apply across all of a user's search preferences unless overridden
at the preference level. Owned by this service (not `user-auth-service`) because these are
job-search preferences, not account settings. Default feature weights apply to all preferences
that do not set their own `feature_importance`. The preferred timezone is used for display-layer
date formatting, and the preferred locale for currency and number formatting in notifications.

### Access Patterns

Supports the settings lookup on every `user-pref.cmd.settings-update-requested` command because
the upsert reads the current row first.

### Constraints & Invariants

One settings row per user, enforced at both the DB level and via the upsert handler.

### Data Lifecycle

- **Created** the first time `user-pref.cmd.settings-update-requested` is consumed for a given
  user
- **Updated** on subsequent `user-pref.cmd.settings-update-requested` events; only fields listed
  in `updated_fields` are written
- **Deleted** when `user-auth.cdc.account-deleted.v1` is consumed (bulk delete on `user_id`)

---

## Outbox Table

This service uses the transactional outbox pattern for guaranteed event delivery. All CDC events
are written to the `outbox` table in the same database transaction as the domain data write, using
`nohiki-db-utils`'s `OutboxWriter`. Debezium's PostgreSQL connector reads the outbox table from
the WAL and publishes events to Kafka via the Outbox Event Router SMT.

Events published via outbox:

- `user-pref.cdc.pref-created.v1`: published after enrichment completes for a new preference
- `user-pref.cdc.pref-updated.v1`: published after enrichment completes for an updated
  preference, and immediately on attachment and feature importance changes, which can happen
  while enrichment for that preference is still in flight
- `user-pref.cdc.pref-deleted.v1`: published when a preference is deleted
- `user-pref.cdc.settings-created.v1`: published when user-level settings are first created
- `user-pref.cdc.settings-updated.v1`: published when user-level settings are updated

The skill normalization request (`skill.cmd.normalization-requested.v1`) and embedding request
(`ml.cmd.embedding-requested.v1`) are also written to the outbox, in the same transaction that
records the dispatch operation identity on the enrichment saga, so a dispatched command and the
saga state it is validated against cannot diverge.

See `infra/k8s/kafka-connect/` for the Debezium connector configuration.

## Consumer Idempotency

The migration also provisions a `processed_events` table for consumer idempotency. No handler in
this service calls `check_and_mark_processed`, so nothing writes to it. Create and update
enrichment commands deduplicate through their saga `request_id`; create commands also recover a
profile by its `request_id` before starting the saga. Attachment association redeliveries reuse
the existing preference-upload pair, and settings update redeliveries take the existing-row
upsert path.

## Schema Sources

- Models: `backend/services/user-pref-service/src/user_pref_service/db/models.py`
- Baseline revision: `backend/services/user-pref-service/alembic/versions/001_initial_migration.py`
- Migration workflow: [root README](../../../README.md#database-migration-workflow)
