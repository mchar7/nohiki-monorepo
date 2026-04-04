# Nohiki Embedding Client

Abstracts the Kafka request/callback pattern for ML embedding operations. Services that need
text vectors publish a fire-and-forget request via `EmbeddingPublisher` and register a separate
`@message_handler` to receive results asynchronously on a service-owned callback topic. Without
this library each service would re-implement `CommandHeader` assembly, `operation_id` generation,
and proto construction independently. Four services depend on it: `job-ingest-enrichment-service`,
`user-pref-service`, `job-correlation-evaluation-service`, and `skill-graph-service`.

## Quick Start

The full request+callback pattern for a single-entity embedding:

```python
# core/embedding.py: create once, reuse via @cache
from functools import cache
from nohiki.ml.v1 import EntityType
from nohiki_embedding_client import EmbeddingPublisher, EmbeddingSpec
from nohiki_kafka_client import Topics
from nohiki_ml_manifest import get_manifest

@cache
def get_embedding_publisher() -> EmbeddingPublisher:
    manifest = get_manifest()
    return EmbeddingPublisher(
        callback_topic=Topics.USER_PREF_EMBEDDING_CALLBACK,
        service_name="user-pref-service",
        collection_version=manifest.get_entity_version(EntityType.PROFILE),
    )
```

```python
# events/handlers.py: fire the request
from nohiki.ml.v1 import EmbeddingType, EncodingMode, EntityType
from nohiki_embedding_client import EmbeddingSpec
from nohiki_kafka_client import CommandContext, MessageContext

operation_id = await get_embedding_publisher().request_embedding(
    text="Python engineer with distributed systems experience",
    entity_id=str(pref_id),
    entity_type=EntityType.PROFILE,
    spec=EmbeddingSpec(
        requested_types=[EmbeddingType.MUVERA, EmbeddingType.SPARSE, EmbeddingType.COLBERT],
        encoding_mode=EncodingMode.DOCUMENT,
        publish_to_index=False,
    ),
    context=CommandContext(caller_context=state.to_bytes()),
)
```

```python
# events/callbacks.py: handle the asynchronous result
from nohiki.ml.v1 import EmbeddingCallback
from nohiki_embedding_client import EmbeddingResult
from nohiki_kafka_client import MessageContext, Topics
from my_service.core.kafka import kafka_client

@kafka_client.message_handler(
    Topics.USER_PREF_EMBEDDING_CALLBACK,
    EmbeddingCallback,
    group_id="user-pref-embedding-callback-primary",
)
async def handle_embedding_callback(message: EmbeddingCallback, context: MessageContext) -> None:
    if message.success is not None:
        result = EmbeddingResult.from_callback(message)
        muvera = result.get_muvera()
        # persist / index the vectors
    elif message.error is not None:
        # log and return; Kafka retry re-delivers
        ...
```

## Core Concepts

### Fire-and-Forget Requests

`EmbeddingPublisher.request_embedding` publishes `EmbeddingRequested` to `ml.cmd.embedding-requested.v1`
and returns immediately with an `operation_id`. The service does not block waiting for vectors. The
`ml-gateway-service` routes the command to compute workers; results arrive later on the service's
callback topic. The returned `operation_id` (UUIDv7) is suitable for correlation logging but is
not needed to match callbacks. The callback carries its own `operation_id` in `CallbackHeader`.

### Callback Correlation via `caller_context`

The `CommandContext.caller_context` bytes field is round-tripped unchanged through the ML pipeline
and echoed back on every `EmbeddingCallback`. Services use it to carry lightweight state: a saga ID,
a serialized dataclass, or anything else needed to resume work when the callback arrives. For
example, `job-ingest-enrichment-service` encodes `{"saga_id": "..."}` in JSON and uses it to
look up the saga record when the callback arrives. `user-pref-service` serializes a
`PrefEmbeddingState` dataclass (~80 bytes) using `CallbackStateMixin.to_bytes()`.

The `attributes` dict (also part of `CommandContext`) is similarly round-tripped and can carry
small string annotations -- `job-ingest-enrichment-service` uses it to track `"embedding_type":
"retrieval"` vs `"embedding_type": "title"` so the callback handler knows which embedding slot
to fill in the saga.

### Batch Embedding

`EmbeddingPublisher.request_batch_embedding` publishes a `BatchEmbeddingRequested` command to
`ml.cmd.batch-embedding-requested.v1` with a list of `BatchEmbeddingItem` objects. The response
arrives as a `BatchEmbeddingCallback` message (not a regular `EmbeddingCallback`), so the
callback handler must be registered on a batch-specific topic and use `BatchEmbeddingItemResult`
rather than `EmbeddingResult`.

`skill-graph-service` uses batch embedding to vectorise skills in pages of 64 skills × 3 variants
each (label, description, alt labels), keeping batch payloads safely below Kafka's 1 MB limit.
Batch is also used for skill normalisation where unmatched raw skill strings are embedded as
`QUERY` mode vectors for Qdrant similarity search.

The Kafka key for batch requests is the `operation_id` (not an `entity_id`), because there is no
single canonical entity associated with a heterogeneous batch.

### `EmbeddingSpec`

`EmbeddingSpec` bundles three embedding parameters into a typed container to keep
`request_embedding` under five positional arguments:

- **`requested_types`** -- which geometry vector(s) to compute: `DENSE`, `MUVERA`, `SPARSE`,
  `COLBERT`. Requesting multiple types produces multiple `EmbeddingVector` entries in the callback.
- **`encoding_mode`** -- `DOCUMENT` uses AVG token aggregation (for entities being indexed);
  `QUERY` uses SUM aggregation (for queries searching against an index). The mode must match
how the target Qdrant collection was built. Mixing modes produces silently degraded results.
- **`publish_to_index`** -- current compatibility flag for the legacy Qdrant Kafka sink path. New
  lifecycle-owner flows should keep this `False`, consume callbacks, persist canonical state, and
  write Qdrant directly only from the entity lifecycle owner for that collection. Remove this flag
  when the legacy sink connector path is deleted.

### Saga Integration

Services that need multiple embedding calls before they can proceed use the saga pattern from
`nohiki-db-utils` alongside this library. `job-ingest-enrichment-service` creates an
`EnrichmentEmbeddingSaga` record with `expected_callbacks=2` before firing two concurrent
`request_embedding` calls (one for retrieval text, one for the job title). Each callback calls
`SagaRepository.record_callback()`, which returns `is_complete=True` only when both have arrived.
This handles pod restarts and out-of-order delivery without timeouts or polling.

### Multi-Pod Safety

Because callback topics are standard Kafka topics, any pod in the service's consumer group can
receive the callback, not necessarily the pod that issued the request. This works correctly as
long as correlation state is stored externally (DB saga, or inline in `caller_context`) and not
in memory. The library enforces this by design: `EmbeddingPublisher` holds no per-request state.

## API Reference

### EmbeddingPublisher

```python
from nohiki_embedding_client import EmbeddingPublisher
```

Instantiate once per service per publisher configuration (use `@functools.cache`):

- **`EmbeddingPublisher(callback_topic, service_name, collection_version)`** -- Constructor.
  `callback_topic` is the `*.sys.embedding-callback.*` topic owned by this service.
  `collection_version` is obtained from `nohiki-ml-manifest` via `manifest.get_entity_version(EntityType.*)`.

- **`await request_embedding(*, text, entity_id, entity_type, spec, context=CommandContext())`**
  -- Publishes `EmbeddingRequested` to `ml.cmd.embedding-requested.v1`, keyed by `entity_id`.
  Returns the `operation_id` string (UUIDv7) for logging. Raises `RuntimeError` if the Kafka
  client is not initialized.

- **`await request_batch_embedding(*, items, entity_type, encoding_mode, context=CommandContext())`**
  -- Publishes `BatchEmbeddingRequested` to `ml.cmd.batch-embedding-requested.v1`, keyed by
  `operation_id`. `items` must be a non-empty sequence of `BatchEmbeddingItem` proto messages.
  Raises `ValueError` for an empty `items` sequence. Raises `RuntimeError` if the Kafka client
  is not initialized.

### EmbeddingSpec

```python
from nohiki_embedding_client import EmbeddingSpec
from nohiki.ml.v1 import EmbeddingType, EncodingMode
```

Frozen dataclass. All fields are optional:

- **`requested_types: list[EmbeddingType]`** -- default `[]`
- **`encoding_mode: EncodingMode`** -- default `EncodingMode.DOCUMENT`
- **`publish_to_index: bool`** -- default `False`; legacy sink compatibility only

### EmbeddingResult

```python
from nohiki_embedding_client import EmbeddingResult
```

Frozen dataclass wrapping the success branch of an `EmbeddingCallback` proto message:

- **`EmbeddingResult.from_callback(message: EmbeddingCallback) -> EmbeddingResult`** -- Extracts
  the `success` branch. Raises `ValueError` if `message.success is None` (i.e., the callback
  carries an error instead). Check `message.error` before calling this.

- **`get_dense() -> EmbeddingVector | None`** -- Retrieves the `DENSE` vector.
- **`get_muvera() -> EmbeddingVector | None`** -- Retrieves the `MUVERA` vector.
- **`get_sparse() -> EmbeddingVector | None`** -- Retrieves the `SPARSE` vector.
- **`get_colbert() -> EmbeddingVector | None`** -- Retrieves the `COLBERT` multi-vector.
- **`get_by_type(embedding_type) -> EmbeddingVector | None`** -- Generic accessor.

Fields: `embeddings`, `entity_id`, `entity_type`, `collection_version`, `content_hash`,
`encoding_mode`.

### BatchEmbeddingItemResult

```python
from nohiki_embedding_client import BatchEmbeddingItemResult
```

Frozen dataclass for a single item within a `BatchEmbeddingCallback` response:

- **`BatchEmbeddingItemResult.from_result_item(item: BatchEmbeddingResultItem)`** -- Constructs
  from the proto message element. `item_attributes` defaults to `{}` when not set.

- **`get_dense()`, `get_muvera()`, `get_sparse()`, `get_colbert()`, `get_by_type()`** -- Same
  accessors as `EmbeddingResult`.

Fields: `point_id`, `entity_id`, `embeddings`, `content_hash`, `item_attributes`.

Batch callback handlers iterate `message.success.results` and call
`BatchEmbeddingItemResult.from_result_item(r)` on each element.

### Exceptions

```python
from nohiki_embedding_client import EmbeddingError, EmbeddingFailedError
```

- **`EmbeddingError`** -- Base exception. Carries `request_id`, `entity_id`, `severity`, and
  `retry_strategy`. Default retry strategy is `RETRY_EXPONENTIAL`.

- **`EmbeddingFailedError(request_id, error_message, error_code, *, entity_id, retryable)`** --
  Raised when the compute side reports a failure. Sets `retry_strategy` to `RETRY_EXPONENTIAL`
  when `retryable=True`, `NO_RETRY` otherwise. Defaults to non-retryable.

In practice, services do not raise these directly. They inspect `message.error` in the callback
handler and log or propagate accordingly. The exceptions exist for callers that prefer exception
semantics over conditional branching on the callback payload.

## Testing

Patch `get_kafka_client` to inject an `AsyncMock` that captures `publish` calls:

```python
from unittest.mock import AsyncMock, patch
from nohiki.ml.v1 import EmbeddingType, EncodingMode, EntityType
from nohiki_embedding_client import EmbeddingPublisher, EmbeddingSpec
from nohiki_kafka_client import Topics

async def test_request_embedding_publishes_to_correct_topic():
    publisher = EmbeddingPublisher(
        callback_topic="test.sys.embedding-callback.v1",
        service_name="test-service",
        collection_version="v1",
    )
    mock_client = AsyncMock()

    with patch("nohiki_embedding_client.publisher.get_kafka_client", return_value=mock_client):
        operation_id = await publisher.request_embedding(
            text="Python engineer",
            entity_id="550e8400-e29b-41d4-a716-446655440000",
            entity_type=EntityType.JOB,
            spec=EmbeddingSpec(requested_types=[EmbeddingType.DENSE]),
        )

    call_kwargs = mock_client.publish.call_args.kwargs
    assert call_kwargs["topic"] == Topics.ML_EMBEDDING_REQUESTED
    assert call_kwargs["key"] == "550e8400-e29b-41d4-a716-446655440000"
```

To test callback handlers, construct an `EmbeddingCallback` proto with a populated `success`
branch and verify that `EmbeddingResult.from_callback(message)` returns the expected vectors.
Passing a callback with only `error` set (no `success`) exercises the error path without
needing a running Kafka cluster.

Run the library tests with:

```bash
just test nohiki-embedding-client
```

## Design Decisions

### Separate callback topic per service

Each service declares its own callback topic (e.g., `user-pref.sys.embedding-callback.v1`,
`job-correlation.sys.embedding-callback.v1`) rather than a shared `ml.fct.embedding-completed.v1`
topic. This enables independent consumer groups, independent scaling, and independent DLQ
policies per service. It also means a compute failure on one service's embedding backlog does
not block other services' callbacks.

### No built-in timeout handling

`EmbeddingPublisher` does not implement timeouts or retry-on-missing-callback. Timeout
detection is the responsibility of the consuming service (typically via the saga's `expires_at`
column and a periodic stale-saga sweep). This keeps the library stateless and compatible with
multi-pod deployments where the issuing pod may have restarted before the callback arrives.

### `collection_version` at construction time

The Qdrant collection version is fixed at publisher construction time via
`manifest.get_entity_version(EntityType.*)`. This prevents accidental cross-version writes
if the manifest changes mid-flight, and allows the staleness check downstream (embedding is
stale if either `content_hash` or `collection_version` has changed).
