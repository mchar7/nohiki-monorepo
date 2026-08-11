# User Upload Service

Manages the lifecycle of user-uploaded documents (resumes, cover letters, portfolio files) for the
Nohiki platform. Stores file metadata in PostgreSQL and delegates physical storage to RustFS
(S3-compatible object storage), keyed per user and upload ID. Kafka-only, stateful with PostgreSQL
and RustFS.

## Role in the System

This service owns the user upload domain: every document a user submits enters the system through
this service, and every downstream service that needs to reference those documents reads from the
`USER_UPLOAD_CREATED` CDC event this service publishes. No other service writes to
`user_upload_schema` or makes decisions about upload validity.

The browser never sends file bytes to any backend service. Instead, the BFF generates a presigned
S3 PUT URL and gives it directly to the browser. The browser uploads to RustFS in one HTTP PUT.
After the upload completes, the BFF verifies the object exists in S3, computes its SHA-256 hash,
and publishes `USER_UPLOAD_CREATE_REQUESTED` to Kafka. This service receives that command, writes
the metadata record to PostgreSQL, and publishes the `USER_UPLOAD_CREATED` CDC event via the
transactional outbox. This architecture keeps large file bytes off the backend message bus and out
of backend service memory entirely.

Two downstream services consume `USER_UPLOAD_CREATED`: the BFF maintains an `AttachmentProjection`
table from it (so the `/api/v1/attachments` endpoint reads locally without querying this service),
and doc-process-service uses it to initiate document parsing with Docling. Account deletion events
from user-auth-service trigger a full cascade: all uploads for the user are soft-deleted in
PostgreSQL and their RustFS objects are removed.

## Event-Driven Integration

### Events Consumed

- **`USER_UPLOAD_CREATE_REQUESTED`** (`UploadCreateRequested`): Command published by bff-service
  after the browser has completed its direct S3 upload and the BFF has verified the object. The
  message carries the `request_id` (used as the upload's `id` for idempotency), `user_id`,
  `storage_key`, `filename`, `content_type`, `file_size`, and a SHA-256 `content_hash` computed
  by the BFF. The handler checks whether a record with that `upload_id` already exists before
  inserting. Duplicate commands are silently dropped. Consumer group:
  `user-upload-service-commands`.

- **`USER_UPLOAD_DELETE_REQUESTED`** (`UploadDeleteRequested`): Command published by bff-service
  when the user deletes an attachment. The handler verifies the requesting `user_id` owns the
  upload before proceeding, making cross-user deletion impossible. If the upload does not exist
  (already deleted), the handler exits cleanly because the delete is idempotent. Consumer group:
  `user-upload-service-commands`.

- **`USER_AUTH_ACCOUNT_DELETED`** (`AccountDeleted`): Published by user-auth-service when a
  user account is removed. This service removes every RustFS object, then marks all active
  records as soft-deleted in one transaction and writes one `USER_UPLOAD_DELETED` outbox event
  per upload. An S3 failure aborts the transaction so Kafka redelivery can retry the cascade.
  Consumer group: `user-upload-service` (default group, separate from the command handlers group).

### Events Published

- **`USER_UPLOAD_CREATED`** (`UploadCreated`, topic: `user-upload.cdc.upload-created.v1`):
  Published via the transactional outbox after a metadata record is successfully inserted.
  Carries the full `UploadSnapshot` (id, user_id, name, content_type, content_hash, file_size,
  storage_key, document_category, timestamps) as ECST: no consumer needs to query back.
  Consumed by: bff-service (creates `AttachmentProjection`) and doc-process-service (initiates
  document parsing).

- **`USER_UPLOAD_DELETED`** (`UploadDeleted`, topic: `user-upload.cdc.upload-deleted.v1`):
  Published via the transactional outbox after a single-file delete or as a batch during an
  account-deletion cascade. Carries `upload_id` and `user_id`. Consumed by bff-service, which
  removes the corresponding `AttachmentProjection` row.

### Notable Patterns

**Transactional outbox**: `USER_UPLOAD_CREATED` and `USER_UPLOAD_DELETED` are written to the
`outbox` table in the same database transaction as the domain data change. Debezium's PostgreSQL
connector reads the outbox from the WAL via the Outbox Event Router SMT and publishes to Kafka.
This preserves events across a crash after the database commit; consumers must still be
idempotent because Kafka delivery is at least once.

**`request_id` as idempotency key**: The BFF generates a UUIDv7 `request_id` before publishing
`USER_UPLOAD_CREATE_REQUESTED` and uses it as both the Kafka message key and the `upload_id`
stored in the command. This service uses that same UUID as the database primary key. If the
command is delivered twice (Kafka at-least-once), the second delivery finds the record already
present and returns without inserting or publishing a duplicate event.

## State & Persistence

### Database

Schema `user_upload_schema` stores one row per user upload: file metadata, RustFS object key,
content hash, and soft-delete flag. The transactional outbox table in the same schema enables
atomic event publishing. See [DATABASE.md](./DATABASE.md) for semantic database design and
lifecycle documentation.

### Object Storage

Files are stored in RustFS under the key pattern `user-uploads/{user_id}/{upload_id}/{filename}`.
The storage key is constructed deterministically by the BFF before the presigned URL is generated,
so user-upload-service receives it in the command and stores it verbatim. No key generation
happens inside this service. The metadata soft-delete and its outbox event are not committed until
S3 deletion succeeds. A storage failure therefore leaves the upload active for Kafka redelivery
to retry; already-successful S3 deletes are safe to repeat.

## Configuration

Settings use `USER_UPLOAD_` as the environment variable prefix. The service composes three
shared mixins:

- **`DatabaseMixin`**: PostgreSQL connection (URL, pool sizes, schema name)
- **`KafkaMixin`**: Bootstrap servers, consumer group base name, SSL/SASL settings
- **`S3Mixin`**: RustFS endpoint, bucket name, access key, secret key

The only service-specific setting is `upload.max_size_mb` (default: `10`), which bounds the
maximum upload size in megabytes. The BFF enforces this limit when verifying the uploaded object;
this service stores the value but currently does not re-validate it on ingest.

## Development

### Local Setup

```bash
uv sync
alembic upgrade head
```

Requires a running PostgreSQL instance (see `infra/compose/`) and a RustFS instance reachable
at the S3 endpoint configured in environment. The Kafka broker must be up before the service
starts. The lifespan waits for broker connectivity before registering consumers.

### Testing

```bash
just test user-upload-service
just test-cov user-upload-service
```

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise
uv run ty check
```
