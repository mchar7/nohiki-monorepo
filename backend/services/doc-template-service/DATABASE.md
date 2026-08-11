# Doc Template Service Database Design

Schema `doc_template_schema` stores the Nohiki template registry: versioned Jinja2 HTML
templates used to render resume and cover letter documents.

Each `document_templates` row is a complete, self-contained template version. The logical template
family is identified by the `(namespace, name, owner_id)` tuple; different versions of the same
template share that tuple but differ by the `version` column. The `outbox` table captures template
lifecycle events (created, updated, deleted) and render-completed facts in the same transaction as
the domain write, giving Debezium an at-least-once delivery guarantee with no separate Kafka publish
step. The baseline migration also creates a `processed_events` table, but no handler in this service
reads or writes it; command deduplication relies on the unique constraint over
`(namespace, name, version, owner_id)` and on handler-level not-found tolerance instead.

## `document_templates`

Stores every version of every Jinja2 HTML template known to the service. The single-table design
means there is no separate template-family or version table: the family is a logical concept
derived from the `(namespace, name, owner_id)` grouping, while this table holds the physical
version rows.

New versions are always inserted as new rows; existing rows are never mutated. `template_content`
is the authoritative copy of the template; the render handler receives this value directly in
`DOC_TEMPLATE_RENDER_REQUESTED` events via ECST, so this field is not queried at render time.

`content_schema` is a JSON Schema object describing the data payload accepted by the template
(`{}` when the template declares none). It is forwarded downstream in the version snapshot, and it
is read at render time: the render handler loads this row by `template_id` and validates the event
payload against this column before rendering, because no producer enforces the schema it was given.

`owner_id` references `user_auth_schema.users.id` (no FK constraint, a cross-schema reference by
UUID). It is set to the creating user's ID for `PRIVATE` templates and left unset otherwise.

Access control is evaluated by `can_access_resource()`: `PUBLIC` templates are readable by every
user, `PRIVATE` templates only by their owner, and `SYSTEM` templates only by the seeder identity
`SYSTEM_SERVICE_UUID`. `list_templates()` applies the same rule, adding the `SYSTEM` branch to its
filter only when the caller is that seeder identity. Only the seeder may create `SYSTEM`-scoped
templates.

The "list all versions of a template family" and "get latest version" queries both filter by the
`(namespace, name, owner_id)` tuple. The access-control filter applied in `list_templates()` is also
backed by the stored scope and owner. Created-time access supports time-range scans and
`ORDER BY created_at DESC` (used to find the latest version). BRIN is appropriate because UUIDv7
primary keys guarantee near-monotonic insertion order, so page-level min/max statistics are tight.

### Constraints & Invariants

- One version string per template family per owner. The service never updates `version` in place;
  to "update" a template, a new row is inserted with a higher version string.
- The uniqueness rule also serves as the idempotency key for create commands: an `IntegrityError`
  on this constraint indicates a duplicate-version attempt, not a data error.
- The `version` column must match the full SemVer 2.0 regex. Enforced at the DB layer as a
  backstop; the service layer validates first via `validate_semantic_version()`.
- The `content_schema` column must be a JSON object. Prevents accidental insertion of scalars or
  arrays where an object is expected.

### Data Lifecycle

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

## `outbox`

Standard transactional outbox table shared across Nohiki stateful services. Every domain event
published by this service is written here first, in the same database transaction as the triggering
domain change. Debezium reads from the PostgreSQL WAL and routes rows to Kafka via the Outbox Event
Router SMT.

Lifecycle events use `"template"` as their aggregate type and `template.id` as their aggregate ID.
Render-completed events use `"render"` as their aggregate type and `correlation_id` as their
aggregate ID. The connector uses the aggregate ID as the Kafka message key and partitioning key,
while the event type determines the destination topic.

Events published via outbox:

- `doc-template.cdc.template-created.v1`: after `create_template()` succeeds (includes seeder)
- `doc-template.cdc.template-updated.v1`: after a new template version row is inserted
- `doc-template.cdc.template-deleted.v1`: after a template version row is deleted
- `doc-template.fct.render-completed.v1`: after a successful render, and with `FAILED` status for
  terminal validation or generation failures. Retryable infrastructure errors re-raise instead of
  publishing, so the render request is redelivered rather than terminated.

Rows are inserted by `outbox.write_event()` within the handler transaction and committed atomically
with the domain change. The writer stores the serialized protobuf payload as bytes. Debezium reads
committed rows from the WAL and never deletes them, and the connector configuration
(`infra/k8s/kafka-connect/connectors/outbox-connector-template.json`) sets no retention or cleanup
for the table, so outbox rows accumulate until something outside this service removes them.

## Schema Sources

- Models: `backend/services/doc-template-service/src/doc_template_service/db/models.py`
- Baseline revision: `backend/services/doc-template-service/alembic/versions/001_initial_migration.py`
- Migration workflow: [root README](../../../README.md#database-migration-workflow)
