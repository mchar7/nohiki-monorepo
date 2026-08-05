# User Upload Database Design

Schema `user_upload_schema` is the user-upload-service's authoritative store for uploaded-document
metadata. The file bytes remain in RustFS object storage; PostgreSQL records who owns each upload,
how the object is identified and classified, and the state needed to publish upload lifecycle
events.

## Metadata and Object-Storage Boundary

Each metadata record represents one file owned by one user. Its owner corresponds to an account
managed by user-auth-service, and all user-facing reads are scoped to that owner. The owner lookup
path is optimized because both upload listings and account-deletion cascades operate over all
uploads for one user.

The BFF constructs the RustFS key as
`user-uploads/{user_id}/{upload_id}/{filename}` and sends it to this service unchanged. The BFF
validates the downloaded object's size and MIME metadata and computes the SHA-256 content hash
before requesting creation. This service maps the forwarded MIME value to its content
classification before persisting the metadata rather than fetching file bytes. Downstream services
use the hash to determine whether content has changed since processing, and receive the storage key
in upload snapshots so they can retrieve the object directly. Document category records the
upload's intended use.

## Identity, Ownership, and Invariants

The BFF generates a UUIDv7 before publishing `USER_UPLOAD_CREATE_REQUESTED`, uses it as the
command's `request_id`, and this service uses it unchanged as the upload identity. The same value
therefore correlates the Kafka command, persisted metadata, and downstream CDC events. A repeated
create command with an identity already present is a no-op, making creation idempotent under
redelivery.

Upload names are unique within a user's uploads. A duplicate name for the same user is rejected
rather than silently overwriting metadata. Delete handling also verifies that the requesting user
owns the upload, preventing one user from deleting another user's object.

## Lifecycle and Retention

Creation follows `USER_UPLOAD_CREATE_REQUESTED` after the BFF has validated the RustFS object.
Deletion is soft:

- `USER_UPLOAD_DELETE_REQUESTED` removes one owned RustFS object and marks its metadata deleted.
- `USER_AUTH_ACCOUNT_DELETED` removes every active object for that user, soft-deletes the
  corresponding metadata together, and emits one deletion event per upload.

The metadata change and its outbox event are not committed until object deletion succeeds. A
storage failure therefore leaves the upload active so Kafka redelivery can retry; repeating an
already successful object deletion is safe. Soft-deleted uploads are excluded from list and get
operations, but their metadata remains as an audit trail after the RustFS object is gone.
Application code never hard-deletes upload records. Audit timestamps record creation and are
refreshed when metadata changes.

## Transactional Event Publication

The transactional outbox is stored beside upload metadata. Creation and soft-deletion write their
respective `USER_UPLOAD_CREATED` or `USER_UPLOAD_DELETED` event in the same database transaction as
the domain change. Cascading account deletion follows the same rule for every affected upload.
This atomicity preserves committed events even if the service crashes immediately afterward.

Debezium reads committed outbox records from the PostgreSQL WAL through the Outbox Event Router
SMT, publishes them to Kafka, and removes them after successful publication. Event metadata
provides the destination, an event identity used as the Kafka message key, and the affected upload
identity used for partitioning so events for one upload remain ordered. Payloads are
Protobuf-serialized, and trace context supports cross-service tracing. Kafka delivery remains at
least once, so consumers must be idempotent.

Created events are routed to `user-upload.cdc.upload-created.v1`; single and cascading deletion
events are routed to `user-upload.cdc.upload-deleted.v1`.

## Operational Signals

The outbox should remain near-empty during normal operation. Its insertion time provides the basis
for lag monitoring, while a growing record count indicates that the Debezium connector is lagging
or has stopped. Connector configuration lives under `infra/k8s/kafka-connect/connectors/`.

The schema itself is defined by the service's SQLAlchemy models in
`backend/services/user-upload-service/src/user_upload_service/db/models.py` and Alembic revision
in `backend/services/user-upload-service/alembic/versions/001_initial_migration.py`.
