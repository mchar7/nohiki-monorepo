# User Entitlement Service Database Schema

Schema `user_entitlement_schema` stores one entitlement record per Nohiki user, capturing
their active subscription tier, computed per-tier limits, and billing provider references.

## Entity Overview

| Table | Purpose |
|-------|---------|
| `entitlements` | One row per user; stores tier, subscription status, computed limits, and billing provider references |
| `outbox` | Transactional outbox for Debezium CDC pickup of `USER_ENTITLEMENT_CHANGED` events |
| `processed_events` | Consumer idempotency log, prevents duplicate processing of incoming Kafka messages |

The `entitlements` table is the only domain table. Every write to it is paired with an `outbox`
row in the same transaction, ensuring the `USER_ENTITLEMENT_CHANGED` event reaches Kafka if
and only if the entitlement row commits.

## Table Details

### `entitlements`

#### Purpose

Stores the subscription tier and computed access limits for each user account. One row per user,
identified by `user_id`. This row is the authoritative record that drives the
`EntitlementSnapshot` carried in all downstream events.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key, generated server-side via `uuidv7()`.
- **`user_id`** (`UUID`): References `user_auth_schema.accounts.id` (no FK constraint --
  cross-schema). UNIQUE: enforces one entitlement per account and serves as the idempotency
  key for the `USER_AUTH_ACCOUNT_UPDATED` handler.
- **`tier`** (`subscription_tier_enum`): The active subscription tier. Values: `UNSPECIFIED`,
  `FREE`, `BASIC`, `PRO`, `ENTERPRISE`. Defaults to `FREE`. Changing the tier automatically
  updates all computed limit columns via `core/tiers.py`.
- **`subscription_status`** (`subscription_status_enum`): Billing lifecycle state. Values:
  `UNSPECIFIED`, `NONE`, `TRIALING`, `ACTIVE`, `PAST_DUE`, `CANCELED`, `EXPIRED`, `PAUSED`.
  The ORM enforces valid transitions via `StateMachineMixin`. Defaults to `NONE` (no billing
  relationship yet, as set for free-tier accounts at provisioning).
- **`billing_provider`** (`billing_provider_enum`): The payment provider handling the
  subscription. Values: `UNSPECIFIED`, `NONE`, `STRIPE`, `PADDLE`, `MANUAL`. Defaults to
  `NONE` for free-tier accounts.
- **`external_subscription_id`** (`VARCHAR(255)`, nullable): Subscription identifier from
  the billing provider (e.g., a Stripe subscription ID). Null until a paid subscription is
  activated.
- **`external_customer_id`** (`VARCHAR(255)`, nullable): Customer identifier from the billing
  provider. Null until a paid subscription is activated.
- **`current_period_start`** / **`current_period_end`** (`TIMESTAMPTZ`, nullable): Billing
  period boundaries from the payment provider. Null for free-tier accounts.
- **`discovery_frequency_limit`** (`discovery_frequency_enum`): How often the
  job-ingest-schedule-service runs discovery for this user. Values: `UNSPECIFIED`, `DAILY`,
  `TWICE_DAILY`, `HOURLY`, `REALTIME`. Derived from tier: FREE/BASIC → `DAILY`, PRO →
  `TWICE_DAILY`, ENTERPRISE → `HOURLY`.
- **`max_prefs`** (`INTEGER`): Maximum number of job search preference profiles the user can
  create. Derived from tier: FREE → 1, BASIC → 2, PRO → 5, ENTERPRISE → 20.
- **`max_uploads_per_pref`** (`INTEGER`): Maximum document uploads per preference profile.
  Derived from tier: FREE → 3, BASIC → 5, PRO → 10, ENTERPRISE → 25.
- **`allowed_sources`** (`job_board_source_enum[]`): Job board sources the user's discovery
  runs may scrape. Derived from tier: FREE → `[INDEED]`, BASIC → `[INDEED, LINKEDIN]`, PRO →
  `[INDEED, LINKEDIN, GLASSDOOR]`, ENTERPRISE → `[INDEED, LINKEDIN, GLASSDOOR, ZIPRECRUITER, GOOGLE]`.
- **`features_enabled`** (`JSONB`): Feature flag map derived from tier. Structure:
  `{"feature_name": bool}`. FREE and BASIC have `{}` (no extra features). PRO adds
  `{"auto_tailor": true, "priority_matching": true}`. ENTERPRISE adds those plus
  `{"api_access": true}`. Defaults to `{}`.

#### Indexes

- **`ix_entitlements_user`** (`user_id`): Supports the primary lookup pattern in all handlers
  -- fetch entitlement by user ID.
- **`ix_entitlements_tier`** (`tier`): Supports bulk queries scoped to a tier (e.g., backfill
  all PRO users when tier limits change).
- **`ix_entitlements_status`** (`subscription_status`): Supports queries scoped to subscription
  state (e.g., find all `PAST_DUE` accounts for billing retry jobs).

#### Constraints

- **UNIQUE** on `user_id`: Enforces one entitlement per account. The `create_default_entitlements`
  function exploits this as an idempotency mechanism, catching `IntegrityError` on duplicate
  insert and returns the existing row, making the handler safe under at-least-once Kafka delivery.
- **PRIMARY KEY** on `id`: Standard row identifier; not used as a join key by other services
  (those use `user_id` instead).

#### Data Lifecycle

- **Created** when `USER_AUTH_ACCOUNT_UPDATED` is consumed for a user that has no existing
  entitlement row. The initial tier is always `FREE` with `subscription_status = NONE`.
- **Updated** when `update_entitlements` is called with new tier or status data. Updating the
  tier atomically rewrites all computed limit columns (`discovery_frequency_limit`, `max_prefs`,
  `max_uploads_per_pref`, `allowed_sources`, `features_enabled`) from `core/tiers.py`.
- **Deleted** when `USER_AUTH_ACCOUNT_DELETED` is consumed. No cascade exists; this is a direct
  `DELETE WHERE user_id = ?`. No outbox event is published on deletion.

## Outbox Table

The service uses the transactional outbox pattern for guaranteed event delivery. The `outbox`
table is written in the same database transaction as every entitlement insert or update.
Debezium's PostgreSQL connector with the Outbox Event Router SMT reads the table from the
PostgreSQL WAL and publishes events to Kafka.

**Event published via outbox:**

- `USER_ENTITLEMENT_CHANGED` (`user-entitlement.cdc.entitlement-changed.v1`) -- Published after
  every entitlement create or update. The `aggregateid` column is set to `user_id`; the
  `aggregatetype` column is `"entitlement"`.

The `outbox` table columns follow the standard Debezium Outbox Event Router schema:
`id` (UUIDv7 PK), `aggregatetype`, `aggregateid`, `type`, `payload` (binary-serialized
protobuf), `timestamp`, and `tracingspancontext`.

See `infra/kafka-connect/` for the Debezium connector configuration.

## Migration Strategy

Nohiki uses **clean-cut deployment**: all services are stopped, schemas are dropped and
recreated, and the single `001_` migration is applied fresh. The migration file is edited in
place rather than creating incremental migrations.

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
