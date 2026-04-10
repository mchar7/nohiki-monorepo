# Doc Content Service

Generates tailored resume and cover letter content by running a PydanticAI LLM agent against a
JSON schema provided in the triggering command event. Kafka-only, completely stateless: every
piece of context needed for generation (job listing data, template schema, user preferences,
example outputs, and processed document attachments) arrives in the `doc-content.cmd.generation-requested`
event and is fetched from S3 within the handler. No database, no Redis, no Qdrant.

## Role in the System

This service is the LLM execution layer in Nohiki's document generation pipeline. The bff-service
publishes a `doc-content.cmd.generation-requested` command on behalf of a user (or the service
triggers automatically when `job-correlation-evaluation-service` produces a high-scoring
`job-correlation.cdc.correlation-evaluated` event). The command carries the full
`ContentGenerationContext`: a `DocumentTemplateVersionSnapshot` (containing the target JSON schema),
references to example uploads and user context uploads (S3 keys), the user's job preference
snapshot, and job listing data.

The service fetches S3 attachments in parallel, preprocesses the schema for LLM consumption, builds
system and user prompts, and calls the LLM via `nohiki-llm-client` (PydanticAI). The LLM produces
structured JSON that must conform to the template schema. PydanticAI validates the output and
retries up to `max_tool_retries` times if the model produces malformed output. On success, the
generated JSON is published to `doc-content.fct.generation-completed`; on failure, to
`doc-content.fct.generation-failed`. The bff-service consumes both fact topics to update its
projection tables, which surface document generation status to the frontend.

Statelessness is the defining characteristic here. Because ECST events carry all required data, the
service holds no local state and scales horizontally without coordination: every pod processes any
request with identical results.

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
  the handler logs that the correlation is auto-generation eligible. This is the hook point for
triggering automated document generation on high-scoring matches without user initiation. The
  actual command publication is the next step in this flow.

### Events Published

- **`DOC_CONTENT_GENERATION_COMPLETED`** (`doc-content.fct.generation-completed.v1`,
  `ContentGenerationCompleted`): Published after the LLM produces a valid schema-conformant output.
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

**Agent caching by schema name:** The service caches PydanticAI agents in a module-level dict keyed
by `schema_name` (the template `version_id` UUID). Creating a `StructuredDict` agent has overhead --
constructing the GBNF grammar from the JSON schema is non-trivial. The first request for a
given template version pays the construction cost; subsequent requests reuse the same agent
instance. This is safe because template versions are immutable once created.

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
only for isolated development. The client wraps PydanticAI's agent execution with Tenacity exponential-backoff
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

**Dynamic schema agent via `StructuredDict`:** Unlike services that generate a fixed Pydantic model
type, this service receives a different JSON schema per template version. It uses
`LLMClient.create_dynamic_schema_agent` with `DynamicAgentConfig`, which constructs a PydanticAI
`StructuredDict` output type at runtime from the preprocessed schema dict. This allows the same
service to generate resumes, cover letters, or any future document type without code changes. The
schema defines the output contract entirely.

**Dynamic system prompt via `system_prompt_fn`:** The system prompt is built at request time (not
baked into the agent at creation), because it incorporates per-request context: the full schema
definition, attachment content, and user preferences. `DynamicAgentConfig.system_prompt_fn` is a
callable that receives `RunContext[DocumentContentContext]` and returns the prompt string. This
avoids the stale-closure pitfall of capturing context in a lambda at agent creation time.

## Configuration

Settings compose `LLMMixin`, `KafkaMixin`, `S3Mixin`, and `NohikiBaseSettings`. All environment
variables use the `DOC_CONTENT_` prefix (e.g., `DOC_CONTENT__KAFKA__BOOTSTRAP_SERVERS`).

Key settings beyond the shared mixins:

| Variable | Default | Purpose |
|---|---|---|
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
