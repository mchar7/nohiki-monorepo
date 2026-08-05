# User Auth Service Database Schema

Schema `user_auth_schema` stores the canonical user identity data for the Nohiki platform:
accounts, active refresh token sessions, OAuth provider links, and the transactional outbox
that propagates account lifecycle events to Kafka.

## Entity Overview

| Table | Purpose |
| ------- | --------- |
| `accounts` | Primary user identity record (email, hashed password, profile fields) |
| `refresh_tokens` | Active refresh token hashes with session family tracking for theft detection |
| `oauth_identities` | OAuth provider links associating external provider accounts to Nohiki accounts |
| `outbox` | Transactional outbox for CDC event publishing via Debezium |

`accounts` is the root entity. Both `refresh_tokens` and `oauth_identities` reference it with
`ON DELETE CASCADE`, so deleting an account removes all sessions and provider links atomically.
`refresh_tokens` groups multiple token rows under a shared `session_family_id`; this grouping
is the basis for the token theft detection mechanism described below.

## Table Details

### `accounts`

#### Purpose

Represents a Nohiki user identity. This is the authoritative source for user existence and
identity data; all other services hold projection copies derived from `USER_AUTH_ACCOUNT_UPDATED`
CDC events.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key, generated server-side via `uuidv7()`. UUIDv7 embeds a
  millisecond timestamp, which means rows sort naturally by creation time.
- **`email`** (`CITEXT`): Case-insensitive email address. The `CITEXT` extension normalizes
  comparisons so `User@Example.com` and `user@example.com` are treated as identical. Unique
  constraint prevents duplicate registrations regardless of case.
- **`hashed_password`** (`VARCHAR(255)`, nullable): Argon2id hash of the user's password
  (time_cost=3, memory_cost=64 MiB). `NULL` for accounts created exclusively via OAuth; such
  accounts have no password-based login path. The `has_password` property on the ORM model
  checks this field and is used to prevent unlinking the last OAuth identity from a
  password-less account.
- **`is_active`** (`BOOLEAN`, default `true`): Disabled accounts fail authentication silently.
  The auth router logs a warning but returns the same generic "incorrect email or password"
  response to avoid leaking account existence.
- **`is_verified`** (`BOOLEAN`, default `false`): Set to `true` when an account is created via
  an OAuth provider that supplies a verified email. Email/password registrations start
  unverified. Email verification flow is not yet implemented.
- **`display_name`**, **`first_name`**, **`last_name`** (`VARCHAR`): Optional profile fields
  carried in the `AccountProto` snapshot on every CDC event. Downstream services display these
  without querying back.
- **`created_at`**, **`updated_at`** (`TIMESTAMPTZ`): Managed by the ORM (`BaseEntity` mixin),
  both default to `now()` on insert.

#### Indexes

- **`ix_accounts_email`** on `email`: Supports the authentication lookup by email address on
  every login attempt.

#### Constraints

- **UNIQUE on `email`**: Enforces one account per email address at the database level. The
  service also checks at the application layer and raises a `ConflictError` before attempting
  the insert.

#### Data Lifecycle

- **Created** when `POST /api/v1/auth/register` succeeds (email/password) or when the OAuth
  callback resolves to a new identity with no matching email in `accounts`.
- **Updated** when `PATCH /api/v1/account` is called. Profile field changes and password changes
  both go through `user_service.update_user`.
- **Deleted** when `DELETE /api/v1/account` is called. Deletion cascades to `refresh_tokens`
  and `oauth_identities`.

---

### `refresh_tokens`

#### Purpose

Stores the Argon2id hashes of active refresh tokens, grouped into session families. A new
family is created on each login; all tokens issued through rotation within that login share
the same `session_family_id`. This grouping enables the token theft detection pattern: if a
rotated token is presented a second time, the entire family is revoked.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key.
- **`account_id`** (`UUID`): FK to `accounts.id` with `ON DELETE CASCADE`. All sessions for
  a deleted account are removed atomically.
- **`token_id`** (`VARCHAR(32)`): Hex-encoded first 16 bytes of the 256-bit random token.
  Stored separately so the service can do a direct indexed lookup without hashing the full
  token first. This is not a secret; it narrows the candidate set before the Argon2id
  verification step.
- **`token_hash`** (`VARCHAR(255)`): Argon2id hash (time_cost=2, memory_cost=19 MiB) of the
  full 256-bit token. The raw token is never stored. Verification calls `_hasher.verify(stored_hash, presented_token)`.
- **`session_family_id`** (`UUID`): Groups all tokens from a single login. Not a FK; it is a
  logical grouping key. When theft is detected, `UPDATE refresh_tokens SET is_revoked = true
  WHERE session_family_id = :family` revokes every token in the family with one statement.
- **`used_at`** (`TIMESTAMPTZ`, nullable): `NULL` means the token has not yet been rotated.
  When a valid token is presented for rotation, `used_at` is set to `now()` before the new
  token is inserted. If a token with `used_at IS NOT NULL` is presented again, theft is assumed.
- **`is_revoked`** (`BOOLEAN`, default `false`): Set to `true` for the entire session family
  on logout or on theft detection. A revoked token fails validation immediately without
  reaching the Argon2id verification step.
- **`expires_at`** (`TIMESTAMPTZ`): 30 days from creation by default. Expired tokens are
  excluded from validation queries and cleaned up by `RefreshTokenService.cleanup_expired`.
- **`created_at`** (`TIMESTAMPTZ`): Token creation time.

#### Indexes

- **`ix_refresh_tokens_token_id`** on `token_id`: The primary lookup path. Every token
  validation starts with `WHERE token_id = :id AND is_revoked = false AND expires_at > now()`.
- **`ix_refresh_tokens_session_family`** on `session_family_id`: Supports the family revocation
  `UPDATE` issued on logout or theft detection.
- **`ix_refresh_tokens_account_id`** on `account_id`: Supports queries that need to enumerate
  or revoke all sessions for a specific user (e.g., logout-from-all-devices).
- **`ix_refresh_tokens_expires_at`** on `expires_at`: Supports the cleanup query
  `WHERE expires_at < now()` without a full table scan.

#### Data Lifecycle

- **Created** on `POST /api/v1/auth/login`, `POST /api/v1/auth/register`, and on OAuth callback
  success. Each creates a new `session_family_id` and inserts the first token in that family.
- **Rotated** on `POST /api/v1/auth/refresh`: the old token row is marked `used_at = now()`;
  a new token row is inserted into the same family.
- **Revoked** on `POST /api/v1/auth/logout` (sets `is_revoked = true` for the entire family)
  or on theft detection (same operation, triggered by a second use of an already-rotated token).
- **Cascade-deleted** when the parent `accounts` row is deleted via `DELETE /api/v1/account`.
- **Cleaned up** periodically by `RefreshTokenService.cleanup_expired`, which deletes rows
  where `expires_at < now()`.

---

### `oauth_identities`

#### Purpose

Links external OAuth provider identities to Nohiki accounts. One account may have multiple
linked providers (e.g., a user who signs in with both GitHub and Google). Each provider/account
combination is unique.

#### Key Columns

- **`id`** (`UUID`): UUIDv7 primary key.
- **`account_id`** (`UUID`): FK to `accounts.id` with `ON DELETE CASCADE`.
- **`provider`** (`VARCHAR(50)`): Provider name string, currently `"github"` or `"google"`.
- **`provider_user_id`** (`VARCHAR(255)`): The external provider's numeric or string user ID.
  Together with `provider`, this uniquely identifies an external identity.
- **`provider_email`** (`VARCHAR(255)`, nullable): The email the provider reports for this
  identity. May differ from `accounts.email` if the user has multiple email addresses.
- **`provider_username`** (`VARCHAR(255)`, nullable): Provider-specific username (e.g., GitHub
  login handle). `NULL` for Google (which has no concept of a username).
- **`raw_profile`** (`JSONB`): The full profile payload from the provider API at the time of
  last login. Structure varies by provider: GitHub returns user data from `/user`; Google
  returns OpenID Connect userinfo claims. Stored for debugging and future enrichment.
- **`access_token_encrypted`**, **`refresh_token_encrypted`** (`TEXT`, nullable): Provider
  OAuth tokens, intended for encrypted storage. Currently stored as-is (encryption not yet
  implemented).
- **`token_expires_at`** (`TIMESTAMPTZ`, nullable): When the provider access token expires.

#### Indexes

- **`ix_oauth_identities_account_id`** on `account_id`: Supports listing all linked providers
  for a user (`GET /api/v1/account/oauth-identities`).
- **`ix_oauth_identities_provider`** on `provider`: Supports filtering identities by provider
  in combination with `account_id`.

#### Constraints

- **UNIQUE `uq_oauth_provider_user` on (`provider`, `provider_user_id`)**: Prevents the same
  external identity from being linked to two different Nohiki accounts.
- **UNIQUE `uq_oauth_account_provider` on (`account_id`, `provider`)**: Prevents a user from
  linking the same provider twice.

#### Data Lifecycle

- **Created** during OAuth callback handling when `_resolve_account` determines the provider
  identity is new. This happens on first login with a provider, or when an existing user logs
  in via a new provider whose email matches their account.
- **Updated** on subsequent OAuth logins (access/refresh tokens and `raw_profile` are refreshed).
- **Deleted** when `DELETE /api/v1/account/oauth/{provider}` is called, provided the account
  retains at least one other authentication method (another provider or a password). The service
  raises `OAuthError("cannot_unlink", ...)` if unlinking would leave the account with no login
  method.
- **Cascade-deleted** when the parent `accounts` row is deleted.

---

## Outbox Table

The `outbox` table follows Debezium's standard Outbox Event Router schema. All three account
lifecycle events are written here inside the same database transaction as the domain change,
guaranteeing at-least-once delivery to Kafka.

Debezium's PostgreSQL connector with the Outbox Event Router SMT monitors this table via the
WAL and routes each row to Kafka based on the `type` column. See
`infra/kafka-connect/connectors/` for connector configuration.

**Events published via outbox:**

- **`user-auth.cdc.account-updated.v1`** -- Written on account creation and on profile updates.
  `aggregatetype = "user"`, `aggregateid = {user_id}`. Carries a serialized `AccountUpdated`
  protobuf with a full `AccountProto` snapshot.

- **`user-auth.cdc.account-deleted.v1`** -- Written on account deletion.
  `aggregatetype = "user"`, `aggregateid = {user_id}`. Carries a serialized `AccountDeleted`
  protobuf containing only the `user_id`.

The outbox rows are never deleted by the application. Debezium reads them from the WAL; the
connector's cleanup policy removes processed rows from the WAL stream. Rows remain in the table
until Debezium confirms delivery.

The migration also creates a `processed_events` table (via `get_create_processed_events_sql`)
for idempotency tracking of any inbound event processing, consistent with other services in the
monorepo (though this service currently has no Kafka consumers).

## Migration Strategy

Nohiki uses **clean-cut deployment**: all services are stopped, schemas are dropped and
recreated, and the single `001_` migration is applied fresh. The migration file is edited in
place rather than creating incremental migrations.

This is possible because Nohiki is pre-release with zero production data. There are no data
migrations or backward compatibility concerns.

```bash
# Apply migration
cd backend/services/user-auth-service
uv run alembic upgrade head

# Generate updated migration after model changes
uv run alembic revision --autogenerate -m "description"

# View current state
uv run alembic current
```
