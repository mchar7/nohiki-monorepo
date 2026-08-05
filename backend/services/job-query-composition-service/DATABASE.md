# Job Query Database Design and Lifecycle

## Ownership and Boundaries

Schema `job_query_schema` owns the deduplicated scrape queries produced by clustering user search preferences and the
contributor records that explain why each query exists.

An ingestion query is the canonical record of what the scraping pipeline will fetch. Its identity combines search
keywords that are lowercased, stripped, and sorted with canonical target locations whose validated values are lowercased
and sorted. Preferences with the same identity share one scrape query rather than causing duplicate scrape runs.

Contributor records map user preferences to their ingestion queries. They retain each preference's individual scheduling
and search parameters and are the source of truth for the query's derived aggregates. References to preferences and
users cross into data owned by the user preference and authentication services; this service retains their identifiers
so it can process preference, entitlement, activity, and account lifecycle events. The job ingest schedule service
consumes the resulting query lifecycle events and schedules discovery only for active queries.

## Aggregation and Recomputation

After a contributor changes, the service eagerly recomputes its parent query from all contributors for correctness. The
derived query state includes:

- the union of active contributors' work arrangements, remote preference labels, and target job boards;
- the most frequent schedule required by an active contributor: free contributors are daily, while any pro or enterprise
  contributor makes the query hourly;
- whether at least one contributor is active; and
- active and total contributor counts.

Each contributor's remote preference label is derived from its preference location types. Unspecified work arrangements
are filtered from the query projection.

Inactive contributors remain part of the total count but do not affect the active aggregates. Their retained parameters
allow the query to be recomputed from first principles when activity changes. The latest recomputation time, contributor
counts, and active state provide operational signals for detecting stale aggregation and understanding schedule
eligibility.

User-wide entitlement, activity, and account changes operate by user, while preference deletion locates the affected
contribution by preference. The storage access paths are optimized for those bulk user operations and direct preference
lookups so handlers do not need full-table scans. Parent-query lookup is optimized for the aggregate recomputation path,
and active-query lookup supports operational inspection during schedule processing.

## Deduplication, Idempotency, and Concurrency

Query deduplication is enforced by `find_or_create_query`, which looks up the normalized keyword and location identity
before inserting. Storage does not independently reject two queries with the same identity, so concurrent creation
relies on the service's serialized transaction and outbox commit discipline rather than a separate database uniqueness
guard.

A contributor is identified by its query and preference. `create_or_update_contributor` first looks up that identity and
then inserts or updates it, allowing a repeated event to update the existing contribution instead of creating another
one. The persisted contributor identity is the final duplicate guard for simultaneous attempts. Operationally, a
preference contributes to at most one query at a time.

## Lifecycle

- `USER_PREF_CREATED` creates a query when its normalized identity is new, creates or refreshes its contributor, and
  recomputes the query.
- `USER_PREF_UPDATED` updates contributor parameters and triggers recomputation.
- `USER_ENTITLEMENT_CHANGED` updates the affected user's contributor frequency and recomputes all affected queries.
- `USER_AUTH_ACTIVITY` reactivates contributors and recomputes their queries. Contributors are marked inactive after the
  configured absence of activity and are restored on the next activity event.
- `USER_PREF_DELETED` removes the contribution and recomputes its query. If it was the last contributor, the query is
  deleted instead.
- `USER_AUTH_ACCOUNT_DELETED` removes all contributions for the user, then recomputes or deletes every affected query.

Normal service operation removes contributors before deleting their parent query. A direct parent deletion also removes
its contributor records. Before deleting the final query record, the service records the deletion event so downstream
scheduling receives the deletion intent.

Material recomputations emit `JOB_QUERY_UPDATED`, while the first and last contributor transitions emit
`JOB_QUERY_CREATED` and `JOB_QUERY_DELETED` respectively. These lifecycle events are the boundary through which the
schedule service observes the query projection and its derived scheduling frequency.

## Transactional Event Delivery

Query creation, material update, and deletion events are written to the service outbox in the same database transaction
as the domain change. This atomicity prevents a committed query transition from being left without its corresponding
outbox record, including when the service crashes between the domain write and Kafka publication.

Debezium reads the outbox changes from the PostgreSQL WAL and routes them to Kafka. The atomic guarantee covers the
domain change and recording of its event; publication is the subsequent CDC step. Creation and update events carry the
changed ingestion-query projection, while deletion events carry the identity needed to remove it downstream.

The schema itself is defined by the service's SQLAlchemy models at
`backend/services/job-query-composition-service/src/job_query_composition_service/db/models.py` and Alembic revision at
`backend/services/job-query-composition-service/alembic/versions/001_initial_migration.py`.
