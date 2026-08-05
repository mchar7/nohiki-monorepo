# Doc Template Service

Owns the Jinja2 HTML template registry for Nohiki document generation. This service stores
versioned templates, validates and renders them, converts the output to PDF or image via Gotenberg,
stores the result in RustFS (S3), and publishes the render outcome to Kafka. It also handles the
full template lifecycle: create, version, delete, triggered by commands from the BFF service.
Kafka-only, stateful with PostgreSQL and Redis.

## Role in the System

This service sits at the rendering layer of the document generation pipeline. The `doc-content-service`
generates the structured JSON content for a resume or cover letter; it or the BFF then publishes
`DOC_TEMPLATE_RENDER_REQUESTED` carrying both the Jinja2 template source and the content data.
This service receives that command, renders the Jinja2 template, sends the resulting HTML to
Gotenberg for PDF or screenshot conversion, stores the output in RustFS, and publishes
`DOC_TEMPLATE_RENDER_COMPLETED` back to Kafka so the requesting service can retrieve the artifact
via the `storage_key`.

Template management commands originate from the BFF service. When a user creates, versions, or
deletes a template through the Nohiki frontend, the BFF publishes the corresponding command topic.
This service performs the authoritative write and publishes CDC events (`DOC_TEMPLATE_CREATED`,
`DOC_TEMPLATE_UPDATED`, `DOC_TEMPLATE_DELETED`) via the transactional outbox, which the BFF
consumes to keep its projection tables current.

On startup, the service seeds system-scoped default templates from the bundled `seed_templates/`
directory. A distributed Redis lock ensures only one pod seeds at a time in multi-replica deployments.
The seeder uses `SYSTEM_SERVICE_UUID` (a deterministic UUID5 derived from the service name) as the
owner identity for system templates, which prevents regular users from creating or modifying
SYSTEM-scoped entries.

## Event-Driven Integration

### Events Consumed

- **`DOC_TEMPLATE_RENDER_REQUESTED`** (`doc-template.cmd.render-requested.v1`, `DocumentRenderRequested`):
  The primary work trigger. The event carries the complete Jinja2 template source, the output data
  as a `map<string, string>` (JSON-serialized values), the requested output format (`PDF`, `IMAGE`,
  or `TEXT`), and a `correlation_id` that ties the render back to the originating document generation
  request. The handler validates the request, renders the template, converts to the target format,
  stores the artifact in S3, and publishes `DOC_TEMPLATE_RENDER_COMPLETED` via the outbox.
  Consumer group: `doc-template-{service_name}-commands`. Partition order is not preserved, allowing
  up to `max_concurrent_handlers` (default: 5) renders to proceed in parallel.

- **`DOC_TEMPLATE_CREATE_REQUESTED`** (`doc-template.cmd.create-requested.v1`, `TemplateCreateRequested`):
  Instructs the service to create a new template at version `1.0.0`. The handler validates that the
  namespace and name are provided, checks for duplicates (unique constraint on namespace + name +
  version + owner_id), and publishes `DOC_TEMPLATE_CREATED` via the outbox on success.
  Consumer group: `doc-template-{service_name}-commands`.

- **`DOC_TEMPLATE_VERSION_ADD_REQUESTED`** (`doc-template.cmd.version-add-requested.v1`, `TemplateVersionAddRequested`):
  Creates a new semantic-versioned row for an existing template family. The handler resolves the
  source template by ID to inherit its namespace and name, then inserts a new row at the requested
  semver version. Publishes `DOC_TEMPLATE_UPDATED` via the outbox.
  Consumer group: `doc-template-{service_name}-commands`.

- **`DOC_TEMPLATE_DELETE_REQUESTED`** (`doc-template.cmd.delete-requested.v1`, `TemplateDeleteRequested`):
  Soft-deletes a specific template version by ID. Idempotent: if the template is not found, the
  handler logs and returns without error. Publishes `DOC_TEMPLATE_DELETED` via the outbox on success.
  Consumer group: `doc-template-{service_name}-commands`.

### Events Published

- **`DOC_TEMPLATE_CREATED`** (`doc-template.cdc.template-created.v1`, `TemplateCreated`):
  Published via transactional outbox after a new template is written to the database. Carries a full
  `DocumentTemplateSnapshot` (ECST) so consumers can build projections without querying back.
  Consumed by `bff-service` to update its template projection tables.

- **`DOC_TEMPLATE_UPDATED`** (`doc-template.cdc.template-updated.v1`, `TemplateUpdated`):
  Published via transactional outbox when a new version is added to an existing template family.
  Also carries a full `DocumentTemplateSnapshot`. Consumed by `bff-service`.

- **`DOC_TEMPLATE_DELETED`** (`doc-template.cdc.template-deleted.v1`, `TemplateDeleted`):
  Published via transactional outbox after a template version is deleted. Carries only the
  `template_id`. Consumed by `bff-service` to remove the projection entry.

- **`DOC_TEMPLATE_RENDER_COMPLETED`** (`doc-template.fct.render-completed.v1`, `DocumentRenderCompleted`):
  Published via transactional outbox after every render attempt, whether successful or failed.
  On success, carries `storage_key` (the S3 path to the artifact), `content_type`, `file_size`,
  `content_hash`, `text_alternative` (if requested), and `result.status = COMPLETED`. On failure,
  carries `result.status = FAILED` with an `error_code` and `error_message`. The `correlation_id`
  in the event metadata ties this response back to the originating request. Consumed by
  `doc-content-service` and `bff-service`.

### Notable Patterns

**Transactional outbox**: All four published event types go through the `outbox` table in `doc_template_schema`.
Each handler writes the domain change and the outbox row in the same database transaction. Debezium
captures the outbox row from the PostgreSQL WAL and routes it to the correct Kafka topic via the
Outbox Event Router SMT. This guarantees exactly-once delivery even if the service crashes after
the DB commit but before a hypothetical direct Kafka publish.

**Render path: failure is a valid outcome**: The render handler publishes `DOC_TEMPLATE_RENDER_COMPLETED`
with `FAILED` status for both `GenerationError` (template/schema/validation failures) and unexpected
exceptions. The consumer always receives a response; the failed status is not retried by this service.
The originating service (e.g., `doc-content-service`) is responsible for interpreting the failure.

## State & Persistence

### Database

Schema `doc_template_schema` stores the template registry using a single-table design: every
`document_templates` row is a complete, immutable template version. Multiple versions of the same
template share `(namespace, name, owner_id)` but differ by `version` (a SemVer-validated string).
The `outbox` and `processed_events` tables support the transactional outbox and idempotency
mechanisms respectively.

See [DATABASE.md](./DATABASE.md) for semantic database design and lifecycle documentation.

### Object Storage

RustFS bucket configured via `DOC_TEMPLATE__S3__*` settings. Rendered documents are stored under
the prefix `rendered/{correlation_id}/{template_id}.{ext}` -- one object per render request.
The extension maps to the output format: `pdf`, `png`, `html`, or `txt`. S3 object metadata
includes `correlation-id`, `template-id`, and `content-hash` for integrity verification downstream.
No lifecycle policy is configured; consumers are expected to retrieve the artifact promptly via
the `storage_key` in the render-completed event.

### Redis

Redis serves two purposes:

1. **Distributed startup lock**: A `distributed_lock` with key `seed_default_templates`, TTL
   600 seconds, and a 60-second acquisition timeout prevents multiple pod replicas from seeding
   simultaneously on startup. The pod that acquires the lock runs the seeder; all others skip.

2. **Template lookup cache**: `get_template_by_id`, `get_template_by_name_version`, and
   `get_latest_template` use the `@cached` decorator with a 2-hour TTL (`_TEMPLATE_CACHE_TTL = 7200`).
   Cache keys follow the patterns `template_by_id:{uuid}`, `template_by_name_version:{ns}:{name}:{ver}`,
   and `template_latest:{ns}:{name}`. On create or delete, the service invalidates affected cache
   entries. Validation results (template syntax + schema checks) are also cached in Redis to avoid
   redundant re-validation of identical template-data pairs.

3. **Circuit breaker state**: The Gotenberg circuit breaker stores its open/half-open/closed state
   in Redis under the key `gotenberg` via `nohiki-redis-utils`.

## External Integrations

### Gotenberg

Gotenberg is an HTTP API (typically at `http://gotenberg:3000`) that converts HTML to PDF or
screenshots. This service calls it via an `httpx.AsyncClient` for every render request that targets
`PDF` or `IMAGE` output. The client posts multipart form data to `/forms/chromium/convert/html`
(PDF) or `/forms/chromium/screenshot/html` (image), including the rendered HTML and page size
and margin parameters.

A circuit breaker (failure threshold: 3 consecutive failures, timeout: 30 seconds) wraps the
Gotenberg HTTP calls. HTTP 4xx responses from Gotenberg raise `GotenbergError` but do **not** trip
the circuit, because they indicate bad input rather than service unavailability. Network errors,
connection failures, and timeouts do count toward the failure threshold. When the circuit is open,
all render requests for PDF and image output fail immediately with `GenerationError`, which the
handler translates to a `DOC_TEMPLATE_RENDER_COMPLETED` event with `FAILED` status.

## Key Design Patterns

### Single-Table Template Versioning

The `document_templates` table uses a single-table design: each row is a complete, immutable
template version. There is no separate "template family" or "version" table. The logical family
is the `(namespace, name, owner_id)` tuple. To list all versions, query by that tuple; to get
the latest, `ORDER BY created_at DESC LIMIT 1`. Version strings must be valid SemVer; the
CHECK constraint and `validate_semantic_version()` enforce this before insert. The unique constraint
`uq_template_name_version_owner` prevents duplicate versions and serves as the idempotency key.

### Template Metadata in HTML Comments

Seed templates declare their metadata inside an HTML comment block parsed by `parse_template_metadata()`:

```html
<!-- TMPL_META
{
  "name": "resume-standard",
  "version": "1.0.0",
  "namespace": "default",
  "description": "Standard resume layout",
  "access_scope": "SYSTEM",
  "content_schema": { ... }
}
-->
```

This convention lets template files be self-describing. The seeder reads this metadata to determine
the template's name, namespace, access scope, and optional JSON Schema for content validation.

### Render Pipeline

Each `DOC_TEMPLATE_RENDER_REQUESTED` event triggers this sequence:

1. **Validation**: The template is rendered through the Jinja2 engine and checked for JavaScript
   (security), invalid HTML, and JSON Schema compliance if a schema is embedded. Validation results
   are Redis-cached by a hash of the template source + schema + data.
2. **Jinja2 rendering**: The template is rendered with the deserialized data dict.
3. **Format conversion**: For `HTML`, the rendered string is returned directly (with optional
   `html2text` plain-text alternative). For `PDF`, the HTML is sent to Gotenberg. For `IMAGE`,
   the HTML is sent to Gotenberg's screenshot endpoint.
4. **S3 storage**: The output bytes are uploaded to RustFS under `rendered/{correlation_id}/{template_id}.{ext}`.
5. **Usage tracking**: `last_used_at` and `usage_count` are updated on the template row
   (best-effort, uses a savepoint so failures do not abort the main transaction).
6. **Outbox write**: `DOC_TEMPLATE_RENDER_COMPLETED` is written to the outbox in the same
   transaction as the usage update, then committed.

## Configuration

Settings use `DatabaseMixin`, `RedisMixin`, `KafkaMixin`, `S3Mixin`, and `NohikiBaseSettings`,
all prefixed by `DOC_TEMPLATE_`.

Key environment variables:

| Variable | Default | Purpose |
| ---------- | --------- | --------- |
| `DOC_TEMPLATE__GOTENBERG__BASE_URL` | `http://gotenberg:3000` | Gotenberg service endpoint |
| `DOC_TEMPLATE__GOTENBERG__REQUEST_TIMEOUT_S` | `10` | Per-request timeout for Gotenberg HTTP calls |
| `DOC_TEMPLATE__TEMPLATE_SETTINGS__SEED_ON_STARTUP` | `true` | Whether to seed default templates on startup |
| `DOC_TEMPLATE__TEMPLATE_SETTINGS__CACHE_MAX_ITEMS` | `1000` | Max items in the in-memory cache layer |
| `DOC_TEMPLATE__TEMPLATE_SETTINGS__CACHE_TTL_SECONDS` | `3600` | TTL for in-memory cache entries |
| `DOC_TEMPLATE__KAFKA__CONSUMER__MAX_CONCURRENT_HANDLERS` | `5` | Parallel render workers |

The Kafka consumer group base is derived from `settings.kafka_consumer_group` and appended with
`-commands` for all handler registrations.

## Development

### Local Setup

```bash
uv sync
alembic upgrade head
```

Gotenberg must be reachable at `DOC_TEMPLATE__GOTENBERG__BASE_URL` for PDF and image renders.
Start it via the monorepo Compose stack:

```bash
just compose-up
```

### Testing

```bash
# From the monorepo root
just test doc-template-service
just test-cov doc-template-service
```

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise
uv run ty check
```
