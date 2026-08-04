# User Entitlement Service

Assigns and manages subscription tier entitlements for every Nohiki user account. When
`user-auth-service` creates an account, this service automatically provisions a free-tier
entitlement record and publishes the initial state to downstream consumers. Tier upgrades
and downgrades are applied here and propagated as `user-entitlement.cdc.entitlement-changed.v1`
events so other services can gate features without querying this service directly. Kafka-only,
stateful with PostgreSQL.

## Role in the System

This service is the single authority on what a user is allowed to do in Nohiki. It owns the
`user_entitlement_schema` and is the only service that reads or writes `entitlements` rows.
Every other service that enforces feature limits, including job query composition, preferences, and
job-ingest scheduling, derives those limits from the `EntitlementSnapshot` carried in
`USER_ENTITLEMENT_CHANGED` events, not from direct queries here.

The service sits early in the user lifecycle: it reacts to `USER_AUTH_ACCOUNT_UPDATED`, which
`user-auth-service` publishes on both account creation and updates. By handling this single
event idempotently, every account always has exactly one entitlement record.
Account deletion triggers hard deletion of that record, with no outbox event published, so the
absence of an entitlement is implicit downstream.

`job-query-composition-service` is the primary downstream consumer of entitlement change events,
using the `discovery_frequency_limit` from the snapshot to gate how often job discovery runs
for a given user.

## Event-Driven Integration

### Events Consumed

- **`USER_AUTH_ACCOUNT_UPDATED`** (`AccountUpdated`): The primary lifecycle trigger. On receipt,
  the handler calls `create_default_entitlements`, which inserts a free-tier row. Because
  `user-auth-service` publishes this event for both creation and updates, the handler handles
  duplicate delivery via `IntegrityError` on the `UNIQUE (user_id)` constraint: it catches the
  error, rolls back the flush, and returns the existing record instead. A
  `USER_ENTITLEMENT_CHANGED` outbox event is published after every successful path.
  Consumer group: `user-entitlement-service-consumer`.

- **`USER_AUTH_ACCOUNT_DELETED`** (`AccountDeleted`): Triggers hard deletion of the user's
  entitlement row. No outbox event is published on deletion, so consumers that track entitlement
  state must handle the account-deleted event from `user-auth-service` directly.
  Consumer group: `user-entitlement-service-consumer`. Partition ordering is preserved so an
  earlier account update cannot recreate entitlements after a later account deletion.

### Events Published

- **`USER_ENTITLEMENT_CHANGED`** (`EntitlementChanged`, topic `user-entitlement.cdc.entitlement-changed.v1`):
  Published via the transactional outbox after every entitlement create or update. Carries a full
  `EntitlementSnapshot` -- tier, subscription status, discovery frequency limit, max preferences,
  max uploads per preference, allowed job board sources, and feature flags, so consumers never
  need to query back. Keyed by `user_id` (as the `aggregate_id`) to preserve per-user ordering.
  Consumed by `job-query-composition-service` to update per-user job discovery frequency.

### Notable Patterns

**Transactional outbox**: `publish_entitlements_changed_event` writes the `EntitlementChanged`
protobuf to the `outbox` table in the same database transaction as the entitlement row insert
or update. Debezium's PostgreSQL connector reads the outbox from the WAL and publishes to Kafka,
guaranteeing the event reaches Kafka if and only if the database write commits.

## State & Persistence

### Database

Schema `user_entitlement_schema` holds a single `entitlements` table: one row per user, plus
the standard `outbox` table for Debezium CDC pickup and a `processed_events` table for consumer
idempotency. The entitlement row stores the active tier, subscription status, billing provider
references, and the computed per-tier limits (discovery frequency, max preferences, allowed job
board sources, feature flags).

See [DATABASE.md](./DATABASE.md) for complete schema documentation.

## Key Design Patterns

**Idempotent provisioning via IntegrityError**: The `create_default_entitlements` function
attempts a blind insert and catches `IntegrityError` from the `UNIQUE (user_id)` constraint
rather than checking for existence first. This avoids a read-before-write race condition and
keeps the handler idempotent under at-least-once Kafka delivery.

**Tier config as code**: `core/tiers.py` is the single source of truth for what each tier
grants. When `update_entitlements` changes a user's tier, it calls `get_tier_config` and
applies the full `TierConfig`, including limits and feature flags, to the entitlement row atomically.
There is no separate lookup at query time; downstream services read limits from the
`EntitlementSnapshot` carried in events.

**State machine on subscription status**: The `Entitlement` model uses `StateMachineMixin`,
which enforces the subscription status transition graph at the ORM layer. Valid transitions
are: `NONE → TRIALING/ACTIVE`, `TRIALING → ACTIVE/CANCELED/EXPIRED`, `ACTIVE → PAST_DUE/CANCELED/PAUSED`,
`PAST_DUE → ACTIVE/CANCELED/EXPIRED`, `CANCELED → EXPIRED/ACTIVE`, `PAUSED → ACTIVE/CANCELED/EXPIRED`,
`EXPIRED → ACTIVE/TRIALING`. Attempts to transition outside these paths raise at the model level
before any database write.

## Configuration

Settings use `DatabaseMixin` and `KafkaMixin` from shared libraries, with the `USER_ENTITLEMENT_`
env prefix.

| Variable | Purpose |
| ---------- | --------- |
| `USER_ENTITLEMENT_KAFKA__DSN` | Kafka bootstrap server URL |
| `USER_ENTITLEMENT_KAFKA__CONSUMER_GROUP` | Consumer group for both handlers (default: `user-entitlement-service-consumer`) |
| `USER_ENTITLEMENT_DATABASE__DSN` | PostgreSQL connection string |
| `USER_ENTITLEMENT_DATABASE__SCHEMA_NAME` | PostgreSQL schema (default: `user_entitlement_schema`) |

## Development

### Local Setup

```bash
uv sync
alembic upgrade head
```

### Testing

```bash
just test user-entitlement-service
just test-cov user-entitlement-service
```

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise
uv run ty check
```
