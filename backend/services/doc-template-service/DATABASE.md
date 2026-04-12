# Doc Template Service Database Schema

Schema `doc_template_schema` stores the Nohiki template registry: versioned Jinja2 HTML
templates used to render resume and cover letter documents.

## Entity Overview

| Table | Purpose |
|-------|---------|
| `document_templates` | Versioned Jinja2 HTML templates; each row is an immutable template version |
| `outbox` | Transactional outbox for CDC event publishing via Debezium |
| `processed_events` | Idempotency log to deduplicate redelivered Kafka messages |

Each `document_templates` row is a complete, self-contained template version. The logical template
family is identified by the `(namespace, name, owner_id)` tuple; different versions of the same
template share that tuple but differ by the `version` column. The `outbox` table captures template
lifecycle events (created, updated, deleted) and render-completed facts in the same transaction as
the domain write, giving Debezium an at-least-once delivery guarantee with no separate Kafka publish
step. The `processed_events` table records consumed command event IDs to prevent duplicate processing
under consumer redelivery.

## Table Details

### `document_templates`

#### Purpose

Stores every version of every Jinja2 HTML template known to the service. The single-table design
means there is no separate template-family or version table: the family is a logical concept
derived from the `(namespace, name, owner_id)` grouping, while this table holds the physical
version rows.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key, generated server-side via `DEFAULT uuidv7()`. The
  timestamp-ordered nature of UUIDv7 makes `created_at DESC` ordering redundant for range scans,
  though both are available.
- **`namespace`** (`VARCHAR(100)`): Logical grouping for templates, defaulting to `"default"`.
  Allows different products or users to maintain separate template namespaces without naming
  conflicts.
- **`name`** (`VARCHAR(255)`): Human-readable template name within a namespace (e.g.,
  `"resume-standard"`). Together with `namespace` and `owner_id`, identifies a template family.
- **`version`** (`VARCHAR(50)`): Semantic version string (e.g., `"1.0.0"`, `"2.1.0-beta"`).
  The `chk_version_semver` CHECK constraint rejects any value that does not match the SemVer
  regex. New versions are always inserted as new rows; existing rows are never mutated.
- **`template_content`** (`TEXT`): The full Jinja2 HTML source. This is the authoritative copy
  of the template; the render handler receives this value directly in `DOC_TEMPLATE_RENDER_REQUESTED`
  events via ECST, so this field is not queried at render time.
- **`content_schema`** (`JSONB`): Optional JSON Schema object that describes and validates the
  data payload before rendering. The `chk_content_schema_json` CHECK constraint requires this
  column to be a JSON object (not a scalar or array). Defaults to `{}` (no validation).
- **`access_scope`** (`access_scope_enum`): Controls who can read and manage the template.
  Possible values: `PUBLIC` (visible to all users), `PRIVATE` (visible only to `owner_id`),
  `SYSTEM` (created by the seeder, visible to all, not modifiable by regular users).
- **`owner_id`** (`UUID`, nullable): References `user_auth_schema.users.id` (no FK constraint --
  cross-schema reference by UUID). `NULL` for `PUBLIC` and `SYSTEM` templates. Set to the
  creating user's ID for `PRIVATE` templates.
- **`last_used_at`** (`TIMESTAMPTZ`, nullable): Updated after each successful render via
  `record_usage()` on the `FreshnessTrackingMixin`. `NULL` until the template is first rendered.
- **`usage_count`** (`INTEGER`): Incremented on each successful render. Tracked for operational
  visibility; templates with `usage_count = 0` that are also old may be candidates for cleanup.

#### Indexes

- **`uq_template_name_version_owner`** UNIQUE on `(namespace, name, version, owner_id)`: Enforces
  one row per template version per owner. Also serves as the idempotency key for create commands:
  an `IntegrityError` on this constraint indicates a duplicate-version attempt, not a data error.
- **`ix_template_namespace_name_owner`** on `(namespace, name, owner_id)`: Supports the
  "list all versions of a template family" and "get latest version" queries, both of which filter
  by this triple.
- **`ix_template_access_scope_owner`** on `(access_scope, owner_id)`: Supports the access-control
  filter applied in `list_templates()` -- queries that combine `access_scope IN (PUBLIC, SYSTEM)`
  with `(access_scope = PRIVATE AND owner_id = ?)`.
- **`ix_template_created`** BRIN on `(created_at)` with `pages_per_range = 32`: Supports
  time-range scans and `ORDER BY created_at DESC` (used to find the latest version). BRIN is
  appropriate because UUIDv7 PKs guarantee near-monotonic insertion order, so page-level min/max
  statistics are tight.

#### Constraints & Invariants

- **UNIQUE** `(namespace, name, version, owner_id)`: One version string per template family per
  owner. The service never updates `version` in place; to "update" a template, a new row is
  inserted with a higher version string.
- **CHECK** `chk_version_semver`: The `version` column must match the full SemVer 2.0 regex.
  Enforced at the DB layer as a backstop; the service layer validates first via `validate_semantic_version()`.
- **CHECK** `chk_content_schema_json`: The `content_schema` column must be a JSON object.
  Prevents accidental insertion of scalars or arrays where an object is expected.

#### Data Lifecycle

- **Created** when `DOC_TEMPLATE_CREATE_REQUESTED` is consumed (initial version `1.0.0`), when
  `DOC_TEMPLATE_VERSION_ADD_REQUESTED` is consumed (subsequent versions), or during startup seeding
  by the `seed_default_templates()` function. All three paths call `create_template()` and commit
  the new row.
- **Updated** only for usage tracking: `last_used_at` and `usage_count` are updated after each
  successful render, using a savepoint so failures do not abort the surrounding transaction.
  The `template_content` and `content_schema` columns are never updated; new content always
  produces a new row at a higher version.
- **Deleted** when `DOC_TEMPLATE_DELETE_REQUESTED` is consumed. Deletion targets a specific
  `(template_id, user_id)` pair; the handler enforces ownership before deleting. The
  `delete_all_template_versions()` function (not exposed via command yet) can remove all versions
  of a template family.

### `outbox`

#### Purpose

Standard transactional outbox table shared across Nohiki stateful services. Every domain event
published by this service is written here first, in the same database transaction as the triggering
domain change. Debezium reads from the PostgreSQL WAL and routes rows to Kafka via the Outbox Event
Router SMT.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key.
- **`aggregate_type`** (`VARCHAR`): Domain entity type. Always `"template"` for template
  lifecycle events; `"render"` for render-completed events.
- **`aggregate_id`** (`VARCHAR`): The entity's UUID as a string. Template lifecycle events use
  `template.id`; render events use `correlation_id`.
- **`event_type`** (`VARCHAR`): The Kafka topic name (e.g., `doc-template.cdc.template-created.v1`).
  Debezium uses this column to determine the destination topic.
- **`payload`** (`JSONB`): betterproto2-serialized event payload, stored as a JSON object.
- **`correlation_id`** (`VARCHAR`, nullable): Copied from the originating event's metadata for
  distributed tracing across services.
- **`created_at`** (`TIMESTAMPTZ`): Insertion timestamp. Debezium processes rows in insertion
  order.

#### Events Published via Outbox

- `doc-template.cdc.template-created.v1` -- after `create_template()` succeeds (includes seeder)
- `doc-template.cdc.template-updated.v1` -- after a new template version row is inserted
- `doc-template.cdc.template-deleted.v1` -- after a template version row is deleted
- `doc-template.fct.render-completed.v1` -- after every render attempt (success or failure)

#### Data Lifecycle

Rows are inserted by `outbox.write_event()` within the handler transaction and committed atomically
with the domain change. Debezium reads processed rows from the WAL and does not delete them;
the Debezium connector configuration (see `infra/kafka-connect/connectors/`) controls retention
of processed outbox entries.

### `processed_events`

#### Purpose

Idempotency log that records the `event_id` of every successfully processed Kafka command. Before
processing a command, the handler checks this table; if the event ID is already present, the
message is a redelivery and the handler skips processing. This prevents double-writes when Kafka
redelivers messages after a consumer restart.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key.
- **`event_id`** (`VARCHAR`): The Kafka message's unique event identifier, sourced from
  `EventMetadata.event_id` in the consumed protobuf message.
- **`event_type`** (`VARCHAR`): The topic name the event was consumed from.
- **`processed_at`** (`TIMESTAMPTZ`): When the event was successfully handled.

#### Data Lifecycle

- **Created** after each command is successfully processed and committed.
- **Never updated or deleted** -- this table grows monotonically. Periodic pruning by wall-clock
  age is possible but not currently implemented.

## Migration Strategy

Nohiki uses **clean-cut deployment**: all services are stopped, schemas are dropped and recreated,
and the single `001_` migration is applied fresh. The migration file is edited in place rather
than creating incremental migrations.

This is possible because Nohiki is pre-release with zero production data. There are no data
migrations or backward compatibility concerns.

```bash
# Apply migration
alembic upgrade head

# Generate updated migration after model changes
alembic revision --autogenerate -m "description"

# View current state
alembic current
```
