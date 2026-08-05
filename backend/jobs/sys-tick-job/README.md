# Sys Tick Job

A one-shot CLI script that publishes a single `ScheduleTick` event to Kafka and exits. This event
is the heartbeat that drives the entire job scraping pipeline: `job-ingest-schedule-service` consumes
the tick, evaluates which scrape queries are due, and triggers discovery accordingly. In production
the job runs on a cron schedule via Kubernetes CronJob; in Docker Compose it uses supercronic.

## Role in the System

Nohiki's job ingestion pipeline is clock-driven but decoupled from wall-clock time by an event
abstraction. Rather than having `job-ingest-schedule-service` run its own internal timer (which
would be non-deterministic across replicas and impossible to test), the scheduling trigger is
externalized as a Kafka event. This job is the sole producer of that trigger.

The data flow is: **sys-tick-job** → `SYS_SCHEDULE_TICK` → **job-ingest-schedule-service** →
`JOB_INGEST_DISCOVERY_REQUESTED` → **job-ingest-discovery-service** → scrape → enrichment pipeline.

By externalizing the clock to a dedicated one-shot job, the schedule service becomes a pure
event processor with no internal scheduling state, and the tick frequency can be changed by
modifying the CronJob schedule without redeploying the schedule service.

## Event Published

- **`SYS_SCHEDULE_TICK`** (`nohiki.sys.v1.ScheduleTick`): Carries `EventMetadata` (source service,
  timestamp, correlation ID) and an optional `batch_limit` integer. When `batch_limit > 0`, the
  schedule service uses that per-tick cap. When `batch_limit = 0` (default), it uses its configured
  bounded default (currently 100).

**Consumed by**: `job-ingest-schedule-service` (consumer group: `schedule-tick-primary`).

## Configuration

| Variable | Default | Purpose |
| ---------- | --------- | --------- |
| `KAFKA_BOOTSTRAP_SERVERS` | *(required)* | Kafka broker address |
| `SCHEDULE_TICK_SOURCE_SERVICE` | `sys-tick-cronjob` | Value for `EventMetadata.source_service` |
| `SCHEDULE_TICK_BATCH_LIMIT` | `0` | Per-tick query cap (0 = schedule service default) |

The job creates a minimal `AutoKafkaClient` configured for producer-only operation (no consumers),
publishes one message, and shuts down. Total runtime is typically under 2 seconds.

## Deployment

### Kubernetes (Production)

Deployed as a `CronJob` resource. The schedule is configurable in the Helm values:

```yaml
sys-tick-job:
  schedule: "*/5 * * * *"   # Every 5 minutes
  concurrencyPolicy: Forbid  # Skip if previous tick is still running
```

### Docker Compose (Local Development)

Uses [supercronic](https://github.com/aptible/supercronic) as a lightweight cron daemon inside
the container. The crontab is mounted from `infra/compose/crontabs/`. The container runs
persistently and executes the script on schedule.

```bash
# Manual trigger (useful for development)
sh infra/compose/scripts/preflight.sh run --rm nohiki-job-schedule-tick python -m sys_tick_job.publish_schedule_tick
```

## Development

```bash
# Run directly (requires KAFKA_BOOTSTRAP_SERVERS)
KAFKA_BOOTSTRAP_SERVERS=localhost:29092 uv run python -m sys_tick_job.publish_schedule_tick
```

The job has no database, no HTTP server, and no long-running process. It exists solely to
translate a cron schedule into a Kafka event.
