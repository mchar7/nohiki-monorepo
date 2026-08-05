# Skill Graph Service Database Design

Schema `skill_graph_schema` stores the canonical skill taxonomy, alias mappings, skill
relationships, occupation-to-skill links, governance staging, and supporting analytics for the
`skill-graph-service`.

`skill_node` is the graph's vertex set. Every other table is either an edge type or a support
structure that hangs off it. `skill_alias` provides the lookup surface for deterministic
normalization: an incoming raw string like "ReactJS" traverses `skill_alias` to reach the
canonical `skill_node` for "react". `skill_relationship` forms the directed edge set that
encodes hierarchical and associative links between canonical skills, modeled as an adjacency
list where each row is one directed edge `(source_skill_id → target_skill_id)` with a typed
`relationship_type` and a `bidirectional` flag that governs whether traversal in both
directions is semantically meaningful.

The occupation tables are a second, largely independent subgraph. `occupation_skill_relation`
stores curated ESCO taxonomy associations. Nothing in the service reads either occupation
relation table: seeding is the only code path that touches them, and occupation-based
pre-filtering of normalization or correlation queries is not implemented.

The governance tables (`proposed_skill`) form a staging area between LLM extraction and the
canonical skill registry. A proposed skill accumulates evidence rows and is promoted to
`skill_node` automatically once it has been observed five times, triggering an outbox write
and a triple-embedding request.

## Table Details

### `skill_node`

#### Purpose

The authoritative record for one deduplicated canonical skill. Every other reference to a skill
anywhere in Nohiki, including job listings, user preferences, correlation features, and BFF projections,
is a UUID that points back to a row in this table.

#### Constraints & Invariants

- One canonical entry per lowercase skill form. The normalization pipeline relies on this
  guarantee for idempotent inserts.
- `normalized_text` is rejected at the database level when it is non-lowercase, untrimmed,
  multi-space, or quoted, ensuring the lookup invariant holds regardless of the insert path.

#### Data Lifecycle

- **Created** via the Tabiya seeding CLI (batch upserts from ESCO CSV) or via `_approve_proposal`
  when `handle_skill_proposed` auto-approves a `proposed_skill` at `proposal_count >= 5`. Only the
  reinforcement path (`_reinforce_existing_proposal`) can reach that threshold; a first-time
  proposal is always stored with status `pending`.
- **Updated** by `handle_skill_mention_created` (increments `mention_count`, refreshes
  `last_seen_at`) for each consumed `skill.fct.mention-created.v1` event. `job_count` counts
  mentions whose `source_type` is `JOB`; `profile_count` counts `PROFILE` mentions. The handler
  returns early without updating counts when the message carries no `match` or no `mention`.
  No service in this repository publishes that topic, so the counters stay at their defaults
  today.
- **Deleted** only on full schema drop. No soft-delete or event-driven deletion path exists.

---

### `skill_alias`

#### Purpose

Maps alternative surface forms of a skill to its canonical `skill_node`. The alias table is
the backbone of normalization stage 2: an incoming raw string is lowercased and looked up
against `alias_text`, optionally scoped to a `context_hint`, and returns the linked canonical
skill without requiring any fuzzy computation.
When a context hint is present, `resolve_alias` tries the context-specific alias first and then
falls back to the universal NULL context. The supporting `ix_skill_alias_lookup` expression
index couples `LOWER(alias_text)` and `context_hint` to that lookup.

#### Constraints & Invariants

- Each surface form is unambiguous within a context. Because the uniqueness constraint treats
  NULLs as equal, there can be at most one universal (NULL context) alias per `alias_text`
  alongside its context-specific siblings.
- `upsert_alias` refuses to repoint an existing alias: the conflict update is gated on the
  incoming `canonical_skill_id` matching the stored one, and a mismatch raises
  `DataIntegrityError`.
- Alias rows are automatically removed when their canonical skill is deleted.

#### Data Lifecycle

- **Created** in bulk during Tabiya ESCO seeding (alt labels from ESCO CSV become aliases with
  `source = "tabiya_esco"`).
- **Created** when a `proposed_skill` is auto-approved: up to 5 `suggested_aliases` are
  inserted with `source = "proposal_approved"`.
- **Upserted** by `handle_alias_learned` when any service publishes `skill.fct.alias-learned.v1`
  after observing a new surface form in the wild. Only this conflict path moves `usage_count` and
  `confidence`: an existing row gains one usage and 0.01 confidence (capped at 1.0). Alias
  resolution during normalization does not touch either counter.
- **Deleted** via CASCADE when the linked `skill_node` is removed.

---

### `skill_relationship`

#### Purpose

An adjacency-list edge table encoding typed directed relationships between canonical skills.
Each row is a single directed edge from `source_skill_id` to `target_skill_id` with a string
`relationship_type`. The `bidirectional` flag indicates
whether the semantic relationship holds in both directions, but the edge itself is always stored
as a directed pair. Traversal in both directions requires either a bidirectional flag check or
two separate rows. The Tabiya parser (`_parse_relationship_row`) emits the CSV `RELATIONTYPE`
verbatim in lowercase, assigns `strength` 1.0 to `essential` edges and 0.5 to everything else,
and always writes `bidirectional = False`, so no seeded edge is currently marked symmetric.

#### Constraints & Invariants

- Duplicate edges of the same type between any ordered pair are rejected. A `"broader"` edge and
  a `"related"` edge may coexist between the same two nodes.
- Self-referential edges, which would create trivial cycles and confuse graph traversal
  algorithms, are rejected.
- Deleting a `skill_node` removes all incident edges in both directions.

#### Data Lifecycle

- **Created** during Tabiya ESCO seeding from the relationships CSV, in batches of 1,000 rows.
- **Deleted** via CASCADE when either endpoint `skill_node` is removed.
- No event-driven creation path exists after bootstrap. Live normalization does not add
  relationship edges.

---

### `proposed_skill`

#### Purpose

Staging area for skills that could not be resolved to a canonical skill and were subsequently
proposed by `job-ingest-enrichment-service` via `skill.cmd.skill-proposed.v1`. A proposal accumulates
evidence from multiple job listings before entering the canonical skill registry.

#### Constraints & Invariants

- One proposal record per lowercase canonical name.
  The governance logic reinforces the existing row rather than inserting a duplicate.
- `source_job_ids` provides evidence traceability and deduplication, so a job listing already in
  the set does not inflate the stored set of job IDs. Each accepted event still increments
  `proposal_count`, including a repeat of an already-recorded job ID.
- Auto-approval triggers at `proposal_count >= 5` (`AUTO_APPROVE_THRESHOLD` in
  `skill_governance.py`).
- `ProposedSkill` declares the transitions `pending → approved`, `pending → rejected`, and
  `rejected → pending` through `StateMachineMixin`, but `_approve_proposal` sets
  `status = "approved"` with a direct UPDATE that bypasses the mixin, and no code path ever
  writes `"rejected"`: a near-duplicate proposal is rejected in-memory by
  `process_skill_proposal` and never persisted.
- If the resulting `skill_node` is ever removed
  (schema drop only), the proposal record is preserved with `approved_skill_id = NULL`.

#### Data Lifecycle

- **Created** by `handle_skill_proposed` when `process_skill_proposal` finds no existing
  proposal for the `canonical_name`.
- **Updated** (proposal_count incremented, source_job_ids accumulated) on subsequent
  `skill.cmd.skill-proposed.v1` events for the same `canonical_name`. `process_skill_proposal`
  selects the existing row `FOR UPDATE`, so concurrent proposals for one name serialize.
- **Promoted to `approved`** by `_approve_proposal` when `proposal_count >= AUTO_APPROVE_THRESHOLD`.
  The same transaction inserts the `skill_node`, inserts alias rows, and writes
  `skill.fct.skill-created.v1` to the outbox.
- **Never deleted** during normal operation: proposal history is retained as audit trail.

---

### `skill_seed_provenance`

#### Purpose

Links each canonical `skill_node` to the named taxonomy source that introduced it. When the
same skill exists in multiple taxonomies (e.g., ESCO v1.1.0 and ESCO v1.1.1), each source
gets its own row, preserving external identifiers and URIs for cross-reference and update
detection.

#### Constraints & Invariants

- One provenance record per skill per source.
- `authority` is an ordered priority level (1, 2, or 3) where the higher value wins:
  `SourceAuthority` ranks `NOHIKI_LEARNED = 1`, `TABIYA = 2`, `CURATED = 3`. The only consumer of
  that ordering is `_fetch_provenance_for_skill_ids`, whose `DISTINCT ON (skill_id)` with
  `ORDER BY authority DESC` picks one row per skill for the provenance attached to bootstrap
  `skill.fct.skill-created.v1` payloads. Nothing resolves `skill_node` display name or metadata
  from provenance.

#### Data Lifecycle

- **Created** during seeding for every `skill_node` upserted from a taxonomy CSV.
- **Deleted** via CASCADE when the linked `skill_node` is removed.

---

### `seed_batch_record`

#### Purpose

Tracks the lifecycle and cumulative outcome statistics for each seeding run identified by
`(source_name, source_version)`. Provides observability into whether a seed batch completed
successfully and how many entities were inserted or updated, without requiring a scan of the
full `skill_node` table.

#### Constraints & Invariants

- Exactly one batch record exists per `(source_name, source_version)` import.
- `error_details` is never written: `_complete_batch_record` updates only status, counters, and
  `completed_at`, and `_start_batch_record` resets `error_details` to NULL. A failed run is
  identifiable by `status = "failed"` plus `error_count`, with the cause only in the logs.

#### Data Lifecycle

- **Created** by `SkillGraphSeeder._start_batch_record` at the start of each import, directly
  with `status = "running"`.
- **Rerun** of the same `(source_name, source_version)` reuses the row and resets it: counters
  back to zero, `completed_at` and `error_details` to NULL, `started_at` to now.
- **Updated** to `"completed"` or `"failed"` on completion. Any batch-level insert error is
  counted, and `_raise_if_seed_errors` turns a nonzero `error_count` into the failure path.

---

### `occupation_skill_relation`

#### Purpose

Stores curated ESCO taxonomy associations between occupation codes and canonical skills. Each
row declares that a given occupation requires or benefits from a specific skill, classified as
`"essential"`, `"optional"`, or `"mentioned"`. `occupation_label` is stored denormalized here to
avoid joins in the common query path, and `occupation_code` is deliberately not a foreign key to
`occupation_node`, so the relation table is independently queryable by code.

#### Constraints & Invariants

- One relation per occupation-skill pair per source, allowing multiple taxonomy sources to
  contribute to the same occupation without collision.

#### Data Lifecycle

- **Created** during Tabiya ESCO seeding from the occupation-skills CSV.
- **Deleted** via CASCADE when the linked `skill_node` is removed.
- Never read: no query in the service selects from this table.

---

### `occupation_skill_observation`

This table is created by the baseline migration only. It has no SQLAlchemy model, no writer, and
no reader anywhere in the repository, so it is permanently empty until an owner is implemented.

---

### `occupation_node`

#### Purpose

Stores ESCO occupation entities (job roles defined in the ESCO taxonomy) intended to support
semantic job title → occupation inference. Occupation embeddings would live in the Qdrant
occupations collection rather than in this table, but nothing requests them:
`build_occupation_batch_item` has no production caller, so the occupations collection is never
populated and no occupation-based narrowing of the skill search space happens.
`handle_batch_embedding_callback` can still route `EntityType.OCCUPATION` results if any arrive.

#### Data Lifecycle

- **Created** during Tabiya ESCO seeding from the occupations CSV.
- **Not updated** by live event handlers. The occupation taxonomy is static between seed runs.

---

## Outbox Table

This service uses the transactional outbox pattern for guaranteed delivery of all
`skill.fct.skill-created.v1` events. On proposal auto-approval, the `skill_node` INSERT and the
`outbox` row write happen in the same database transaction. Debezium's PostgreSQL connector
reads the outbox table from the WAL and routes events to Kafka via the Outbox Event Router SMT.

Bootstrap uses a separate consumer transaction after the seeding CLI has committed the
`skill_node` rows. `handle_skill_graph_seeded` calls
`publish_skill_created_events_for_bootstrap` with `commit_batches=False`, so the processed-event
claim, every outbox batch, and the embedding commands commit together. A crash before that
commit replays the whole handler rather than permanently skipping work.

The `processed_events` table provides idempotency for the state-changing Kafka handlers:
`handle_skill_graph_seeded`, `handle_skill_mention_created`, `handle_alias_learned`, and
`handle_skill_proposed` each call `_claim_event_once`, which claims `metadata.event_id` in the
handler transaction and returns early when the event was already claimed. An event without an
`event_id` is processed without deduplication. The embedding and normalization callback handlers
do not claim events.

**Events published via outbox:**

- **`skill.fct.skill-created.v1`** (`SkillCreated`): Published whenever a canonical `skill_node`
  enters the taxonomy. `bff-service` consumes this to populate its skills projection table.
  `job-correlation-evaluation-service` consumes it to update its local skill index.

Debezium connector configuration: `infra/k8s/kafka-connect/connectors/`.

## Schema Sources

- Models: `backend/services/skill-graph-service/src/skill_graph_service/db/models.py`
- Baseline revision:
  `backend/services/skill-graph-service/alembic/versions/001_initial_migration.py`
- Migration workflow: [root README](../../../README.md#database-migration-workflow)
