# Skill Graph Service Database Schema

Schema `skill_graph_schema` stores the canonical skill taxonomy, alias mappings, skill relationships,
relationships, occupation-to-skill links, governance staging, and supporting analytics for the
`skill-graph-service`.

## Entity Overview

| Table | Purpose |
| ------- | --------- |
| `skill_node` | Canonical, deduplicated skill entities: the authoritative skill registry |
| `skill_alias` | Surface-form variations that resolve to a canonical `skill_node` |
| `skill_relationship` | Directed, typed edges between canonical skills (adjacency list) |
| `proposed_skill` | Governance staging for skills proposed by LLM extraction |
| `skill_seed_provenance` | Links each canonical skill to its origin in a named taxonomy source |
| `seed_batch_record` | Tracks per-source, per-version seeding lifecycle and cumulative statistics |
| `occupation_skill_relation` | Curated ESCO occupation-to-skill associations (essential / optional / mentioned) |
| `occupation_skill_observation` | Empirical skill co-occurrence counts derived from live job listings |
| `occupation_node` | ESCO occupation entities used for job title → occupation inference |
| `outbox` | Transactional outbox for CDC event delivery via Debezium |
| `processed_events` | Idempotency store for Kafka consumer deduplication |

`skill_node` is the graph's vertex set. Every other table is either an edge type or a support
structure that hangs off it. `skill_alias` provides the lookup surface for deterministic
normalization: an incoming raw string like "ReactJS" traverses `skill_alias` to reach the
canonical `skill_node` for "react". `skill_relationship` forms the directed edge set that
encodes hierarchical and associative links between canonical skills, modeled as an adjacency
list where each row is one directed edge `(source_skill_id → target_skill_id)` with a typed
`relationship_type` and a `bidirectional` flag that governs whether traversal in both
directions is semantically meaningful.

The occupation tables are a second, largely independent subgraph. `occupation_skill_relation`
stores curated ESCO taxonomy associations; `occupation_skill_observation` stores live empirical
signals accumulated as job listings are processed. Both tables reference `skill_node` by
`skill_id` and are queried together to infer which ESCO occupation codes best describe a set
of canonical skills, enabling the normalization pipeline to narrow Qdrant search to the ~50-200
skills relevant to a given job role rather than all ~13,890.

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

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key, generated server-side via `uuidv7()`.
- **`normalized_text`** (`VARCHAR(100)`): Lowercase, trimmed, single-spaced canonical form.
  A CHECK constraint enforces `LOWER(normalized_text) = normalized_text`, `BTRIM(...) = ...`,
  no consecutive whitespace, and no quote characters. This is the lookup key for exact-match
  normalization and the UNIQUE constraint that prevents duplicates entering the taxonomy.
- **`display_name`** (`VARCHAR(200)`): Human-readable label (may differ in capitalisation and
  spacing from `normalized_text`). Nullable: ESCO-seeded skills have display names; auto-approved
  proposals inherit the LLM-suggested `display_name`.
- **`skill_type`** (`VARCHAR(20)`): Classification from ESCO taxonomy: `"knowledge"`,
  `"skill/competence"`, or `"specialized"` (default for auto-approved proposals).
- **`reuse_level`** (`VARCHAR(25)`): ESCO reuse level: `"cross-sector"`, `"sector-specific"`,
  `"occupation-specific"`, or NULL for auto-approved skills without ESCO provenance.
- **`category`** / **`subcategory`** (`VARCHAR(150)`): Hierarchical classification. Populated
  during Tabiya CSV seeding from skill group assignments. NULL for skills created via proposal
  approval.
- **`confidence_score`** (`FLOAT`): 0.5 default for auto-approved proposals and seeded skills
  without explicit quality annotation. Intended for future model-derived quality scoring.
- **`review_status`** (`VARCHAR(20)`): `"pending"` or `"approved"`. ESCO-seeded skills are
  inserted as `"approved"`. Auto-approved proposals are promoted to `"approved"` by
  `_approve_proposal`. The partial index `ix_skill_node_review_status` covers only non-approved
  rows, making pending-skill queries fast without indexing the large approved population.
- **`mention_count`** / **`job_count`** / **`profile_count`** (`INTEGER`): Demand signals
  incremented by `handle_skill_mention_created` each time `skill-graph-service` publishes a normalization result.
  `job_count` counts mentions whose `source_type` is `JOB`; `profile_count` counts `PROFILE`
  mentions. These drive downstream scoring and surface "trending" skills.
- **`first_seen_at`** / **`last_seen_at`** (`TIMESTAMPTZ`): Temporal bookends on skill activity.
  `last_seen_at` is updated on every `SkillMentionCreated` event.

#### Indexes

- **`ix_skill_node_normalized_text`** (`normalized_text`): Supports exact-match lookup in the
  normalization pipeline (stage 1) and the Jaccard corpus scan (stage 3).
- **`ix_skill_node_confidence`** (`confidence_score DESC`): Supports descending-confidence
  queries used during candidate ranking.
- **`ix_skill_node_job_count`** (`job_count DESC`): Supports "most in-demand skills" queries
  from the BFF.
- **`ix_skill_node_review_status`** (`review_status`) WHERE `review_status != 'approved'`:
  Partial index covering only the minority pending/rejected rows, keeping governance queries
  fast as the approved population grows.
- **`ix_skill_node_created_at_brin`** (`created_at`) BRIN, pages_per_range=32: Low-overhead
  index for time-range scans across the append-heavy `skill_node` table; BRIN is appropriate
  because UUIDv7 primary keys encode creation time, so physical row order correlates with
  `created_at`.

#### Constraints & Invariants

- **UNIQUE** on `normalized_text`: Enforces one canonical entry per lowercase skill form.
  The normalization pipeline relies on this guarantee for idempotent inserts.
- **CHECK** `skill_node_normalized_text_format`: Rejects non-lowercase, untrimmed, multi-space,
  or quoted values at the database level, ensuring the lookup invariant holds regardless of
  the insert path.

#### Data Lifecycle

- **Created** via the Tabiya seeding CLI (batch upserts from ESCO CSV) or via `_approve_proposal`
  when `handle_skill_proposed` auto-approves a `proposed_skill` at `proposal_count >= 5`.
- **Updated** by `handle_skill_mention_created` (increments `mention_count`, `job_count`,
  `profile_count`, refreshes `last_seen_at`).
- **Deleted** only on full schema drop. No soft-delete or event-driven deletion path exists.

---

### `skill_alias`

#### Purpose

Maps alternative surface forms of a skill to its canonical `skill_node`. The alias table is
the backbone of normalization stage 2: an incoming raw string is lowercased and looked up
against `alias_text`, optionally scoped to a `context_hint`, and returns the linked canonical
skill without requiring any fuzzy computation.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key.
- **`alias_text`** (`VARCHAR(200)`): Lowercased surface form, e.g., `"reactjs"`, `"react.js"`,
  `"react js"`. Stored lowercase; the resolution query uses `LOWER(alias_text)` comparison.
- **`canonical_skill_id`** (`UUID`): References `skill_graph_schema.skill_node.id`
  (FK with `ON DELETE CASCADE`). Deleting a canonical skill removes all its aliases.
- **`context_hint`** (`VARCHAR(100)`): Optional industry or category hint that scopes the
  alias to a specific context. `("python", "data-science")` can resolve differently from
  `("python", NULL)`. The UNIQUE constraint is on `(alias_text, context_hint)`, so the same
  surface form may map to different canonical skills in different contexts, but must be unique
  within any one context (including the NULL/universal context).
- **`confidence`** (`FLOAT`): Match confidence, defaulting to 0.9. Incremented by 0.01 (capped
  at 1.0) each time `upsert_alias` is called for an existing alias, reinforcing high-frequency
  associations over time.
- **`usage_count`** (`INTEGER`): Incremented on each successful alias resolution and on every
  upsert, providing a demand signal for alias quality ranking.
- **`source`** (`VARCHAR(50)`): Origin of the alias: `"tabiya_esco"` for seeded aliases,
  `"proposal_approved"` for aliases extracted from approved proposals, or the source service
  name for dynamically learned aliases from `AliasLearned` events.
- **`source_job_id`** (`UUID`): Optional reference to the job listing that produced this alias,
  enabling traceability back to the extraction source.

#### Indexes

- **`ix_skill_alias_text`** (`alias_text`): Primary lookup index for normalization stage 2.
- **`ix_skill_alias_context`** (`alias_text`, `context_hint`): Composite index serving the
  context-aware alias resolution query (first tries context-specific, then falls back to
  universal NULL context).
- **`ix_skill_alias_canonical`** (`canonical_skill_id`): Supports forward traversal from a
  canonical skill to all its known surface forms, used during skill export and BFF display.
- **`ix_skill_alias_source`** (`source`): Supports provenance-based queries, e.g., listing
  all ESCO-seeded aliases vs. dynamically learned ones.

#### Constraints & Invariants

- **UNIQUE** on `(alias_text, context_hint)`: Ensures each surface form is unambiguous within
  a context. Because NULL values are not equal in PostgreSQL's unique index semantics, universal
  aliases (NULL context) and context-specific aliases may coexist for the same `alias_text`.
- **FK CASCADE** on `canonical_skill_id`: Alias rows are automatically removed when their
  canonical skill is deleted.

#### Data Lifecycle

- **Created** in bulk during Tabiya ESCO seeding (alt labels from ESCO CSV become aliases with
  `source = "tabiya_esco"`).
- **Created** when a `proposed_skill` is auto-approved: up to 5 `suggested_aliases` are
  inserted with `source = "proposal_approved"`.
- **Upserted** (created or usage-count-incremented) by `handle_alias_learned` when any service
  publishes `skill.fct.alias-learned.v1` after observing a new surface form in the wild.
- **Deleted** via CASCADE when the linked `skill_node` is removed.

---

### `skill_relationship`

#### Purpose

An adjacency-list edge table encoding typed directed relationships between canonical skills.
Each row is a single directed edge from `source_skill_id` to `target_skill_id` with a string
`relationship_type`. Relationship types from ESCO include `"broader"` (parent concept),
`"narrower"` (child concept), and `"related"` (associative). The `bidirectional` flag indicates
whether the semantic relationship holds in both directions, but the edge itself is always stored
as a directed pair. Traversal in both directions requires either a bidirectional flag check or
two separate rows.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key.
- **`source_skill_id`** (`UUID`): The origin node. References `skill_node.id` with `ON DELETE CASCADE`.
- **`target_skill_id`** (`UUID`): The destination node. References `skill_node.id` with `ON DELETE CASCADE`.
- **`relationship_type`** (`VARCHAR(50)`): Semantic label for the edge, e.g., `"broader"`,
  `"narrower"`, `"related"`, `"requires"`, `"optional_knowledge_of"`. Populated from ESCO
  taxonomy relationships during seeding.
- **`strength`** (`FLOAT`): Edge weight in [0.0, 1.0]. Defaults to 1.0 for all seeded ESCO
  relationships. Reserved for future model-derived edge weighting.
- **`bidirectional`** (`BOOLEAN`): When `true`, the relationship is semantically symmetric
  and traversal in either direction is valid. `"related"` edges are typically bidirectional;
  `"broader"`/`"narrower"` pairs are directional.

#### Indexes

- **`ix_skill_rel_source`** (`source_skill_id`): Supports forward graph traversal -- "what skills
  does this skill relate to?"
- **`ix_skill_rel_target`** (`target_skill_id`): Supports reverse traversal -- "what skills
  point to this skill?" (e.g., finding all narrower skills given a broader concept).
- **`ix_skill_rel_type`** (`relationship_type`): Supports filtering by edge type, e.g.,
  retrieving only `"broader"` edges for hierarchy traversal.

#### Constraints & Invariants

- **UNIQUE** on `(source_skill_id, target_skill_id, relationship_type)`: Prevents duplicate
  edges of the same type between any ordered pair. A `"broader"` edge and a `"related"` edge
  may coexist between the same two nodes.
- **CHECK** `source_skill_id != target_skill_id`: Prevents self-referential edges, which would
  create trivial cycles and confuse graph traversal algorithms.
- **FK CASCADE** on both endpoints: Deleting a `skill_node` removes all incident edges in both
  directions.

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

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key.
- **`canonical_name`** (`VARCHAR(100)`): Lowercased proposed canonical form. UNIQUE constraint means
  the same skill increments `proposal_count` rather than creating a duplicate row.
- **`display_name`** (`VARCHAR(200)`): LLM-suggested human-readable label.
- **`suggested_aliases`** (`JSONB`): Array of alternative surface forms suggested by the LLM.
  Structure: `["alias1", "alias2", ...]`. Up to 5 are inserted as `skill_alias` rows when the
  proposal is approved.
- **`source_job_ids`** (`JSONB`): Array of job listing UUIDs (as strings) that contributed to
  this proposal. Provides evidence traceability and deduplication, so a job listing already in
  the set does not inflate `proposal_count`. Structure: `["uuid1", "uuid2", ...]`.
- **`proposal_count`** (`INTEGER`): Number of distinct times this skill has been proposed.
  Auto-approval triggers at `proposal_count >= 5` (configurable via `AUTO_APPROVE_THRESHOLD`).
- **`proposed_by`** (`VARCHAR(50)`): Source service or mechanism (e.g., `"llm_extraction"`).
- **`status`** (`VARCHAR(20)`): State machine with transitions `pending → approved` and
  `pending → rejected → pending`. Managed by `StateMachineMixin`. Values: `"pending"`,
  `"approved"`, `"rejected"`.
- **`approved_skill_id`** (`UUID`): References `skill_node.id` (FK `ON DELETE SET NULL`).
  Set when the proposal is approved; provides a forward link from the proposal record to the
  canonical skill it produced.

#### Indexes

- **`ix_proposed_skill_status`** (`status`): Supports governance queries filtering proposals
  by review state (e.g., all pending proposals for a human reviewer dashboard).
- **`ix_proposed_skill_name`** (`canonical_name`): Supports the idempotency check in
  `process_skill_proposal` that looks up whether a proposal already exists before creating
  a new one.
- **`ix_proposed_skill_count`** (`proposal_count DESC`): Supports queries that surface
  high-evidence proposals first.

#### Constraints & Invariants

- **UNIQUE** on `canonical_name`: One proposal record per lowercase canonical name.
  The governance logic reinforces the existing row rather than inserting a duplicate.
- **FK SET NULL** on `approved_skill_id`: If the resulting `skill_node` is ever removed
  (schema drop only), the proposal record is preserved with `approved_skill_id = NULL`.

#### Data Lifecycle

- **Created** by `handle_skill_proposed` when `process_skill_proposal` finds no existing
  proposal for the `canonical_name`.
- **Updated** (proposal_count incremented, source_job_ids accumulated) on subsequent
  `skill.cmd.skill-proposed.v1` events for the same `canonical_name`.
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

#### Key Columns

- **`skill_id`** (`UUID`): References `skill_node.id` (FK `ON DELETE CASCADE`).
- **`source_name`** (`VARCHAR(50)`): Taxonomy name, e.g., `"tabiya_esco"`.
- **`source_version`** (`VARCHAR(50)`): Version string, e.g., `"1.1.1"`.
- **`authority`** (`SMALLINT`): Ordered priority level (1, 2, or 3). A CHECK constraint restricts
  values to this set. Lower values represent higher authority. When multiple sources define the
  same skill, authority 1 wins for display name and metadata resolution.
- **`external_id`** (`VARCHAR(500)`): The skill's identifier in the source taxonomy (e.g., ESCO
  concept URI path).
- **`external_uri`** (`VARCHAR(1000)`): Fully qualified URI for the skill concept in the source
  taxonomy, enabling deep links to the origin taxonomy for editorial review.

#### Indexes

- **`ix_skill_seed_prov_skill`** (`skill_id`): Forward lookup from skill to its provenance records.
- **`ix_skill_seed_prov_source`** (`source_name`, `source_version`): Supports queries enumerating
  all skills from a specific taxonomy version, used during re-seeding to detect additions and
  removals.
- **`ix_skill_seed_prov_authority`** (`authority`): Supports priority-ordered resolution when
  merging metadata from multiple sources.

#### Constraints & Invariants

- **UNIQUE** on `(skill_id, source_name)`: One provenance record per skill per source.

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

#### Key Columns

- **`source_name`** / **`source_version`** (`VARCHAR(50)`): Identifies the taxonomy and version
  being seeded. The UNIQUE constraint on this pair ensures exactly one batch record per import.
- **`status`** (`VARCHAR(20)`): `"pending"`, `"running"`, `"completed"`, or `"failed"`.
  A CHECK constraint restricts to these four values. The partial index covers non-completed
  rows, enabling fast polls for in-flight or failed batches.
- **`skills_added`** / **`skills_updated`** / **`aliases_added`** / **`relationships_added`** /
  **`occupation_relations_added`** / **`occupations_added`** / **`error_count`** (`INTEGER`):
  Cumulative counters updated as the seeding CLI processes each batch.
- **`error_details`** (`TEXT`): Free-form error description written on `status = "failed"`.

#### Indexes

- **`ix_seed_batch_source`** (`source_name`, `source_version`): Supports idempotency checks
  before starting a new seed run.
- **`ix_seed_batch_status`** (`status`) WHERE `status != 'completed'`: Partial index for
  monitoring active or failed runs.

#### Data Lifecycle

- **Created** by the seeding CLI at the start of each import with `status = "pending"`.
- **Updated** to `"running"` when processing begins, and to `"completed"` or `"failed"` on
  completion.

---

### `occupation_skill_relation`

#### Purpose

Stores curated ESCO taxonomy associations between occupation codes and canonical skills. Each
row declares that a given occupation requires or benefits from a specific skill, classified as
`"essential"`, `"optional"`, or `"mentioned"`. This table is the authoritative source for
occupation-based skill pre-filtering in the normalization and correlation pipelines.

#### Key Columns

- **`occupation_code`** (`VARCHAR(50)`): ESCO occupation code (e.g., `"2511.1"`). Not a FK to
  `occupation_node` -- the relation table is independently queryable by code.
- **`occupation_label`** (`VARCHAR(300)`): Human-readable occupation title stored denormalized
  here to avoid joins in the common query path.
- **`skill_id`** (`UUID`): References `skill_node.id` (FK `ON DELETE CASCADE`).
- **`relation_type`** (`VARCHAR(20)`): `"essential"` -- skill is required; `"optional"` -- skill
  is beneficial; `"mentioned"` -- skill appears in the occupation description. A CHECK constraint
  restricts to these three values.
- **`source_metadata`** (`JSONB`): Source-specific metadata from the taxonomy (e.g., ESCO
  concept URIs, frequency scores). Structure is source-dependent; defaults to `{}`.

#### Indexes

- **`ix_occupation_skill_occupation`** (`occupation_code`): Primary lookup -- "all skills for
  this occupation code."
- **`ix_occupation_skill_skill`** (`skill_id`): Reverse lookup -- "all occupations that require
  this skill."
- **`ix_occupation_skill_relation_type`** (`relation_type`): Supports filtering to essential-only
  skill sets, which is the default for occupation-based normalization pre-filtering.
- **`ix_occupation_skill_source`** (`source_name`, `source_version`): Supports provenance queries
  and re-seeding diff calculations.

#### Constraints & Invariants

- **UNIQUE** on `(occupation_code, skill_id, source_name)`: One relation per occupation-skill
  pair per source, allowing multiple taxonomy sources to contribute to the same occupation
  without collision.

#### Data Lifecycle

- **Created** during Tabiya ESCO seeding from the occupation-skills CSV.
- **Deleted** via CASCADE when the linked `skill_node` is removed.

---

### `occupation_skill_observation`

#### Purpose

Accumulates empirical evidence of skill co-occurrence with occupation codes observed in live
job listing data. Unlike `occupation_skill_relation` (which is static, curated taxonomy data),
this table updates in real-time as the ingest pipeline processes job listings. The
`OccupationService` combines both tables when inferring occupations from a skill set, using
observations above a minimum count threshold to reduce noise from one-off job postings.

#### Key Columns

- **`occupation_code`** (`VARCHAR(50)`): ESCO code inferred from the job listing's title or
  job context.
- **`skill_id`** (`UUID`): References `skill_node.id` (FK `ON DELETE CASCADE`).
- **`dominant_relation`** (`VARCHAR(20)`): Most frequent relation type observed across all
  job listings for this pair: `"essential"`, `"optional"`, or `"mentioned"`. A CHECK constraint
  restricts to these three values.
- **`observation_count`** (`INTEGER`): Number of job listings in which this occupation-skill
  pair has been observed. A CHECK constraint enforces `>= 1`. Pairs with fewer than
  `min_observations` (default 3) are excluded from occupation inference to suppress noise.
- **`first_observed_at`** / **`last_observed_at`** (`TIMESTAMPTZ`): Temporal bounds on
  observed co-occurrence, supporting freshness-based filtering.

#### Indexes

- **`ix_occ_skill_obs_occupation`** (`occupation_code`): Forward lookup for the inference query.
- **`ix_occ_skill_obs_skill`** (`skill_id`): Reverse lookup for occupation coverage per skill.
- **`ix_occ_skill_obs_count`** (`observation_count DESC`): Supports threshold filtering: the
  `infer_occupations` query restricts to rows where `observation_count >= min_observations`.
- **`ix_occ_skill_obs_last_seen`** (`last_observed_at DESC`): Supports recency-based queries.

#### Constraints & Invariants

- **UNIQUE** on `(occupation_code, skill_id)`: One counter per occupation-skill pair; new
  observations increment `observation_count` rather than inserting duplicate rows.

#### Data Lifecycle

- **Created or updated** (observation_count incremented) as the ingest pipeline processes job
  listings and identifies occupation-skill co-occurrences.
- **Deleted** via CASCADE when the linked `skill_node` is removed.

---

### `occupation_node`

#### Purpose

Stores ESCO occupation entities (job roles defined in the ESCO taxonomy) to support semantic
job title → occupation inference. Embeddings for these occupation nodes are stored in the
Qdrant occupations collection (not in this table), enabling vector similarity search against
a job title string to narrow the skill search space before Qdrant normalization search.

#### Key Columns

- **`occupation_code`** (`VARCHAR(50)`): UNIQUE ESCO occupation code. The primary lookup key
  for cross-referencing with `occupation_skill_relation` and `occupation_skill_observation`.
- **`preferred_label`** (`VARCHAR(300)`): Official ESCO occupation title, e.g., `"software developer"`.
- **`alt_labels`** (`JSONB`): Array of alternative titles from the ESCO taxonomy, e.g.,
  `["programmer", "coder", "software engineer"]`. Used as additional embedding input during
  bootstrap seeding.
- **`isco_group_code`** (`VARCHAR(20)`): ISCO-08 group code for broad occupational classification.
  Nullable: not all ESCO occupations have an explicit ISCO group mapping.
- **`occupation_type`** (`VARCHAR(50)`): ESCO occupation taxonomy level: `"escooccupation"`
  (default) or `"localoccupation"`.

#### Indexes

- **`ix_occupation_node_code`** (`occupation_code`): Fast code-based lookup.
- **`ix_occupation_node_label`** GIN on `to_tsvector('english', preferred_label)`: Full-text
  search index on the occupation label, supporting `search_occupations` queries from the BFF.
- **`ix_occupation_node_isco`** (`isco_group_code`) WHERE `isco_group_code IS NOT NULL`:
  Partial index for group-based occupation filtering.
- **`ix_occupation_node_source`** (`source_name`, `source_version`): Provenance queries during
  re-seeding.

#### Data Lifecycle

- **Created** during Tabiya ESCO seeding from the occupations CSV.
- **Not updated** by live event handlers. The occupation taxonomy is static between seed runs.

---

## Outbox Table

This service uses the transactional outbox pattern for guaranteed delivery of all
`skill.fct.skill-created.v1` events. When a canonical skill is created, either during bootstrap
seeding or on proposal auto-approval, the `skill_node` INSERT and the `outbox` row write happen
in the same database transaction. Debezium's PostgreSQL connector reads the outbox table from the
WAL and routes events to Kafka via the Outbox Event Router SMT.

The `processed_events` table provides idempotency for Kafka consumer handlers: before processing
any incoming event, handlers check whether the message ID has already been recorded in this table
and skip re-processing if so.

**Events published via outbox:**

- **`skill.fct.skill-created.v1`** (`SkillCreated`): Published whenever a canonical `skill_node`
  enters the taxonomy. `bff-service` consumes this to populate its skills projection table.
  `job-correlation-evaluation-service` consumes it to update its local skill index.

Debezium connector configuration: `infra/kafka-connect/connectors/`.

## Migration Strategy

Nohiki uses **clean-cut deployment**: all services are stopped, schemas are dropped and recreated,
and the single `001_` migration is applied fresh. The migration file is edited in place rather
than creating incremental migrations.

This is possible because Nohiki is pre-release with zero production data. There are no data
migrations or backward compatibility concerns.

```bash
# Apply migration
uv run --package skill-graph-service alembic upgrade head

# Generate updated migration after model changes
uv run --package skill-graph-service alembic revision --autogenerate -m "description"

# View current state
uv run --package skill-graph-service alembic current
```
