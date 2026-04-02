"""Transactional outbox implementation for atomic database + event publishing.

The OutboxWriter enables services to write events to an outbox table within the same
database transaction as their business data. This ensures atomic commit of data + event
intent, preventing message loss if the service crashes between database commit and
Kafka publish.

Events written to the outbox are captured by Debezium CDC, which reads from PostgreSQL's
Write-Ahead Log (WAL) and publishes to Kafka topics using the Outbox Event Router SMT.

Usage:
    async with db.begin():
        # Write business data
        db.add(new_entity)

        # Write event to outbox (same transaction)
        await outbox_writer.write_event(
            db=db,
            aggregate_type="job",
            aggregate_id=str(job.id),
            event_type=Topics.JOB_LISTING_CREATED,
            event=job_store_created_pb,
        )
        # Commit is automatic with context manager

Column names match Debezium's expected outbox format exactly:
- aggregatetype, aggregateid, type, payload, tracingspancontext
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

from nohiki_observability import get_logger
from sqlalchemy import text
from uuid_utils.compat import uuid7

from ._validators import validate_schema_name
from .outbox_metrics import get_outbox_metrics

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


def _get_insert_sql(schema: str) -> str:
    """Generate INSERT SQL for the given schema."""
    return (
        f"INSERT INTO {schema}.outbox "
        "(id, aggregatetype, aggregateid, type, payload, timestamp, tracingspancontext) "
        "VALUES (:id, :aggregate_type, :aggregate_id, :event_type, :payload, :timestamp, :correlation_id)"
    )


@runtime_checkable
class OutboxPayload(Protocol):
    """Protocol for outbox-serializable messages."""

    def __bytes__(self) -> bytes:
        """Serialize message to bytes."""
        ...


@runtime_checkable
class OutboxBatchWriter(Protocol):
    """Protocol for outbox writers that support batch inserts."""

    async def write_events(
        self,
        db: AsyncSession | None,
        entries: Sequence[tuple[OutboxEventParams, OutboxPayload]],
    ) -> list[UUID]:
        """Write multiple events to the outbox table."""
        ...


@dataclass(frozen=True, slots=True)
class OutboxEventParams:
    """Parameters for writing an event to the outbox.

    This dataclass encapsulates the required parameters for outbox event writing,
    reducing function argument count and improving API clarity.

    Attributes:
        aggregate_type: Type of aggregate (e.g., "job", "profile", "user").
        aggregate_id: ID of the aggregate this event relates to.
        event_type: Kafka topic name (e.g., Topics.JOB_LISTING_CREATED).
        correlation_id: Optional correlation ID for distributed tracing.

    """

    aggregate_type: str
    aggregate_id: str
    event_type: str
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    """Represents an outbox table entry for CDC pickup.

    This is an immutable record of an event waiting to be published.
    The entry is written to the database in the same transaction as the business data.

    Attributes:
        id: Unique identifier for this outbox entry.
        aggregate_type: Type of aggregate (e.g., "job", "profile", "user").
        aggregate_id: ID of the aggregate this event relates to.
        event_type: Kafka topic name (e.g., Topics.JOB_LISTING_CREATED).
        payload: Serialized protobuf message bytes.
        timestamp: When the event was created.
        correlation_id: Optional correlation ID for distributed tracing.

    """

    id: UUID
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: bytes
    timestamp: datetime
    correlation_id: str | None = None


class OutboxWriter:
    """Write events to outbox table for Debezium CDC pickup.

    The OutboxWriter provides a simple interface for writing events to the
    transactional outbox. Events are written within the caller's database
    transaction, ensuring that either both the business data and the event
    are committed, or neither is.

    The writer does NOT commit the transaction - that responsibility remains
    with the caller, allowing multiple events to be written in a single
    transaction if needed.

    Each service should use its own schema to avoid conflicts:
        outbox = OutboxWriter(schema="user_pref_schema")

    Example:
        outbox = OutboxWriter(schema="my_service_schema")

        async with db.begin():
            # Business logic
            job = Listing(title="Software Engineer", ...)
            db.add(job)

            # Write event to outbox (same transaction)
            entry_id = await outbox.write_event(
                db=db,
                aggregate_type="job",
                aggregate_id=str(job.id),
                event_type=Topics.JOB_LISTING_CREATED,
                event=job_store_created_pb,
                correlation_id=ctx.correlation_id,
            )
            # Transaction commits automatically, or rolls back on error

    """

    __slots__ = ("_db", "_insert_sql", "_schema")

    def __init__(
        self,
        schema: str | None,
        db: AsyncSession | None = None,
    ) -> None:
        """Initialize OutboxWriter.

        Args:
            schema: The schema containing the outbox table (REQUIRED - no default).
            db: Optional session to bind for reuse.

        Raises:
            ValueError: If schema is not provided or empty.

        """
        if not schema:
            msg = "OutboxWriter requires explicit schema - each service must specify its own outbox schema"
            raise ValueError(msg)
        validate_schema_name(schema)
        self._schema = schema
        self._db = db
        self._insert_sql = text(_get_insert_sql(schema))

    def _serialize(self, event: OutboxPayload) -> bytes:
        """Serialize betterproto2 message to bytes."""
        return bytes(event)

    async def write_event(
        self,
        db: AsyncSession | None,
        params: OutboxEventParams,
        event: OutboxPayload,
    ) -> UUID:
        """Write event to outbox table within the caller's transaction.

        This method serializes the protobuf message and inserts it into the
        outbox table. The insert happens within the caller's transaction,
        so the event will only be visible after the transaction commits.

        Args:
            db: Async SQLAlchemy session (must be within a transaction).
            params: Event parameters (aggregate_type, aggregate_id, event_type, correlation_id).
            event: Protobuf message to serialize and store.

        Returns:
            UUID of the created outbox entry.

        Raises:
            SQLAlchemyError: If the database insert fails.

        Note:
            This method does NOT commit the transaction. The caller is
            responsible for committing (or rolling back) the transaction.

        """
        session = db or self._db
        if session is None:
            msg = "AsyncSession is required to write outbox event"
            raise ValueError(msg)

        entry_id = uuid7()
        payload = self._serialize(event)
        timestamp = datetime.now(UTC)
        outbox_metrics = get_outbox_metrics()
        start = time.perf_counter()

        try:
            await session.execute(
                self._insert_sql,
                {
                    "id": str(entry_id),
                    "aggregate_type": params.aggregate_type,
                    "aggregate_id": params.aggregate_id,
                    "event_type": params.event_type,
                    "payload": payload,
                    "timestamp": timestamp,
                    "correlation_id": params.correlation_id,
                },
            )
        except Exception as exc:
            outbox_metrics.record_error(params.event_type, type(exc).__name__)
            raise

        duration = time.perf_counter() - start
        outbox_metrics.record_write(
            event_type=params.event_type,
            aggregate_type=params.aggregate_type,
            duration_seconds=duration,
            payload_bytes=len(payload),
        )
        logger.debug(
            "Wrote event to outbox",
            outbox_entry_id=str(entry_id),
            schema=self._schema,
            aggregate_type=params.aggregate_type,
            aggregate_id=params.aggregate_id,
            event_type=params.event_type,
            payload_size_bytes=len(payload),
            correlation_id=params.correlation_id,
        )

        return entry_id

    async def write_events(
        self,
        db: AsyncSession | None,
        entries: Sequence[tuple[OutboxEventParams, OutboxPayload]],
    ) -> list[UUID]:
        """Write multiple events to the outbox table within one transaction.

        Args:
            db: Async SQLAlchemy session (must be within a transaction).
            entries: Event parameters and protobuf payloads to store.

        Returns:
            UUIDs of the created outbox entries in write order.

        Raises:
            SQLAlchemyError: If the database insert fails.

        """
        if not entries:
            return []

        session = db or self._db
        if session is None:
            msg = "AsyncSession is required to write outbox event"
            raise ValueError(msg)

        prepared_entries: list[tuple[UUID, OutboxEventParams, bytes, datetime]] = []
        for params, event in entries:
            prepared_entries.append((uuid7(), params, self._serialize(event), datetime.now(UTC)))

        outbox_metrics = get_outbox_metrics()
        start = time.perf_counter()

        try:
            await session.execute(
                self._insert_sql,
                [
                    {
                        "id": str(entry_id),
                        "aggregate_type": params.aggregate_type,
                        "aggregate_id": params.aggregate_id,
                        "event_type": params.event_type,
                        "payload": payload,
                        "timestamp": timestamp,
                        "correlation_id": params.correlation_id,
                    }
                    for entry_id, params, payload, timestamp in prepared_entries
                ],
            )
        except Exception as exc:
            for _, params, _, _ in prepared_entries:
                outbox_metrics.record_error(params.event_type, type(exc).__name__)
            raise

        duration = time.perf_counter() - start
        payload_sizes = [len(payload) for _, _, payload, _ in prepared_entries]

        if len(prepared_entries) == 1:
            entry_id, params, payload, _ = prepared_entries[0]
            outbox_metrics.record_write(
                event_type=params.event_type,
                aggregate_type=params.aggregate_type,
                duration_seconds=duration,
                payload_bytes=len(payload),
            )
            logger.debug(
                "Wrote event to outbox",
                outbox_entry_id=str(entry_id),
                schema=self._schema,
                aggregate_type=params.aggregate_type,
                aggregate_id=params.aggregate_id,
                event_type=params.event_type,
                payload_size_bytes=len(payload),
                correlation_id=params.correlation_id,
            )
            return [entry_id]

        first_params = prepared_entries[0][1]
        outbox_metrics.record_batch_write(
            event_type=first_params.event_type,
            aggregate_type=first_params.aggregate_type,
            duration_seconds=duration,
            payload_bytes=payload_sizes,
        )
        logger.debug(
            "Wrote events to outbox",
            outbox_entry_ids=[str(entry_id) for entry_id, _, _, _ in prepared_entries],
            schema=self._schema,
            aggregate_type=first_params.aggregate_type,
            event_type=first_params.event_type,
            event_count=len(prepared_entries),
        )

        return [entry_id for entry_id, _, _, _ in prepared_entries]

    async def write_event_raw(
        self,
        db: AsyncSession | None,
        params: OutboxEventParams,
        payload: bytes,
    ) -> UUID:
        """Write raw bytes to outbox table within the caller's transaction.

        This is a lower-level method for cases where the caller has already
        serialized the message or needs to write non-protobuf data.

        Args:
            db: Async SQLAlchemy session (must be within a transaction).
            params: Event parameters (aggregate_type, aggregate_id, event_type, correlation_id).
            payload: Raw bytes to store.

        Returns:
            UUID of the created outbox entry.

        Raises:
            SQLAlchemyError: If the database insert fails.

        """
        session = db or self._db
        if session is None:
            msg = "AsyncSession is required to write raw outbox event"
            raise ValueError(msg)

        entry_id = uuid7()
        timestamp = datetime.now(UTC)
        outbox_metrics = get_outbox_metrics()
        start = time.perf_counter()

        try:
            await session.execute(
                self._insert_sql,
                {
                    "id": str(entry_id),
                    "aggregate_type": params.aggregate_type,
                    "aggregate_id": params.aggregate_id,
                    "event_type": params.event_type,
                    "payload": payload,
                    "timestamp": timestamp,
                    "correlation_id": params.correlation_id,
                },
            )
        except Exception as exc:
            outbox_metrics.record_error(params.event_type, type(exc).__name__)
            raise

        duration = time.perf_counter() - start
        outbox_metrics.record_write(
            event_type=params.event_type,
            aggregate_type=params.aggregate_type,
            duration_seconds=duration,
            payload_bytes=len(payload),
        )

        logger.debug(
            "Wrote raw event to outbox",
            outbox_entry_id=str(entry_id),
            schema=self._schema,
            aggregate_type=params.aggregate_type,
            aggregate_id=params.aggregate_id,
            event_type=params.event_type,
            payload_size_bytes=len(payload),
            correlation_id=params.correlation_id,
        )

        return entry_id
