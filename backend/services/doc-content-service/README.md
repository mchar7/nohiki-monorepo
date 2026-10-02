# Doc Content Service

Generates tailored resume and cover letter content with PydanticAI using a JSON schema supplied in a Kafka command.
Generation has no local database; the command supplies context and S3 references for document attachments.
The schema guides model output; doc-template-service validates the content schema before rendering.
The service uses no Redis or Qdrant.

## Role in the System

The bff-service publishes `doc-content.cmd.generation-requested` on behalf of a user.
Automatic generation from high-scoring correlations is not implemented.
The command carries the full `ContentGenerationContext`: a `DocumentTemplateVersionSnapshot` containing the target JSON
schema, S3 references to example and context uploads, the user preference snapshot, and job listing data.

The service fetches S3 attachments concurrently, preprocesses the schema, builds prompts, and calls `nohiki-llm-client`.
PydanticAI returns a string-keyed dictionary; this service does not validate that dictionary against the template schema.
Configured validation retries apply to output-type validation, not full template-schema conformance.
On success, the service publishes the generated JSON to `doc-content.fct.generation-completed`.
On failure, the service publishes to `doc-content.fct.generation-failed`.
The bff-service consumes both topics to update document generation status.

Requests carry the context needed for any pod to process them.
LLM output can vary between calls; statelessness does not imply identical generated content.

## Event-Driven Integration

### Events Consumed

- **`DOC_CONTENT_GENERATION_REQUESTED`** (`doc-content.cmd.generation-requested.v1`,
  `ContentGenerationRequested`): The primary command. Carries the full generation context: a
  `ContentGenerationContext` struct with the `DocumentTemplateVersionSnapshot` (including the raw
  JSON schema string), `ListingSnapshot`, user preference snapshot, S3 references to example output
  uploads (few-shot examples), and S3 references to user context uploads (processed resume documents
  from the doc-process-service pipeline). The handler extracts all S3 keys, fetches attachment
  content concurrently with `asyncio.TaskGroup`, preprocesses the schema, and runs the LLM.
  Consumer group: `settings.kafka.consumer_group` (configured via `DOC_CONTENT__KAFKA__CONSUMER_GROUP`).

- **`JOB_CORRELATION_EVALUATED`** (`job-correlation.cdc.correlation-evaluated.v1`,
  `CorrelationEvaluated`): Monitors job-user fit scores produced by `job-correlation-evaluation-service`.
  When `fit_score` meets or exceeds the user preference's `auto_tailor_threshold` (default: 80),
  the handler logs that the correlation is auto-generation eligible.
  The handler does not publish a generation command.

### Events Published

- **`DOC_CONTENT_GENERATION_COMPLETED`** (`doc-content.fct.generation-completed.v1`,
  `ContentGenerationCompleted`): Published after the LLM returns a string-keyed dictionary.
  Carries `request_id`, `listing_id`, `template_version_id`, and `generated_content_json` (the
  LLM output serialized as a JSON string). Keyed by `request_id`. The bff-service consumes this
  to record the generated content in its projection table and notify the frontend via its
  document-tracking endpoints.

- **`DOC_CONTENT_GENERATION_FAILED`** (`doc-content.fct.generation-failed.v1`,
  `ContentGenerationFailed`): Published when the LLM call fails after all retries, including on
  `LLMValidationError` (PydanticAI validation retries exhausted) and unrecoverable provider errors.
  Carries `request_id`, `listing_id`, `template_version_id`, and an `ErrorInfo` with
  `error_code=GENERATION_FAILED`. Keyed by `request_id`. The bff-service consumes this to surface
  the failure to the frontend.

### Notable Patterns

**Schema-name caching:** The service caches PydanticAI instances by `schema_name`, the template version UUID.
Requests for the same immutable template version reuse the configured output type and runtime context.

## Object Storage

The service reads from S3 but never writes to it. It fetches attachment content using storage keys
carried in the `ContentGenerationContext`:

- **Example uploads** (`context.example_uploads`): Few-shot example outputs stored by
  `user-upload-service` and processed by `doc-process-service`. These are injected into the system
  prompt under a `# Examples and Context` section so the LLM can match their style and structure.
- **Context uploads** (`context.context_uploads`): User-uploaded background documents (e.g.,
  existing resume text extracted by `doc-process-service`). Also injected into the system prompt to
  give the LLM access to the user's actual experience and history.

Both attachment types are fetched concurrently via `asyncio.TaskGroup`. A missing S3 object raises
`DataNotAvailableError` (triggerable for retry); an S3 connection failure raises the same.

## External Integrations

**OpenRouter / LLM provider** (via `nohiki-llm-client`): The service calls the LLM through
`LLMClient`, which wraps PydanticAI internally. The client resolves the named chain
`"doc_tailoring"` from `LLMSettings.chains`. Release deployments configure that chain with
`openai:gpt-5.6-sol` and `reasoning_effort="high"`; falling back to the generic provider is intended
only for isolated development. The client wraps PydanticAI execution with Tenacity exponential-backoff
retry on `LLMTransientError` (5xx responses, momentary provider failures), raises
`LLMValidationError` non-retryably when PydanticAI's own structured-output retries are exhausted,
and raises `LLMRateLimitError` on HTTP 429. Token usage, cost (pulled from OpenRouter response
metadata or estimated via `genai-prices`), and latency are recorded as Prometheus metrics.

## Key Design Patterns

**Schema preprocessing for LLM consumption:** The JSON schema arriving in the event is authored for
doc-template-service and contains frontend-specific `x-*` vendor extensions (e.g., `x-ui-widget`,
`x-display-order`) and `x-llm-hint` fields meant to guide generation. Before passing the schema to
PydanticAI, `preprocess_schema_for_llm` performs four transformations on a deep copy:

1. Merges `x-llm-hint` text into `description` fields (where the LLM actually reads it).
2. Strips all remaining `x-*` extensions (they confuse the grammar generator).
3. Adds `additionalProperties: false` to every object node (prevents the LLM from inventing extra
   fields outside the schema).
4. Removes `format` values unsupported by GBNF grammars (e.g., `"email"`, `"uri"`) that cause
   Ollama's grammar-constrained generation to fail.

The original schema dict is never mutated. The function returns a deep copy.

**Dynamic schema output via `StructuredDict`:** Each template version supplies its own JSON schema.
`LLMClient.create_dynamic_schema_agent` constructs a `StructuredDict` output type from the preprocessed schema.
The schema describes the requested output but is not enforced on receipt.
The output type validates only that `result.output` is a dictionary with string keys.
Doc-template-service validates the render payload against the stored `content_schema` and rejects nonconforming content.

**Dynamic system prompt via `system_prompt_fn`:** The service builds the prompt at request time from each request's context.
The prompt includes the schema, attachments, and user preferences.
The prompt does not capture one request's context for later calls.

## Configuration

Settings compose `LLMMixin`, `KafkaMixin`, `S3Mixin`, and `NohikiBaseSettings`. All environment
variables use the `DOC_CONTENT_` prefix (e.g., `DOC_CONTENT__KAFKA__BOOTSTRAP_SERVERS`).

Key settings beyond the shared mixins:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DOC_CONTENT__GENERATION__TIMEOUT_SECONDS` | `120` | Per-generation processing timeout |
| `DOC_CONTENT__GENERATION__MAX_RETRY_ATTEMPTS` | `3` | Kafka-level retry attempts on handler failure |
| `DOC_CONTENT__LLM__PROVIDER__MODELS__0__MODEL` | -- | Primary model in `provider:model` format (required) |
| `DOC_CONTENT__LLM__PROVIDER__API_KEYS__OPENROUTER` | -- | OpenRouter API key (or use `/run/secrets/`) |
| `DOC_CONTENT__LLM__CHAINS__DOC_TAILORING__*` | -- | Named chain config for this service's generation use case |
| `DOC_CONTENT__LLM__PROVIDER__MAX_TOOL_RETRIES` | `3` | PydanticAI structured-output validation retries |

The `doc_tailoring` named chain routes document generation through the stronger
`openai:gpt-5.6-sol` model with high reasoning effort. It inherits `provider.api_keys`, so this does
not duplicate API-key configuration.

## Development

### Local Setup

```bash
uv sync
```

The service requires Kafka and an S3-compatible store (RustFS) to be running, plus an accessible
LLM endpoint. Use `just infra-up` then `just compose-up` to bring up the full local stack.

### Testing

```bash
just test doc-content-service
just test-cov doc-content-service
```

### Linting & Type Checking

```bash
just fix
just typecheck doc-content-service
```
