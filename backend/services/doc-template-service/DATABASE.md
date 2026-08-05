# Doc Template Database Design

## Purpose and Boundaries

The service owns the Nohiki template registry for versioned Jinja2 HTML used to render resume and
cover letter documents. Each stored version is a complete, self-contained template. The full HTML
source is authoritative here, while an optional content schema describes and validates the render
payload.

Render requests receive the template source through event-carried state transfer, so the render
path does not query the registry for that content.

## Version Families and Immutability

A logical template family is identified by its namespace, name, and owner. Namespaces allow
different products or users to maintain independent naming domains. Each semantic version in a
family is stored separately; template source and content-schema changes always create a new,
higher version rather than mutating an existing version.

Only one instance of a version string may exist within a family. A duplicate-version attempt is
therefore treated as create-command idempotency rather than as an unrelated data error. Semantic
versions are validated by the service and backed by a database invariant.

Keeping each version self-contained avoids a separate family/version hierarchy. The design is
optimized around grouping all versions of a family, selecting its latest version, and applying
visibility filters by access scope and owner. Time-ordered identifiers keep insertion order
near-monotonic, which makes coarse page-level time summaries effective for time-range and
recent-version scans.

## Ownership and Access

Access semantics distinguish public templates visible to everyone, private templates visible only
to their owner, and system templates created by the seeder that everyone may read but regular
users may not modify. Private ownership refers to the creating user's identity in
`user-auth-service`; public and system templates have no user owner.

## Template Lifecycle

- `DOC_TEMPLATE_CREATE_REQUESTED` creates an initial `1.0.0` version.
- `DOC_TEMPLATE_VERSION_ADD_REQUESTED` adds a subsequent immutable version.
- Startup seeding uses the same creation path for default templates.
- Successful renders update last-used time and usage count. This tracking uses a savepoint so a
  tracking failure does not abort the surrounding transaction.
- `DOC_TEMPLATE_DELETE_REQUESTED` deletes a specific template version only after checking the
  requesting user's ownership. An internal operation can delete every version in a family, but it
  is not currently exposed as a command.

Last-used time and usage count provide operational visibility. Old templates that have never been
used may be candidates for cleanup, but no automatic template-retention policy is described here.

## Transactional Events and Delivery

Domain events are recorded transactionally with the change that produced them. Debezium reads the
records from the PostgreSQL WAL and routes them to Kafka through the Outbox Event Router SMT, so
there is no separate Kafka publish step that can diverge from the committed domain state. Delivery
is at least once.

The service publishes:

- `doc-template.cdc.template-created.v1` after template creation, including seeding;
- `doc-template.cdc.template-updated.v1` after inserting a new template version;
- `doc-template.cdc.template-deleted.v1` after deleting a template version; and
- `doc-template.fct.render-completed.v1` after every render attempt, whether it succeeds or fails.

Template lifecycle events are associated with the template identity; render events are associated
with the request correlation identity. Event payloads use betterproto2 JSON serialization, and
originating correlation metadata is carried for distributed tracing. Debezium processes the
transactional event records in insertion order.

Debezium does not delete event records after reading them from the WAL. Connector configuration
controls their retention, so successful delivery does not by itself bound database growth.

## Consumer Idempotency and Retention

Before handling a Kafka command, the service checks whether its event identity was processed
successfully before. A recorded identity marks a redelivery, which is skipped to prevent duplicate
writes after consumer restarts. Successfully handled command identities are recorded after
processing and commit.

These records are never updated or deleted and therefore grow monotonically. Age-based pruning is
possible, but it is not currently implemented.

The schema itself is defined by the SQLAlchemy models in
`backend/services/doc-template-service/src/doc_template_service/db/models.py` and the Alembic
revision in
`backend/services/doc-template-service/alembic/versions/001_initial_migration.py`.
