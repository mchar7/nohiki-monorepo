# User Auth Service

Issues and manages RS256 JWTs for all authenticated Nohiki users. This is one of only two
HTTP-exposed services in the platform (the other is `bff-service`) and the only stateful service
that consumes no Kafka topics. It owns user identity, email/password authentication, OAuth2 social
login, HttpOnly cookie-based sessions, and refresh token rotation, and publishes account lifecycle
events via the transactional outbox.

## Role in the System

Every other service that needs to know "who is this user?" verifies the JWT that this service
issued, without ever calling this service. `user-auth-service` exposes its RSA public key at
`/.well-known/jwks.json`; services such as `bff-service` fetch that key once (with a 1-hour
cache) and verify tokens locally. This makes the auth service non-critical-path for the vast
majority of API calls: after login, a user can make hundreds of requests without the auth service
being involved at all.

On the Kafka side, this service is a pure producer. When accounts are created, updated, or
deleted, it writes CDC events to the transactional outbox, and Debezium captures those writes
from the PostgreSQL WAL. Downstream services (notably `bff-service`, `user-pref-service`,
`user-upload-service`, `user-entitlement-service`, and `job-query-composition-service`) consume
`USER_AUTH_ACCOUNT_UPDATED` and `USER_AUTH_ACCOUNT_DELETED` to maintain their own projection
tables and enforce account lifecycle rules (e.g., cascade-deleting preferences when an account
is removed). Because the outbox pattern guarantees atomic DB-plus-Kafka writes, downstream
services can trust that every account change eventually propagates, even if the broker is
temporarily unavailable.

The service sits at the top of the user domain hierarchy. It is on the critical path for login,
registration, and token refresh, but not for any ongoing job-matching or document-generation
workflows.

## Event-Driven Integration

### Events Published

- **`USER_AUTH_ACCOUNT_UPDATED`** (`user-auth.cdc.account-updated.v1`, `AccountUpdated`): Published
  on both account creation and profile updates. Carries a full `AccountProto` snapshot (id, email,
  display name, first/last name, `is_active`, `email_verified`, timestamps) so downstream services
  never need to query back. `bff-service` uses this to maintain its `accounts` projection table.
  `user-pref-service` and other domain services use it to associate preferences and uploads with
  a verified user identity. Published via the transactional outbox, keyed by `user_id`.

- **`USER_AUTH_ACCOUNT_DELETED`** (`user-auth.cdc.account-deleted.v1`, `AccountDeleted`): Published
  when a user deletes their account. Carries only the `user_id`. All downstream services that
  maintain per-user data (`user-pref-service`, `user-upload-service`, `user-entitlement-service`,
  `job-correlation-evaluation-service`) consume this event to cascade-delete their own records.
  Published via the transactional outbox, keyed by `user_id`.

### Notable Patterns

#### Transactional Outbox

All CDC events are written to the `outbox` table inside the same database transaction as the
domain data change. Debezium's PostgreSQL connector reads the WAL and publishes rows to Kafka
using the Outbox Event Router SMT. This means a registration that succeeds in the database is
guaranteed to eventually produce a `USER_AUTH_ACCOUNT_UPDATED` event on Kafka; no separate
publish step can fail silently.

The outbox table uses Debezium's standard column layout (`aggregatetype`, `aggregateid`, `type`,
`payload`, `timestamp`, `tracingspancontext`). Connector configuration lives in
`infra/kafka-connect/connectors/`.

## State & Persistence

### Database

Schema `user_auth_schema` stores accounts, refresh tokens (with session family tracking for theft
detection), OAuth provider links, and the outbox. The schema is the source of truth for user
identity; all other services hold projection copies derived from CDC events.

See [DATABASE.md](./DATABASE.md) for semantic database design and lifecycle documentation.

### Redis

Redis serves two distinct roles:

- **Rate limiting** -- Login attempts are rate-limited per email address and per client IP using
  sliding-window counters. Registration is rate-limited per IP. Limits are set conservatively in
  production (5 logins/minute, 20/hour; 3 registrations/hour, 10/day) and relaxed in development.
  Failed login attempts increment a counter; successful login clears it. Key prefix: managed by
  `nohiki-redis-utils` `AuthRateLimiter`.

- **OAuth state storage** -- During the OAuth authorization flow, a PKCE code verifier and state
  token are stored in Redis under `oauth_state:{state}` with a 600-second TTL. The entry is
  consumed and deleted atomically when the provider callback arrives, preventing replay attacks.

- **Token blacklist** -- Individual JWTs can be blacklisted by JTI (`token:blacklist:{jti}`) with
  a TTL matching the token's remaining lifetime (up to 30 days). A "revoke all" timestamp per
  user (`user:revoke_all:{user_id}`) enables logout-from-all-devices without enumerating tokens.

## Key Design Patterns

### RS256 JWT with JWKS Distribution

The service uses asymmetric RS256: a 2048-bit RSA private key signs access tokens; the
corresponding public key is published as a JSON Web Key Set at `/.well-known/jwks.json` with a
`Cache-Control: public, max-age=3600` header. Any service that trusts the JWKS URL can verify
tokens without sharing a secret with this service and without any network call to the auth service
per request.

The `kid` (key ID) header in each JWT (`nohiki-key-1` by default) lets verifiers select the
correct key from the JWKS when multiple keys are present during rotation. The JWKS endpoint
supports including previous keys alongside the current one, so in-flight tokens signed with the
old key remain valid during a rotation window.

Access tokens expire after 10 minutes. The token lifetime limits exposure if a token is stolen.
A stolen token can still authorize requests before expiration.

### HttpOnly Cookies with `__Host-` Prefix

JWTs are never returned in response bodies. After a successful login, registration, or token
refresh, the service sets two `HttpOnly` cookies:

- `__Host-nohiki_at` -- the RS256 access token, `max-age` = 10 minutes
- `__Host-nohiki_rt` -- the opaque refresh token, `max-age` = 30 days

`HttpOnly` prevents JavaScript from reading the token, eliminating the most common XSS token
theft vector. The `__Host-` cookie prefix (used in production; plain names in development for
HTTP compatibility) enforces two additional browser constraints: the cookie must be sent over
HTTPS only, and it cannot have a `Domain` attribute, which prevents a subdomain from setting a
cookie that applies to the parent domain. Combined with `SameSite=Lax`, cross-site form-POST
attacks cannot carry the cookie.

Both cookies use `Path=/` so they are sent with every request to the service, including the
`/api/v1/auth/refresh` endpoint.

### Refresh Token Rotation with Session Family Tracking

Each login, whether email/password or OAuth, creates a new _session family_ identified by a
UUID. All refresh tokens issued for that login share the same `session_family_id`. On every call
to `POST /api/v1/auth/refresh`:

1. The old refresh token is looked up by its `token_id` (the first 16 bytes of the 256-bit
   random token, stored as hex for fast indexed lookup).
2. The Argon2id hash of the presented token is verified against the stored hash.
3. If the token has already been marked `used_at` (i.e., it was rotated in a previous request),
   the service detects token reuse: the entire session family is immediately revoked by setting
   `is_revoked = true` on every row sharing that `session_family_id`. All active sessions for
   that login are terminated.
4. If the token is valid and unused, it is marked `used_at = now`, and a new refresh token is
   inserted into the same family. The new token is returned in the cookie; the old one is now
   permanently invalid.

This pattern detects stolen tokens. If an attacker intercepts a refresh token and uses it after
the legitimate user has already rotated it, the second use triggers family revocation. The
legitimate user's next request will fail, alerting them that their session was compromised.

Refresh tokens are stored only as Argon2id hashes (time_cost=2, memory_cost=19 MiB). Plaintext
tokens never appear in the database.

### CSRF Protection via Origin Header Validation

The service does not use double-submit tokens or synchronizer token patterns. Instead,
`CSRFMiddleware` validates two browser-controlled headers on all state-changing requests
(`POST`, `PUT`, `PATCH`, `DELETE`) that include cookies:

- **`Origin`** -- must match the configured `CSRF_ALLOWED_ORIGINS` allowlist. Browsers always
  send `Origin` on cross-origin requests; same-origin requests may omit it, which is permitted.
- **`Sec-Fetch-Site`** -- if present, must be `same-origin` or `same-site`. This header is
  browser-enforced and cannot be forged by JavaScript.

The middleware skips validation for requests without cookies (non-browser clients) and for
safe methods. This approach is viable because `SameSite=Lax` cookies already block cross-site
form-POST attacks from third-party sites, and the Origin check provides a defense-in-depth layer
without requiring token synchronization.

### OAuth2 with PKCE

The OAuth flow uses PKCE (Proof Key for Code Exchange) via Authlib, even with server-side
clients, for defense against authorization code interception. A `code_verifier` (64-byte
base64url random string) and its SHA-256 challenge are generated server-side. The verifier is
stored in Redis with the state token and consumed atomically on callback.

State parameters are one-time-use: `retrieve_and_delete` fetches and deletes the Redis entry
in a single operation, preventing state replay. If the OAuth provider returns an error or the
state does not match, the user is redirected to the configured error URL with an error code
query parameter.

Account resolution on callback follows this priority:

1. If the provider's user ID is already linked to an existing account, return that account.
2. If the provider's email matches an existing account, link the new provider to that account.
3. Otherwise, create a new account with no password (`hashed_password = NULL`).

An OAuth-only account (no password) cannot unlink its sole OAuth identity; the service rejects
such requests with a 400 to prevent lockout.

## Configuration

The service uses `DatabaseMixin`, `RedisMixin`, and `KafkaMixin` from `nohiki-core-settings`,
with the env prefix `USER_AUTH_`. Key settings:

| Variable | Default | Notes |
| ---------- | --------- | ------- |
| `USER_AUTH_JWT__PRIVATE_KEY_PATH` | `/run/secrets/jwt_private_key.pem` | RSA private key PEM file. Mount as a Kubernetes secret. |
| `USER_AUTH_JWT__KEY_ID` | `nohiki-key-1` | `kid` claim in tokens and JWKS. Change during key rotation. |
| `USER_AUTH_JWT__ISSUER` | `https://api.nohiki.com` | `iss` claim. Must match verifier configuration. |
| `USER_AUTH_JWT__AUDIENCE` | `https://app.nohiki.com` | `aud` claim. Must match verifier configuration. |
| `USER_AUTH_JWT__ACCESS_TOKEN_EXPIRE_MINUTES` | `10` | Short-lived by design. |
| `USER_AUTH_JWT__REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Controls session lifetime. |
| `USER_AUTH_COOKIE__SAMESITE` | `lax` | `strict` breaks OAuth redirects; `lax` is the correct choice. |
| `USER_AUTH_SECURITY__CORS_ALLOWED_ORIGINS` | localhost variants | Comma-separated list. |
| `USER_AUTH_SECURITY__CSRF_ALLOWED_ORIGINS` | localhost variants | Comma-separated list. Must include the frontend origin. |
| `USER_AUTH_OAUTH__GITHUB__ENABLED` | `false` | Set `true` and provide `CLIENT_ID`/`CLIENT_SECRET`. |
| `USER_AUTH_OAUTH__GOOGLE__ENABLED` | `false` | Set `true` and provide `CLIENT_ID`/`CLIENT_SECRET`. |
| `USER_AUTH_OAUTH__CALLBACK_BASE_URL` | `http://localhost:8000` | Must be the public URL of this service. |

Rate limits are configured under `USER_AUTH_CACHING__RATE_LIMIT__*`. In production the defaults
are deliberately restrictive (5 logins/minute, 3 registrations/hour).

## Development

### Local Setup

```bash
uv sync
# Provide an RSA private key (generate one for local dev):
openssl genrsa -out /tmp/jwt_private_key.pem 2048
export USER_AUTH_JWT__PRIVATE_KEY_PATH=/tmp/jwt_private_key.pem

# Apply database migrations (requires running PostgreSQL)
cd backend/services/user-auth-service
uv run alembic upgrade head
```

### Testing

```bash
# From repo root
just test user-auth-service

# With coverage
just test-cov user-auth-service

# Single file
uv run --package user-auth-service pytest backend/services/user-auth-service/tests/path/to/test_file.py --tb=short
```

Tests use `generate_rsa_keypair()` from `core/jwt_rs256.py` to produce ephemeral key pairs
in fixtures, so no key file is required to run the test suite.

### Linting and Type Checking

```bash
just lint-service user-auth-service
just typecheck user-auth-service
```
