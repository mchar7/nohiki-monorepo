# Nohiki Qdrant Client

Wraps the Qdrant gRPC client for MUVERA + Sparse hybrid search, ColBERT MaxSim reranking, and
collection management. Vector names and roles derive from `QdrantCollectionSchema` at construction
time rather than from configuration, making the manifest the single source of truth for the search
topology. Search services use this library for reads (search, payload retrieval). The target write
boundary is lifecycle-owner direct mutation: jobs by `job-storage-service`, profiles by
`user-pref-service`, and skills/occupations by `skill-graph-service`. The current tree still has
legacy Qdrant Kafka sink artifacts; do not add new sink usage while that cleanup remains pending.

---

## Quick Start

### Hybrid search (job correlation)

```python
from nohiki_qdrant_client import QdrantVectorClient, QdrantSettings, SearchParams
from nohiki_ml_manifest import QdrantCollectionSchema

settings = QdrantSettings(host="qdrant", grpc_port=6334)
client = QdrantVectorClient(settings, collection_schema=schema)  # schema from manifest

results = await client.search_hybrid(
    query_muvera_fde=profile_muvera_fde,        # list[float], length 8192
    query_sparse_indices=profile_sparse_indices,  # list[int]
    query_sparse_values=profile_sparse_values,    # list[float]
    params=SearchParams(
        collection_name="jobs_jobs_semantic_repr_v1",
        limit=1000,
        filters={"is_active": True},
    ),
)

for r in results:
    print(r.id, r.score, r.payload["entity_id"])
```

### Upsert (skill-graph-service)

```python
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector
from nohiki_qdrant_client import UpsertPayload, VectorPoint, QdrantVectorClient

payload = UpsertPayload(
    entity_id="skill-uuid",
    entity_type="skill",
    collection_version="v1",
    content_hash="sha256-...",
    extra={"skill_id": "skill-uuid", "embedding_source": "label"},
)
point = VectorPoint(
    point_id="deterministic-uuid5",
    embeddings=[
        EmbeddingVector(
            embedding_type=EmbeddingType.MUVERA,
            dense=DenseData(values=[...]),  # 8192 floats
            collection_version="v1",
        )
    ],
    payload=payload,
)

count = await client.upsert_vector_points_batch(
    collection_name="skills_skills_semantic_repr_v1",
    points=[point],
    batch_size=100,
)
```

---

## Core Concepts

### Schema-driven vector dispatch

`QdrantVectorClient` requires a `QdrantCollectionSchema` at construction, sourced from
`nohiki-ml-manifest`. The schema tells the client which named vector slot each `EmbeddingType`
maps to (`MUVERA`/`DENSE` → `primary_dense_name`, `SPARSE` → `"sparse"`, `COLBERT` → `colbert_name`).
Services never hardcode vector names: the manifest is the source of truth.

Attempting to upsert an `EmbeddingType.SPARSE` vector when the schema has `has_sparse_vectors=False`
raises `ValueError` immediately, before any network call.

### Hybrid search with RRF fusion

`search_hybrid` runs two Qdrant `Prefetch` queries in a single network call: one against the MUVERA
FDE dense index, one against the sparse index, and fuses their rank lists using Qdrant's native
Reciprocal Rank Fusion (`models.Fusion.RRF`). This is the Stage 1 retrieval step in the
`job-correlation-evaluation-service` scoring pipeline, returning up to 1000 candidates before
ColBERT MaxSim reranking.

If sparse vectors are not present in the query (e.g., unavailable for a new profile), fall back to
`search_muvera_only`.

### Multi-stage ColBERT MaxSim

The `multivector` module supports Qdrant's native multi-vector ColBERT MaxSim reranking, eliminating
S3/Redis round-trips for token retrieval. Two variants exist:

- **`search_multistage`** -- Three-vector pipeline: MUVERA + Sparse prefetch with RRF fusion, then
  ColBERT MaxSim reranking in a single Qdrant query. Use when all three vector types are indexed.
- **`search_muvera_then_maxsim`** -- Two independent concurrent queries (MUVERA retrieval + MUVERA
  prefetch → MaxSim rerank) run via `asyncio.TaskGroup`. Returns both `muvera_score` and
  `maxsim_score` per result, which the L2R model uses as separate features.

Collections that support multi-stage search are created with `create_multivector_collection`, which
indexes all three vector types (`muvera`, `sparse`, `colbert`) and applies INT8 scalar quantization
for the MUVERA index.

### Payload structure and soft deletion

Every point carries a structured `UpsertPayload` with `entity_id`, `entity_type`,
`collection_version`, `content_hash`, and `is_active`. The `extra` field merges domain-specific
fields (e.g., `skill_id`, `embedding_source`, `job_type`) into the Qdrant payload, making them
available as filter targets.

Soft deletion via `set_points_inactive` sets `is_active=False` without removing the point. Searches
that pass `filters={"is_active": True}` exclude inactive points without collection rebuilds.

### Grouped search for skill deduplication

`search_grouped` wraps Qdrant's native `group_by` feature. `skill-graph-service` stores each skill
with three embedding variants (label, description, alt\_labels) as separate points. `search_grouped`
with `group_by="skill_id"` and `group_size=1` returns the best-matching variant per skill, collapsing
triplicate points server-side rather than in Python.

### Filter builder

`build_filter` converts a plain Python dict to a Qdrant `Filter` object. Supported value types:

| Value type | Qdrant operator |
|------------|----------------|
| `bool`, `str`, `int` | `MatchValue` (exact match) |
| `list[str \| int]` | `MatchAny` |
| `{"$gt": v}`, `{"$gte": v, "$lte": v}` | `Range` |
| `{"$gte": datetime(...)}` | `Range` (converted to Unix timestamp) |
| `None` | Condition omitted |

`build_filter_with_should` adds support for `must`, `should`, and `must_not` clause groupings.

### Transport and connection

`create_async_qdrant_client` returns a raw `AsyncQdrantClient` configured for gRPC transport
(`prefer_grpc=True`). All operations go over gRPC port 6334 by default. TLS and API key are
optional toggles -- `QdrantMixin` enforces that `QDRANT__API_KEY` is set in non-development
environments.

Use `create_async_qdrant_client` directly (without `QdrantVectorClient`) for schema-free operations
such as health probes and collection management in initialization scripts.

---

## API Reference

### Search

- **`QdrantVectorClient.search_hybrid(query_muvera_fde, query_sparse_indices, query_sparse_values, params)`** --
  MUVERA + Sparse hybrid search with RRF fusion. Raises `ValueError` if the schema has no sparse
  vectors. Returns `list[HybridSearchResult]`.

- **`QdrantVectorClient.search_muvera_only(collection_name, query_muvera_fde, limit, filters, score_threshold)`** --
  Dense-only fallback when sparse vectors are unavailable.

- **`QdrantVectorClient.search_dense(query_vector, params)`** --
  Single dense vector search. Used by `skill-graph-service` for occupation similarity.
  `params.vector_name` overrides the schema's primary dense name.

- **`QdrantVectorClient.search_dense_batch(queries, params)`** --
  Sends all queries in a single `query_batch_points` gRPC call. Returns
  `list[list[HybridSearchResult]]` in the same order as input. Skill normalization uses this to
  batch all candidate embeddings in one round-trip.

- **`QdrantVectorClient.search_grouped(query_vector, params)`** --
  Dense search with Qdrant-native `group_by`. `GroupedSearchParams` extends `SearchParams` with
  `group_by: str` and `group_size: int`. Returns one result per group (the best hit per group\_by
  field value).

### Multi-stage (ColBERT MaxSim)

These functions operate on the raw `AsyncQdrantClient` (not `QdrantVectorClient`) and require a
collection created with `create_multivector_collection`.

- **`search_multistage(client, collection_name, query)`** --
  Full three-vector pipeline: MUVERA + Sparse RRF prefetch → ColBERT MaxSim rerank, in one Qdrant
  query. `MultiStageQuery.prefetch_limit` controls the candidate pool; `final_limit` controls the
  reranked output. Returns `list[MultiStageSearchResult]` with both `muvera_score` and `maxsim_score`.

- **`search_muvera_then_maxsim(client, collection_name, query)`** --
  Two concurrent queries via `asyncio.TaskGroup` -- MUVERA-only retrieval and MUVERA → MaxSim
  rerank, providing both score signals for the L2R model. Use `MuveraMaxSimQuery` as input.

### Upsert and mutation

- **`QdrantVectorClient.upsert_vector_point(collection_name, point)`** --
  Upsert a single `VectorPoint`. Blocks until Qdrant confirms (`wait=True`). Dispatches each
  `EmbeddingVector` to the correct named vector slot using schema-driven `match-case`.

- **`QdrantVectorClient.upsert_vector_points_batch(collection_name, points, batch_size=100)`** --
  Upsert multiple points in sequential chunks of `batch_size`. Each chunk blocks before the next.
  Returns the total number of points upserted.

- **`QdrantVectorClient.set_points_inactive(collection_name, point_ids)`** --
  Soft-delete: sets `is_active=False` via `set_payload`. Points remain in the index.

- **`QdrantVectorClient.delete_points(collection_name, point_ids)`** --
  Hard delete. Points are removed from the index entirely.

### Point retrieval

- **`QdrantVectorClient.get_point(collection_name, point_id)`** --
  Returns payload dict or `None` if not found.

- **`QdrantVectorClient.get_points_batch(collection_name, point_ids)`** --
  Batch retrieve payloads in one `retrieve` call. Returns `dict[str, dict[str, Any]]` mapping
  point ID to payload. Missing points are omitted.

- **`QdrantVectorClient.point_exists(collection_name, point_id)`** --
  Convenience wrapper over `get_point`.

- **`QdrantVectorClient.retrieve_vectors(collection_name, point_ids, vector_name=None)`** --
  Retrieve raw dense vector values (not payloads) by point ID. Used by `skill-graph-service` to
  compare stored embeddings for deduplication.

- **`QdrantVectorClient.count_points(collection_name, filters=None)`** --
  Exact count (not approximate) matching the filter.

### Collection management

Collection creation is normally handled by the `infra/shared/qdrant-init/` initialization scripts
rather than service code. These functions are exported for initialization and migration tooling:

- **`create_collection_from_manifest(client, config)`** -- Sync. Creates a MUVERA + Sparse collection
  from a `CollectionConfig`. Sets up INT8 scalar quantization and all `PAYLOAD_INDEX_SCHEMAS` indexes.

- **`create_multivector_collection(client, config)`** -- Async. Creates a MUVERA + Sparse + ColBERT
  multi-vector collection for MaxSim reranking. ColBERT uses `MAX_SIM` comparator with HNSW disabled
  (`m=0`, exhaustive scan).

- **`update_alias(client, alias_name, new_collection_name)`** -- Atomic alias swap for zero-downtime
  model migrations. Deletes then creates the alias in a single `update_collection_aliases` call.

- **`get_collection_name(entity_type, semantic_repr_id)`** --
  Produces deterministic collection names: `{entity_type}_{sanitized_semantic_repr_id}`.
  E.g., `get_collection_name("jobs", "jobs.semantic_repr.v1")` → `"jobs_jobs_semantic_repr_v1"`.

### Health

- **`QdrantHealthProbe`** -- Implements the `HealthProbe` protocol from `nohiki-common-exceptions`.
  `check()` calls `get_collections()` to verify connectivity and optionally asserts that a list of
  named collections exist. Returns `HealthProbeResult` with latency.

- **`ensure_qdrant_ready(client, timeout_seconds=30.0, retry_interval_seconds=2.0, required_collections=None)`** --
  Polls `QdrantHealthProbe.check()` until healthy or `timeout_seconds` elapses, then raises
  `RuntimeError`. Call this during FastAPI lifespan startup before registering Kafka consumers.

### Settings types

- **`QdrantSettings`** -- Pydantic `BaseModel` for connection parameters.
- **`QdrantMixin`** -- Pydantic settings mixin for services that connect to Qdrant.

### Data types

- **`VectorPoint`** -- Topology-agnostic point for upsert. Carries `point_id: str`, `embeddings:
  list[EmbeddingVector]`, and `payload: UpsertPayload`.
- **`UpsertPayload`** -- Structured payload with standard fields plus `extra: dict | None` for
  domain-specific fields. `to_dict()` merges `extra` into the base dict.
- **`HybridSearchResult`** -- Frozen dataclass: `id: str`, `score: float`, `payload: dict`.
- **`MultiStageSearchResult`** -- Frozen dataclass: `id: str`, `muvera_score: float`,
  `maxsim_score: float`, `payload: dict`.
- **`SearchParams`** -- `collection_name`, `limit`, `filters`, `score_threshold`, `vector_name`.
- **`GroupedSearchParams`** -- Extends `SearchParams` with `group_by: str`, `group_size: int`.

---

## Configuration

### QdrantSettings

Direct connection configuration. Collection and vector names come from the manifest, not from here.

```python
class QdrantSettings(BaseModel):
    host: str = "qdrant"
    grpc_port: int = 6334
    api_key: SecretStr | None = None
    timeout_seconds: int = 10
    use_tls: bool = False
```

### QdrantMixin

Add to a service's settings class to expose `settings.qdrant: QdrantSettings`:

```python
from nohiki_qdrant_client import QdrantMixin
from nohiki_core_settings import NohikiBaseSettings

class Settings(NohikiBaseSettings, QdrantMixin):
    ...
```

Environment variables (all prefixed with the service prefix):

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT__HOST` | `"qdrant"` | Hostname or IP |
| `QDRANT__GRPC_PORT` | `6334` | gRPC port |
| `QDRANT__API_KEY` | `None` | Required in non-dev environments |
| `QDRANT__TIMEOUT_SECONDS` | `10` | Per-operation timeout |
| `QDRANT__USE_TLS` | `false` | Enable TLS (or rely on service mesh mTLS) |

`QdrantMixin` raises `ValueError` at settings parse time if `QDRANT__API_KEY` is absent in any
environment outside `DEVELOPMENT_ENVIRONMENTS`.

---

## Testing

Tests mock `AsyncQdrantClient` directly with `unittest.mock.patch`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
from nohiki_qdrant_client import QdrantSettings, QdrantVectorClient, SearchParams
from nohiki_ml_manifest import QdrantCollectionSchema, QdrantVectorDefinition

def make_schema() -> QdrantCollectionSchema:
    return QdrantCollectionSchema(
        vectors={"muvera": QdrantVectorDefinition(size=8192, distance="Dot")},
        has_sparse_vectors=True,
        primary_dense_name="muvera",
        colbert_name=None,
    )

@pytest.mark.asyncio
async def test_search_hybrid() -> None:
    with patch("nohiki_qdrant_client.client.AsyncQdrantClient") as mock_qdrant:
        mock_instance = AsyncMock()
        mock_point = MagicMock()
        mock_point.id = "job-1"
        mock_point.score = 0.9
        mock_point.payload = {"entity_id": "job-1"}
        mock_instance.query_points.return_value = MagicMock(points=[mock_point])
        mock_qdrant.return_value = mock_instance

        client = QdrantVectorClient(QdrantSettings(), make_schema())
        results = await client.search_hybrid(
            query_muvera_fde=[0.1] * 8192,
            query_sparse_indices=[1, 5],
            query_sparse_values=[0.5, 0.3],
            params=SearchParams(collection_name="jobs_v1", limit=10),
        )
        assert results[0].id == "job-1"
```

`QdrantVectorClient` instantiates `AsyncQdrantClient` in `__init__`, so the patch target is
`nohiki_qdrant_client.client.AsyncQdrantClient` (not the qdrant\_client module directly).

`build_filter` and `build_filter_with_should` have no external dependencies and test without mocking.

---

## Design Decisions

### Schema-driven instead of configuration-driven vector names

Earlier iterations passed vector names as string arguments to every method. This created silent
mismatches between what a service thought a collection contained and what the manifest specified.
Deriving vector names from `QdrantCollectionSchema` at construction time means a schema change in
the manifest propagates automatically: the client raises `ValueError` immediately if a vector type
is requested that the schema doesn't declare, rather than sending a malformed query to Qdrant.

### Native MaxSim over external token retrieval

The alternative to `search_multistage` is fetching ColBERT tokens from S3 or Redis and computing
MaxSim locally in Python. Qdrant's native MaxSim is SIMD-optimized in Rust and avoids the
additional network round-trips. The trade-off is approximately 20× the storage footprint for full
ColBERT token vectors versus MUVERA-only collections. On-disk storage (`on_disk=True`) with INT8
scalar quantization keeps memory footprint manageable.

### Soft deletion over hard deletion

Job listings can be re-activated (e.g., relisted after expiry). `set_points_inactive` preserves the
vector while filtering it from active searches, avoiding the re-embedding cost of a hard delete
followed by a re-insert.
