# ML Compute Service

Executes ColBERT, MUVERA, and sparse embedding computations on demand for the Nohiki ML
retrieval pipeline. This service is the only place in the platform where heavy inference
libraries (PyLate, fastembed, sentence-transformers) run. It consumes compute requests that
`ml-gateway-service` routes from the broader embedding request flow, runs inference using
`nohiki-ml-core`, and publishes `EmbeddingCallback` / `BatchEmbeddingCallback` events to the
requester's callback topic. Kafka-only, stateless, no database. Application-data Qdrant
mutations belong to entity lifecycle services via `nohiki-qdrant-client`; the
`publish_to_index=True` path publishes a JSON payload to the Qdrant Kafka Sink Connector topic
for compatibility with that path.

## Role in the System

Every service that needs text embeddings -- `job-correlation-evaluation-service`,
`user-pref-service`, `job-ingest-enrichment-service`, `skill-graph-service` -- publishes an
`EmbeddingRequested` command to `ml.cmd.embedding-requested.v1`. The `ml-gateway-service`
receives those commands, selects a compute provider (Kubernetes or Modal), and routes them
internally. This service consumes from `ml.sys.kubernetes-compute.v1` -- the K8s-targeted
routing topic, then executes the actual inference.

This service is the sole compute executor for the three retrieval vector types used in job-user
matching. Lifecycle-owning services persist the vectors it returns and write Qdrant points from
committed lifecycle facts; those points serve as the first two stages of the four-stage retrieval
pipeline in `job-correlation-evaluation-service`: MUVERA ANN → ColBERT MaxSim re-rank → LLM
re-rank → L2R.

In production Kubernetes, KEDA scales this service from zero replicas to N based on consumer
group lag on `ml.sys.kubernetes-compute.v1`. Instances spin up when embedding requests accumulate
and terminate when the queue drains. In Docker Compose, it runs as a single persistent consumer.
This means the service must tolerate cold starts: model weights load from S3 on each pod
initialisation before the Kafka consumer begins accepting work.

## Event-Driven Integration

### Events Consumed

- **`ML_INTERNAL_K8S_COMPUTE`** (`ml.sys.kubernetes-compute.v1`, `InternalComputeRequest`):
  The primary work queue. `ml-gateway-service` places compute requests here after routing
  decisions. Each message carries an `operation_type` (`EMBEDDING`, `BATCH_EMBEDDING`, or
  `RERANK`) plus the full nested request payload, including the text to encode, entity type,
  collection version, requested embedding types, and the `callback_topic` the requester expects
  a response on. Consumer group: `settings.kafka.consumer_group` (configured via
  `ML_COMPUTE_KAFKA__CONSUMER_GROUP`). `preserve_partition_order=False` allows concurrent
  processing across partitions, which is necessary since each message is independently
  CPU-bound. `max_concurrent_handlers` defaults to 2 to avoid saturating the compute thread
  pool on CPU-only instances.

  The handler dispatches on `operation_type`:
  - `EMBEDDING`: runs the full retrieval pipeline (ColBERT → MUVERA → Sparse) and/or the
    dense pipeline depending on `requested_types`. Publishes one `EmbeddingCallback` to the
    requester's callback topic. Requests with `publish_to_index=True` additionally publish a
    JSON payload to the Qdrant Kafka Sink Connector topic for compatibility with that path; new
    flows should let the requester own any persistence or Qdrant indexing via
    `nohiki-qdrant-client`.
  - `BATCH_EMBEDDING`: encodes a list of texts in one model forward pass via
    `pipeline.encode_dense_batch`. Publishes a `BatchEmbeddingCallback` to the requester's
    callback topic. Used by `skill-graph-service` for bulk skill embedding.
  - `RERANK`: not executed here. This operation requires GPU and routes to the Modal provider.
    The handler logs a warning and drops the message.

### Events Published

- **`{req.command.callback_topic}`** (`EmbeddingCallback` / `BatchEmbeddingCallback`):
  Published immediately after inference completes or fails. The topic is dynamic, and it comes
  from the original command's `callback_topic` field, allowing any number of services to
  receive results without this service knowing their identities. On success, carries the
  computed `EmbeddingResult` with all requested `EmbeddingVector` instances (MUVERA, ColBERT,
  Sparse, Dense), the `content_hash`, and `collection_version`. On failure, carries
  `ErrorInfo(error_code="PIPELINE_ERROR", retryable=False)` so the requester can mark the
  operation as permanently failed rather than retrying indefinitely. Published via direct
  `kafka_client.publish` -- no outbox.

### Notable Patterns

**Callback pattern**: Every `InternalComputeRequest` embeds a `CommandHeader` with an
`operation_id` and a `callback_topic`. After inference, this service publishes the result
keyed by `entity_id` (or `operation_id` for batch) to that callback topic. The requester's
handler correlates the response by `operation_id`. This decouples compute duration from the
requester's processing loop: the requesting service publishes and moves on, then handles the
result when it arrives.

**Error propagation via callback**: Rather than letting exceptions crash the consumer and
trigger DLQ redelivery, inference failures publish an `EmbeddingCallback` with `error` set
and `retryable=False` to the requester's callback topic. This gives requesters deterministic
failure handling without relying on Kafka retry semantics for logic-level errors.

**Qdrant mutation boundary**: This service does not call Qdrant directly. Lifecycle-owning
services decide whether callback results become Qdrant points. A JSON sink-payload publication
path on the Qdrant Kafka Sink Connector topic is retained for compatibility with that path.

## State & Persistence

### Object Storage

Model weights are stored in RustFS (S3-compatible) under three key prefixes:

- `models/colbert/{model_id}/model.tar.gz` -- PyLate ColBERT model (HuggingFace)
- `models/dense/{model_id}/model.tar.gz` -- sentence-transformers dense model (HuggingFace)
- `models/sparse/{model_id}/model.tar.gz` -- fastembed sparse model (PyPI)

On startup, `ModelCacheManager` checks a local `.cache_version` marker against the current
manifest hash. If the cache is stale or absent, it acquires a Redis distributed lock
(`model-download-{manifest_hash}`, 10-minute TTL) to prevent multiple pods from downloading
simultaneously. Under the lock, it downloads each archive from S3. If an archive is absent
from S3 (first deployment after a model change), it downloads directly from HuggingFace Hub
or PyPI, packages the result as `tar.gz`, uploads it to S3 for subsequent pods, then extracts
locally. Subsequent pods find the lock already released and the local marker valid, and skip
the entire download.

The `cache_dir` defaults to `/home/app/.cache` and is configured via
`ML_COMPUTE_PROCESSING__CACHE_DIR`.

### Vector Store

This service does not call Qdrant directly. It returns embedding vectors in callbacks. The target
collection, if any, is resolved by the lifecycle-owning service that consumes the callback. The
legacy sink connector path remains a cleanup item and should not be expanded.

Lifecycle-owner writers store three named vectors where applicable:

- **`muvera`** -- fixed-dimensional dense vector from MUVERA FDE. Used for approximate nearest
  neighbour (ANN) search as the first retrieval stage. Dimension determined by the manifest
  config (`2^k_sim × dim_proj × r_reps`). Qdrant distance metric must be `DOT`.
- **`colbert`** -- multi-vector token embeddings from ColBERT, stored flattened with `num_tokens`
  and `token_dim` in the payload. Used for MaxSim late-interaction re-ranking as the second
  retrieval stage.
- **`sparse`** -- learned sparse token-weight map from fastembed (`minicoil-v1` or equivalent).
  Provides keyword-sensitive retrieval as a complement to the dense MUVERA vectors.

### Redis

Redis serves two purposes:

1. **Distributed lock** during model download -- `model-download-{manifest_hash}` prevents
   concurrent pods from racing to fetch the same model archives from S3 on cold start.
2. **ColBERT token cache** -- computed tokens are cached with a 7-day TTL
   (`colbert_token_ttl`, configurable via `ML_COMPUTE_CACHING__COLBERT_TOKEN_TTL`), since
   ColBERT encoding is the most expensive step and tokens for the same content are stable
   across requests.

## Key Design Patterns

**Readiness gate with deferred consumer start**: Model download and warm-up run as a background
task (`asyncio.create_task`) so the FastAPI health endpoints (`/livez`, `/readyz`) are
reachable immediately on startup. While models are loading, `/readyz` returns 503 with state
`models_loading`. Only after `_warm_up_models_and_start_consumers` completes successfully does
the gate transition to `READY` and `kafka_client.start_consumers()` get called. If warm-up
fails, the gate transitions to `FAILED` and `/readyz` stays unhealthy, triggering Kubernetes
pod restarts. This is critical for KEDA: a pod that fails model loading must not accept
compute requests.

**Three-tier model caching with manifest-driven invalidation**: The local cache is keyed by a
16-character SHA-256 prefix over `(late_interaction.model_id, sparse.model_id, dense.model_id,
token_dim, embedding_dim)`. Changing any model identifier or dimension in the
`SemanticRepresentationManifest` automatically invalidates the cache and triggers a fresh
download. This ensures the running inference matches the manifest version that produced the
`collection_version` field stored in every Qdrant point.

**Inference backends per encoder**: ColBERT runs `DIRECT` through PyLate to preserve distinct
query and document encoding semantics. Dense supports `DIRECT` through sentence-transformers,
quantized `ONNX`, and `TEI` over HTTP. MUVERA and Sparse run locally through fastembed. The
manifest selects the supported backend for each encoder without branching in the handler.

**Asymmetric encoding for retrieval**: The pipeline distinguishes document encoding from query
encoding at the ColBERT and MUVERA layers. Documents use `is_query=False` (MAX aggregation in
MUVERA, `encode_document` in ColBERT). Queries use `is_query=True` (SUM aggregation in MUVERA,
`encode_query` in ColBERT). The `encoding_mode` field on `EmbeddingRequested` (`DOCUMENT` or
`QUERY`) drives this dispatch. Getting this wrong silently degrades retrieval quality, so the
handler raises `ValueError` on any unknown `encoding_mode`.

## Configuration

Settings use the `ML_COMPUTE_` env prefix. Key settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ML_COMPUTE_PROCESSING__COMPUTE_BACKEND` | `cpu` | Compute backend: `cpu`, `gpu`, or `auto`. `gpu` fails fast at startup if CUDA is unavailable. `auto` detects and logs the actual backend used. |
| `ML_COMPUTE_PROCESSING__MAX_REQUEST_ITEMS` | `100` | Maximum items admitted in one batch embedding request (clamped 1-100). |
| `ML_COMPUTE_PROCESSING__INFERENCE_BATCH_SIZE` | `8` | Maximum items per native model forward pass (clamped 1-64). |
| `ML_COMPUTE_PROCESSING__CACHE_DIR` | `/home/app/.cache` | Local directory for downloaded model artifacts. |
| `ML_COMPUTE_PROCESSING__TIMEOUT_SECONDS` | `300` | Per-request inference timeout (30-600 s). |
| `ML_COMPUTE_KAFKA__CONSUMER__MAX_CONCURRENT_HANDLERS` | `2` | Concurrent Kafka handler slots. Keep low for CPU-bound inference to avoid starving the thread pool. Raise for GPU instances where inference is faster. |
| `ML_COMPUTE_CACHING__COLBERT_TOKEN_TTL` | `604800` | Redis TTL for cached ColBERT tokens, in seconds (7 days). |
| `ML_COMPUTE_MANIFEST_PATH` | -- | Path to the `SemanticRepresentationManifest` YAML. Drives model selection, encoder dimensions, and collection versioning. |
| `ML_COMPUTE_S3_*` | -- | RustFS endpoint and credentials for model artifact storage. |
| `ML_COMPUTE_REDIS_URL` | -- | Redis URL for model download lock and token cache. |

Mixins used: `RedisMixin`, `KafkaMixin`, `S3Mixin`, `ManifestMixin`, `NohikiBaseSettings`.

## Development

### Local Setup

```bash
uv sync
```

This service has no database and no migrations. It requires Kafka, Redis, and a reachable S3
endpoint. On first run, it will attempt to download model artifacts from S3 (or fall back to
HuggingFace Hub / PyPI if the S3 bucket is empty). Set `ML_COMPUTE_PROCESSING__CACHE_DIR` to
a local path where the service has write access.

The compute backend defaults to `cpu`. To test GPU paths, set
`ML_COMPUTE_PROCESSING__COMPUTE_BACKEND=gpu` and ensure CUDA is available, or use `auto` to
let the service detect the best available backend at startup.

### Testing

```bash
just test ml-compute-service
just test-cov ml-compute-service
```

Tests use mocked `MLEncodingPipeline`, `ModelCacheManager`, and Kafka clients. No actual model
inference runs in unit tests.

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise
uv run ty check
```
