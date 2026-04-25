# Skill Graph Service

Maintains the canonical skill taxonomy for Nohiki. When any service encounters a raw skill string
(whether from a job listing, user preference, or document extraction), it publishes a normalization
command here. This service resolves the mention to a canonical `skill_node` using a four-stage
cascade (exact DB match → alias lookup → Jaccard n-gram → Qdrant semantic search) and returns the
result via a callback topic. It also governs new skill creation via a proposal/approval workflow and
seeds the initial skill graph from the Tabiya ESCO taxonomy. Kafka-only, stateful with PostgreSQL,
Qdrant, and Redis.

## Role in the System

Every skill string in Nohiki is eventually normalized through this service. Without it, "React.js",
"ReactJS", and "React JS" would be treated as three different skills by the correlation engine,
poisoning match scores and degrading recommendation quality. This service is the single authority
that collapses all surface variations onto a canonical `normalized_text` key and assigns them a
stable UUID primary key used everywhere else.

`job-ingest-enrichment-service` publishes `skill.cmd.normalization-requested` after LLM extraction
from a job listing. `user-pref-service` publishes the same command when a user declares skills in
their preference profile. Both services supply a `callback_topic` in the command header, either
`job-ingest.sys.skill-callback.v1` or `user-pref.sys.skill-callback.v1` -- and this service
delivers the normalized result there. `job-correlation-evaluation-service` and `bff-service`
consume the downstream `skill.fct.skill-created.v1` to build and maintain skill projections.

When normalization encounters a skill that cannot be matched to any existing canonical skill and
scores above the novelty threshold, it triggers the governance workflow: a `skill.cmd.skill-proposed.v1`
event causes this service to create a `proposed_skill` record. Proposals accumulate evidence from
multiple job listings; once a proposal is seen five times (`AUTO_APPROVE_THRESHOLD`), the service
auto-approves it, creates a canonical `skill_node`, publishes `skill.fct.skill-created.v1`, and
immediately requests Qdrant embedding for the new skill.

## Event-Driven Integration

### Events Consumed

- **`skill.cmd.normalization-requested.v1`** (`SkillNormalizationRequested`): The primary entry
  point. Carries a list of raw skill strings, an optional `job_context` with industry hint for
  alias disambiguation, and a `command` header containing `callback_topic` and `operation_id`.
  The handler runs deterministic matching (exact/alias/Jaccard) concurrently across all input
  skills. If every skill matches deterministically, the callback is published immediately. If any
  skill remains unmatched, the handler encodes the partial state into a `NormalizationEmbeddingState`
  and publishes a batch embedding request to `ml.cmd.batch-embedding-requested.v1` with
  `skill.sys.normalization-embedding-callback.v1` as the callback topic. Consumer group:
  `skill-graph-service-normalization`.

- **`skill.sys.normalization-embedding-callback.v1`** (`BatchEmbeddingCallback`): Carries dense
  embeddings for skills that failed deterministic matching. The handler reconstructs the full
  normalization context from the `caller_context` field (which holds a serialized
  `NormalizationEmbeddingState`), runs Qdrant batch dense search against the skills collection,
  applies semantic thresholds from the manifest (auto-match vs. uncertain vs. no-match), assembles
  the final `SkillNormalizationCallback`, and publishes it to the original requester's callback
  topic. On embedding failure, propagates an error callback rather than silently dropping the
  request. Consumer group: `skill-normalization-embedding-primary`.

- **`skill.sys.batch-embedding-callback.v1`** (`BatchEmbeddingCallback`): Carries batch dense
  embeddings produced during bootstrap seeding or after a new skill is approved. Routes by
  `entity_type` -- `SKILL` embeddings go to the skills Qdrant collection; `OCCUPATION` embeddings
  go to the occupations collection. Qdrant is the source of truth for embedding status; no
  database update is required. Consumer group: `skill-graph-batch-embedding-callback-primary`.

- **`skill.fct.skill-graph-seeded.v1`** (`SkillGraphSeeded`): Published by the seeding CLI after
  a Tabiya import completes. This handler has two responsibilities: it streams `skill.fct.skill-created.v1`
  events through the outbox for all seeded skills (so BFF projections catch up), then queries
  Qdrant for already-embedded skills to avoid duplicate embedding work, batches the remainder into
  groups of two skills (six embedding items per batch), and publishes requests within the
  Kubernetes compute worker's eight-item inference limit. Consumer group:
  `skill-graph-bootstrap-seeded-primary`.

- **`skill.fct.mention-created.v1`** (`SkillMentionCreated`): Carries the result of a completed
  normalization including `canonical_id` and `source_type` (JOB or PROFILE). The handler
  increments `mention_count`, `job_count`, or `profile_count` on the canonical `skill_node`,
  keeping demand signals current for downstream scoring. Consumer group:
  `skill-graph-service-mention-primary`.

- **`skill.fct.alias-learned.v1`** (`AliasLearned`): Carries a raw alias string, its resolved
  `canonical_skill_id`, confidence score, and optional context hint. The handler upserts the alias
  into `skill_alias` using `(alias_text, context_hint)` as the uniqueness key, enabling the
  deterministic matching pipeline to recognize the alias on future normalization requests.
  Consumer group: `skill-graph-service-alias`.

- **`skill.cmd.skill-proposed.v1`** (`SkillProposed`): Published when normalization returns
  `NO_MATCH` and the caller includes a proposal payload with suggested canonical name, display
  name, aliases, and optionally an embedding. This service checks for near-duplicates in Qdrant
  (similarity threshold 0.85), reinforces an existing proposal if one already exists for the same
  `canonical_name`, or creates a new `proposed_skill` record. If a proposal reaches
  `AUTO_APPROVE_THRESHOLD` (5 sightings), it is promoted to a `skill_node`, and a triple embedding
  request (preferred label, description, alt labels) is published via `ml.cmd.batch-embedding-requested.v1`.
  Consumer group: `skill-graph-service-proposed`.

### Events Published

- **`skill.fct.skill-created.v1`** (`SkillCreated`): Published via the transactional outbox
  whenever a canonical skill is created, either via bootstrap seeding or auto-approval of a
  proposal. Carries a `CanonicalSkill` snapshot with normalized text, display name, category,
  skill type, reuse level, confidence score, and demand counters. `bff-service` consumes this to
  populate its skills projection table. Published via outbox; Debezium captures from WAL.

- **`SkillNormalizationCallback`** (to requester's `callback_topic`): Returned directly to
  `job-ingest.sys.skill-callback.v1` or `user-pref.sys.skill-callback.v1` depending on the
  originating service. Carries per-skill match results (canonical ID, match type, confidence),
  an aggregated embedding vector for the full skill set, and optionally a list of clarification
  requests for uncertain matches. Published via direct `kafka_client.publish` (not outbox).

### Notable Patterns

#### Two-Stage Callback Pattern (Normalization)

Normalization uses a nested callback pattern. The original requester publishes
`skill.cmd.normalization-requested.v1` with `callback_topic` set to its own skill callback topic.
This service either replies immediately (all deterministic matches) or initiates a secondary
request to `ml.cmd.batch-embedding-requested.v1` with `skill.sys.normalization-embedding-callback.v1`
as its own callback topic. The `NormalizationEmbeddingState`, containing the original requester's
`operation_id`, callback topic, and all partial match results, is serialized into the
`caller_context` field of the embedding command. When the embedding callback arrives, the state is
deserialized without any database lookups, Qdrant is queried, and the response is published to the
original requester's callback topic. Two separate embedding publishers (`get_batch_embedding_publisher`
and `get_normalization_embedding_publisher`) use distinct callback topics to prevent bootstrap and
normalization callbacks from interfering with each other.

#### Transactional Outbox

All `skill.fct.skill-created.v1` events are written via `OutboxWriter` in the same database
transaction as the `skill_node` INSERT. Debezium's PostgreSQL connector reads the WAL and publishes
events to Kafka, guaranteeing that the skill appears in downstream projections if and only if the
database commit succeeded.

#### Readiness Gate

The service blocks Kubernetes readiness (`/readyz`) until Qdrant contains at least one skill
embedding. `SkillEmbeddingReadinessGate` polls Qdrant every 5 seconds (configurable). This
prevents the normalization handlers from accepting work before the skills collection is
searchable, which would produce false `NO_MATCH` responses for every skill.

## State & Persistence

### Database

Schema `skill_graph_schema` stores the canonical skill taxonomy and its supporting structures.
`skill_node` is the central entity: each row is a deduplicated, lowercased canonical skill
name with quality metrics and ESCO-derived metadata. `skill_alias` maps surface variations to
canonical skills. `skill_relationship` forms a directed graph of skill dependencies and
co-occurrence edges. Governance tables (`proposed_skill`) stage novel skills before they enter
the taxonomy. Occupation data (`occupation_node`, `occupation_skill_relation`,
`occupation_skill_observation`) links skills to job roles for demand signal computation.

See [DATABASE.md](./DATABASE.md) for complete schema documentation.

### Vector Store

This service maintains two Qdrant collections. The **skills collection** stores dense embeddings
(dimensionality configured in the manifest) for every approved `skill_node`. Each point carries
the skill's `entity_id` (UUID), `normalized_text`, and ESCO metadata as payload. Search during
normalization uses dense vector similarity with a score threshold derived from the manifest's
`normalization.uncertain_min_threshold`. During bootstrap, the collection is populated in batches
of two skills (six embedding items per batch, covering preferred label, description, and alt
labels). The **occupations collection** stores embeddings for `occupation_node` entries,
enabling future job title → occupation inference.

Qdrant is populated exclusively through the `skill.sys.batch-embedding-callback.v1` handler --
never via direct writes from the normalization path or seeding pipeline.

### Redis

Redis is initialized via `RedisMixin` for circuit breaker state management on the Qdrant client.
No application-level caching or distributed locking is implemented beyond what `nohiki-qdrant-client`
provides internally.

## Key Design Patterns

### Four-Stage Normalization Cascade

Normalization applies stages in ascending cost order:

1. **Exact DB match** -- case-insensitive lookup of `skill_node.normalized_text`. O(1) index hit.
   Returns `CONFIDENT / EXACT`.

2. **Alias lookup** -- query `skill_alias` by `(alias_text, context_hint)`. The optional industry
   hint allows "python" to resolve differently in a data science vs. finance context.
   Returns `CONFIDENT / ALIAS`.

3. **Jaccard n-gram similarity** -- compares against up to 1,000 candidate skills fetched once
   per normalization batch. Threshold 0.92 was calibrated empirically to yield zero false positives
   on 60K distinct pairs. Catches common typographic variants ("reacts", "react js").
   Returns `AUTO_MATCH / JACCARD`.

4. **Qdrant semantic search**: only reached when stages 1-3 fail. The skill text is embedded via
   `ml.cmd.batch-embedding-requested.v1` (query mode), then searched against the skills collection.
   Scores above `auto_match_threshold` produce `AUTO_MATCH / SEMANTIC`; scores between
   `uncertain_min_threshold` and `auto_match_threshold` produce `UNCERTAIN` with a candidate list
   for LLM clarification; scores below `uncertain_min_threshold` produce `NO_MATCH`.

All skills in a normalization request are processed concurrently for stages 1-3 using
`asyncio.TaskGroup` with one DB session per skill to avoid shared-session contention.

### Skill Proposal Governance

New skills enter the taxonomy through a controlled workflow rather than direct insertion. When
normalization returns `NO_MATCH`, downstream services (primarily `job-ingest-enrichment-service`)
publish `skill.cmd.skill-proposed.v1` with the LLM's suggested canonical name and embedding.
This service:

1. Checks for near-duplicates in Qdrant at threshold 0.85 -- rejects proposals too similar to
   existing skills.
2. If no duplicate: creates a `proposed_skill` record with `status=pending`.
3. On subsequent proposals for the same `canonical_name`: increments `proposal_count` and
   accumulates `source_job_ids` as evidence.
4. At `proposal_count >= 5`: auto-approves the proposal, creates the `skill_node`, writes
   `skill.fct.skill-created.v1` to the outbox, and requests triple embedding for the new skill.

This design prevents noise skills from entering the taxonomy after a single mention while
allowing genuinely common skills to be promoted automatically.

### Bootstrap Seeding via Kubernetes Job

The initial skill taxonomy is seeded by running the CLI module embedded in the service container
as a Kubernetes Job, not as a separate image. The seeding CLI (`skill_graph_service.seeding.cli`)
reads Tabiya ESCO v1.1.1 CSV exports, upserts skills, aliases, skill-to-skill relationships, and
occupation-to-skill relations in batches of 1,000 rows, then publishes `skill.fct.skill-graph-seeded.v1`
to trigger embedding generation.

## Configuration

Settings are composed from these mixins: `DatabaseMixin`, `KafkaMixin`, `RedisMixin`,
`QdrantMixin`, `ManifestMixin`.

Key environment variables (prefix `SKILL_GRAPH_`):

| Variable | Purpose |
|----------|---------|
| `SKILL_GRAPH_DATABASE__URL` | PostgreSQL connection string for `skill_graph_schema` |
| `SKILL_GRAPH_QDRANT__HOST` | Qdrant host for skills and occupations collections |
| `SKILL_GRAPH_MANIFEST_PATH` | Path to `nohiki-ml-manifest` YAML (semantic thresholds, collection names) |
| `SKILL_GRAPH_NORMALIZATION__JACCARD_AUTO_MATCH` | Jaccard threshold (default 0.92; calibrate before changing) |
| `SKILL_GRAPH_NORMALIZATION__TOP_N_CANDIDATES` | Candidates returned for LLM clarification (default 5) |
| `SKILL_GRAPH_NORMALIZATION__MAX_JACCARD_CANDIDATES` | Skills fetched for Jaccard comparison (default 1,000) |
| `SKILL_GRAPH_READINESS_GATE__MIN_POINT_COUNT` | Qdrant points required before `/readyz` returns 200 (default 1) |
| `SKILL_GRAPH_READINESS_GATE__POLL_INTERVAL_SECONDS` | Seconds between Qdrant readiness polls (default 5.0) |
| `SKILL_GRAPH_KAFKA__CONSUMER__MAX_CONCURRENT_HANDLERS` | Concurrent Kafka handlers (default 5; ML callbacks are CPU-light) |

The semantic normalization thresholds (`auto_match_threshold`, `uncertain_min_threshold`) live in
the ML manifest rather than here, because they are model-dependent and change when the embedding
model is updated. Run `scripts/calibrate_skill_thresholds/` after a model change to re-derive them.

For bootstrap seeding, the Kubernetes Job requires:

| Variable | Purpose |
|----------|---------|
| `TABIYA_SKILLS_CSV` | Path to Tabiya `skills.csv` |
| `TABIYA_SOURCE_VERSION` | ESCO version string (e.g., `1.1.1`) |
| `TABIYA_RELATIONSHIPS_CSV` | (Optional) skill-to-skill relations |
| `TABIYA_OCCUPATION_SKILLS_CSV` | (Optional) occupation-to-skill relations |
| `TABIYA_OCCUPATIONS_CSV` | (Optional) occupation metadata |
| `TABIYA_SKILL_GROUPS_CSV` | (Optional) skill groups for category derivation |
| `TABIYA_SKILLS_HIERARCHY_CSV` | (Optional) skill hierarchy for subcategory derivation |

## Development

### Local Setup

```bash
uv sync
# Apply the schema migration
uv run --package skill-graph-service alembic upgrade head
```

Qdrant must be running and reachable at the address in `SKILL_GRAPH_QDRANT__HOST`. The service
blocks readiness until the skills collection contains at least one point; run the seeding CLI
or insert a test point before sending traffic.

### Bootstrap Seeding (Local)

```bash
TABIYA_SKILLS_CSV=/path/to/skills.csv \
TABIYA_SOURCE_VERSION=1.1.1 \
SKILL_GRAPH_DATABASE__URL=postgresql+asyncpg://... \
uv run --package skill-graph-service python -m skill_graph_service.seeding.cli
```

Optional CSVs can be omitted; category derivation and relationship seeding are skipped gracefully.

### Testing

```bash
# Run tests for this service only
just test skill-graph-service

# With coverage
just test-cov skill-graph-service
```

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise backend/services/skill-graph-service/
uv run ty check
```
