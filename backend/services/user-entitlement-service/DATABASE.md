# User Entitlement Service Database Design

Schema `user_entitlement_schema` stores one entitlement record per Nohiki user, capturing
their active subscription tier, computed per-tier limits, and billing provider references.

## `entitlements`

The `entitlements` table is the only domain table. Every `USER_AUTH_ACCOUNT_UPDATED` delivery is
paired with an `outbox` row in the same nested transaction, including the idempotent path where
the row already exists and is returned unchanged, so `USER_ENTITLEMENT_CHANGED` is republished on
every account update rather than only on provisioning.

Stores the subscription tier and computed access limits for each user account. One row per user,
identified by `user_id`. This row is the authoritative record that drives the
`EntitlementSnapshot` carried in all downstream events. `user_id` references
`user_auth_schema.accounts.id` without a database-level foreign key, because the reference
crosses schemas, and it serves as the idempotency key for the `USER_AUTH_ACCOUNT_UPDATED`
handler. The primary key is a standard row identifier, not used as a join key by other services
(those use `user_id` instead).

The computed limit columns (`discovery_frequency_limit`, `max_prefs`, `max_uploads_per_pref`,
`allowed_sources`, `features_enabled`) are derived from the tier by `core/tiers.py`, which is the
single source of truth for what each tier grants.

Uniqueness on `user_id` enforces one entitlement per account. The `create_default_entitlements`
function catches `IntegrityError` on duplicate insert and returns the existing row, preventing
duplicate entitlement rows under at-least-once Kafka delivery. It does not claim the event or
prevent another outbox event. An `IntegrityError` that is not a duplicate user is re-raised
unchanged.

Fetching an entitlement by user ID is the primary lookup pattern. Account deletion also deletes
by user ID. The schema supports bulk queries scoped to a tier and queries scoped to subscription
state, although no current service code issues either query.

### Subscription state

`subscription_status` is a state machine field backed by `StateMachineMixin`. The model permits
`NONE` to transition to `TRIALING` or `ACTIVE`. Validation happens only when a caller invokes
`transition_to`, which raises `InvalidTransitionError` for undeclared targets. No current code
path in this service calls it, so no status change is validated today.

### Data Lifecycle

- **Created** when `USER_AUTH_ACCOUNT_UPDATED` is consumed for a user that has no existing
  entitlement row. The initial tier is always `FREE` with `subscription_status = NONE`.
- **Updated** by no code path in this service. Creation is the only writer of tier and limit
  columns, so the derived limits are applied once, at provisioning.
- **Deleted** when `USER_AUTH_ACCOUNT_DELETED` is consumed. No cascade exists; this is a direct
  `DELETE WHERE user_id = ?`. No outbox event is published on deletion.

## Outbox Table

The service uses the transactional outbox pattern for guaranteed event delivery. Every
`USER_AUTH_ACCOUNT_UPDATED` delivery writes an `outbox` row in the same nested transaction as the
entitlement insert attempt, including when the existing entitlement is returned unchanged.
Debezium's PostgreSQL connector with the Outbox Event Router SMT reads the table from the
PostgreSQL WAL and publishes events to Kafka.

**Event published via outbox:**

- `USER_ENTITLEMENT_CHANGED` (`user-entitlement.cdc.entitlement-changed.v1`), published on every
  `USER_AUTH_ACCOUNT_UPDATED` delivery. The `aggregateid` column is set to `user_id`; the
  `aggregatetype` column is `"entitlement"`.

The application never deletes outbox rows, and Debezium does not remove source rows after reading
them. The connector disables tombstones on source deletion. Without external cleanup, the table
only grows.

The migration also provisions a `processed_events` table for consumer idempotency. No handler in
this service calls `check_and_mark_processed`, so nothing writes to it and incoming events are not
claimed. Duplicate `USER_AUTH_ACCOUNT_UPDATED` deliveries are absorbed only at the entitlement
insert by uniqueness on `user_id`; each delivery still writes another outbox event.

See `infra/k8s/kafka-connect/` for the Debezium connector configuration.

## Sources

- Models: `backend/services/user-entitlement-service/src/user_entitlement_service/db/models.py`
- Baseline revision:
  `backend/services/user-entitlement-service/alembic/versions/001_initial_migration.py`
- Migration workflow: [root README](../../../README.md#database-migration-workflow)
