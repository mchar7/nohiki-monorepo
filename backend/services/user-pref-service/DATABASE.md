# User Pref Service Database Design

The `user_pref_schema` schema is the authoritative store for user job target profiles, user-level
job-search settings, profile-to-document associations, and the state needed to complete profile
enrichment. It retains the raw targeting intent together with normalized skills and retrieval
artifacts so downstream services can consume complete profile snapshots without querying this
service.

`user-auth-service` remains the source of truth for user identity. This service owns job-search
preferences and settings and removes its records when it consumes
`user-auth.cdc.account-deleted.v1`. Uploaded documents remain owned by `user-upload-service`;
this schema owns only their associations with preferences.

## Profile State and Enrichment

A profile is a named, complete job-search targeting specification: titles and keywords,
disallowed terms, physical and remote locations, work arrangements, seniority, salary
preferences, required skills, source exclusions, relocation openness, commute preferences,
scoring thresholds, and document-tailoring configuration. Physical locations retain city,
country, and geocoded coordinates. Salary preferences retain their range, currency, and period.
A minimum fit threshold can automatically
disqualify weak matches, while an auto-tailor threshold can trigger document tailoring for strong
matches. Per-profile feature importance controls how strongly
`job-correlation-evaluation-service` weights skill match, location, work arrangement, experience,
salary, and recency. Profiles can also select a schema family from `doc_template_schema` and
retain tailoring preferences consumed by `doc-content-service`.

The profile record deliberately keeps enrichment results beside the targeting intent. Canonical
skill identifiers, skill embeddings, and skill entries preserving proficiency, provenance, and
extraction confidence come from `skill-graph-service`. Dense query embeddings and the MUVERA,
SPARSE, and COLBERT retrieval artifacts come from `ml-gateway-service` and are used for retrieval
by `job-correlation-evaluation-service`. The recorded collection version, together with the
content hash, allows stale embeddings to be detected when the encoding manifest changes.

Enrichment is sequential:

1. **Skill normalization** -- when a profile contains skills, the service requests normalization
   from `skill-graph-service`. The callback persists the canonical identifiers, complete skill
   entries, and skills embedding.
2. **Query embedding** -- the normalized skill result feeds the combined skill-and-keyword query
   sent to `ml-gateway-service`. Its callback persists the query retrieval artifacts, reloads the
   skill data saved by the first stage, marks enrichment complete, and permits lifecycle event
   publication.

Persisting the first-stage result lets the second callback load it locally instead of carrying an
unbounded skill list through Kafka state. A profile without skills skips skill normalization but
still requests query embedding, which remains the gate for completion and publication.

Enrichment completeness is both a publication gate and an idempotency boundary. No profile CDC
event is published while enrichment is incomplete. The BFF-assigned request identifier admits at
most one profile creation for an originating command. If that command is redelivered while the
existing profile is incomplete, the handler re-enters enrichment from the beginning rather than
creating another profile; a completed delivery does not restart the flow. Persisted consumed-event
markers provide the corresponding idempotency boundary for other Kafka redeliveries.

## Profile Lifecycle and Activity

A profile is created when `user-pref.cmd.create-requested` is consumed and the originating request
has not already created one. Enrichment callbacks add normalized skill state and query artifacts.
The profile can then be changed by `user-pref.cmd.update-requested`, attachment and detachment
commands, or `user-pref.cmd.pref-importance-update-requested`.

An active profile participates in job matching. An inactive profile is retained for the user but
excluded from correlation scoring. The active-only access path is intentionally optimized so
matching queries do not scan retained inactive profiles. Other database access paths support the
BFF-driven per-user listing path and account cleanup, and locate an originating request during
create-command redelivery.

A single preference is removed on `user-pref.cmd.delete-requested`. Account deletion removes all
profiles for the user in one bulk operation. Profile deletion also removes its document
associations.

## Document Associations

A preference can reference documents owned by `user-upload-service`. Each preference-upload pair
has one association. Attach-command categories 1 and 2 classify the document as an example, such
as a resume or work sample used for tailoring; all other categories classify it as additional
context for `doc-content-service`.

`user-pref.cmd.attach-upload.v1` creates the association. Reattaching the same document with a new
category updates the existing association, which makes attachment and recategorization
idempotent. `user-pref.cmd.detach-upload.v1` removes it. Associations are also removed with their
parent profile or when `user-upload.cdc.upload-deleted.v1` reports that an upload was deleted. The
reverse upload lookup is intentionally optimized because upload deletion must find associations
across every preference without scanning the entire association set.

## User-Level Settings

This service owns one settings record per user because timezone, locale, and default feature
importance are job-search preferences rather than account settings. Default feature importance
applies across the user's profiles unless a profile overrides it. The IANA timezone supports
display-layer date formatting, while the BCP 47 locale supports currency and number formatting in
notifications.

The first `user-pref.cmd.settings-update-requested` for a user creates the settings state.
Subsequent deliveries update only the fields named by the command, preserving all other values.
The one-record-per-user invariant and update-on-conflict behavior make repeated settings updates
safe. Settings are removed when the owning account deletion event is consumed, and the per-user
lookup is optimized for both updates and cleanup.

## Event Publication and Outbox Boundary

CDC state-change events are written to the transactional outbox in the same database transaction
as the domain write through `nohiki-db-utils`'s `OutboxWriter`. Debezium reads committed outbox
records from the PostgreSQL WAL and the Outbox Event Router SMT publishes them to Kafka. This
atomic boundary prevents a crash from committing a domain change without its corresponding CDC
outbox record.

The service publishes:

- `user-pref.cdc.pref-created.v1` after a new profile completes enrichment.
- `user-pref.cdc.pref-updated.v1` after an updated profile completes enrichment, and immediately
  after attachment or feature-importance changes.
- `user-pref.cdc.pref-deleted.v1` when a profile is deleted.
- `user-pref.cdc.settings-created.v1` when user-level settings are first created.
- `user-pref.cdc.settings-updated.v1` when user-level settings change.

The skill-normalization and embedding requests are outgoing commands, not CDC state-change events.
They are published directly through the Kafka client rather than through the transactional outbox.
As commands, they sit outside the exactly-once guarantee used for source-of-truth CDC publication;
the outbox atomicity guarantee applies only to the CDC events above. The
enrichment-completeness gate and create-command redelivery behavior allow an interrupted,
incomplete enrichment flow to be requested again. Debezium connector configuration lives under
`infra/k8s/kafka-connect/connectors/`.

The schema itself is defined by the SQLAlchemy models in
`backend/services/user-pref-service/src/user_pref_service/db/models.py` and the Alembic revision
in `backend/services/user-pref-service/alembic/versions/001_initial_migration.py`.
