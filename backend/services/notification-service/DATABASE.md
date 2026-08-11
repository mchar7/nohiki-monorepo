# Notification Service Database Design

Schema `notification_schema` stores notification messages and their delivery lifecycle: from initial
enqueue through provider dispatch outcomes.

Every notification the service enqueues has exactly one `messages` row. The row tracks the
recipient, channel, rendered content, retry state, and provider-assigned message ID. When the
outbox worker transitions a message to `sent` or `failed`, it writes a corresponding outbox row
in the same database transaction: the status update and the event publication are atomic.

## `messages`

Represents a single outbound notification in the delivery queue. A row is created by a Kafka
event handler when it determines a notification should be sent, and the outbox worker transitions
it through its lifecycle states until the message is `sent`, `failed`, or `cancelled`.

The `channel` value is the canonical delivery channel. Storage vocabulary is independent of
provider availability; the service currently implements provider routing only for `EMAIL`.

Active inline Jinja2 notifications are rendered safely before enqueue. A row enters
`waiting_for_render` when template rendering has been requested via
`DOC_TEMPLATE_RENDER_REQUESTED`. The body remains `NULL`; no render-result handler exists, so the
row stays parked until the expiry sweep cancels it. The external layout reference is currently
unused in practice for the two active notification types, which use inline Jinja2 templates
rather than Gotenberg-rendered layouts.

### Queue and retry semantics

The `priority` value controls queue ordering: higher values are dispatched first. A partial
dispatch index covers the outbox worker's queue query: highest-priority messages first, then
oldest-created. It excludes already-terminal rows.

The outbox worker skips messages where `scheduled_at > now()`.

Retry timing is set by `RetryStrategy`
using exponential backoff: `base_delay_seconds × 2^(retry_count - 1)`, capped at
`max_retry_delay_seconds`. The worker skips messages where `retry_at > now()`.

The retry count resets to 0 on successful delivery. If `provider_name` is absent, the worker uses
the configured default.

### Expiry

`expires_at` is the point past which the message is cancelled instead of sent.
Stamped at creation from `message_ttl.default_ttl_hours`, relative to `scheduled_at` when a
schedule is given. `MessageExpirySweep` cancels elapsed rows that are still awaiting delivery,
and the outbox worker re-checks the value before each dispatch to cover the gap between claim
and send. Either path writes a `NotificationFailed` outbox row in the same transaction, so an
expiry is observable downstream rather than a row that silently stopped moving. NULL means
no expiry.

A partial expiry index covers the sweep's claim query and excludes terminal rows and rows without
an expiry. Its status list is every state still awaiting a delivery attempt and must stay identical
to `MessageExpirySweep.build_expired_query`, or the sweep degrades to a sequential scan.

### Duplicate suppression

The unique user-listing constraint prevents the service from sending duplicate notifications for
the same user-listing pair. It acts as the idempotency guard for the
`JOB_CORRELATION_EVALUATED` handler: a second correlation event for the same listing and user is
silently rejected by an `IntegrityError` rather than producing a second email.

`user_id` identifies the account owned by `user-auth-service`, and `stored_listing_id` identifies
`job_storage_schema.listings.id`. Both are cross-schema references without foreign keys.

### Data Lifecycle

- **Created** by `handle_notification_event` when a `JOB_CORRELATION_EVALUATED` or
  `DOC_CONTENT_GENERATION_COMPLETED` Kafka event passes all threshold and status checks.
  Initial status is `pending` (body pre-rendered) or `waiting_for_render` (if body requires
  external template rendering).
- **Updated** by the outbox worker on each dispatch attempt: status transitions to `retrying`
  (failure, will retry), `sent` (success), or `failed` (exhausted retries or non-retryable error).
  `retry_count`, `retry_at`, `sent_at`, `last_error`, and `provider_msg_id` are updated
  accordingly.
- **Cancelled** via `MessageRepository.cancel()` if the message is in a cancellable state
  (`pending`, `waiting_for_render`, or `retrying`). Terminal states (`sent`, `failed`) cannot be
  cancelled.
- **Deleted** only via schema DROP on deployment. No row-level deletion occurs in normal operation.

## Outbox Table

The service uses the transactional outbox pattern for guaranteed delivery of notification lifecycle
events. The `outbox` table structure is defined by `nohiki-db-utils` (`get_create_outbox_table_sql`)
and follows the standard Nohiki outbox schema.

`NotificationEventPublisher` (`services/outbox/event_publisher.py`) writes outbox rows using
`OutboxWriter` from `nohiki-db-utils`. The caller (outbox worker) always writes the outbox row
**before** calling `db.commit()`, ensuring the domain state change and the event record land in
the same PostgreSQL transaction.

**Events published via outbox:**

- **`NOTIFICATION_SENT`** (`notification.fct.sent.v1`): Written when a provider confirms
  delivery.

- **`NOTIFICATION_FAILED`** (`notification.fct.failed.v1`): Written when a message reaches
  terminal failure, and when the TTL path cancels a message. A dispatch attempt that defers the
  message to `retrying` writes no outbox row; the event is emitted once the retry budget is spent.

Both event kinds use aggregate type `"notification"` and the message ID as `aggregate_id`.
Debezium uses `aggregate_id` as the Kafka message key, preserving per-message partition ordering.

`correlation_id` tracks the originating Kafka message correlation ID through the delivery
lifecycle. If absent, it falls back to the message id.

Debezium's PostgreSQL connector with the Outbox Event Router SMT reads the outbox table from the
WAL and publishes events to Kafka after commit. See
`infra/k8s/kafka-connect/connectors/` for the connector configuration. Neither the connector nor
the service deletes outbox rows, so rows remain after publication.

## Processed Events Table

The `processed_events` table is created by the migration via `get_create_processed_events_sql` from
`nohiki-db-utils`. No handler in this service currently writes or reads it, so it provides no
deduplication today. Handler idempotency rests on the unique `(user_id, stored_listing_id)`
constraint, which does not cover notifications enqueued without a `stored_listing_id` (for example
document generation notifications).

## Sources

- Models: `src/notification_service/db/models.py`
- Baseline revision: `alembic/versions/001_initial_migration.py`
- Migration workflow: [../../../README.md#database-migration-workflow](../../../README.md#database-migration-workflow)
