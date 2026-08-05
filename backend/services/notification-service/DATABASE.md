# Notification Service Database Design

## Ownership and boundaries

The `notification_schema` schema is the notification service's durable source of truth for delivery work and delivery
outcomes. Every notification accepted for delivery has exactly one persisted message that carries its recipient and
channel, rendered content, scheduling and retry state, provider selection and response context, and origin metadata
through the full delivery lifecycle.

User identity comes from the ECST event snapshot rather than a database relationship to the account service. Listing
identity refers to the job-storage domain when a notification concerns a specific listing. The service retains those
identities for history and correlation without claiming ownership of either domain. The persisted message identity is
the outbox aggregate identity. The originating Kafka correlation identifier follows the notification separately for
tracing, falling back to the message identity when no originating correlation is available.

The storage vocabulary for notification channels is intentionally independent of current provider availability. Delivery
routing currently implements email only. A message may name a provider or allow the worker to use the configured
provider. Active inline notifications render their Jinja content safely before enqueue. The lifecycle also supports an
external document-template rendering handoff, in which a message waits for rendered content, although the current
notification types do not use that path. Template context is retained for rendering and audit, while provider delivery
context can retain details such as a plain-text alternative.

## Delivery lifecycle

A Kafka handler creates the durable message after deciding that a notification should be sent. A message normally begins
`pending`; an external rendering request instead begins `waiting_for_render`. The outbox worker advances eligible work
through the lifecycle until it becomes `sent`, `failed`, or `cancelled`:

- `waiting_for_render` becomes dispatchable when the render callback supplies the content.
- `pending` work is eligible once any scheduled delivery time has passed.
- A retryable provider failure moves the message to `retrying`, records the latest error, and defers another attempt
  until the computed retry time. The delay grows exponentially from the configured base, is capped by the configured
  maximum, and honors a provider `Retry-After` value as a minimum.
- Provider confirmation moves the message to `sent`, records the successful delivery time and provider-assigned message
  identity for provider-side tracing, and resets the attempt count.
- Exhausted retries or a non-retryable provider error move the message to `failed`.
- Manual cancellation is allowed only while a message remains pending, waiting for rendering, or retrying. Terminal
  messages cannot be cancelled.

Eligible work is dispatched by priority, with older work first among equal priorities. The worker skips future-scheduled
messages and retrying messages whose retry time has not arrived.

Expiry is based on the message's delivery horizon. For future-scheduled work, that horizon starts at the scheduled time
rather than enqueue time. The expiry sweep cancels elapsed messages that are still awaiting delivery, and the worker
rechecks expiry immediately before each provider dispatch to cover the race between sweep selection and send. Both paths
persist a `NOTIFICATION_FAILED` outbox outcome in the same transaction as cancellation, so expiry is observable
downstream rather than silently stopping work. Messages without an expiry remain eligible indefinitely.

## Deduplication and concurrency

A user can receive at most one notification for the same stored listing. This database invariant is the idempotency
guard for the job-correlation handler: a second correlation event for the same pair is rejected instead of producing
another email.

The shared processed-event log records Kafka message identities that have completed successfully. It supplies a second,
message-level deduplication layer, including notification flows that have no listing identity, such as
document-generation notifications. Together these guards cover domain-level duplicates and redelivery of the same Kafka
message.

The dispatch queue claims `pending` and `retrying` work. Expiry also covers `waiting_for_render`, so a stalled rendering
handoff can expire without becoming dispatchable; both paths exclude terminal history. Concurrent workers claim delivery
work through the repository's queue semantics rather than treating a read as ownership.

## Transactional outcomes and CDC

The service uses the standard `nohiki-db-utils` transactional outbox. `NotificationEventPublisher` adds an outcome to
the caller's database transaction and never commits independently. The caller always commits, so the message transition
and its outcome either both commit or neither commits.

A provider-confirmed delivery records `NOTIFICATION_SENT`, including the notification, recipient and channel, provider
outcome, user and listing context, and delivery time. A terminal provider failure or expiry records
`NOTIFICATION_FAILED`, including the error, failure cause, attempt history, and failure time. These are delivery facts
for downstream projections; the notification database remains the source of truth for the message lifecycle.

Debezium's PostgreSQL connector and Outbox Event Router SMT read committed outbox entries from the WAL and publish them
to Kafka after commit. Database atomicity therefore covers the lifecycle transition and outbox entry; Kafka publication
is the subsequent CDC step. Connector configuration lives under `infra/k8s/kafka-connect/connectors/`.

## Operations, retention, and access rationale

Lifecycle state, scheduled and retry timing, attempt count, the most recent provider error, successful-delivery time,
expiry, and provider message identity are the primary operational signals for delayed, repeatedly failing, expired, and
provider-confirmed notifications. The latest error intentionally replaces the prior one so operators see the current
failure, while retry history remains visible through the attempt count and lifecycle outcomes.

Access paths reflect the workload rather than serving as a general schema catalog:

- Notification history is overwhelmingly append-only, so chronological scans exploit the physical correlation between
  creation order and stored rows.
- Worker access concentrates on the active lifecycle set. Its queue path excludes terminal history and supports
  highest-priority, then oldest-first dispatch; state equality is optimized because the worker repeatedly selects
  pending and retrying work.
- Expiry access is limited to nonterminal messages that actually expire, so a sweep does not scan terminal rows or
  messages with no delivery horizon.
- User history, origin-correlation tracing, and listing-specific lookup paths cover only messages that carry the
  relevant association, avoiding unnecessary entries for system or unrelated messages.

Notification rows are retained for lifecycle and audit history. Normal operation does not perform row-level deletion.

The schema itself is defined by the service's SQLAlchemy models in
`backend/services/notification-service/src/notification_service/db/models.py` and Alembic revision
`backend/services/notification-service/alembic/versions/001_initial_migration.py`.
