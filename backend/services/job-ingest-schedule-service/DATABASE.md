# Job Ingest Schedule Database Design

The `job_schedule_schema` schema stores the materialized scheduling state for registered search
queries: the search configuration needed for dispatch, activation state, and previous and planned
execution times. It is a projection of events from the job-query-composition-service. That service
remains the source of truth for query definitions; this service owns only the scheduling metadata
derived from them.

## Projection and Ownership Boundaries

Each schedule represents one query owned by the job-query-composition-service. Its identity and
search criteria are copied from query-created and query-updated CDC events, making the query
identity a logical cross-service reference rather than a locally generated identity. Keeping the
keywords, locations, work arrangements, and job-board sources in the projection lets the scheduler
publish a complete discovery command without reading the source service when a query becomes due.
Unspecified work-arrangement and source values are not retained in the projection.

The scraper lookback and result target come from this service's configuration rather than the CDC
payload. The schedule frequency comes from the event payload. This separation keeps query-owned
configuration synchronized through CDC while leaving scheduler-controlled dispatch parameters
under this service's control.

## Scheduling Lifecycle

A query-created event creates its schedule. Processing the same creation more than once does not
create another schedule: the handler first checks whether the query already has one.

A query-updated event refreshes the projected query parameters and activation state. If an update
arrives before its corresponding creation event, the handler creates the missing schedule, allowing
out-of-order delivery to converge on a usable projection.

An active query is dispatched immediately when it is activated, then planned for one frequency
interval after that dispatch. Scheduler ticks consider only active schedules whose planned execution
time has arrived. After a successful dispatch, the schedule records that dispatch as its most recent
successful run and advances the next execution by one frequency interval. The successful-run
marker remains absent until the first tick dispatch. Inactive schedules have no planned execution
time and are excluded from due processing.

A query-deleted event removes the schedule. Deleting an already missing schedule is treated as
success, so deletion is idempotent.

## Delivery and Idempotency

Kafka messages are delivered at least once. A consumer-side processing log, provided by
`nohiki-db-utils`, records the message offset or correlation identifier after successful processing
so redeliveries can be skipped. These records are not updated or deleted; the log grows
monotonically as the service processes messages.

Discovery commands are published directly to Kafka. The schema has no transactional outbox, so
command delivery is not mediated by database outbox state.

## Due-Query and Storage Design

The scheduler's primary read path selects active schedules whose planned execution time is due.
The corresponding storage optimization excludes inactive schedules and schedules without a planned
execution, matching that predicate while keeping the due-read structure compact.

Activation-state equality lookups use an equality-oriented structure because single-value equality
access on a low-cardinality value is smaller and faster than a general ordered structure.
Creation-time range access uses a low-overhead range summary because rows
are expected to be largely append-ordered. These choices support the service's operational reads
without changing the projection's ownership boundaries.

The most recent successful dispatch and next planned execution retain their distinct operational
meaning: one records completed dispatch progress, while the other drives future due selection.

The schema itself is defined by the service's SQLAlchemy models in
`backend/services/job-ingest-schedule-service/src/job_ingest_schedule_service/db/models.py` and
Alembic revision
`backend/services/job-ingest-schedule-service/alembic/versions/001_initial_migration.py`.
