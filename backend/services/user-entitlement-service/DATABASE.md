# User Entitlement Database Design

The user-entitlement service owns `user_entitlement_schema` and is the authority for each
Nohiki user's active subscription tier, billing lifecycle, and effective access limits. A user
has one entitlement record, identified by the account owned by `user-auth-service`. Downstream
services consume the resulting `EntitlementSnapshot`; they do not query this service for limits.

## Entitlement Lifecycle

### Provisioning and Idempotency

`USER_AUTH_ACCOUNT_UPDATED` provisions an entitlement when the user has none. Provisioning
starts the user on the free tier with no billing relationship. The service deliberately attempts
the create rather than performing a read-before-write check. Concurrent or repeated delivery for
the same user is resolved by the one-entitlement-per-user invariant: the losing create is rolled
back and the existing entitlement is returned. This keeps provisioning safe under Kafka's
at-least-once delivery model.

Incoming event identities are also recorded so that repeated Kafka messages do not repeat
consumer side effects.

### Tier-Derived Access

The active tier determines the complete effective limit set. `src/user_entitlement_service/core/tiers.py`
is the source of truth for these grants:

- **Free** -- daily discovery, one preference profile, three uploads per preference, Indeed as
  the allowed source, and no additional features.
- **Basic** -- daily discovery, two preference profiles, five uploads per preference, Indeed and
  LinkedIn as allowed sources, and no additional features.
- **Pro** -- twice-daily discovery, five preference profiles, ten uploads per preference, Indeed,
  LinkedIn, and Glassdoor as allowed sources, with automatic tailoring and priority matching.
- **Enterprise** -- hourly discovery, twenty preference profiles, twenty-five uploads per
  preference, the Pro sources plus ZipRecruiter and Google, with the Pro features plus API access.

A tier change rewrites the entire derived limit set from that configuration in the same
transaction. The stored limits are therefore a materialized entitlement decision, not an
independent configuration to edit piecemeal. They are included in the downstream snapshot so
consumers can enforce access without querying this database. In particular,
`job-ingest-schedule-service` uses the discovery frequency decision to schedule discovery work.

### Billing Lifecycle

Free-tier provisioning begins with no billing relationship. Paid activation associates the
entitlement with its billing provider, external customer and subscription identities, and the
provider's current billing period.

The model enforces billing lifecycle transitions before persistence:

- No billing relationship can enter trialing or active service.
- Trialing service can become active, canceled, or expired.
- Active service can become past due, canceled, or paused.
- Past-due service can return to active or become canceled or expired.
- Canceled service can become expired or reactivate.
- Paused service can return to active or become canceled or expired.
- Expired service can reactivate or begin another trial.

Attempts to move outside this graph fail before a database write.

### Deletion

`USER_AUTH_ACCOUNT_DELETED` causes the service to hard-delete the user's entitlement directly.
Deletion does not publish an entitlement-change outbox event, so consumers that retain an
entitlement projection must use the account-deleted lifecycle event to remove it.

## Transactional Event Publication

Every entitlement create or update writes a `USER_ENTITLEMENT_CHANGED` event to the transactional
outbox alongside the domain change. A transaction commits both the entitlement state and its
corresponding event record, or neither, eliminating an application-level database/Kafka dual
write. The event is associated with the user as the entitlement aggregate and carries the full
snapshot of tier, billing status, derived limits, allowed sources, and enabled features.

Debezium reads committed outbox records from the PostgreSQL WAL and publishes them to
`user-entitlement.cdc.entitlement-changed.v1` after the database transaction. Publication is
therefore asynchronous, while the durable outbox record remains atomic with the entitlement
change. Connector behavior is configured under `infra/k8s/kafka-connect/connectors/`.

## Operational Use

The primary access path is by user identity. Tier-scoped selection supports recomputing and
backfilling materialized limits when tier policy changes, while billing-lifecycle selection
supports operational work such as retrying past-due subscriptions. These uses explain the
service's lookup design without making this database a query surface for other services.

The schema itself is defined by the service's SQLAlchemy models in
[`src/user_entitlement_service/db/models.py`](./src/user_entitlement_service/db/models.py) and
Alembic revision [`alembic/versions/001_initial_migration.py`](./alembic/versions/001_initial_migration.py).
