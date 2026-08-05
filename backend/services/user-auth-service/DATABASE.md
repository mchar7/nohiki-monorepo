# User Auth Database Design

## Identity ownership

The user auth service owns Nohiki's canonical user identity and is the authoritative source for whether a user exists.
Other services keep projection copies derived from `USER_AUTH_ACCOUNT_UPDATED` events rather than querying this
database. Account events carry profile data so downstream services can display a user without querying back.

Accounts are the root of the service's persisted relationships. Each account can own refresh sessions and multiple OAuth
provider links; deleting the account removes those sessions and links atomically.

Email identity is case-insensitive, so differently cased forms of the same address identify one account and duplicate
registrations are rejected. The service also checks for an existing address before creation and reports a conflict.
Password credentials are stored as Argon2id hashes. OAuth-only accounts have no password credential and therefore no
password-based login path.

An account can be disabled without disclosing its existence: authentication fails with the same generic
incorrect-credentials response used for other failures, while the auth router records a warning. OAuth providers that
supply a verified email create verified accounts. Email/password registrations begin unverified; the email verification
flow is not yet implemented.

## Account lifecycle

An account is created by successful email/password registration or when an OAuth callback cannot resolve an existing
account. Profile and password changes go through the account update service and result in a refreshed account projection
event. Account deletion removes the identity, its active refresh-session records, and its provider relationships.

`USER_AUTH_ACCOUNT_UPDATED` is emitted for account creation and profile updates. Its payload is a full `AccountProto`
snapshot. `USER_AUTH_ACCOUNT_DELETED` is emitted on deletion and carries only the user ID. The account is the event
aggregate, identified by that user ID.

## Refresh sessions and token theft

Every successful login, registration, or OAuth callback creates a new logical session family and its first refresh
token. Tokens issued by later rotations remain in that family. The family is a logical grouping rather than a separate
persisted parent.

Refresh-token secrets are random and are stored only as Argon2id hashes; plaintext tokens never enter the database. A
separate non-secret token identifier narrows validation to one candidate before the expensive hash check. Revocation is
also checked before Argon2id verification so already-revoked tokens fail cheaply.

Rotation is atomic: the presented token is marked used before its replacement is inserted into the same family. A used
token is permanently invalid. Presenting it again is treated as token theft and immediately revokes every token in that
family, terminating all sessions from that login. Normal logout also revokes the current family, while account-wide
lookup supports revoking every session for logout from all devices.

Refresh tokens expire 30 days after creation. Expired records are excluded from validation and are periodically removed
by the refresh-token cleanup operation. Account deletion removes all of the account's remaining refresh-token records.

## OAuth identity relationships

An OAuth identity links one external provider identity to one Nohiki account. A provider identity cannot belong to two
Nohiki accounts, and an account cannot link the same provider more than once. An account may link multiple different
providers. Provider-reported email addresses may differ from the account email when a user has multiple addresses.

On an OAuth callback, an existing provider link continues to resolve to its account. A new provider identity is linked
to an existing account when the provider email matches that account; otherwise a new account and link are created.
Subsequent OAuth logins refresh the stored provider tokens and raw provider profile.

Provider profile payloads are retained for debugging and future enrichment because their structure varies by provider.
OAuth access and refresh tokens are intended for encrypted storage, but encryption is not yet implemented and they are
currently stored as received. Provider token expiry is retained with the relationship.

Unlinking is allowed only when the account retains another authentication method, either a password or another provider.
The service rejects an unlink that would leave the account with no way to log in. Deleting the account removes all
provider links.

## Transactional outbox and delivery

Account lifecycle events are written to the outbox in the same database transaction as the account change. This atomic
write prevents a committed identity change from silently missing its corresponding event and gives Debezium
at-least-once delivery to Kafka.

Debezium's PostgreSQL connector observes the outbox through the WAL and routes each record by event type. Connector
configuration lives under `infra/k8s/kafka-connect/connectors/`. Delivery is at least once, so it does not imply
exactly-once consumption.

The application never deletes outbox records. Debezium reads them from the WAL, and connector cleanup removes processed
records from the WAL stream; records remain in the table until Debezium confirms delivery. The database revision also
provisions the monorepo's standard processed-event ledger for inbound-event idempotency, although this service currently
consumes no Kafka events.

The schema itself is defined by the service's SQLAlchemy models at
[`backend/services/user-auth-service/src/user_auth_service/db/models.py`](./src/user_auth_service/db/models.py) and
Alembic revision at
[`backend/services/user-auth-service/alembic/versions/001_initial_migration.py`](./alembic/versions/001_initial_migration.py).
