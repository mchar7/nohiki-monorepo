# User Auth Service Database Design

Schema `user_auth_schema` stores the canonical user identity data for the Nohiki platform:
accounts, active refresh token sessions, OAuth provider links, and the transactional outbox
that propagates account lifecycle events to Kafka.

`accounts` is the root entity. Both `refresh_tokens` and `oauth_identities` reference it with
`ON DELETE CASCADE`, so deleting an account removes all sessions and provider links atomically.
`refresh_tokens` groups multiple token rows under a shared `session_family_id`; this grouping
is the basis for the token theft detection mechanism described below.

## `accounts`

### Purpose

Represents a Nohiki user identity. This is the authoritative source for user existence and
identity data; all other services hold projection copies derived from `USER_AUTH_ACCOUNT_UPDATED`
CDC events.

### Semantics

- `id`: UUIDv7 embeds a millisecond timestamp, which means rows sort naturally by creation time.
- `email`: The `CITEXT` extension normalizes comparisons so `User@Example.com` and
  `user@example.com` are treated as identical. Enforces one account per email address at the
  database level. The service also checks at the application layer and raises a `ConflictError`
  before attempting the insert.
  Supports the authentication lookup by email address on every login attempt.
- `hashed_password`: Argon2id hash of the user's password (time_cost=3, memory_cost=64 MiB).
  `NULL` for accounts created exclusively via OAuth; such accounts have no password-based login
  path. The `has_password` property on the ORM model checks this field and is used to prevent
  unlinking the last OAuth identity from a password-less account.
- `is_active`: Disabled accounts fail authentication silently. The auth router logs a warning but
  returns the same generic "incorrect email or password" response to avoid leaking account
  existence.
- `is_verified`: Set to `true` when an account is created via an OAuth provider that supplies a
  verified email. Email/password registrations start unverified. Email verification flow is not
  yet implemented.
- `display_name`, `first_name`, `last_name`: Optional profile fields carried in the `AccountProto`
  snapshot on every CDC event. Downstream services display these without querying back.

### Data Lifecycle

- **Created** when `POST /api/v1/auth/register` succeeds (email/password) or when the OAuth
  callback resolves to a new identity with no matching email in `accounts`.
- **Updated** when `PATCH /api/v1/account` is called. Profile field changes and password changes
  both go through `user_service.update_user`.
- **Deleted** when `DELETE /api/v1/account` is called. Deletion cascades to `refresh_tokens`
  and `oauth_identities`.

---

## `refresh_tokens`

### Purpose

Stores the Argon2id hashes of active refresh tokens, grouped into session families. A new
family is created on each login; all tokens issued through rotation within that login share
the same `session_family_id`. This grouping enables the token theft detection pattern: if a
rotated token is presented a second time, the entire family is revoked.

### Semantics

- `token_id`: Hex-encoded first 16 bytes of the 256-bit random token. Stored separately so the
  service can do a direct indexed lookup without hashing the full token first. This is not a
  secret; it narrows the candidate set before the Argon2id verification step.
- `token_hash`: Argon2id hash (time_cost=2, memory_cost=19 MiB) of the full 256-bit token. The
  raw token is never stored. Verification calls `_hasher.verify(stored_hash, presented_token)`.
- `session_family_id`: Groups all tokens from a single login. Not a FK; it is a logical grouping
  key. When theft is detected, `UPDATE refresh_tokens SET is_revoked = true WHERE
  session_family_id = :family` revokes every token in the family with one statement.
- `used_at`: `NULL` means the token has not yet been rotated. When a valid token is presented for
  rotation, `used_at` is set to `now()` before the new token is inserted. If a token with
  `used_at IS NOT NULL` is presented again, theft is assumed.
- `is_revoked`: Set to `true` for the entire session family on logout or on theft detection. A
  revoked token fails validation immediately without reaching the Argon2id verification step.
- `expires_at`: 30 days from creation by default. Expired tokens are excluded from validation
  queries and cleaned up by `RefreshTokenService.cleanup_expired`.
- Token validation's primary lookup filters by `token_id`, revocation state, and expiration.
- Session-family access supports the revocation `UPDATE` issued on logout or theft detection.
- Account-scoped family access supports both that logout update and the per-request
  `is_session_family_revoked` check.
- Expiration access supports cleanup without a full table scan.

### Data Lifecycle

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

## `oauth_identities`

### Purpose

Links external OAuth provider identities to Nohiki accounts. One account may have multiple
linked providers (e.g., a user who signs in with both GitHub and Google). Each provider/account
combination is unique.

### Semantics

- `provider_email`: The email the provider reports for this identity. May differ from
  `accounts.email` if the user has multiple email addresses.
- `provider_username`: Provider-specific username (e.g., GitHub login handle). `NULL` for Google
  (which has no concept of a username).
- `raw_profile`: The full profile payload from the provider API, captured when the identity row
  is created and never refreshed afterwards. Structure varies by provider: GitHub returns user
  data from `/user`; Google returns OpenID Connect userinfo claims. Stored for debugging and
  future enrichment.
- `access_token_encrypted`, `refresh_token_encrypted`, `token_expires_at`: Provider token storage
  reserved for a future encrypted-token flow. No code path writes them today, so they are always
  `NULL`.
- Supports listing all linked providers for a user (`GET /api/v1/account/oauth-identities`).
- Prevents the same external identity from being linked to two different Nohiki accounts.
- Prevents a user from linking the same provider twice.

### Data Lifecycle

- **Created** during OAuth callback handling when `_resolve_account` determines the provider
  identity is new. This happens on first login with a provider, or when an existing user logs
  in via a new provider whose email matches their account.
- **Never updated after creation.** On subsequent OAuth logins `_resolve_account` returns the
  identity found by `_find_identity` unchanged, so no provider tokens, `raw_profile`, or profile
  columns are rewritten.
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
`infra/k8s/kafka-connect/connectors/` for connector configuration.

**Events published via outbox:**

- **`user-auth.cdc.account-updated.v1`** -- Written on account creation and on profile updates.
  `aggregatetype = "user"`, `aggregateid = {user_id}`. Carries a serialized `AccountUpdated`
  protobuf with a full `AccountProto` snapshot.

- **`user-auth.cdc.account-deleted.v1`** -- Written on account deletion.
  `aggregatetype = "user"`, `aggregateid = {user_id}`. Carries a serialized `AccountDeleted`
  protobuf containing only the `user_id`.

- **`user-auth.fct.access-token-revoked.v1`** -- Written on logout, and on refresh-token reuse
  detection when the session family is revoked. `aggregatetype = "user"`,
  `aggregateid = {user_id}`. Carries a serialized `AccessTokenRevoked` protobuf with the revoked
  `jti` and/or `session_family_id`.

The outbox rows are never deleted, by the application or by Debezium. Debezium reads committed
rows from the WAL and publishes them; the table itself only grows. Pruning is an unimplemented
operational task.

The migration also creates a `processed_events` table for idempotency tracking of any inbound
event processing, consistent with other services in the monorepo. This service registers no Kafka
consumers, so nothing writes to that table today.

## Source of Truth

- Models: `backend/services/user-auth-service/src/user_auth_service/db/models.py`
- Baseline revision: `backend/services/user-auth-service/alembic/versions/001_initial_migration.py`
- Migration workflow and commands:
  [`README.md#database-migration-workflow`](../../../README.md#database-migration-workflow)
