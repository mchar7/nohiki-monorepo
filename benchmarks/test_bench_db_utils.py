"""Benchmarks for DB utility operations (nohiki-db-utils).

Measures ORM mixin overhead, state machine transitions, outbox event
construction, and query building patterns used across all services.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from nohiki_db_utils.state_machine import InvalidTransitionError, StateMachineMixin
from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.dialects.postgresql import insert as pg_insert
from uuid_utils import uuid7

_SENIOR_SENIORITY_LEVEL = 3

# State machine benchmarks (used by job-storage, doc-template, etc.)

_LISTING_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"ACTIVE", "REJECTED"}),
    "ACTIVE": frozenset({"STALE", "EXPIRED", "ARCHIVED"}),
    "STALE": frozenset({"ACTIVE", "EXPIRED", "ARCHIVED"}),
    "EXPIRED": frozenset({"ARCHIVED"}),
    "REJECTED": frozenset({"ARCHIVED"}),
    "ARCHIVED": frozenset(),
}


class _ListingEntity(StateMachineMixin):
    """Stub entity for benchmarking StateMachineMixin."""

    __transitions__ = _LISTING_TRANSITIONS
    __status_field__ = "status"

    def __init__(self, status: str = "PENDING") -> None:
        self.status = status


def test_bench_state_machine_valid_transition(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark validating and applying a legal state transition."""
    entity = _ListingEntity(status="PENDING")

    def transition() -> _ListingEntity:
        entity.status = "PENDING"
        return entity.transition_to("ACTIVE")

    benchmark(transition)


def test_bench_state_machine_invalid_transition(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark detecting an illegal state transition (raises exception)."""
    entity = _ListingEntity(status="ARCHIVED")

    def attempt_invalid() -> bool:
        try:
            entity.transition_to("PENDING")
        except InvalidTransitionError:
            return True
        return False

    benchmark(attempt_invalid)


def test_bench_state_machine_is_terminal(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark checking if current state is terminal."""
    entity = _ListingEntity(status="ARCHIVED")
    benchmark(lambda: entity.is_terminal)


def test_bench_state_machine_allowed_transitions(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark retrieving allowed transitions from current state."""
    entity = _ListingEntity(status="ACTIVE")
    benchmark(lambda: entity.allowed_transitions)


# UUID generation (UUIDv7 used for all primary keys)


def test_bench_uuid7_generation(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark uuid7 generation (used for all entity PKs)."""
    benchmark(uuid7)


def test_bench_uuid_to_string(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark UUID to string conversion (used in event payloads)."""
    uid = uuid.uuid4()
    benchmark(str, uid)


# SQLAlchemy query building patterns (no DB connection needed)

_metadata = MetaData()
_listings_table = Table(
    "listings",
    _metadata,
    Column("id", sa.Uuid, primary_key=True),
    Column("title", String(255)),
    Column("status", String(50)),
    Column("company_name", String(255)),
    Column("seniority_level", sa.Integer),
    Column("created_at", sa.DateTime(timezone=True)),
)


def test_bench_select_query_build(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building a simple SELECT query."""
    benchmark(
        lambda: sa.select(_listings_table).where(_listings_table.c.status == "ACTIVE"),
    )


def test_bench_select_with_multiple_filters(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building SELECT with multiple WHERE conditions."""

    def build_query() -> sa.Select:
        return (
            sa.select(_listings_table)
            .where(_listings_table.c.status == "ACTIVE")
            .where(_listings_table.c.seniority_level >= _SENIOR_SENIORITY_LEVEL)
            .where(_listings_table.c.company_name.ilike("%acme%"))
            .order_by(_listings_table.c.created_at.desc())
            .limit(50)
        )

    benchmark(build_query)


def test_bench_insert_query_build(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building an INSERT statement."""
    uid = uuid.uuid4()
    now = datetime.now(UTC)
    benchmark(
        lambda: _listings_table.insert().values(
            id=uid,
            title="Staff Engineer",
            status="PENDING",
            company_name="Acme Corp",
            seniority_level=4,
            created_at=now,
        ),
    )


def test_bench_upsert_query_build(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building an upsert (INSERT ... ON CONFLICT) statement."""
    uid = uuid.uuid4()
    now = datetime.now(UTC)

    def build_upsert() -> sa.Insert:
        stmt = pg_insert(_listings_table).values(
            id=uid,
            title="Staff Engineer",
            status="PENDING",
            company_name="Acme Corp",
            seniority_level=4,
            created_at=now,
        )
        return stmt.on_conflict_do_nothing(index_elements=["id"])

    benchmark(build_upsert)


# Outbox event payload construction (simulated, no DB)


@dataclass
class _OutboxEvent:
    """Simulates the outbox table row structure."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    aggregate_type: str = ""
    aggregate_id: str = ""
    event_type: str = ""
    payload: bytes = b""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def test_bench_outbox_event_construction(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark constructing an outbox event row."""
    payload = b"\x08\x01\x12\x10test-payload-data" * 50  # ~900 bytes

    def build() -> _OutboxEvent:
        return _OutboxEvent(
            aggregate_type="Listing",
            aggregate_id="550e8400-e29b-41d4-a716-446655440000",
            event_type="job-listing.cdc.listing-created.v1",
            payload=payload,
        )

    benchmark(build)


def test_bench_outbox_event_batch_10(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark constructing 10 outbox events (batch publish pattern)."""
    payload = b"\x08\x01\x12\x10test-payload-data" * 50

    def build_batch() -> list[_OutboxEvent]:
        return [
            _OutboxEvent(
                aggregate_type="Listing",
                aggregate_id=f"listing-{i}",
                event_type="job-listing.cdc.listing-created.v1",
                payload=payload,
            )
            for i in range(10)
        ]

    benchmark(build_batch)


# Datetime operations (heavily used in audit columns)


def test_bench_datetime_utc_now(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark datetime.now(UTC) (used in every audit column)."""
    benchmark(datetime.now, UTC)


def test_bench_datetime_isoformat(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark datetime serialization to ISO format."""
    now = datetime.now(UTC)
    benchmark(now.isoformat)
