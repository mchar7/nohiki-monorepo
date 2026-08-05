# Nohiki WAL Router SMT

A Kafka Connect Single Message Transform (SMT) that routes Debezium pgoutput
**logical-decoding message events** (emitted via `pg_logical_emit_message`) to
their target Kafka topic, bypassing the intermediate outbox table.

Services emit events by writing a routing envelope plus a protobuf payload
directly to the PostgreSQL WAL via `pg_logical_emit_message`; Debezium
captures the WAL message; this SMT rewrites the Connect record so the topic,
key, value, and headers match the canonical Nohiki event shape expected by
downstream consumers.

## Contract

### Input: WAL message envelope (emitted by services)

```sql
SELECT pg_logical_emit_message(
  true,             -- transactional
  '{"id":"<uuid>","topic":"<kafka topic>","aggregate_id":"<uuid>",
    "aggregate_type":"<str>","correlation_id":"<uuid|null>",
    "traceparent":"<w3c|null>"}',
  '<raw protobuf bytes>'::bytea
);
```

### Output: Kafka record (byte-identical to current outbox EventRouter output)

| Field | Value |
| -------- | ------- |
| Topic | `prefix.topic` |
| Key | `prefix.aggregate_id` as `OPTIONAL_STRING_SCHEMA` |
| Value | `message.content` as `OPTIONAL_BYTES_SCHEMA` (raw protobuf bytes) |
| Header `aggregatetype` | `prefix.aggregate_type` |
| Header `tracingspancontext` | `prefix.correlation_id` |
| Header `id` | `prefix.id` |
| Header `traceparent` | `prefix.traceparent` (optional) |

### Drop behaviour

- Records with `op != "m"` (publication table rows, snapshots, etc.) are dropped.
- Records whose value is not a `Struct` are dropped.
- Records with `prefix` starting `dbz-` (Debezium internal signals) are dropped.
- Records with malformed prefix JSON or missing required `topic` are dropped and logged.
- The SMT must run only in a dedicated WAL connector; it is not an outbox migration shim.

## Build

The SMT is built exclusively via the parent Dockerfile's multi-stage build.
**There is no committed Gradle wrapper.** All builds happen inside
`gradle:9.6.1-jdk25-alpine@sha256:4d50266538c871adbcd8ece20d61d10e42b6c8c7dec1f10498d9508d45759c35`. See `../Dockerfile`.

To build the Kafka Connect image (which includes this SMT):

```bash
sh infra/compose/scripts/preflight.sh build nohiki-cp-kafka-connect
```

### Local iteration (optional)

If you want fast inner-loop iteration without full Docker rebuilds:

```bash
# One-shot test run in an ephemeral container
docker run --rm -v "$PWD/smt:/build" -w /build gradle:9.6.1-jdk25-alpine@sha256:4d50266538c871adbcd8ece20d61d10e42b6c8c7dec1f10498d9508d45759c35 \
  gradle --no-daemon test

# Produce the shaded JAR
docker run --rm -v "$PWD/smt:/build" -w /build gradle:9.6.1-jdk25-alpine@sha256:4d50266538c871adbcd8ece20d61d10e42b6c8c7dec1f10498d9508d45759c35 \
  gradle --no-daemon shadowJar
```

## Dependencies

All versions pinned to current stable releases:

| Component | Version | Purpose |
| ----------- | --------- | --------- |
| Gradle | 9.6.1 | build tool |
| JDK (build) | 25 (Alpine toolchain) | latest LTS for compiler/tooling |
| JDK (bytecode target) | 21 (`--release 21`) | binary compat with Debezium runtime |
| Shadow plugin | 9.4.1 | fat JAR with dependency relocation |
| JaCoCo | 0.8.14 | coverage enforcement (≥ 95% line, ≥ 90% branch) |
| Kafka Connect API | 4.1.0 (`compileOnly`) | matches Debezium 3.6 runtime |
| jackson-jr-objects | 2.19.0 (shaded, ~106 KB) | prefix envelope JSON parsing |
| JUnit BOM | 6.0.3 | test framework |
| AssertJ core | 3.27.3 | test assertions |
| SLF4J API | 2.0.17 (`compileOnly`) | logging facade provided by runtime |

## Connector configuration

Register this SMT in a dedicated Debezium PostgreSQL connector that enables
logical-decoding message capture. PostgreSQL publications require at least one
table, so the connector includes the service's `processed_events` table; the SMT
drops every resulting row record.

```json
{
  "name": "<service>-wal",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "plugin.name": "pgoutput",
    "slot.name": "<service>_wal_slot",
    "publication.name": "<service>_wal_pub",
    "publication.autocreate.mode": "filtered",
    "schema.include.list": "<service_schema>",
    "table.include.list": "<service_schema>.processed_events",
    "message.prefix.include.list": ".*",

    "transforms": "walRoute",
    "transforms.walRoute.type": "ai.nohiki.kafka.connect.transforms.NohikiWalRouterSmt",

    "key.converter": "org.apache.kafka.connect.storage.StringConverter",
    "value.converter": "io.debezium.converters.BinaryDataConverter",
    "value.converter.delegate.converter.type": "org.apache.kafka.connect.json.JsonConverter",
    "value.converter.delegate.converter.type.schemas.enable": "false"
  }
}
```

The transform is deliberately ungated: applying it to every record is what prevents
the minimal publication's table rows from reaching Kafka. Do not add a topic
predicate or combine it with an outbox EventRouter.
