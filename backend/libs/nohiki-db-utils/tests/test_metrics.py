"""Tests for database metrics."""

from __future__ import annotations

from unittest.mock import patch

from nohiki_db_utils.metrics import DatabaseMetrics, get_database_metrics

# Test data constants
EXPECTED_ROWS_AFFECTED = 10
MINIMUM_CACHE_HITS = 2


class TestDatabaseMetrics:
    """Tests for DatabaseMetrics class."""

    def test_init_creates_all_metrics(self) -> None:
        """Test that all metrics are created during initialization."""
        metrics = DatabaseMetrics()

        assert metrics._meter is not None
        assert metrics.queries is not None
        assert metrics.query_duration is not None
        assert metrics.connections_active is not None
        assert metrics.connections_idle is not None
        assert metrics.pool_size is not None
        assert metrics.errors is not None
        assert metrics.transactions is not None

    def test_record_query_success(self) -> None:
        """Test recording a successful query."""
        metrics = DatabaseMetrics()

        with (
            patch.object(metrics.queries, "add") as mock_queries_add,
            patch.object(metrics.query_duration, "record") as mock_duration_record,
        ):
            metrics.record_query(
                operation="SELECT",
                duration_seconds=0.05,
                success=True,
                table="users",
                rows_affected=EXPECTED_ROWS_AFFECTED,
            )

            # Verify queries counter was incremented
            mock_queries_add.assert_called_once()
            call_args = mock_queries_add.call_args
            assert call_args.args[0] == 1
            assert call_args.args[1]["operation"] == "SELECT"
            assert call_args.args[1]["status"] == "success"
            assert call_args.args[1]["table"] == "users"
            assert call_args.args[1]["rows_affected"] == EXPECTED_ROWS_AFFECTED

            # Verify duration was recorded
            mock_duration_record.assert_called_once()

    def test_record_query_error(self) -> None:
        """Test recording a failed query."""
        metrics = DatabaseMetrics()

        with (
            patch.object(metrics.queries, "add") as mock_queries_add,
            patch.object(metrics.errors, "add") as mock_errors_add,
        ):
            metrics.record_query(
                operation="INSERT",
                duration_seconds=0.1,
                success=False,
            )

            # Verify queries counter was incremented with error status
            call_args = mock_queries_add.call_args
            assert call_args.args[1]["status"] == "error"

            # Verify error counter was incremented
            mock_errors_add.assert_called_once_with(1, {"operation": "INSERT"})

    def test_record_query_without_optional_params(self) -> None:
        """Test recording a query without optional parameters."""
        metrics = DatabaseMetrics()

        with patch.object(metrics.queries, "add") as mock_queries_add:
            metrics.record_query(
                operation="UPDATE",
                duration_seconds=0.02,
            )

            call_args = mock_queries_add.call_args
            assert "table" not in call_args.kwargs
            assert "rows_affected" not in call_args.kwargs

    def test_record_transaction_committed(self) -> None:
        """Test recording a committed transaction."""
        metrics = DatabaseMetrics()

        with (
            patch.object(metrics.transactions, "add") as mock_transactions_add,
            patch.object(metrics.query_duration, "record") as mock_duration_record,
        ):
            metrics.record_transaction(
                committed=True,
                duration_seconds=0.15,
            )

            # Verify transaction counter
            mock_transactions_add.assert_called_once_with(1, {"status": "committed"})

            # Verify duration was recorded
            mock_duration_record.assert_called_once()
            duration_call = mock_duration_record.call_args
            assert duration_call.args[1]["operation"] == "TRANSACTION"
            assert duration_call.args[1]["status"] == "committed"

    def test_record_transaction_rolled_back(self) -> None:
        """Test recording a rolled back transaction."""
        metrics = DatabaseMetrics()

        with patch.object(metrics.transactions, "add") as mock_transactions_add:
            metrics.record_transaction(
                committed=False,
                duration_seconds=0.08,
            )

            mock_transactions_add.assert_called_once_with(1, {"status": "rolled_back"})

    def test_record_pool_stats(self) -> None:
        """Test recording connection pool statistics."""
        metrics = DatabaseMetrics()

        with (
            patch.object(metrics.pool_size, "add") as mock_pool_add,
            patch.object(metrics.connections_active, "add") as mock_active_add,
            patch.object(metrics.connections_idle, "add") as mock_idle_add,
        ):
            metrics.record_pool_stats(
                pool_name="default",
                size=10,
                checked_out=3,
                overflow=2,
            )

            mock_pool_add.assert_called_once_with(10, {"pool": "default"})
            mock_active_add.assert_called_once_with(3, {"pool": "default"})
            mock_idle_add.assert_called_once_with(9, {"pool": "default"})

    def test_record_pool_stats_zero_idle(self) -> None:
        """Test recording pool stats when idle is zero."""
        metrics = DatabaseMetrics()

        with patch.object(metrics.connections_idle, "add") as mock_idle_add:
            metrics.record_pool_stats(
                pool_name="test_pool",
                size=5,
                checked_out=5,
                overflow=0,
            )
            mock_idle_add.assert_called_once_with(0, {"pool": "test_pool"})


class TestGetDatabaseMetrics:
    """Tests for get_database_metrics singleton function."""

    def test_returns_singleton(self) -> None:
        """Test that get_database_metrics returns the same instance."""
        # Clear the cache first
        get_database_metrics.cache_clear()

        metrics1 = get_database_metrics()
        metrics2 = get_database_metrics()

        assert metrics1 is metrics2

    def test_returns_database_metrics_instance(self) -> None:
        """Test that the returned value is a DatabaseMetrics instance."""
        get_database_metrics.cache_clear()

        metrics = get_database_metrics()
        assert isinstance(metrics, DatabaseMetrics)

    def test_lru_cache_limits_size(self) -> None:
        """Test that LRU cache limits to 1 instance."""
        get_database_metrics.cache_clear()

        # Create multiple instances should return same cached value
        get_database_metrics()
        get_database_metrics()
        get_database_metrics()

        # Cache info should show 2 hits
        info = get_database_metrics.cache_info()
        assert info.hits >= MINIMUM_CACHE_HITS
        assert info.maxsize == 1
