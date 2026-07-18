# Kafka Connect: CDC Connectors

This directory contains Kafka Connect configuration for Debezium PostgreSQL CDC over
the transactional outbox pattern. Legacy Qdrant sink artifacts may still exist in the tree while
the lifecycle-owner direct-write migration is pending; do not add new Qdrant sink usage.

## Overview

Debezium captures changes from the PostgreSQL outbox table and publishes them to Kafka topics.
This replaces polling-based event publishing with real-time CDC that:

- Captures outbox inserts from PostgreSQL WAL (Write-Ahead Log)
- Routes events to Kafka topics based on the `type` field
- Provides at-least-once CDC delivery; consumers must remain idempotent
- Eliminates polling overhead and latency

## High-Level Architecture

```text
  Service              PostgreSQL           Kafka
  (OutboxWriter)  -->   outbox table  -->    Topics
                            |                   ^
                            | WAL               |
                            v                   |
                        Debezium  --------------+
                        Connector
```

## Files

| File | Description |
|------|-------------|
| `Dockerfile` | Custom Kafka Connect image with Debezium plugins |
| `connectors/outbox-connector-template.json` | Template expanded into one connector per service schema |
| `connectors/qdrant-embedding-sink.json` | Legacy Qdrant sink config; do not deploy for new flows |

## Prerequisites

1. **PostgreSQL Configuration**
   - `wal_level = logical`
   - `max_replication_slots >= 2`
   - `max_wal_senders >= 2`

2. **Database Setup**
   - `debezium` user with REPLICATION privilege
   - `outbox_schema.outbox` table exists
   - One publication and replication slot per service schema

The Compose PostgreSQL initialization and Kafka Connect entrypoint create and register these
resources. The entrypoint runs `register-connectors.sh register` on every start: it is idempotent
and non-destructive. For manual deployments, run `scripts/register-connectors.sh` inside an
environment that mounts `/run/secrets/database/dsn` and can reach PostgreSQL and Kafka Connect.

### Migrating off legacy connectors (destructive, explicit only)

The legacy Compose connector identities and their replication slots/publications are removed only
by the explicit `scripts/register-connectors.sh migrate-legacy` command, never at startup. It
deletes the legacy connectors, drops their (inactive) replication slots and publications, then
re-registers the current connectors. From the Compose stack:

```bash
just connect-migrate-legacy
```

Run it once when migrating an existing environment; it refuses to drop a slot that is still active.

## Local Development

### Start Kafka Connect

From the repository root, the standard Compose stack builds Kafka Connect and registers the
per-service connectors automatically:

```bash
just compose-up
```

Do not post `outbox-connector-template.json` directly: it contains placeholders that
`scripts/register-connectors.sh` expands for each service schema.

### Check Connector Status

```bash
# List all connectors
curl http://localhost:8083/connectors | jq

# Check connector status
curl http://localhost:8083/connectors/nohiki-outbox-connector/status | jq
```

### Verify CDC Flow

Inspect connector status and produce a test event through the owning service. The repository
does not provide a standalone `verify-debezium.sh` command.

## Kubernetes Deployment

The Kafka Connect Helm chart is included in the umbrella chart:

```bash
helm upgrade --install nohiki ./infra/k8s/helm -n nohiki
```

## Connector Configuration

The connector uses Debezium's Outbox Event Router SMT (Single Message Transform) to:

1. **Route by Type**: Events are routed to topics based on the `type` field
2. **Extract Payload**: The `payload` field becomes the Kafka message value
3. **Set Key**: The `aggregateid` field becomes the Kafka message key
4. **Add Headers**: `tracingspancontext` and `aggregatetype` are added as headers

### Key Configuration Options

| Option | Value | Description |
|--------|-------|-------------|
| `table.include.list` | `<service_schema>.outbox` | Capture one service outbox table |
| `transforms.outbox.route.by.field` | `type` | Route to topic based on type field |
| `snapshot.mode` | `when_needed` | Snapshot when no usable offsets exist |
| `poll.interval.ms` | `100` | Low-latency polling |

## Troubleshooting

### Connector Not Starting

1. Check PostgreSQL wal_level:

   ```sql
   SHOW wal_level;  -- Must be 'logical'
   ```

2. Check replication slot:

   ```sql
   SELECT * FROM pg_replication_slots;
   ```

3. Check publication:

   ```sql
   SELECT * FROM pg_publication_tables WHERE pubname = 'nohiki_outbox_publication';
   ```

### Events Not Appearing in Kafka

1. Verify connector status:

   ```bash
   curl http://localhost:8083/connectors/nohiki-outbox-connector/status
   ```

2. Check Kafka Connect logs:

   ```bash
   docker logs nohiki-cp-kafka-connect
   ```

3. Verify outbox table has data:

   ```sql
   SELECT COUNT(*) FROM outbox_schema.outbox;
   ```

### High Latency

1. Reduce `poll.interval.ms` (default: 100ms)
2. Increase `max.batch.size` for throughput
3. Check Kafka Connect worker resources

---

## Qdrant Boundary

Kafka Connect is not used for Qdrant application-data mutation. Qdrant points are written by
entity lifecycle services via `nohiki-qdrant-client` direct writes: jobs by
`job-storage-service`, profiles by `user-pref-service`, and skills/occupations by
`skill-graph-service`. The repository carries Qdrant Sink Connector configuration
([`connectors/qdrant-embedding-sink.json`](./connectors/qdrant-embedding-sink.json) and
Helm template entries) for compatibility with the `ml-compute-service` JSON publish path on
`ml.fct.embedding-completed-json.v1`; do not add new sink usage.

Qdrant collection creation, payload indexes, and aliases remain infra/admin bootstrap
responsibilities under `infra/shared/qdrant-init/` and related scripts.

---

## References

- [Debezium PostgreSQL Connector](https://debezium.io/documentation/reference/stable/connectors/postgresql.html)
- [Outbox Event Router](https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html)
- [Transactional Outbox Pattern](https://microservices.io/patterns/data/transactional-outbox.html)
