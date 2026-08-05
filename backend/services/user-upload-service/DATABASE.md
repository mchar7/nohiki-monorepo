# User Upload Service Database Design

Schema `user_upload_schema` stores metadata for every document a user has uploaded to Nohiki.

Each `uploads` row represents a single file owned by one user. The `outbox` table receives an
entry in the same database transaction as every insert or soft-delete on `uploads`, guaranteeing
that the corresponding `USER_UPLOAD_CREATED` or `USER_UPLOAD_DELETED` event reaches Kafka even
if the process crashes immediately after committing.

## `uploads`

Stores the metadata record for a user-uploaded document. The actual file bytes live in RustFS;
this table holds everything needed to identify, classify, and reference the file without fetching
it from object storage.

The BFF generates `id` before publishing `USER_UPLOAD_CREATE_REQUESTED` and sets it as the
command's `request_id`. The handler uses it verbatim as the row's `id`, so the same UUID links
the Kafka command, the database record, and all downstream CDC events.

`user_id` references `user_auth_schema.accounts.id` (no FK constraint, cross-schema UUID
reference). Every query that fetches a user's uploads filters on this column.

`content_hash` is the SHA-256 hex digest of the file content, computed by the BFF after
downloading the object from RustFS during upload completion.

The BFF validates that `file_size` matches the actual downloaded object before publishing the
command.

`storage_key` is the RustFS object key, constructed by the BFF as
`user-uploads/{user_id}/{upload_id}/{filename}`. This service stores it verbatim and passes
it through to the `UploadSnapshot` in CDC events so consumers can access the file directly.

Rows are never hard-deleted; `is_deleted = true` excludes a row from all list and get queries.
This preserves the audit trail even after the RustFS object has been removed.

Uniqueness of `(user_id, name)` is enforced only over rows with `is_deleted = false`. A user
cannot hold two live uploads with the same name, and the same name becomes available again once
the earlier row is soft-deleted. If the BFF attempts to create a duplicate name for the same
live upload, the handler receives an integrity error rather than silently overwriting.

### Data Lifecycle

- **Created** when the `USER_UPLOAD_CREATE_REQUESTED` command is processed. The handler first
  checks for an existing row with the same `id`; if found, it exits without inserting, making
  the operation idempotent.
- **Soft-deleted** in two scenarios:
  - Single file: when `USER_UPLOAD_DELETE_REQUESTED` is processed. The handler validates user
    ownership, removes the RustFS object, and only then sets `is_deleted = true`, so a failed
    object deletion leaves the row live for Kafka redelivery to retry.
  - Bulk cascade: when `USER_AUTH_ACCOUNT_DELETED` is received. RustFS objects for all
    non-deleted uploads of the user are removed first, then the rows are soft-deleted in a
    single flush.
- **Never hard-deleted** by application code. The downgrade migration drops the entire schema
  (`DROP SCHEMA ... CASCADE`) for clean-cut redeployment.

## `outbox`

Implements the transactional outbox pattern. Each row represents a Kafka event that must be
published. Debezium reads new rows from the PostgreSQL WAL via the Outbox Event Router SMT
and publishes them to the appropriate Kafka topic.
The `type` column carries the destination Kafka topic name (e.g.
`user-upload.cdc.upload-created.v1`); the Outbox Event Router SMT routes each row by that field.

`aggregateid` carries the `upload_id` of the affected record and is used as the Kafka message
partition key, ensuring all events for a given upload are ordered within a partition.

An `upload-created` event is written atomically with the `uploads` insert, and an
`upload-deleted` event is written atomically with each single or cascading soft-delete.

### Data Lifecycle

Rows are inserted by the application and are not deleted afterwards: neither Debezium nor this
service removes a published outbox row, so the table grows with every event and row count is not
a lag signal. See `infra/k8s/kafka-connect/connectors/` for the connector configuration.

## Sources

- Models: `backend/services/user-upload-service/src/user_upload_service/db/models.py`
- Baseline revision: `backend/services/user-upload-service/alembic/versions/001_initial_migration.py`
- Migration workflow: [root README](../../../README.md#database-migration-workflow)
