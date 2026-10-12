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

The pinned developer and CI toolchain is JDK 25.0.4+1 with Gradle 9.6.1:

```bash
nix develop .#jvm --command just test-jvm
```

The recipe verifies the committed Gradle 9.6.1 wrapper, then runs `clean build`
with the flake-provided Gradle. The build executes the test and coverage gates
and produces `build/libs/nohiki-wal-router-smt-0.1.0-all.jar`.

The Kafka Connect image keeps the production build path in
`infra/k8s/kafka-connect/Dockerfile`: its pinned builder copies this module,
runs `test shadowJar`, and the runtime stage copies the shaded JAR into
`/kafka/connect/nohiki-wal-router/`.

To build the Kafka Connect image:

```bash
sh infra/compose/scripts/preflight.sh build nohiki-cp-kafka-connect
```

## Dependencies

Dependency versions live in [`build.gradle.kts`](build.gradle.kts), not a separate documentation table.
The module compiles with the pinned JDK and targets Java 21 bytecode for the Debezium runtime.
Kafka Connect and SLF4J APIs are compile-only dependencies supplied by that runtime.
Jackson is shaded and relocated to avoid runtime dependency conflicts.

`just test-jvm` runs the module tests and JaCoCo verification.
The coverage gate requires at least 95% line, 90% branch, and 95% instruction coverage.

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
