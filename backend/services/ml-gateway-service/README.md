# ML Gateway Service

Routes ML compute requests from all producer services to the appropriate compute backend via Kafka.
This service owns no ML logic: it selects a provider, wraps the incoming request in an
`InternalComputeRequest`, and publishes to the correct internal topic. Kafka-only, stateless, with
Redis for provider fallback state tracking. No database, no LLM, no outbox.

## Role in the System

Every service that needs embeddings (job-correlation-evaluation-service, job-ingest-enrichment-service,
user-pref-service, skill-graph-service) publishes `ml.cmd.embedding-requested.v1` to request a compute
operation. The ml-gateway-service is the single consumer of that topic. It selects the best available
provider from its registry and forwards the wrapped request to the provider's internal topic
(`ml.sys.kubernetes-compute.v1` or `ml.sys.modal-compute.v1`). The gateway is never in the response
path: the compute worker publishes the result directly to the `callback_topic` embedded in the original
request.

This service and ml-compute-service form a routing + execution pair. The gateway handles "which backend,
and should this be computed at all?" while the compute service handles "run the encoder and publish the
result." Separating them lets the same routing gateway front multiple compute backends: in-cluster
Kubernetes workers for CPU-bound embeddings and Modal serverless functions for GPU-required operations
(reranking).

The gateway sits on the critical path for every embedding request in the platform. All ML work flows
through it before reaching a compute worker.

## Event-Driven Integration

### Events Consumed

- **`ML_EMBEDDING_REQUESTED`** (`ml.cmd.embedding-requested.v1`, `EmbeddingRequested`): The primary
  routing channel. Any service that needs a single embedding publishes here. The gateway selects the
  best provider for the operation (preferring the Kubernetes worker: CPU-capable, cost-effective),
  wraps the message in `InternalComputeRequest`, and publishes to the selected provider's internal
  topic. If no provider is available, it publishes an `EmbeddingCallback` error directly to the
  requester's `callback_topic` with `error_code="NO_PROVIDER"`. Consumer group:
  `ml-gateway-embedding-primary`. `preserve_partition_order=False` allows up to 20 concurrent
  handlers for throughput.

- **`ML_BATCH_EMBEDDING_REQUESTED`** (`ml.cmd.batch-embedding-requested.v1`,
  `BatchEmbeddingRequested`): Routes batch embedding requests, which contain multiple items under a
  single `operation_id`. The gateway selects a provider that declares `supports_batch_embedding=True`.
  Currently only the Kubernetes provider and Modal provider support batch operations. On failure,
  publishes `BatchEmbeddingCallback` with `retryable=False` to the requester's callback topic.
  Consumer group: `ml-gateway-batch-embedding-primary`.

- **`ML_RERANK_REQUESTED`** (`ml.cmd.rerank-requested.v1`, `RerankRequested`): Routes rerank requests.
  Reranking runs the Qwen3-Reranker model, which requires GPU. The gateway calls
  `get_provider_for_operation(RERANK, require_gpu=True)`, which restricts selection to providers with
  `gpu_available=True`. In practice this means Modal only: the Kubernetes provider declares
  `supports_rerank=False`. On failure, publishes `RerankCallback` with `error_code="NO_PROVIDER"` to
  the requester's callback topic. Consumer group: `ml-gateway-rerank-primary`.

### Events Published

- **`ML_INTERNAL_K8S_COMPUTE`** (`ml.sys.kubernetes-compute.v1`, `InternalComputeRequest`): Forwarded
  to ml-compute-service when the Kubernetes provider is selected. The payload wraps the original
  request (embedding, batch embedding, or rerank) and adds `selected_provider="kubernetes"` and
  `retry_attempt=0`. ml-compute-service consumes this topic, executes the encoder via nohiki-ml-core,
  and publishes the result directly to the `callback_topic` from the original command. Direct publish
  (no outbox). Keyed by `operation_id`.

- **`ML_INTERNAL_MODAL_COMPUTE`** (`ml.sys.modal-compute.v1`, `InternalComputeRequest`): Same
  structure as the Kubernetes topic, but consumed by Modal serverless functions rather than
  ml-compute-service. Used when GPU is required (reranking) or when Modal is the selected provider
  for embedding. Direct publish. Keyed by `operation_id`.

- **Callback topics** (various `*.sys.*-callback.v1`, `EmbeddingCallback` / `BatchEmbeddingCallback` /
  RerankCallback): Published only on routing failure, when no provider is available. Each
  incoming command carries a `callback_topic`; on `NoProviderAvailableError`, the gateway publishes
  an error response directly to that topic rather than letting the message re-queue. Under normal
  operation the gateway never touches the callback topic; the compute worker does that.

### Notable Patterns

**Callback pattern**: Each incoming command (`EmbeddingRequested`, `BatchEmbeddingRequested`,
`RerankRequested`) carries a `command.callback_topic` and `command.operation_id`. The gateway
propagates both fields into the `InternalComputeRequest` it publishes. The compute worker reads
them and publishes its result directly to `callback_topic` keyed by `operation_id`. The gateway
is out of the loop once it forwards the request.

**Provider fallback with Redis health tracking**: Under the `dynamic` routing strategy (default),
the gateway tracks per-provider error counts in Redis using keys of the form
`ml_provider_fallback:{provider_name}`. When a provider accumulates `min_consecutive_errors`
(default: 3) over `error_duration_threshold_seconds` (default: 300 s), the strategy flags it as
unhealthy. For rate-limit errors specifically, fallback triggers immediately if
`retry_after_seconds` exceeds `rate_limit_wait_threshold_seconds` (default: 1800 s). The state
entry has a TTL of `provider_fallback_state_ttl_seconds` (default: 86400 s) and is cleared on
provider success via `clear_provider_state`.

## State & Persistence

### Redis

Redis holds provider fallback state only: no request or embedding data is stored here. Each entry
tracks `first_error_at`, `last_error_at`, and `consecutive_errors` for a provider under the key
prefix `ml_provider_fallback:{provider_name}`. Entries expire after 24 hours (configurable via
`ML_GATEWAY_CACHING__PROVIDER_FALLBACK_STATE_TTL_SECONDS`). On provider recovery the entry is
explicitly deleted via `clear_provider_state`.

## Key Design Patterns

**Provider registry with pluggable routing strategies**: The gateway discovers two providers at
startup -- `KubernetesMLProvider` (priority 10, CPU, no GPU) and `ModalMLProvider` (priority 50,
GPU, supports rerank). The registry indexes providers by operation type and sorts them by priority.
Three routing strategies are available, configured via `ML_GATEWAY_PROVIDER_REGISTRY__ROUTING_STRATEGY`:

| Strategy | Behaviour | Use case |
|----------|-----------|----------|
| `dynamic` (default) | Highest-priority enabled provider; falls back on sustained errors | Production |
| `balancing` | Round-robin across enabled providers via Redis counter | Distributing load evenly |
| `explicit` | Single named provider, no fallback | Testing, cost experiments |

The strategy selection is resolved at handler time through the provider registry's
`get_provider_for_operation` call, not pre-selected at startup.

**Operation-aware provider selection**: Each handler passes `require_gpu` to
`get_provider_for_operation`. Embedding and batch embedding use `require_gpu=False` (Kubernetes
preferred at priority 10). Rerank uses `require_gpu=True` (only Modal qualifies -- `gpu_available=True`,
priority 50). This prevents reranking from silently falling back to a CPU worker that would produce
wrong or degraded results.

**`InternalComputeRequest` envelope**: The gateway never republishes raw incoming messages. Every
forwarded message is an `InternalComputeRequest` that carries `operation_type`, `selected_provider`,
`retry_attempt`, and one of `embedding_request`, `batch_embedding_request`, or `rerank_request`.
This lets the compute worker log which provider was selected and manage retry semantics without
re-inspecting the original message type.

**Error callback on routing failure**: If `NoProviderAvailableError` is raised (all providers
are disabled or none match the capability constraint), the handler publishes a typed error response
(`EmbeddingCallback`, `BatchEmbeddingCallback`, or `RerankCallback`) to the requester's callback
topic before re-raising. The requester observes a normal callback shape with `error.error_code`
set, rather than receiving no response or seeing a DLQ message.

## Configuration

Settings are under `ML_GATEWAY_` prefix. Inherits `KafkaMixin` and `RedisMixin`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `ML_GATEWAY_PROVIDER_REGISTRY__ROUTING_STRATEGY` | `dynamic` | Provider selection strategy (`dynamic`, `balancing`, `explicit`) |
| `ML_GATEWAY_PROVIDER_REGISTRY__EXPLICIT_PROVIDER_NAME` | `None` | Required when strategy is `explicit` |
| `ML_GATEWAY_PROVIDER_REGISTRY__PROVIDERS` | `[]` | JSON array of `ProviderConfigSettings` for priority/enabled overrides |
| `ML_GATEWAY_CACHING__PROVIDER_FALLBACK_STATE_TTL_SECONDS` | `86400` | TTL for per-provider error state in Redis |
| `ML_GATEWAY_CACHING__QDRANT_PROVIDER__FALLBACK_TTL_SECONDS` | `86400` | Qdrant circuit-breaker fallback TTL |
| `ML_GATEWAY_KAFKA__CONSUMER__MAX_CONCURRENT_HANDLERS` | `20` | Concurrent Kafka handler count (high: pure I/O routing) |

Provider priority and enabled state can be overridden at runtime via the
`ML_GATEWAY_PROVIDER_REGISTRY__PROVIDERS` JSON array without redeploying. For example, to disable
the Kubernetes provider and force Modal:

```json
[
  {"name": "kubernetes", "enabled": false, "priority": 10},
  {"name": "modal", "enabled": true, "priority": 50}
]
```

## Development

### Local Setup

```bash
uv sync
```

This service has no database. Run with Kafka and Redis available (see `just infra-up`).

### Testing

```bash
just test ml-gateway-service
just test-cov ml-gateway-service
```

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise
uv run ty check
```

### Notes

- The service starts no HTTP API routes beyond `/health`, `/metrics`, and `/`. All ML work is
  event-driven.
- To add a new compute backend, implement `BaseMLProvider` (declare `name`, `capabilities`,
  `get_target_topic`), add it to `discover_providers()`, and create the corresponding Kafka topic
  in `Topics`. The registry and handler code need no changes.
- `preserve_partition_order=False` on all handlers is intentional: routing is stateless and
  requests are independent, so parallel consumption is safe.
