# Document Processing Service

Converts user-uploaded documents (PDFs, DOCX, images) into structured text representations by
submitting them to Docling Serve (IBM's document intelligence HTTP API) and publishing the
extracted content back to Kafka via the callback pattern. Kafka-only, stateless, with no
database. Reads source files from S3, writes nothing back to S3 (the structured output is
carried directly in the callback event as a `ProcessedDocumentSnapshot`).

## Role in the System

This service sits between user file uploads and any downstream service that needs document
content as text. When a caller publishes `doc-process.cmd.processing-requested.v1` (carrying an
S3 `storage_key`, a `content_id`, a desired `ProcessingLevel`, and a `callback_topic`), this
service handles everything: fetches the file from S3, submits it to Docling Serve, polls for the
async result, and publishes a `ProcessingCallback` to the caller's nominated `callback_topic`.

The primary intended consumer of `doc-process.cmd.processing-requested.v1` is the `bff-service`,
which publishes processing commands when a user attaches a document to a job application profile.
The `doc-content-service`, which generates tailored resumes and cover letters via LLM, reads
the `ProcessedDocumentSnapshot` payload from the callback to obtain the user's resume text as
structured markdown and table data before constructing its LLM prompt.

No other service in the platform performs document-to-text extraction. This service is the sole
gateway through which raw document bytes become machine-readable content for downstream LLM and
ML pipelines.

## Event-Driven Integration

### Events Consumed

- **`DOC_PROCESS_PROCESSING_REQUESTED`** (`doc-process.cmd.processing-requested.v1`,
  `ProcessingRequested`): The entry point for all document processing. The message carries the
  S3 `storage_key` for the source file, a caller-assigned `content_id` used as the cache
  identity, a `ProcessingLevel` enum value controlling which Docling features to activate (OCR,
  table extraction, image extraction, VLM descriptions), and a `CommandHeader` containing the
  `callback_topic` and `operation_id`. The handler fetches the raw bytes from S3, maps the
  `ProcessingLevel` to `ProcessingOptions`, delegates to `ProcessingService`, and publishes the
  result to `params.command.callback_topic`. Consumer group: `doc-process-service-primary`.

### Events Published

- **`ProcessingCallback` → caller's `callback_topic`** (direct publish): Published on both
  success and failure paths. On success, carries a `ProcessingResult` containing a
  `ProcessedDocumentSnapshot` with `markdown`, `html`, `serialized_document` (full DoclingDocument
  JSON), `table_count`, `image_count`, `content_hash`, and the effective `ProcessingLevel`. On
  failure, carries an `ErrorInfo` with `error_code` (`DOCUMENT_NOT_FOUND`, `PROCESSING_FAILED`,
  or `INTERNAL_ERROR`), `error_message`, and a `retryable` flag. The callback topic is determined
  entirely by the command's `callback_topic` field. This service does not publish to a fixed
  output topic.

- **`DOC_PROCESS_PROCESSING_COMPLETED`** (`doc-process.fct.processing-completed.v1`): A broadcast
  fact topic defined in the `Topics` registry. Not published by the current handler implementation;
  reserved for future fanout use cases where multiple consumers need to react to processing
  completion independently of the callback pattern.

### Notable Patterns

**Callback pattern**: This service implements the standard Nohiki request/callback pattern.
The requester publishes a command to `doc-process.cmd.processing-requested.v1` with a
`callback_topic` field in the `CommandHeader`. This service processes the document and publishes
`ProcessingCallback` directly to that `callback_topic`, keyed by `operation_id`. The requester
must separately consume its own callback topic. The `callback_from_command()` helper from
`nohiki-kafka-client` constructs the `CallbackHeader` from the original `CommandHeader`,
preserving `operation_id` and `correlation_id` through the async processing boundary.

**Error classification**: The handler distinguishes three failure modes with different
`retryable` signals. `S3ObjectNotFoundError` maps to `DOCUMENT_NOT_FOUND` (not retryable --
the file is permanently missing). Internal `ProcessingService` failures from Docling map to
`PROCESSING_FAILED` (not retryable because the document was received but Docling rejected it).
Unexpected `OSError`, `RuntimeError`, or `ValueError` from the processing pipeline map to
`INTERNAL_ERROR` (retryable for transient infrastructure issues). The `retryable` field in
`ErrorInfo` tells callers whether to republish the command or route to DLQ.

## State & Persistence

### Object Storage

This service reads from the bucket configured by `DOC_PROCESS_S3__BUCKET_NAME`. The `storage_key`
in the processing command is a path within that bucket, set by the uploader (typically
`user-upload-service`) at the time the file was stored. The service does not write processed
output back to S3 -- the `ProcessedDocumentSnapshot` is carried inline in the Kafka callback event,
which keeps the callback self-contained and eliminates a second S3 round-trip for the consumer.

### Redis

Redis serves as a two-tier content-addressable cache. The `CacheManager` stores raw document
bytes under `doc-process:raw:{content_id}` (TTL: 7 days) and serialized
`ProcessedDocumentSnapshot` objects under `doc-process:processed:{sha256_hash}:{level}` (TTL: 7
days). The cache key for processed content uses the SHA-256 hash of the raw bytes, not the
`content_id` -- so identical document content processed at the same level reuses the cached result
regardless of which upload triggered it. Before calling Docling Serve,
`ProcessingService.process()` checks the processed cache; on a hit it returns a snapshot rebound
to the requesting `content_id` without any HTTP call. The `CacheManager` also stores a
`doc-process:checksum:{content_id}` key to detect when a re-uploaded file has changed content.

## External Integrations

### Docling Serve

Docling Serve is an HTTP API wrapping IBM's Docling library for document understanding. This
service submits documents to `POST /v1/convert/file/async` as multipart form data, receiving a
`task_id` in return. It then polls `GET /v1/status/poll/{task_id}` (with configurable
`wait` parameter) until the task reaches `SUCCESS` or `FAILURE` status, then fetches the
structured result from `GET /v1/result/{task_id}`.

The response `document` payload carries top-level `md_content`, `html_content`, and
`json_content` fields. This service uses `md_content`/`html_content` as the primary extracted
content and serializes the full `json_content` dict to `serialized_document` for consumers that
need the complete structured representation.

**MIME detection**: The client detects PDF and image types from byte signatures and identifies
DOCX archives by their `word/document.xml` member to set the multipart filename and
`Content-Type`. Unknown formats retain the compatibility fallback of `application/pdf`.

**Processing pipeline options** passed as multipart fields:

| Field | Default | Purpose |
|---|---|---|
| `pipeline` | `standard` | Processing pipeline (`standard` or `vlm`) |
| `pdf_backend` | `docling_parse` | PDF parsing backend |
| `ocr_engine` | `rapidocr` | OCR engine (`auto`, `easyocr`, `kserve_v2_ocr`, `ocrmac`, `rapidocr`, `tesseract`, `tesserocr`) |
| `table_mode` | `accurate` | Table extraction mode (`fast` or `accurate`) |
| `do_ocr` | `true` | Enable OCR |
| `do_table_structure` | `true` | Enable table structure extraction |
| `include_images` | `true` | Include image regions |
| `do_picture_description` | `false` | Enable VLM image captioning |

**VLM integration**: When `DOC_PROCESS_VLM__ENABLED=true`, the client passes a
`picture_description_custom_config` JSON blob to Docling Serve, which proxies image captioning
requests to the configured external VLM endpoint. This requires the
Docling Serve deployment to enable remote services and custom picture description config
(`DOCLING_SERVE_ENABLE_REMOTE_SERVICES=true` and
`DOCLING_SERVE_ALLOW_CUSTOM_PICTURE_DESCRIPTION_CONFIG=true`). This enables the `FULL`
processing level to produce natural-language descriptions of figures and diagrams in documents.

**Availability check**: `DoclingClient.is_available()` hits `GET /ready` before processing and
caches successful readiness. Failures are not cached, so a recovered provider is probed again on
the next request. `reset_availability()` clears a successful cached state. The configured circuit
breaker thresholds are currently not wired into the client.

**Timeout and polling**: The HTTP client timeout defaults to 300 seconds per request. Polling is
bounded by `poll_interval_seconds * max_poll_attempts` (five minutes by default), although an
individual in-flight HTTP request can run until its per-request timeout.

## Key Design Patterns

### Processing Level Mapping

`ProcessingLevel` is a protobuf enum (`BASIC`, `TABLES`, `OCR`, `IMAGES`, `FULL`) that the
command sender uses to declare the minimum fidelity required. The handler maps this to a
`ProcessingOptions` dataclass using inequality comparisons on the enum values -- `level >= OCR`
enables OCR, `level >= TABLES` enables table extraction, and so on. This means requesting `FULL`
activates all capabilities including VLM image descriptions. `ProcessingOptions` determines the
effective processing level, which is used as the processed-cache suffix; a cached snapshot at a
higher level can satisfy a lower-level request.

### Blocking I/O in Executor

Docling Serve communication runs over synchronous `httpx.Client`, not the async `httpx.AsyncClient`.
The `ProcessingService.process()` method dispatches the `DoclingClient.process()` call via
`asyncio.get_running_loop().run_in_executor(None, ...)` to avoid blocking the asyncio event loop
during the HTTP submission and polling cycle, which can take several minutes for large documents.
This is the correct pattern for CPU-bound or blocking I/O work inside an async Kafka consumer.

### Idempotency via Content-Addressable Cache

The processed content cache is keyed by `sha256(raw_bytes):{level}`, not by `content_id` or
`operation_id`. This means reprocessing the same document bytes at the same level, from any
number of command messages, returns the cached snapshot without touching Docling Serve. The
cache check happens inside `ProcessingService.process()` before the Docling HTTP call, so a
cache hit bypasses both the availability check and all network I/O.

## Configuration

Settings compose three shared mixins -- `KafkaMixin`, `RedisMixin`, `S3Mixin` -- plus four
service-specific nested models. All environment variables use the `DOC_PROCESS_` prefix.

### Docling Settings (`DOC_PROCESS_DOCLING__*`)

| Variable | Default | Notes |
|---|---|---|
| `DOC_PROCESS_DOCLING__BASE_URL` | `http://docling-serve:5001` | Docling Serve endpoint |
| `DOC_PROCESS_DOCLING__API_KEY` | `null` | API key for authenticated deployments |
| `DOC_PROCESS_DOCLING__TIMEOUT_SECONDS` | `300` | Per-request HTTP timeout |
| `DOC_PROCESS_DOCLING__MAX_DOCUMENT_BYTES` | `52428800` | Reject larger files before caching or Docling submission |
| `DOC_PROCESS_DOCLING__PIPELINE` | `standard` | `standard` or `vlm` pipeline |
| `DOC_PROCESS_DOCLING__PDF_BACKEND` | `docling_parse` | PDF parsing backend |
| `DOC_PROCESS_DOCLING__OCR_ENGINE` | `rapidocr` | OCR implementation |
| `DOC_PROCESS_DOCLING__TABLE_MODE` | `accurate` | `fast` or `accurate` |
| `DOC_PROCESS_DOCLING__POLL_INTERVAL_SECONDS` | `1.0` | Polling frequency (0.1-10.0s) |
| `DOC_PROCESS_DOCLING__MAX_POLL_ATTEMPTS` | `300` | Polling timeout multiplier |

### VLM Settings (`DOC_PROCESS_VLM__*`)

| Variable | Default | Notes |
|---|---|---|
| `DOC_PROCESS_VLM__ENABLED` | `false` | Enable VLM image captioning |
| `DOC_PROCESS_VLM__ENGINE_TYPE` | implementation default | Picture description engine type |
| `DOC_PROCESS_VLM__API_URL` | implementation default | VLM endpoint |
| `DOC_PROCESS_VLM__MODEL` | implementation default | VLM model identifier |
| `DOC_PROCESS_VLM__TIMEOUT_SECONDS` | `180` | VLM request timeout |
| `DOC_PROCESS_VLM__THINKING_BUDGET` | `1024` | Token budget for chain-of-thought |

### Cache Settings (`DOC_PROCESS_CACHE__*`)

| Variable | Default | Notes |
|---|---|---|
| `DOC_PROCESS_CACHE__RAW_TTL_SECONDS` | `604800` | 7-day TTL for raw bytes |
| `DOC_PROCESS_CACHE__PROCESSED_TTL_SECONDS` | `604800` | 7-day TTL for snapshots |
| `DOC_PROCESS_CACHE__KEY_PREFIX` | `doc-process` | Redis key namespace |

### Circuit Breaker Settings (`DOC_PROCESS_CIRCUIT_BREAKER__*`)

| Variable | Default | Notes |
|---|---|---|
| `DOC_PROCESS_CIRCUIT_BREAKER__ENABLED` | `true` | Reserved; not currently wired into the client |
| `DOC_PROCESS_CIRCUIT_BREAKER__FAILURE_THRESHOLD` | `5` | Reserved |
| `DOC_PROCESS_CIRCUIT_BREAKER__SUCCESS_THRESHOLD` | `2` | Reserved |
| `DOC_PROCESS_CIRCUIT_BREAKER__TIMEOUT_SECONDS` | `30` | Reserved |

## Development

### Local Setup

```bash
uv sync
```

This service has no database migrations. Ensure Kafka, Redis, S3, and a Docling Serve instance
are reachable at their configured endpoints before starting the service.

### Testing

```bash
just test doc-process-service
just test-cov doc-process-service
```

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise
uv run ty check
```

From the monorepo root:

```bash
just lint-service doc-process-service
just typecheck doc-process-service
```
