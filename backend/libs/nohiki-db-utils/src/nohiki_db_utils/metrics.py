"""Database metrics - owned by nohiki-db-utils."""

from __future__ import annotations

from functools import lru_cache

from opentelemetry import metrics


class DatabaseMetrics:
    """PostgreSQL database metrics using OpenTelemetry."""

    def __init__(self) -> None:
        """Initialize database metrics with OpenTelemetry meter."""
        self._meter = metrics.get_meter("nohiki.database")

        self.queries = self._meter.create_counter(
            "nohiki_db_queries_total",
            description="Total database queries executed",
            unit="1",
        )
        self.query_duration = self._meter.create_histogram(
            "nohiki_db_query_duration_seconds",
            description="Query execution time",
            unit="s",
        )
        self.connections_active = self._meter.create_up_down_counter(
            "nohiki_db_connections_active",
            description="Active database connections",
            unit="1",
        )
        self.connections_idle = self._meter.create_up_down_counter(
            "nohiki_db_connections_idle",
            description="Idle database connections",
            unit="1",
        )
        self.pool_size = self._meter.create_up_down_counter(
            "nohiki_db_pool_size",
            description="Connection pool size",
            unit="1",
        )
        self.errors = self._meter.create_counter(
            "nohiki_db_errors_total",
            description="Database errors",
            unit="1",
        )
        self.transactions = self._meter.create_counter(
            "nohiki_db_transactions_total",
            description="Database transactions",
            unit="1",
        )

    def record_query(
        self,
        operation: str,
        duration_seconds: float,
        *,
        success: bool = True,
        table: str | None = None,
        rows_affected: int | None = None,
    ) -> None:
        """Record a database query."""
        attrs: dict[str, str | int] = {
            "operation": operation.upper(),
            "status": "success" if success else "error",
        }
        if table:
            attrs["table"] = table
        if rows_affected is not None:
            attrs["rows_affected"] = rows_affected

        self.queries.add(1, attrs)
        self.query_duration.record(duration_seconds, attrs)

        if not success:
            self.errors.add(1, {"operation": operation.upper()})

    def record_transaction(
        self,
        *,
        committed: bool,
        duration_seconds: float,
    ) -> None:
        """Record a transaction completion."""
        self.transactions.add(
            1,
            {"status": "committed" if committed else "rolled_back"},
        )
        self.query_duration.record(
            duration_seconds,
            {
                "operation": "TRANSACTION",
                "status": "committed" if committed else "rolled_back",
            },
        )

    def record_pool_stats(
        self,
        pool_name: str,
        size: int,
        checked_out: int,
        overflow: int,
    ) -> None:
        """Record connection pool statistics."""
        attrs = {"pool": pool_name}
        idle = size - checked_out + overflow
        self.pool_size.add(size, attrs)
        self.connections_active.add(checked_out, attrs)
        self.connections_idle.add(idle, attrs)


@lru_cache(maxsize=1)
def get_database_metrics() -> DatabaseMetrics:
    """Get singleton DatabaseMetrics instance."""
    return DatabaseMetrics()
