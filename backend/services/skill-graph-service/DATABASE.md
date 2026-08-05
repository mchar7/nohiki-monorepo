# Skill Graph Database Design

Schema `skill_graph_schema` is owned by `skill-graph-service`. It is the source of truth for the canonical skill
taxonomy, alias resolution, skill-to-skill graph, taxonomy provenance, governance of novel skills, and
occupation-to-skill evidence. It also holds the transactional outbox used to announce taxonomy changes and the
idempotency records used by Kafka consumers.

The canonical skill registry is the graph's vertex set. Aliases and skill relationships hang from that registry, while
occupation data forms a largely independent subgraph joined through canonical skills. Embeddings are not stored in
PostgreSQL: skill and occupation vectors live in Qdrant.

## Canonical Taxonomy and Normalization

### Canonical skills

A canonical skill is the authoritative, deduplicated identity for a skill. References from job listings, user
preferences, correlation features, and BFF projections use the canonical skill UUID rather than copying the skill text.

Canonical text is lowercase, trimmed, single-spaced, and excludes quotes. There is exactly one canonical identity for
each such form, which makes exact-match normalization and repeated inserts idempotent regardless of the write path. A
separate display label preserves human-friendly capitalization and spacing. ESCO imports also contribute taxonomy
classification, reuse, category, and subcategory metadata; skills promoted through governance may not have that taxonomy
context. Quality confidence is retained for ranking and future model-derived scoring.

The normalization pipeline depends on several distinct access patterns:

1. Stage 1 resolves exact canonical text.
2. Stage 2 resolves aliases, including context-specific aliases before the universal fallback.
3. Stage 3 scans the canonical corpus for Jaccard candidates.

Candidate ranking can use quality confidence. Demand counters record total mentions and distinguish job-listing demand
from profile demand, allowing downstream scoring and BFF views to surface trending skills. First-seen and last-seen
times bound skill activity, with the latter refreshed on every `SkillMentionCreated` event.

Canonical skills enter the registry through Tabiya taxonomy seeding or when governance approves a proposal after at
least five distinct observations. Seeded skills and automatically promoted proposals enter as approved. Proposal
promotion also initiates the triple-embedding flow and records a skill-created event in the outbox. During normal
operation, mention events update demand and activity signals, but canonical skills are not deleted; removal occurs only
with a full schema drop.

The approved population is expected to dominate, so governance access is optimized around the small set that still needs
review rather than the full registry. The registry is append-heavy, and UUIDv7 creation ordering correlates physical row
order with creation time; this is why low-overhead time-range access is favored over a large general-purpose time index.

### Aliases

Aliases map observed surface forms such as "ReactJS" to a canonical identity such as "react" and provide deterministic
normalization without fuzzy computation. Resolution lowercases the input, tries an alias scoped to the supplied industry
or category context, and then falls back to a universal alias. The same surface form may resolve differently in
different contexts, but it is unambiguous within a context.

Alias records retain their origin. Tabiya alternative labels, aliases suggested by approved proposals, and dynamically
learned aliases can therefore be distinguished, and a learned alias may retain the originating job listing for evidence
traceability. Repeated evidence reinforces an existing alias: an upsert increases confidence by 0.01 up to 1.0, while
both upserts and successful resolutions contribute to its usage signal. Forward traversal from a canonical skill
supplies all known forms for exports and BFF display.

Tabiya seeding creates aliases from ESCO alternative labels. Governance approval may attach up to five suggested aliases
to the promoted skill. During live operation, `skill.fct.alias-learned.v1` causes `handle_alias_learned` to create or
reinforce the relevant mapping. An alias has no lifecycle independent of its canonical skill and is removed if that
skill is removed.

### Skill relationships

Skill relationships are an adjacency-list graph of typed, directed edges between canonical skills. The edge vocabulary
distinguishes hierarchy, association, requirements, and optional knowledge. Each stored edge has an explicit source and
target. A symmetric marker means traversal in either direction is semantically valid, but it does not make the stored
pair undirected; directional hierarchy still requires the appropriate edge direction.

Relationships also carry a strength signal for traversal and ranking. Seeded relationships use full strength; the signal
is reserved for future model-derived edge weighting.

Only one edge of a given meaning may exist for an ordered pair, although edges with different meanings may coexist.
Self-edges are excluded because they create trivial cycles and undermine traversal. Removing a canonical skill also
removes every incident edge.

Relationships are imported from the Tabiya ESCO taxonomy. Live normalization does not infer or add new graph edges, so
the seeded taxonomy remains the source of truth between imports.

## Governance, Provenance, and Seeding

### Novel-skill governance

`proposed_skill` is the audit-preserving staging area between LLM extraction and the canonical registry.
`job-ingest-enrichment-service` proposes an unresolved skill through `skill.cmd.skill-proposed.v1`. Proposals retain the
service or mechanism that introduced them and use a normalized canonical name, so repeated evidence reinforces one
proposal rather than creating parallel candidates. Contributing job IDs are retained and deduplicated, preventing one
job from inflating the evidence count.

The configurable auto-approval threshold is five distinct proposals. The state machine permits `pending -> approved` and
`pending -> rejected -> pending`; the latter allows a rejected candidate to return to review when new evidence warrants
it. A successful promotion retains a forward link from the audit record to the resulting canonical skill.

Approval is atomic: the service creates the canonical skill, adds up to five suggested aliases, marks the proposal
approved, and writes `skill.fct.skill-created.v1` to the outbox in the same transaction. If a canonical skill is later
removed, the proposal history remains even though its forward link no longer resolves. Proposal records are otherwise
retained indefinitely as the review and evidence trail.

### Taxonomy provenance

Every seeded canonical skill is linked to the named taxonomy source and version that introduced it, including the
external identifier and URI needed for cross-reference, editorial review, and update detection. A skill present in
multiple taxonomy sources keeps separate provenance for each source rather than collapsing their identities.

Sources have an ordered authority. Lower authority numbers have higher precedence, and the highest-authority source wins
when display labels or taxonomy metadata disagree. There is one provenance association per skill and source. Provenance
is created during seeding and has no lifecycle independent of the canonical skill.

### Seed lifecycle and observability

A seed batch record represents one taxonomy source and version and prevents duplicate lifecycle records for the same
import. It moves from pending to running and then to either completed or failed. Cumulative outcomes report skills and
occupations added or updated, aliases and relationships added, and errors; failures retain diagnostic detail without
requiring operators to scan the full taxonomy.

Operational monitoring should focus on in-flight and failed imports, their error counts and details, and the cumulative
outcomes for the source version. Completed imports remain available as an import history and comparison point for later
taxonomy versions.

## Occupation Model

Occupation data supports job-title-to-occupation inference and constrains skill normalization to the roughly 50-200
skills relevant to an inferred role instead of searching all roughly 13,890 canonical skills. Curated taxonomy
associations and empirical live observations are deliberately kept separate and combined only during inference.

### Curated occupation-to-skill associations

Curated associations are the authoritative ESCO statement of how a canonical skill relates to an occupation. Their
semantics distinguish skills required by the occupation, skills that are beneficial but optional, and skills merely
mentioned in its description. Normalization defaults to the strongest, required associations when pre-filtering, while
the correlation pipeline can use the broader relationship semantics.

Associations are independently queryable by ESCO occupation code and can also be traversed from a skill to the
occupations that use it. The occupation label is intentionally repeated on the association so the common
occupation-to-skills path avoids a join. Source-specific metadata and source/version provenance support editorial
traceability and re-seeding comparisons, and multiple taxonomy sources may contribute the same occupation-skill pair
without colliding.

Curated associations are created by the Tabiya ESCO import and do not change through live event handling. They are
removed if their canonical skill is removed.

### Empirical occupation observations

Empirical observations accumulate occupation-skill co-occurrences from live job listings and are not a replacement for
curated taxonomy data. One running observation exists for each occupation-skill pair; later sightings increment it
instead of producing duplicates. The record also preserves the dominant observed relationship semantics and the first
and last observation times for freshness-sensitive decisions.

`OccupationService` combines curated associations with empirical observations during inference. An empirical pair must
have at least three observations before it participates, suppressing noise from one-off listings. Observation volume and
recency are therefore the principal operational signals for live occupation evidence. Observations are removed if their
canonical skill is removed.

### Occupation catalog and vector boundary

Occupation nodes represent both ESCO job-role concepts and locally defined occupation concepts used to infer an
occupation from a job title. Official and alternative titles provide the text used during bootstrap embedding, while
ISCO grouping supports broader occupational classification. The relational catalog also supports title search for BFF
queries and retains taxonomy provenance for re-seeding.

Occupation embeddings live in the Qdrant occupations collection, not PostgreSQL. Vector similarity against a job title
selects likely occupation codes, which then connect to curated and empirical skill evidence in PostgreSQL. Occupation
nodes are imported during Tabiya seeding and remain static between seed runs; live handlers do not update them.

## Event Delivery and Consumer Idempotency

Canonical skill creation uses the transactional outbox pattern. Whether creation happens during bootstrap seeding or
proposal approval, the canonical skill and its `skill.fct.skill-created.v1` outbox event are recorded in one database
transaction. A failed commit records neither; a successful commit makes both visible together.

Debezium reads the PostgreSQL WAL and routes the outbox event to Kafka through the Outbox Event Router SMT. This
atomicity covers the database state and the intent to publish; relay and consumer processing remain asynchronous.
Consumers therefore use `processed_events` message IDs to skip redelivery and prevent repeated side effects.

`bff-service` consumes skill-created events to populate its skills projection. `job-correlation-evaluation-service`
consumes them to refresh its local skill index. Connector configuration lives under
`infra/k8s/kafka-connect/connectors/`.

The schema itself is defined by the service's SQLAlchemy models in
`backend/services/skill-graph-service/src/skill_graph_service/db/models.py` and Alembic revision
`backend/services/skill-graph-service/alembic/versions/001_initial_migration.py`.
