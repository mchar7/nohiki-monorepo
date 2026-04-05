# Nohiki ML Core

Provides the ML encoding implementations used across Nohiki's retrieval pipeline: ColBERT token
encoders, MUVERA fixed-dimensional encoding, sparse vector encoding, dense sentence embeddings,
and a PLAID batch index for offline scoring. The primary consumer is `ml-compute-service`, which
executes encoding in response to `ml.sys.kubernetes-compute` Kafka commands routed by
`ml-gateway-service`.

## Quick Start

```python
from nohiki_ml_core.pipeline import MLEncodingPipeline
from nohiki_ml_manifest import SemanticRepresentationManifest

# Load manifest (from file or Pydantic settings)
manifest = SemanticRepresentationManifest.model_validate_json(
    Path("/app/config/manifest.json").read_text()
)

# Initialize once per process. Models load lazily on the first encode call
pipeline = MLEncodingPipeline(manifest=manifest)

# Warm up ColBERT and sparse models before accepting requests
pipeline.colbert.warm_up()
pipeline.sparse.warm_up()

# Encode a job listing (document mode)
result = pipeline.encode_document(
    text="Senior Python Engineer -- distributed systems, Kafka, PostgreSQL...",
    entity_id="listing-abc123",
)
# result.colbert_tokens  → np.ndarray shape (num_tokens, 48)  -- ColBERT per-token embeddings
# result.muvera_fde      → np.ndarray shape (8192,)           -- MUVERA fixed-dim vector for ANN
# result.sparse_vector   → SparseVector(indices=[...], values=[...])
# result.content_hash    → str  -- SHA-256 of normalized text

# Encode a user profile (query mode: asymmetric aggregation)
query_result = pipeline.encode_query(text="senior python developer kafka")

# Encode a skill name (dense only: no ColBERT/MUVERA/sparse)
dense_result = pipeline.encode_dense(text="Apache Kafka", entity_id="skill-xyz")
# dense_result.dense_embedding → np.ndarray shape (1024,)
```

## Core Concepts

### Manifest-Driven Configuration

Every encoder reads all parameters, including model IDs, token dimensions, MUVERA geometry, and
distance metrics, from a `SemanticRepresentationManifest` (defined in `nohiki-ml-manifest`). No
encoder accepts these values as constructor arguments. This guarantees that a single manifest
change propagates consistently to all encoders without touching encoder code. The manifest also
declares which Qdrant collection each entity type maps to and which vector names to use.

### Lazy Model Loading

Encoders do not load model weights at construction time. The first call to `encode_document()`
or `encode_query()` triggers the actual model download and GPU/CPU placement. Call `warm_up()`
during service startup to front-load this latency rather than hitting it on the first live request.
The `ModelCacheManager` handles pre-fetching model weights from S3 (or downloading from
HuggingFace/PyPI on first deployment) before `warm_up()` is called.

### Inference Backends

`ColBERTEncoder` and `DenseEncoder` support two backends, selected by the manifest:

- **`DIRECT`** -- loads the model in-process using PyLate (ColBERT) or sentence-transformers
  (Dense). ColBERT requires DIRECT so PyLate preserves distinct query and document encoding
  semantics. Requires the `[inference]` extra. Used by `ml-compute-service` pods.
- **`ONNX`** -- runs Dense models through ONNX Runtime.
- **`TEI`** -- calls Text Embeddings Inference over HTTP for Dense embeddings.

`MUVERAEncoder` and `SparseEncoder` always run locally and always require the `[inference]` extra.
Backend selection is transparent to `MLEncodingPipeline`; it dispatches each encoder through its
supported manifest backend.

### Asymmetric Encoding (Document vs. Query)

ColBERT and MUVERA encoding is asymmetric: document encoding and query encoding produce
different representations even for identical text, because they use different aggregation
strategies tuned for MaxSim similarity computation.

- `encode_document()` -- uses `is_query=False` for ColBERT, then AVG aggregation in MUVERA.
- `encode_query()` -- uses `is_query=True` for ColBERT, then SUM aggregation in MUVERA.

Passing a document through `encode_query()` or vice versa produces embeddings that will not
score correctly against their counterparts in Qdrant. Always use the right encoding mode.

### MUVERA Distance Metric

MUVERA FDE vectors stored in Qdrant **must** use **DOT product** distance, not Cosine. The
MUVERA asymmetric encoding is not length-normalized; Cosine normalization would destroy the
encoding's accuracy guarantees. This is enforced in the manifest's Qdrant collection config,
but worth knowing if you ever inspect Qdrant collection parameters directly.

### Content Hash

`MLEncodingPipeline` computes a SHA-256 hash of the lowercased, whitespace-stripped input text
and includes it in every result. Downstream services (`job-correlation-evaluation-service`,
`skill-graph-service`) compare this hash against stored hashes to detect whether re-encoding
is required. Staleness detection also requires checking `collection_version` from the
manifest, because a model or MUVERA geometry change produces a different representation even for
identical text. See `nohiki-ml-manifest` for the full staleness logic.

## API Reference

### MLEncodingPipeline

The main entry point. Instantiate once per process with a manifest.

```python
from nohiki_ml_core.pipeline import MLEncodingPipeline

pipeline = MLEncodingPipeline(manifest=manifest)
```

**Methods:**

- **`encode_document(text, entity_id) -> EncodingResult`** -- Full retrieval encoding for a
  document: ColBERT tokens → MUVERA FDE → sparse vector. Use for job listings, user profiles.
- **`encode_query(text) -> EncodingResult`** -- Full retrieval encoding for a query using
  asymmetric (SUM-aggregated MUVERA) mode. Use for search queries.
- **`encode_dense(text, entity_id) -> DenseEncodingResult`** -- Dense-only encoding. Use for
  skills, job titles, and any entity that does not require multi-vector retrieval.
- **`encode_dense_batch(texts, entity_ids, batch_size=32) -> DenseBatchEncodingResult`** -- Encodes
  multiple texts in a single model forward pass. Use when processing many items at once (e.g.,
  batch skill normalization) to avoid N sequential inference calls.

**Result types:**

- **`EncodingResult`** -- Frozen dataclass: `colbert_tokens: np.ndarray`, `muvera_fde: np.ndarray`,
  `sparse_vector: SparseVector`, `content_hash: str`.
- **`DenseEncodingResult`** -- Frozen dataclass: `dense_embedding: np.ndarray`, `content_hash: str`.
- **`DenseBatchEncodingResult`** -- Frozen dataclass: `dense_embeddings: np.ndarray` (shape
  `(n, dim)`), `content_hashes: list[str]`.

**Direct encoder access:** `pipeline.colbert`, `pipeline.muvera`, `pipeline.sparse`,
`pipeline.dense` are all public attributes. `ml-compute-service` calls
`pipeline.colbert.warm_up()` and `pipeline.sparse.warm_up()` explicitly during startup.

### ColBERTEncoder

Produces per-token embeddings for late interaction (MaxSim) similarity. ColBERT runs directly
through PyLate so query and document encoding retain their distinct model semantics. Every text
becomes a matrix of vectors, with one vector per token, rather than a single pooled vector. This
matrix is used both directly and as input to `MUVERAEncoder`.

```python
from nohiki_ml_core.encoders.colbert import ColBERTEncoder

encoder = ColBERTEncoder(manifest)

tokens = encoder.encode_document("Senior Python Engineer")
# tokens.shape == (num_tokens, token_dim)  e.g. (37, 48)

query_tokens = encoder.encode_query("python engineer")
# query_tokens.shape == (num_query_tokens, token_dim)

batch = encoder.encode_batch(["text one", "text two"], is_query=False, batch_size=8)
# list of np.ndarray, each shape (num_tokens, token_dim)
```

**Constructor raises:**

- `ValueError` -- ColBERT backend is not `DIRECT`.
- `MissingLocalDependencyError` -- PyLate is not installed.

### MUVERAEncoder

Converts a ColBERT token matrix into a single fixed-dimensional vector (FDE) suitable for
approximate nearest-neighbor (ANN) search in Qdrant. Takes the output of `ColBERTEncoder`
directly as input, never raw text.

```python
from nohiki_ml_core.encoders.muvera import MUVERAEncoder

encoder = MUVERAEncoder(manifest)

# Always pass ColBERT token output, never raw text
fde = encoder.encode(colbert_tokens, is_query=False)
# fde.shape == (output_dimension,)  -- computed from manifest as 2^k_sim * dim_proj * r_reps

print(encoder.output_dimension)  # e.g. 8192
```

Output dimension is derived from manifest parameters `k_sim`, `dim_proj`, and `r_reps`. With
the default manifest (`k_sim=6, dim_proj=16, r_reps=8`) the output is `2^6 * 16 * 8 = 8192`.

**Constructor raises:** `MissingLocalDependencyError` if `fastembed` is not installed.

### SparseEncoder

Produces learned sparse embeddings (token ID → weight maps) for keyword-sensitive retrieval.
Significantly outperforms BM25 on domain-specific vocabulary. The default model
(`Qdrant/minicoil-v1`) can be overridden via the manifest's `sparse.model_id` field.

```python
from nohiki_ml_core.encoders.sparse import SparseEncoder, SparseVector

encoder = SparseEncoder(manifest)

vector = encoder.encode("Apache Kafka distributed streaming")
# SparseVector(indices=[1024, 5821, ...], values=[0.82, 0.61, ...])

batch = encoder.encode_batch(["text one", "text two"])
# list[SparseVector]

# Compute sparse similarity directly (not used in retrieval, useful in tests)
score = vector.dot_product(other_vector)  # O(n + m) intersection
```

When `manifest.sparse.enabled` is `False`, both `encode()` and `encode_batch()` return empty
`SparseVector` instances without loading any model.

**Constructor raises:** `MissingLocalDependencyError` if `fastembed` is not installed and
`enabled=True`.

### DenseEncoder

Encodes text into a single pooled dense vector for semantic similarity. Used for skills,
occupations, and any entity requiring standard cosine similarity rather than multi-vector
MaxSim. Supports DIRECT (sentence-transformers), ONNX quantized, and TEI HTTP backends.

```python
from nohiki_ml_core.encoders.dense import DenseEncoder

encoder = DenseEncoder(manifest)

embedding = encoder.encode("Software Engineer")
# np.ndarray shape (embedding_dim,)  e.g. (1024,)

batch = encoder.encode_batch(["text one", "text two"], batch_size=32)
# np.ndarray shape (n, embedding_dim)

similarity = encoder.compute_similarity("python developer", "software engineer")
# float in [0, 1] -- cosine similarity
```

### GPU Detection

`ml-compute-service` calls these at startup to determine the available compute backend and
fail fast if a GPU is configured but absent:

```python
from nohiki_ml_core import (
    ComputeBackend,
    GpuNotAvailableError,
    detect_gpu_capabilities,
    get_available_backend,
    validate_compute_backend,
)

caps = detect_gpu_capabilities()
# GpuCapabilities(cuda_available=True, device_count=1, device_names=('A100',), ...)

backend = get_available_backend()
# ComputeBackend.CUDA or ComputeBackend.CPU

# Fail fast during startup if GPU is explicitly required but unavailable
try:
    validate_compute_backend(ComputeBackend.CUDA)
except GpuNotAvailableError as e:
    logger.error("GPU not available", reason=e.reason)
    raise
```

`detect_gpu_capabilities()` is cached after the first call. Call `reset_gpu_detection_cache()`
in tests to clear it between test cases.

### ModelCacheManager

Handles model weight distribution across pods using a three-tier strategy: local disk cache
(checked first), S3 shared bucket (downloaded under a Redis distributed lock so only one pod
fetches at a time), and upstream source (HuggingFace Hub or PyPI, only on first-ever deployment
or when the manifest changes). The service provides a `SourceDownloader` callback that performs
the actual upstream download using its heavy ML libraries -- `ModelCacheManager` itself has no
dependency on PyLate or fastembed.

```python
from nohiki_ml_core.model_cache import ModelCacheManager

manager = ModelCacheManager(
    s3_client=s3_client,
    redis_cache=redis_cache,
    cache_dir=Path("/models"),
    manifest=manifest,
    source_downloader=my_download_callback,  # service-provided async callable
)

# Call once during service lifespan startup, before warm_up()
await manager.ensure_models_available()
```

Cache invalidation is manifest-driven: if any model ID or dimension changes in the manifest,
the manifest hash changes and `ensure_models_available()` re-downloads all model archives.

### PLAID Batch Index

For offline batch scoring (nightly re-scoring of all profiles against all jobs), the `batch`
submodule provides a PyLate PLAID index wrapper that is 5x faster than online Qdrant search for
throughput-optimized scenarios:

```python
from nohiki_ml_core.batch import PLAIDIndex, PLAIDIndexConfig, PLAIDRetriever

config = PLAIDIndexConfig(
    index_folder="/data/plaid-indexes",
    index_name="jobs_v1",
)

# Build from document ColBERT tokens
index = PLAIDIndex(config)
index.build(document_ids=["doc-1", "doc-2"], document_embeddings=[tokens1, tokens2])

# Batch retrieval
retriever = PLAIDRetriever(index)
results = retriever.retrieve_batch(queries_embeddings=[q1_tokens, q2_tokens], k=100)
# list[list[RetrievalResult(document_id=..., score=...)]]

# Score specific pairs (avoids IVF over-fetch)
pairs = retriever.score_pairs(query_embeddings=[q_tokens], document_ids=["doc-1", "doc-2"])
```

`PLAIDIndexMetrics` emits three OTel metrics for index health monitoring:
`nohiki_plaid_cluster_threshold` (75th percentile L2 residual norm). Rising values indicate
codebook staleness after `add_documents()` calls. The other metrics are
`nohiki_plaid_docs_since_rebuild_total` and `nohiki_plaid_rebuilds_total`. FastPlaid's incremental `add_documents()` does
not recompute centroids, so the cluster threshold metric is the signal for when a full rebuild
is needed.

### Seniority Derivation

```python
from nohiki_ml_core.seniority import derive_seniority_level
from nohiki.common.v1 import SeniorityLevel

level = derive_seniority_level(min_years=3)  # SeniorityLevel.MID
level = derive_seniority_level(min_years=None)  # SeniorityLevel.UNSPECIFIED
```

Maps `min_years_experience` from a job listing to the `SeniorityLevel` protobuf enum. Default
thresholds: ENTRY (0-2), MID (2-5), SENIOR (5-10), STAFF (10+). All thresholds are
configurable via keyword arguments.

### Dependency Guards

Constructing an encoder without its required extra raises immediately with a clear message:

```python
from nohiki_ml_core import (
    MissingLocalDependencyError,
    check_fastembed_available,
    check_pylate_available,
)

if not check_pylate_available():
    # Route inference through ml-gateway.
    ...
```

## Installation Extras

The base package installs without any ML libraries. Add extras based on the execution context:

| Extra | Adds | Use when |
|-------|------|----------|
| `[inference]` | numpy, pylate, fastembed, sentence-transformers, scikit-learn, onnxruntime, httpx | Direct ColBERT and Dense inference; Dense ONNX and HTTP TEI inference |
| `[cache]` | nohiki-s3-client, nohiki-redis-utils | Using `ModelCacheManager` |
| `[gpu]` | triton | GPU acceleration on Linux (requires NVIDIA hardware) |

```toml
# pyproject.toml: for ml-compute-service
dependencies = [
    "nohiki-ml-core[inference,cache]==0.1.0",
]
```

## Retrieval Pipeline Context

The encoding layer for Nohiki's 4-stage retrieval pipeline:

| Stage | Method | Encoder | Purpose |
|-------|--------|---------|---------|
| 1 -- ANN | Qdrant HNSW | `MLEncodingPipeline.encode_document/query` → MUVERA FDE | Fast approximate candidate retrieval (thousands of candidates → hundreds) |
| 1 -- Hybrid | Qdrant sparse | `SparseEncoder` | Keyword-sensitive recall alongside MUVERA |
| 2 -- Rerank | MaxSim | ColBERT tokens stored in Qdrant multivector | Precise late-interaction scoring of Stage 1 candidates |
| 3 -- LLM Rerank | job-correlation service | -- | Top candidates re-scored by LLM |
| 4 -- L2R | LightGBM LambdaMART | -- | Final ranking using composite feature vector |

`ml-compute-service` runs Stages 1 and 2 encoding. It receives `InternalComputeRequest` Kafka
commands from `ml-gateway-service`, calls `MLEncodingPipeline`, and publishes the resulting
`EmbeddingCallback` back to the requester's `callback_topic`. Indexing is owned by lifecycle
services: each entity owner persists callback results and writes Qdrant points when its entity
should be searchable. A `publish_to_index=True` sink path also publishes raw sink payloads on the
Qdrant Kafka Sink Connector topic for compatibility with that path.

## Testing

All encoders use lazy model loading, so tests can construct encoders and patch the model load
without installing PyLate or fastembed:

```python
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
from nohiki_ml_core.encoders.colbert import ColBERTEncoder

@pytest.fixture
def encoder(manifest):
    with patch("nohiki_ml_core.encoders.colbert.require_pylate"):
        enc = ColBERTEncoder(manifest)
    enc._model = MagicMock()
    enc._model.encode.return_value = [
        np.random.default_rng(42).standard_normal((20, 48)).tolist()
    ]
    return enc
```

For `MLEncodingPipeline`, patch all four encoder constructors at the `pipeline` module level,
then inject mock encoder instances directly:

```python
from unittest.mock import patch, MagicMock
from nohiki_ml_core.pipeline import MLEncodingPipeline

with (
    patch("nohiki_ml_core.pipeline.ColBERTEncoder"),
    patch("nohiki_ml_core.pipeline.MUVERAEncoder"),
    patch("nohiki_ml_core.pipeline.SparseEncoder"),
    patch("nohiki_ml_core.pipeline.DenseEncoder"),
):
    pipeline = MLEncodingPipeline(manifest)

pipeline.colbert = mock_colbert
pipeline.muvera = mock_muvera
```

For GPU detection tests, call `reset_gpu_detection_cache()` between test cases to clear the
`@cache` result:

```python
from nohiki_ml_core import reset_gpu_detection_cache

def test_gpu_not_available(monkeypatch):
    reset_gpu_detection_cache()
    monkeypatch.setattr("nohiki_ml_core.gpu._check_cuda_deps_installed", lambda: False)
    ...
```

Run tests from the repo root:

```bash
uv run --package nohiki-ml-core pytest backend/libs/nohiki-ml-core/tests/ --tb=short
```

## Design Decisions

**No S3/Redis in the pipeline.** The earlier design stored ColBERT tokens in S3 and cached them
in Redis. The current design returns all embeddings inline from `MLEncodingPipeline`. A legacy
Kafka-sink indexing path still exists for compatibility; the target design has lifecycle-owning
services decide whether returned embeddings are written to Qdrant. This eliminates a separate token
retrieval round-trip from the hot path and keeps the pipeline a pure in → out computation with no
external I/O.

**`SourceDownloader` protocol.** `ModelCacheManager` accepts a `SourceDownloader` callback for
upstream model fetching rather than importing PyLate or fastembed directly. This keeps the base
package lightweight and allows `ml-compute-service` to control exactly how models are downloaded
(including HuggingFace Hub cache path manipulation) without coupling that logic into this library.

**Fail-fast dependency checks.** All encoders validate their required extras at construction
time, not at first encode call. A `MissingLocalDependencyError` at pod startup is far easier to
diagnose than an `ImportError` arriving mid-request after the service is already handling load.
