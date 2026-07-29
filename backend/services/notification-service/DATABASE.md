# Notification Service Database Schema

Schema `notification_schema` stores notification messages and their delivery lifecycle: from initial
enqueue through provider dispatch outcomes.

## Entity Overview

| Table | Purpose |
|---|---|
| `messages` | Notification messages in all lifecycle states, with retry metadata and provider response data |
| `outbox` | Transactional outbox for `NOTIFICATION_SENT` and `NOTIFICATION_FAILED` CDC events |
| `processed_events` | Idempotency log for Kafka handler deduplication |

Every notification the service enqueues has exactly one `messages` row. The row tracks the
recipient, channel, rendered content, retry state, and provider-assigned message ID. When the
outbox worker transitions a message to `sent` or `failed`, it writes a corresponding outbox row
in the same database transaction: the status update and the event publication are atomic.

## Table Details

### `messages`

#### Purpose

Represents a single outbound notification in the delivery queue. A row is created by a Kafka
event handler when it determines a notification should be sent, and the outbox worker transitions
it through its lifecycle states until the message is `sent`, `failed`, or `cancelled`.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key, generated server-side via `uuidv7()`. Encodes creation
  timestamp.
- **`user_id`** (`UUID`): References the Nohiki user account. Nullable; populated from
  `pref_snapshot.user_id` in the ECST event. No FK constraint: cross-schema reference.
- **`correlation_id`** (`UUID`): Tracks the originating Kafka message correlation ID through the
  delivery lifecycle. Used as the `aggregate_id` in outbox events. If absent, falls back to the
  message `id`.
- **`stored_listing_id`** (`UUID`): References `job_storage_schema.listings.id` when the
  notification relates to a specific job listing. Nullable; used as part of the `UNIQUE`
  constraint that prevents duplicate notifications for the same user-listing pair.
- **`channel`** (`notification_channel_enum`): Delivery channel -- `EMAIL` or `PUSH_API`. Only
  `EMAIL` has an active provider. The enum is defined in the schema and maps directly to the
  `NotificationChannel` protobuf enum.
- **`provider_name`** (`VARCHAR(255)`): The provider that should handle this message
  (`"resend"` or `"twilio_sendgrid"`). Nullable; if absent, the worker uses the configured default.
- **`status`** (`msg_status_enum`): Current delivery state. Valid values and their meanings:
  - `pending` -- created, awaiting outbox worker pickup
  - `waiting_for_render` -- template rendering has been requested via `DOC_TEMPLATE_RENDER_REQUESTED`;
    body is NULL until render completes
  - `retrying` -- previous attempt failed; `retry_at` is set and the worker skips until that time passes
  - `sent` -- provider confirmed delivery; `sent_at` is set
  - `failed` -- exhausted all retry attempts, or a non-retryable error occurred
  - `cancelled` -- manually cancelled before dispatch
- **`external_layout_id`** (`UUID`): References a `doc-template-service` layout when template
  rendering is requested externally. Nullable; currently unused in practice for the two active
  notification types, which use inline Jinja2 templates rather than Gotenberg-rendered layouts.
- **`recipient`** (`VARCHAR(255)`): Destination address: email address for `EMAIL` channel.
  Required (NOT NULL).
- **`subject`** (`TEXT`): Rendered subject line. Nullable; populated at enqueue time from the
  template's subject format string.
- **`body`** (`TEXT`): Rendered HTML body. Active inline Jinja2 notifications are rendered safely
  before enqueue. It is NULL while an external `doc-template-service` render is pending and is
  populated by that service's render callback.
- **`template_vars`** (`JSONB`): Context retained for template audit and external rendering.
  Structure varies by notification type (see README for per-template variable lists). Validated
  by a CHECK constraint requiring it to be a JSON object when present.
- **`provider_payload`** (`JSONB`): Provider-specific delivery metadata. Currently holds
  `"text_alt"` (plain-text email alternative) when a plain-text version is included. Validated
  by a CHECK constraint requiring it to be a JSON object when present.
- **`retry_count`** (`INTEGER`): Number of delivery attempts made. Bounded 0-10 by a CHECK
  constraint. Resets to 0 on successful delivery.
- **`priority`** (`SMALLINT`): Queue ordering priority: higher values are dispatched first.
  Defaults to 0. Validated ≥ 0 by CHECK constraint.
- **`scheduled_at`** (`TIMESTAMPTZ`): Optional future delivery time. The outbox worker skips
  messages where `scheduled_at > now()`.
- **`retry_at`** (`TIMESTAMPTZ`): Earliest time for the next retry attempt. Set by `RetryStrategy`
  using exponential backoff: `base_delay_seconds × 2^(retry_count - 1)`, capped at
  `max_retry_delay_seconds`. The worker skips messages where `retry_at > now()`.
- **`sent_at`** (`TIMESTAMPTZ`): Timestamp of successful provider delivery. A CHECK constraint
  enforces that this is non-NULL when `status = 'sent'`.
- **`expires_at`** (`TIMESTAMPTZ`): Point past which the message is cancelled instead of sent.
  Stamped at creation from `message_ttl.default_ttl_hours`, relative to `scheduled_at` when a
  schedule is given. `MessageExpirySweep` cancels elapsed rows that are still awaiting delivery,
  and the outbox worker re-checks the value before each dispatch to cover the gap between claim
  and send. Either path writes a `NotificationFailed` outbox row in the same transaction, so an
  expiry is observable downstream rather than a row that silently stopped moving. NULL means
  no expiry.
- **`last_error`** (`TEXT`): Error description from the most recent failed delivery attempt.
  Overwritten on each failure.
- **`provider_msg_id`** (`VARCHAR(255)`): The message ID assigned by the external provider on
  successful delivery (e.g., Resend's `id` field, SendGrid's `X-Message-Id` response header).
  Useful for provider-side delivery tracing.

#### Indexes

- **`ix_messages_created_at_brin`** BRIN on `(created_at)` with `pages_per_range = 32`:
  Time-series scan for chronological message history. BRIN is appropriate because messages are
  overwhelmingly append-only, making physical row order highly correlated with `created_at`.
- **`ix_messages_status_hash`** HASH on `(status)`: Equality lookups by status. Hash indexes
  are efficient for the repeated `WHERE status IN ('pending', 'retrying')` filter the worker uses.
- **`ix_messages_queue`** partial B-tree on `(priority DESC, created_at)` WHERE `status IN
  ('pending', 'retrying')`: The primary dispatch index. Covers the outbox worker's queue query --
  highest-priority messages first, then oldest-created. Partial to exclude already-terminal rows.
- **`ix_messages_user`** partial B-tree on `(user_id, created_at DESC)` WHERE `user_id IS NOT NULL`:
  Supports per-user message history queries (e.g., BFF delivery audit). Partial to exclude system
  messages without a user association.
- **`ix_messages_correlation_id`** partial B-tree on `(correlation_id)` WHERE
  `correlation_id IS NOT NULL`: Lookup messages by originating Kafka correlation ID for tracing.
- **`ix_messages_stored_listing_id`** partial B-tree on `(stored_listing_id)` WHERE
  `stored_listing_id IS NOT NULL`: Lookup all notifications related to a specific job listing.
- **`ix_messages_expires_at`** partial B-tree on `(expires_at)` WHERE `status IN
  ('pending', 'waiting_for_render', 'retrying') AND expires_at IS NOT NULL`: The TTL sweep's claim
  index. The status list is every state still awaiting a delivery attempt and must stay identical
  to `MessageExpirySweep.build_expired_query`, or the sweep degrades to a sequential scan. Partial
  so the sweep never walks terminal rows or rows without an expiry.

#### Constraints

- **UNIQUE** `uq_messages_user_stored_job` on `(user_id, stored_listing_id)`: Prevents the
  service from sending duplicate notifications for the same user-listing pair. Acts as the
  idempotency guard for the `JOB_CORRELATION_EVALUATED` handler: a second correlation event
  for the same listing and user is silently rejected by an `IntegrityError` rather than
  producing a second email.
- **CHECK** `chk_retry_count_range`: `retry_count >= 0 AND retry_count <= 10` -- prevents runaway
  retry counters.
- **CHECK** `chk_sent_at_consistency`: `(status = 'sent' AND sent_at IS NOT NULL) OR (status != 'sent')`
  -- ensures the audit timestamp is always present on delivered messages.
- **CHECK** `chk_priority_range`: `priority >= 0` -- priority must be non-negative.
- **CHECK** `chk_template_vars_json`: `template_vars IS NULL OR template_vars IS JSON OBJECT` --
  rejects non-object JSONB payloads.
- **CHECK** `chk_provider_payload_json`: `provider_payload IS NULL OR provider_payload IS JSON OBJECT`
  -- rejects non-object JSONB payloads.

#### Data Lifecycle

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
and follows the standard Nohiki outbox schema, including indexes from
`get_create_outbox_indexes_sql`.

`NotificationEventPublisher` (`services/outbox/event_publisher.py`) writes outbox rows using
`OutboxWriter` from `nohiki-db-utils`. The caller (outbox worker) always writes the outbox row
**before** calling `db.commit()`, ensuring the domain state change and the event record land in
the same PostgreSQL transaction.

**Events published via outbox:**

- **`NOTIFICATION_SENT`** (`notification.fct.sent.v1`): Written when a provider confirms
  delivery. Carries `notification_id`, `channel`, `recipient`, `sent_at`, `provider_name`,
  `provider_message_id`, `user_id`, and `listing_id`. `aggregate_type = "notification"`;
  `aggregate_id = message.id`.

- **`NOTIFICATION_FAILED`** (`notification.fct.failed.v1`): Written when a message reaches
  terminal failure. Carries `error_message`, `failure_cause`, `retry_count`, `will_retry`,
  `failed_at`. Also written when the delivery attempt transitions to `retrying` status after
  exceeding `max_retries`.

Debezium's PostgreSQL connector with the Outbox Event Router SMT reads the outbox table from the
WAL and publishes events to Kafka after commit. See
`infra/kafka-connect/connectors/` for the connector configuration.

## Processed Events Table

The `processed_events` table (created by `get_create_processed_events_sql` from `nohiki-db-utils`)
tracks Kafka message IDs that have been successfully handled. The `notification_handler.py`
handler is idempotent at the database level via the `UNIQUE` constraint on
`(user_id, stored_listing_id)`, but `processed_events` provides a secondary deduplication layer
at the Kafka message ID level for cases where `stored_listing_id` is absent (e.g., document
generation notifications).

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
