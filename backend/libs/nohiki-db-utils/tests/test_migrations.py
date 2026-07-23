"""Tests for database migrations utilities."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_db_utils.migrations import (
    DatabaseConfig,
    LockContext,
    MigrationError,
    MigrationState,
    get_migration_state,
    initialize_database,
    run_migrations_with_coordination,
    skip_migrations,
)
from nohiki_db_utils.migrations.coordinator import (
    _run_with_lock,
)
from nohiki_db_utils.migrations.lock import (
    clear_lock_metadata as _clear_lock_metadata,
)
from nohiki_db_utils.migrations.lock import (
    ensure_lock_meta_table as _ensure_lock_meta_table,
)
from nohiki_db_utils.migrations.lock import (
    get_lock_metadata as _get_lock_metadata,
)
from nohiki_db_utils.migrations.lock import (
    release_lock as _release_lock,
)
from nohiki_db_utils.migrations.lock import (
    set_lock_metadata as _set_lock_metadata,
)
from nohiki_db_utils.migrations.lock import (
    try_acquire_lock as _try_acquire_lock,
)
from nohiki_db_utils.migrations.lock import (
    wait_for_lock_release as _wait_for_lock_release,
)
from nohiki_db_utils.migrations.state import (
    set_migration_status as _set_migration_status,
)
from nohiki_db_utils.migrations.url_utils import (
    to_async_url as _to_async_url,
)
from nohiki_db_utils.migrations.url_utils import (
    to_sync_url as _to_sync_url,
)
from nohiki_db_utils.migrations.version import (
    check_migration_needed as _check_migration_needed,
)
from nohiki_db_utils.migrations.version import (
    is_transient_error as _is_transient_error,
)
from sqlalchemy.exc import OperationalError


class _BlockedExecutor:
    """Drive an executor future from a thread without sleeps or deadlines."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self.future = loop.create_future()
        self.started = threading.Event()
        self.release = threading.Event()
        self.exited = threading.Event()

    def run_in_executor(self, *_args: object) -> asyncio.Future[None]:
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        return self.future

    def _run(self) -> None:
        self.started.set()
        self.release.wait()
        self.exited.set()
        self._loop.call_soon_threadsafe(self.future.set_result, None)


class TestMigrationState:
    """Tests for MigrationState dataclass."""

    def test_default_values(self) -> None:
        """Test default values of MigrationState."""
        state = MigrationState()
        assert state.status == "not_started"
        assert state.error is None
        assert state.started_at is None
        assert state.completed_at is None
        assert state.current_revision is None
        assert state.target_revision is None

    def test_is_healthy_completed(self) -> None:
        """Test is_healthy returns True for completed status."""
        state = MigrationState(status="completed")
        assert state.is_healthy() is True

    def test_is_healthy_other_statuses(self) -> None:
        """Test is_healthy returns False for non-completed statuses."""
        assert MigrationState(status="not_started").is_healthy() is False
        assert MigrationState(status="in_progress").is_healthy() is False
        assert MigrationState(status="failed").is_healthy() is False

    def test_to_dict_with_timestamps(self) -> None:
        """Test conversion to dictionary with timestamps."""
        state = MigrationState(
            status="completed",
            error=None,
            started_at=123.0,
            completed_at=456.0,
            current_revision="abc123",
            target_revision="def456",
        )
        result = state.to_dict()

        assert result["status"] == "completed"
        assert result["healthy"] is True
        assert result["started_at"] == pytest.approx(123.0)
        assert result["completed_at"] == pytest.approx(456.0)


class TestGetAndSetMigrationState:
    """Tests for migration state getters and setters."""

    def test_get_migration_state_returns_singleton(self) -> None:
        """Test get_migration_state returns the global state."""
        state1 = get_migration_state()
        state2 = get_migration_state()
        assert state1 is state2

    def test_skip_migrations(self) -> None:
        """Test skip_migrations marks state as completed."""
        skip_migrations()
        state = get_migration_state()
        assert state.status == "completed"
        assert state.completed_at is not None

    def test_set_migration_status_updates_state(self) -> None:
        """Test _set_migration_status updates global state."""
        _set_migration_status("in_progress")
        state = get_migration_state()
        assert state.status == "in_progress"
        assert state.started_at is not None

        _set_migration_status("completed", current_revision="abc", target_revision="def")
        assert state.status == "completed"
        assert state.current_revision == "abc"
        assert state.target_revision == "def"
        assert state.completed_at is not None


class TestUrlConversion:
    """Tests for URL conversion functions."""

    def test_to_sync_url_converts_asyncpg(self) -> None:
        """Test _to_sync_url converts asyncpg to psycopg."""
        asyncpg_url = "postgresql+asyncpg://user:pass@localhost/db"
        result = _to_sync_url(asyncpg_url)
        assert result == "postgresql+psycopg://user:pass@localhost/db"

    def test_to_sync_url_adds_psycopg(self) -> None:
        """Test _to_sync_url adds psycopg to plain postgresql URL."""
        plain_url = "postgresql://user:pass@localhost/db"
        result = _to_sync_url(plain_url)
        assert result == "postgresql+psycopg://user:pass@localhost/db"

    def test_to_async_url_converts_to_asyncpg(self) -> None:
        """Test _to_async_url converts to asyncpg."""
        plain_url = "postgresql://user:pass@localhost/db"
        result = _to_async_url(plain_url)
        assert result == "postgresql+asyncpg://user:pass@localhost/db"

    def test_to_async_url_leaves_asyncpg_unchanged(self) -> None:
        """Test _to_async_url leaves asyncpg URLs unchanged."""
        asyncpg_url = "postgresql+asyncpg://user:pass@localhost/db"
        result = _to_async_url(asyncpg_url)
        assert result == asyncpg_url


class TestTransientErrorDetection:
    """Tests for _is_transient_error function."""

    def test_detects_connection_refused(self) -> None:
        """Test detection of connection refused errors."""
        error = OperationalError("connection refused", {}, Exception())
        assert _is_transient_error(error) is True

    def test_detects_name_resolution_failure(self) -> None:
        """Test detection of name resolution failures."""
        error = OperationalError("name or service not known", {}, Exception())
        assert _is_transient_error(error) is True

    def test_detects_timeout(self) -> None:
        """Test detection of timeout errors."""
        error = OperationalError("timeout occurred", {}, Exception())
        assert _is_transient_error(error) is True

    def test_non_transient_error(self) -> None:
        """Test non-transient errors return False."""
        error = OperationalError("syntax error", {}, Exception())
        assert _is_transient_error(error) is False


class TestLockOperations:
    """Tests for lock-related operations."""

    @pytest.mark.asyncio
    async def test_try_acquire_lock(self) -> None:
        """Test lock acquisition."""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = True
        mock_conn.execute.return_value = mock_result

        result = await _try_acquire_lock(mock_conn, 12345)

        assert result is True
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_lock(self) -> None:
        """Test lock release."""
        mock_conn = AsyncMock()

        await _release_lock(mock_conn, 12345)

        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_for_lock_release_success(self) -> None:
        """Test waiting for lock release - success case."""
        mock_conn = AsyncMock()

        # First call fails to acquire, second succeeds, third for release
        mock_result_locked = MagicMock()
        mock_result_locked.scalar.return_value = False
        mock_result_acquired = MagicMock()
        mock_result_acquired.scalar.return_value = True
        mock_result_release = MagicMock()  # For _release_lock call

        mock_conn.execute.side_effect = [
            mock_result_locked,  # First poll - still locked
            mock_result_acquired,  # Second poll - acquired
            mock_result_release,  # Release lock call
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await _wait_for_lock_release(mock_conn, 12345, 5, "test-service")

    @pytest.mark.asyncio
    async def test_wait_for_lock_release_timeout(self) -> None:
        """Test that timeout is not rounded up to the polling interval."""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = False
        mock_conn.execute.return_value = mock_result

        started = time.monotonic()
        with pytest.raises(MigrationError, match="Timeout waiting"):
            await _wait_for_lock_release(mock_conn, 12345, 0.05, "test-service")

        assert time.monotonic() - started < 0.2


class TestLockMetadataOperations:
    """Tests for lock metadata operations."""

    @pytest.mark.asyncio
    async def test_ensure_lock_meta_table(self) -> None:
        """Test lock metadata table creation."""
        mock_conn = AsyncMock()

        await _ensure_lock_meta_table(mock_conn)

        mock_conn.run_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_lock_metadata(self) -> None:
        """Test setting lock metadata."""
        mock_conn = AsyncMock()

        await _set_lock_metadata(mock_conn, 12345, "pod-1")

        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_lock_metadata_found(self) -> None:
        """Test getting lock metadata when it exists."""
        mock_conn = AsyncMock()
        mock_row = MagicMock()
        mock_row.acquired_at = datetime.now(UTC)
        mock_row.holder_id = "pod-1"

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_result

        result = await _get_lock_metadata(mock_conn, 12345)

        assert result is not None
        assert result[1] == "pod-1"

    @pytest.mark.asyncio
    async def test_get_lock_metadata_not_found(self) -> None:
        """Test getting lock metadata when it doesn't exist."""
        mock_conn = AsyncMock()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        result = await _get_lock_metadata(mock_conn, 12345)

        assert result is None

    @pytest.mark.asyncio
    async def test_clear_lock_metadata(self) -> None:
        """Test clearing lock metadata."""
        mock_conn = AsyncMock()

        await _clear_lock_metadata(mock_conn, 12345)

        mock_conn.execute.assert_called_once()


class TestRunWithLock:
    """Tests for _run_with_lock function."""

    @pytest.mark.asyncio
    @patch("nohiki_db_utils.migrations.coordinator.execute_migrations")
    @patch("nohiki_db_utils.migrations.coordinator.get_db_version_info")
    async def test_successful_migration(
        self,
        mock_get_version: MagicMock,
        mock_execute: AsyncMock,
    ) -> None:
        """Test successful migration with lock."""
        mock_conn = AsyncMock()
        ctx = LockContext("test-service", "pod-1", "postgresql://localhost/db", "alembic.ini")

        mock_get_version.return_value = ("abc123", "def456")

        await _run_with_lock(mock_conn, 12345, ctx, 120, "def456")

        mock_execute.assert_called_once()
        state = get_migration_state()
        assert state.status == "completed"

    @pytest.mark.asyncio
    @patch("nohiki_db_utils.migrations.coordinator.execute_migrations")
    @patch("nohiki_db_utils.migrations.coordinator.get_db_version_info")
    async def test_migration_failure_sets_failed_state(
        self,
        mock_get_version: MagicMock,
        mock_execute: AsyncMock,
    ) -> None:
        """Test migration failure sets state to failed."""
        mock_conn = AsyncMock()
        ctx = LockContext("test-service", "pod-1", "postgresql://localhost/db", "alembic.ini")

        mock_get_version.return_value = ("abc123", "def456")
        mock_execute.side_effect = MigrationError("Migration failed")

        with pytest.raises(MigrationError, match="Migration failed"):
            await _run_with_lock(mock_conn, 12345, ctx, 120, "def456")

        state = get_migration_state()
        assert state.status == "failed"
        assert state.error is not None
        assert "Migration failed" in state.error

    @pytest.mark.asyncio
    async def test_timeout_then_cancellation_keeps_lock_until_executor_exits(self) -> None:
        """A cancellation during timeout draining cannot release a live migration lock."""
        loop = asyncio.get_running_loop()
        executor = _BlockedExecutor(loop)
        timeout_observed = asyncio.Event()
        lock_released = asyncio.Event()
        second_started = asyncio.Event()
        second_entered = asyncio.Event()
        executor_loop = MagicMock()
        executor_loop.run_in_executor.side_effect = executor.run_in_executor

        async def force_timeout(_awaitable: object, **kwargs: float) -> None:
            assert kwargs["timeout"] == 30
            await asyncio.to_thread(executor.started.wait)
            timeout_observed.set()
            raise TimeoutError

        async def release_lock(_conn: object, _lock_id: int) -> None:
            lock_released.set()

        async def second_coordinator() -> None:
            second_started.set()
            await lock_released.wait()
            second_entered.set()

        conn = AsyncMock()
        ctx = LockContext("test-service", "pod-1", "postgresql://localhost/db", "alembic.ini")
        with (
            patch("nohiki_db_utils.migrations.executor.asyncio.get_event_loop", return_value=executor_loop),
            patch("nohiki_db_utils.migrations.executor.asyncio.wait_for", side_effect=force_timeout),
            patch(
                "nohiki_db_utils.migrations.coordinator.clear_lock_metadata",
                new_callable=AsyncMock,
            ) as mock_clear,
            patch(
                "nohiki_db_utils.migrations.coordinator.release_lock",
                new_callable=AsyncMock,
                side_effect=release_lock,
            ) as mock_release,
        ):
            migration_task = asyncio.create_task(_run_with_lock(conn, 12345, ctx, 30, "def456"))
            await asyncio.to_thread(executor.started.wait)
            await timeout_observed.wait()
            second_task = asyncio.create_task(second_coordinator())
            await second_started.wait()
            assert not second_entered.is_set()
            migration_task.cancel()
            assert not lock_released.is_set()
            assert not mock_clear.await_count
            assert not mock_release.await_count

            executor.release.set()
            await asyncio.to_thread(executor.exited.wait)
            with pytest.raises(MigrationError, match="Migration timed out"):
                await migration_task
            await second_task

        assert second_entered.is_set()
        mock_clear.assert_awaited_once_with(conn, 12345)
        mock_release.assert_awaited_once_with(conn, 12345)

    @pytest.mark.asyncio
    async def test_cancellation_before_timeout_keeps_lock_until_executor_exits(self) -> None:
        """Cancellation before the deadline drains the executor before releasing the lock."""
        loop = asyncio.get_running_loop()
        executor = _BlockedExecutor(loop)
        cancellation_observed = asyncio.Event()
        lock_released = asyncio.Event()
        second_started = asyncio.Event()
        second_entered = asyncio.Event()
        executor_loop = MagicMock()
        executor_loop.run_in_executor.side_effect = executor.run_in_executor

        async def wait_without_timeout(awaitable: Awaitable[object], **_kwargs: float) -> object:
            try:
                return await awaitable
            except asyncio.CancelledError:
                cancellation_observed.set()
                raise

        async def release_lock(_conn: object, _lock_id: int) -> None:
            lock_released.set()

        async def second_coordinator() -> None:
            second_started.set()
            await lock_released.wait()
            second_entered.set()

        conn = AsyncMock()
        ctx = LockContext("test-service", "pod-1", "postgresql://localhost/db", "alembic.ini")
        with (
            patch("nohiki_db_utils.migrations.executor.asyncio.get_event_loop", return_value=executor_loop),
            patch("nohiki_db_utils.migrations.executor.asyncio.wait_for", side_effect=wait_without_timeout),
            patch(
                "nohiki_db_utils.migrations.coordinator.clear_lock_metadata",
                new_callable=AsyncMock,
            ) as mock_clear,
            patch(
                "nohiki_db_utils.migrations.coordinator.release_lock",
                new_callable=AsyncMock,
                side_effect=release_lock,
            ) as mock_release,
        ):
            migration_task = asyncio.create_task(_run_with_lock(conn, 12345, ctx, 30, "def456"))
            await asyncio.to_thread(executor.started.wait)
            second_task = asyncio.create_task(second_coordinator())
            await second_started.wait()
            migration_task.cancel()
            await cancellation_observed.wait()
            assert not second_entered.is_set()
            assert not lock_released.is_set()
            assert not mock_clear.await_count
            assert not mock_release.await_count

            executor.release.set()
            await asyncio.to_thread(executor.exited.wait)
            with pytest.raises(asyncio.CancelledError):
                await migration_task
            await second_task

        assert second_entered.is_set()
        mock_clear.assert_awaited_once_with(conn, 12345)
        mock_release.assert_awaited_once_with(conn, 12345)

    @pytest.mark.asyncio
    async def test_repeated_cancellation_drains_executor_before_releasing_lock(self) -> None:
        """Repeated cancellation cannot interrupt draining a blocked executor thread."""
        loop = asyncio.get_running_loop()
        executor = _BlockedExecutor(loop)
        cancellation_observed = asyncio.Event()
        lock_released = asyncio.Event()
        second_started = asyncio.Event()
        second_entered = asyncio.Event()
        executor_loop = MagicMock()
        executor_loop.run_in_executor.side_effect = executor.run_in_executor

        async def wait_without_timeout(awaitable: Awaitable[object], **_kwargs: float) -> object:
            try:
                return await awaitable
            except asyncio.CancelledError:
                cancellation_observed.set()
                raise

        async def release_lock(_conn: object, _lock_id: int) -> None:
            lock_released.set()

        async def second_coordinator() -> None:
            second_started.set()
            await lock_released.wait()
            second_entered.set()

        conn = AsyncMock()
        ctx = LockContext("test-service", "pod-1", "postgresql://localhost/db", "alembic.ini")
        with (
            patch("nohiki_db_utils.migrations.executor.asyncio.get_event_loop", return_value=executor_loop),
            patch("nohiki_db_utils.migrations.executor.asyncio.wait_for", side_effect=wait_without_timeout),
            patch(
                "nohiki_db_utils.migrations.coordinator.clear_lock_metadata",
                new_callable=AsyncMock,
            ) as mock_clear,
            patch(
                "nohiki_db_utils.migrations.coordinator.release_lock",
                new_callable=AsyncMock,
                side_effect=release_lock,
            ) as mock_release,
        ):
            migration_task = asyncio.create_task(_run_with_lock(conn, 12345, ctx, 30, "def456"))
            await asyncio.to_thread(executor.started.wait)
            second_task = asyncio.create_task(second_coordinator())
            await second_started.wait()
            migration_task.cancel()
            await cancellation_observed.wait()
            migration_task.cancel()
            migration_task.cancel()
            assert not second_entered.is_set()
            assert not lock_released.is_set()
            assert not mock_clear.await_count
            assert not mock_release.await_count

            executor.release.set()
            await asyncio.to_thread(executor.exited.wait)
            with pytest.raises(asyncio.CancelledError):
                await migration_task
            await second_task

        assert second_entered.is_set()
        mock_clear.assert_awaited_once_with(conn, 12345)
        mock_release.assert_awaited_once_with(conn, 12345)


class TestCheckMigrationNeeded:
    """Tests for _check_migration_needed function."""

    @patch("nohiki_db_utils.migrations.version.get_db_version_info")
    def test_no_migration_needed(self, mock_get_version: MagicMock) -> None:
        """Test when database is already up to date."""
        mock_get_version.return_value = ("abc123", "abc123")

        needs_migration, head_rev = _check_migration_needed("postgresql://localhost/db", "alembic.ini", "test-service")

        assert needs_migration is False
        assert head_rev == "abc123"

    @patch("nohiki_db_utils.migrations.version.get_db_version_info")
    def test_migration_needed(self, mock_get_version: MagicMock) -> None:
        """Test when migration is needed."""
        mock_get_version.return_value = ("abc123", "def456")

        needs_migration, head_rev = _check_migration_needed("postgresql://localhost/db", "alembic.ini", "test-service")

        assert needs_migration is True
        assert head_rev == "def456"

    @patch("nohiki_db_utils.migrations.version.get_db_version_info")
    def test_uninitialized_database(self, mock_get_version: MagicMock) -> None:
        """Test when database has no alembic_version table."""
        mock_get_version.return_value = (None, "abc123")

        needs_migration, head_rev = _check_migration_needed("postgresql://localhost/db", "alembic.ini", "test-service")

        assert needs_migration is True
        assert head_rev == "abc123"


class TestDatabaseConfigProtocol:
    """Tests for DatabaseConfig protocol."""

    def test_protocol_attributes(self) -> None:
        """Test DatabaseConfig protocol has required attributes."""
        assert hasattr(DatabaseConfig, "connection_string")
        assert hasattr(DatabaseConfig, "migrate_on_startup")
        assert hasattr(DatabaseConfig, "migration_timeout_seconds")
        assert hasattr(DatabaseConfig, "get_connect_args")


class TestLockContext:
    """Tests for LockContext dataclass."""

    def test_creation(self) -> None:
        """Test LockContext creation."""
        ctx = LockContext("svc", "pod-1", "postgresql://localhost/db", "alembic.ini")
        assert ctx.service_name == "svc"
        assert ctx.pod_id == "pod-1"
        assert ctx.database_url == "postgresql://localhost/db"
        assert ctx.alembic_config_path == "alembic.ini"


class TestMigrationError:
    """Tests for MigrationError exception."""

    def test_error_message(self) -> None:
        """Test MigrationError stores message."""
        error = MigrationError("test error message")
        assert str(error) == "test error message"
        assert error.message == "test error message"


class TestCreateAsyncEngineWithSSL:
    """Tests for _create_async_engine_with_ssl function."""

    @patch("nohiki_db_utils.migrations.url_utils.create_async_engine")
    @patch("nohiki_db_utils.migrations.url_utils.ssl.create_default_context")
    def test_create_engine_without_ssl(self, mock_ssl_context: MagicMock, mock_create_engine: MagicMock) -> None:
        """Test engine creation without SSL."""
        from nohiki_db_utils.migrations.coordinator import (
            create_async_engine_with_ssl as _create_async_engine_with_ssl,
        )

        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        result = _create_async_engine_with_ssl("postgresql+asyncpg://user:pass@localhost/db")

        assert result == mock_engine
        mock_create_engine.assert_called_once()
        mock_ssl_context.assert_not_called()

    @patch("nohiki_db_utils.migrations.url_utils.create_async_engine")
    @patch("nohiki_db_utils.migrations.url_utils.ssl.SSLContext")
    def test_create_engine_with_ssl_require(self, mock_ssl_context: MagicMock, mock_create_engine: MagicMock) -> None:
        """Test engine creation with SSL mode require."""
        from nohiki_db_utils.migrations.coordinator import (
            create_async_engine_with_ssl as _create_async_engine_with_ssl,
        )

        mock_context = MagicMock()
        mock_ssl_context.return_value = mock_context
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        result = _create_async_engine_with_ssl("postgresql+asyncpg://user:pass@localhost/db?sslmode=require")

        assert result == mock_engine
        mock_ssl_context.assert_called_once()
        mock_create_engine.assert_called_once()

    @patch("nohiki_db_utils.migrations.url_utils.create_async_engine")
    @patch("nohiki_db_utils.migrations.url_utils.ssl.SSLContext")
    def test_create_engine_with_ssl_prefer(self, mock_ssl_context: MagicMock, mock_create_engine: MagicMock) -> None:
        """Test engine creation with SSL mode prefer."""
        from nohiki_db_utils.migrations.coordinator import (
            create_async_engine_with_ssl as _create_async_engine_with_ssl,
        )

        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        result = _create_async_engine_with_ssl("postgresql+asyncpg://user:pass@localhost/db?sslmode=prefer")

        assert result == mock_engine
        mock_create_engine.assert_called_once()


class TestHandleLockNotAcquired:
    """Tests for _handle_lock_not_acquired function."""

    @patch("nohiki_db_utils.migrations.coordinator.get_db_version_info")
    @patch("nohiki_db_utils.migrations.coordinator.get_lock_metadata")
    @patch("nohiki_db_utils.migrations.coordinator.wait_for_lock_release")
    @pytest.mark.asyncio
    async def test_handle_lock_not_acquired_with_metadata(
        self,
        mock_wait: AsyncMock,
        mock_get_meta: AsyncMock,
        mock_get_version: MagicMock,
    ) -> None:
        """Test handling lock not acquired with existing metadata."""
        from nohiki_db_utils.migrations.coordinator import _handle_lock_not_acquired

        conn = AsyncMock()
        ctx = LockContext("test-service", "pod-1", "postgresql://localhost/db", "alembic.ini")

        acquired_at = datetime.now(UTC)
        mock_get_meta.return_value = (acquired_at, "other-pod")
        mock_get_version.return_value = ("abc123", "abc123")

        await _handle_lock_not_acquired(conn, 12345, 30, ctx)

        mock_get_meta.assert_called_once()
        mock_wait.assert_called_once()
        mock_get_version.assert_called_once()

    @patch("nohiki_db_utils.migrations.coordinator.get_db_version_info")
    @patch("nohiki_db_utils.migrations.coordinator.get_lock_metadata")
    @patch("nohiki_db_utils.migrations.coordinator.wait_for_lock_release")
    @pytest.mark.asyncio
    async def test_handle_lock_not_acquired_no_metadata(
        self,
        mock_wait: AsyncMock,
        mock_get_meta: AsyncMock,
        mock_get_version: MagicMock,
    ) -> None:
        """Test handling lock not acquired with no metadata (legacy lock)."""
        from nohiki_db_utils.migrations.coordinator import _handle_lock_not_acquired

        conn = AsyncMock()
        ctx = LockContext("test-service", "pod-1", "postgresql://localhost/db", "alembic.ini")

        mock_get_meta.return_value = None
        mock_get_version.return_value = ("abc123", "abc123")

        await _handle_lock_not_acquired(conn, 12345, 30, ctx)

        mock_get_meta.assert_called_once()
        mock_wait.assert_called_once()


class TestRunMigrationsWithCoordination:
    """Tests for run_migrations_with_coordination function."""

    @patch("nohiki_db_utils.migrations.coordinator.check_migration_needed")
    @patch("nohiki_db_utils.migrations.coordinator.create_async_engine_with_ssl")
    @pytest.mark.asyncio
    async def test_no_migration_needed_early_return(
        self,
        mock_create_engine: MagicMock,
        mock_check: MagicMock,
    ) -> None:
        """Test early return when no migration needed."""
        mock_check.return_value = (False, "abc123")
        mock_engine = AsyncMock()
        mock_create_engine.return_value = mock_engine

        await run_migrations_with_coordination(
            "test-service",
            database_url="postgresql://localhost/db",
            alembic_config_path="alembic.ini",
        )

        mock_check.assert_called_once()
        mock_engine.connect.assert_not_called()

    @patch("nohiki_db_utils.migrations.coordinator.check_migration_needed")
    @pytest.mark.asyncio
    async def test_missing_database_url(self, mock_check: MagicMock) -> None:
        """Test error when database_url is None."""
        with pytest.raises(MigrationError, match="database_url is required"):
            await run_migrations_with_coordination("test-service", database_url=None)

    @patch("nohiki_db_utils.migrations.coordinator.check_migration_needed")
    @pytest.mark.asyncio
    async def test_non_postgresql_url(self, mock_check: MagicMock) -> None:
        """Test error when non-PostgreSQL URL provided."""
        with pytest.raises(MigrationError, match="PostgreSQL required"):
            await run_migrations_with_coordination("test-service", database_url="mysql://localhost/db")


class TestExecuteMigrations:
    """Tests for _execute_migrations function."""

    @patch("nohiki_db_utils.migrations.executor.asyncio.wait_for")
    @patch("nohiki_db_utils.migrations.executor.asyncio.get_event_loop")
    @pytest.mark.asyncio
    async def test_execute_migration_timeout(self, mock_get_loop: MagicMock, mock_wait_for: AsyncMock) -> None:
        """Test timeout handling in _execute_migrations."""
        from nohiki_db_utils.migrations.coordinator import (
            execute_migrations as _execute_migrations,
        )

        mock_wait_for.side_effect = TimeoutError()

        with pytest.raises(MigrationError, match="Migration timed out"):
            await _execute_migrations("test-service", "postgresql://localhost/db", 30, "alembic.ini")


class TestHandleLockNotAcquiredExtended:
    """Extended tests for _handle_lock_not_acquired to cover edge cases."""

    @patch("nohiki_db_utils.migrations.coordinator.get_db_version_info")
    @patch("nohiki_db_utils.migrations.coordinator.get_lock_metadata")
    @patch("nohiki_db_utils.migrations.coordinator.wait_for_lock_release")
    @pytest.mark.asyncio
    async def test_stale_lock_detection(
        self,
        mock_wait: AsyncMock,
        mock_get_meta: AsyncMock,
        mock_get_version: MagicMock,
    ) -> None:
        """Test stale lock detection when lock age exceeds timeout."""
        from datetime import timedelta

        from nohiki_db_utils.migrations.coordinator import _handle_lock_not_acquired

        conn = AsyncMock()
        ctx = LockContext("test-service", "pod-1", "postgresql://localhost/db", "alembic.ini")

        # Lock acquired 100 seconds ago (exceeds 30 second timeout)
        acquired_at = datetime.now(UTC) - timedelta(seconds=100)
        mock_get_meta.return_value = (acquired_at, "other-pod")
        mock_get_version.return_value = ("abc123", "abc123")

        await _handle_lock_not_acquired(conn, 12345, 30, ctx)

        mock_get_meta.assert_called_once()
        mock_wait.assert_called_once()
        mock_get_version.assert_called_once()

    @patch("nohiki_db_utils.migrations.coordinator.get_db_version_info")
    @patch("nohiki_db_utils.migrations.coordinator.get_lock_metadata")
    @patch("nohiki_db_utils.migrations.coordinator.wait_for_lock_release")
    @patch("nohiki_db_utils.migrations.coordinator.try_acquire_lock")
    @patch("nohiki_db_utils.migrations.coordinator.set_lock_metadata")
    @patch("nohiki_db_utils.migrations.coordinator.execute_migrations")
    @patch("nohiki_db_utils.migrations.coordinator.clear_lock_metadata")
    @patch("nohiki_db_utils.migrations.coordinator.release_lock")
    @pytest.mark.asyncio
    async def test_recovery_migration_success(
        self,
        mock_release: AsyncMock,
        mock_clear: AsyncMock,
        mock_execute: AsyncMock,
        mock_set_meta: AsyncMock,
        mock_acquire: AsyncMock,
        mock_wait: AsyncMock,
        mock_get_meta: AsyncMock,
        mock_get_version: MagicMock,
    ) -> None:
        """Test recovery migration when other pod failed."""
        from nohiki_db_utils.migrations.coordinator import _handle_lock_not_acquired

        conn = AsyncMock()
        ctx = LockContext("test-service", "pod-1", "postgresql://localhost/db", "alembic.ini")

        acquired_at = datetime.now(UTC)
        mock_get_meta.return_value = (acquired_at, "other-pod")
        # Current rev != head rev means other pod didn't complete
        mock_get_version.side_effect = [("abc123", "def456"), ("def456", "def456")]
        mock_acquire.return_value = True

        await _handle_lock_not_acquired(conn, 12345, 30, ctx)

        mock_get_meta.assert_called_once()
        mock_wait.assert_called_once()
        mock_acquire.assert_called_once()
        mock_execute.assert_called_once()
        mock_set_meta.assert_called_once()
        mock_clear.assert_called_once()
        mock_release.assert_called_once()

    @patch("nohiki_db_utils.migrations.coordinator.get_db_version_info")
    @patch("nohiki_db_utils.migrations.coordinator.get_lock_metadata")
    @patch("nohiki_db_utils.migrations.coordinator.wait_for_lock_release")
    @patch("nohiki_db_utils.migrations.coordinator.try_acquire_lock")
    @pytest.mark.asyncio
    async def test_recovery_migration_lock_failure(
        self,
        mock_acquire: AsyncMock,
        mock_wait: AsyncMock,
        mock_get_meta: AsyncMock,
        mock_get_version: MagicMock,
    ) -> None:
        """Test recovery failure when can't acquire lock."""
        from nohiki_db_utils.migrations.coordinator import _handle_lock_not_acquired

        conn = AsyncMock()
        ctx = LockContext("test-service", "pod-1", "postgresql://localhost/db", "alembic.ini")

        acquired_at = datetime.now(UTC)
        mock_get_meta.return_value = (acquired_at, "other-pod")
        # Current rev != head rev means other pod didn't complete
        mock_get_version.return_value = ("abc123", "def456")
        mock_acquire.return_value = False

        with pytest.raises(MigrationError, match="Failed to acquire lock"):
            await _handle_lock_not_acquired(conn, 12345, 30, ctx)

        mock_get_meta.assert_called_once()
        mock_wait.assert_called_once()
        mock_acquire.assert_called_once()


class TestRunAlembicUpgradeErrors:
    """Tests for _run_alembic_upgrade error paths."""

    @patch("nohiki_db_utils.migrations.executor.Path.exists")
    def test_config_not_found(self, mock_exists: MagicMock) -> None:
        """Test error when alembic config not found."""
        from nohiki_db_utils.migrations.executor import (
            run_alembic_upgrade as _run_alembic_upgrade,
        )

        mock_exists.return_value = False

        with pytest.raises(MigrationError, match="config not found"):
            _run_alembic_upgrade("/nonexistent/alembic.ini", "postgresql://localhost/db")

    @patch("nohiki_db_utils.migrations.executor.alembic_command.upgrade")
    @patch("nohiki_db_utils.migrations.executor.Config")
    @patch("nohiki_db_utils.migrations.executor.Path.exists")
    def test_alembic_command_error(
        self,
        mock_exists: MagicMock,
        mock_config: MagicMock,
        mock_upgrade: MagicMock,
    ) -> None:
        """Test CommandError handling in _run_alembic_upgrade."""
        from alembic.util.exc import CommandError
        from nohiki_db_utils.migrations.executor import (
            run_alembic_upgrade as _run_alembic_upgrade,
        )

        mock_exists.return_value = True
        mock_upgrade.side_effect = CommandError("Migration script error")

        with pytest.raises(MigrationError, match="CommandError"):
            _run_alembic_upgrade("alembic.ini", "postgresql://localhost/db")

    @patch("nohiki_db_utils.migrations.executor.alembic_command.upgrade")
    @patch("nohiki_db_utils.migrations.executor.Config")
    @patch("nohiki_db_utils.migrations.executor.Path.exists")
    def test_unexpected_error(
        self,
        mock_exists: MagicMock,
        mock_config: MagicMock,
        mock_upgrade: MagicMock,
    ) -> None:
        """Test unexpected error handling in _run_alembic_upgrade."""
        from nohiki_db_utils.migrations.executor import (
            run_alembic_upgrade as _run_alembic_upgrade,
        )

        mock_exists.return_value = True
        mock_upgrade.side_effect = RuntimeError("Unexpected failure")

        with pytest.raises(MigrationError, match="Unexpected error"):
            _run_alembic_upgrade("alembic.ini", "postgresql://localhost/db")

    @patch("nohiki_db_utils.migrations.executor.alembic_command.upgrade")
    @patch("nohiki_db_utils.migrations.executor.Config")
    @patch("nohiki_db_utils.migrations.executor.Path.exists")
    def test_sqlalchemy_error(
        self,
        mock_exists: MagicMock,
        mock_config: MagicMock,
        mock_upgrade: MagicMock,
    ) -> None:
        """Test SQLAlchemy error handling in _run_alembic_upgrade."""
        from nohiki_db_utils.migrations.executor import (
            run_alembic_upgrade as _run_alembic_upgrade,
        )
        from sqlalchemy.exc import SQLAlchemyError

        mock_exists.return_value = True
        mock_upgrade.side_effect = SQLAlchemyError("Database connection lost")

        with pytest.raises(MigrationError, match="SQLAlchemy error"):
            _run_alembic_upgrade("alembic.ini", "postgresql://localhost/db")


class TestExecuteMigrationsErrors:
    """Tests for _execute_migrations error paths."""

    @patch("nohiki_db_utils.migrations.executor.asyncio.wait_for")
    @patch("nohiki_db_utils.migrations.executor.asyncio.get_event_loop")
    @pytest.mark.asyncio
    async def test_execute_migration_error(self, mock_get_loop: MagicMock, mock_wait_for: AsyncMock) -> None:
        """Test error handling in _execute_migrations."""
        from nohiki_db_utils.migrations.coordinator import (
            execute_migrations as _execute_migrations,
        )

        mock_wait_for.side_effect = RuntimeError("Migration script failed")

        with pytest.raises(MigrationError, match="Migration failed"):
            await _execute_migrations("test-service", "postgresql://localhost/db", 30, "alembic.ini")


class TestGetCurrentRevisionFromConnection:
    """Tests for _get_current_revision_from_connection function."""

    @patch("nohiki_db_utils.migrations.version.MigrationContext")
    def test_without_version_table_schema(self, mock_context_class: MagicMock) -> None:
        """Test getting revision without schema specified."""
        from nohiki_db_utils.migrations.version import (
            get_current_revision_from_connection as _get_current_revision_from_connection,
        )

        mock_conn = MagicMock()
        mock_context = MagicMock()
        mock_context.get_current_revision.return_value = "abc123"
        mock_context_class.configure.return_value = mock_context

        result = _get_current_revision_from_connection(mock_conn, None)

        assert result == "abc123"
        mock_context_class.configure.assert_called_once_with(mock_conn)

    @patch("nohiki_db_utils.migrations.version.MigrationContext")
    def test_with_version_table_schema_exists(self, mock_context_class: MagicMock) -> None:
        """Test getting revision when schema exists."""
        from nohiki_db_utils.migrations.version import (
            get_current_revision_from_connection as _get_current_revision_from_connection,
        )

        mock_conn = MagicMock()
        mock_conn.execute.return_value.scalar.return_value = True  # schema exists
        mock_context = MagicMock()
        mock_context.get_current_revision.return_value = "def456"
        mock_context_class.configure.return_value = mock_context

        result = _get_current_revision_from_connection(mock_conn, "migrations")

        assert result == "def456"
        mock_context_class.configure.assert_called_once()

    @patch("nohiki_db_utils.migrations.version.MigrationContext")
    def test_with_version_table_schema_not_exists(self, mock_context_class: MagicMock) -> None:
        """Test getting revision when schema does not exist."""
        from nohiki_db_utils.migrations.version import (
            get_current_revision_from_connection as _get_current_revision_from_connection,
        )

        mock_conn = MagicMock()
        mock_conn.execute.return_value.scalar.return_value = False  # schema doesn't exist

        result = _get_current_revision_from_connection(mock_conn, "migrations")

        assert result is None
        mock_context_class.configure.assert_not_called()


class TestInitializeDatabase:
    """Tests for initialize_database function."""

    @patch("nohiki_db_utils.migrations.coordinator.run_migrations_with_coordination")
    @pytest.mark.asyncio
    async def test_migrate_on_startup_enabled(self, mock_run_migrations: AsyncMock) -> None:
        """Test initialize_database runs migrations when migrate_on_startup is True."""

        class MockSettings:
            service_name = "test-service"
            database = MagicMock()
            database.connection_string = "postgresql://localhost/db"
            database.migration_timeout_seconds = 120
            database.migrate_on_startup = True

        settings = MockSettings()

        await initialize_database(settings)

        mock_run_migrations.assert_called_once()

    @patch("nohiki_db_utils.migrations.coordinator.run_migrations_with_coordination")
    @pytest.mark.asyncio
    async def test_migrate_on_startup_disabled(self, mock_run_migrations: AsyncMock) -> None:
        """Test initialize_database skips migrations when migrate_on_startup is False."""

        class MockSettings:
            service_name = "test-service"
            database = MagicMock()
            database.connection_string = "postgresql://localhost/db"
            database.migration_timeout_seconds = 120
            database.migrate_on_startup = False

        settings = MockSettings()

        await initialize_database(settings)

        mock_run_migrations.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_database_config(self) -> None:
        """Test initialize_database raises error when database config is None."""
        from nohiki_db_utils.migrations import MigrationError

        class MockSettings:
            service_name = "test-service"
            database = None

        settings = MockSettings()

        with pytest.raises(MigrationError, match="Database configuration is required"):
            await initialize_database(settings)


class TestGetDbVersionInfo:
    """Tests for _get_db_version_info function."""

    @patch("nohiki_db_utils.migrations.version.get_current_revision_from_connection")
    @patch("nohiki_db_utils.migrations.version.create_engine")
    @patch("nohiki_db_utils.migrations.version.ScriptDirectory")
    @patch("nohiki_db_utils.migrations.executor.Config")
    def test_successful_version_retrieval(
        self,
        mock_config_cls: MagicMock,
        mock_script_dir: MagicMock,
        mock_create_engine: MagicMock,
        mock_get_rev: MagicMock,
    ) -> None:
        """Test successful retrieval of current and head revisions."""
        from nohiki_db_utils.migrations.version import (
            get_db_version_info as _get_db_version_info,
        )

        mock_cfg = MagicMock()
        mock_cfg.get_main_option.return_value = None
        mock_config_cls.return_value = mock_cfg

        mock_script = MagicMock()
        mock_script.get_current_head.return_value = "head123"
        mock_script_dir.from_config.return_value = mock_script

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_create_engine.return_value = mock_engine

        mock_get_rev.return_value = "abc123"

        result = _get_db_version_info("postgresql+psycopg://localhost/db", "alembic.ini")

        assert result == ("abc123", "head123")
        mock_engine.dispose.assert_called_once()

    @patch("nohiki_db_utils.migrations.version.create_engine")
    @patch("nohiki_db_utils.migrations.version.ScriptDirectory")
    @patch("nohiki_db_utils.migrations.executor.Config")
    @patch("nohiki_db_utils.migrations.lock.time.sleep")
    def test_transient_error_retry(
        self,
        mock_sleep: MagicMock,
        mock_config_cls: MagicMock,
        mock_script_dir: MagicMock,
        mock_create_engine: MagicMock,
    ) -> None:
        """Test retry on transient OperationalError."""
        from nohiki_db_utils.migrations.version import (
            get_db_version_info as _get_db_version_info,
        )

        mock_cfg = MagicMock()
        mock_cfg.get_main_option.return_value = None
        mock_config_cls.return_value = mock_cfg

        mock_script = MagicMock()
        mock_script.get_current_head.return_value = "head123"
        mock_script_dir.from_config.return_value = mock_script

        transient_err = OperationalError("connection", {}, Exception("connection refused"))

        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(side_effect=transient_err)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_create_engine.return_value = mock_engine

        with (
            patch(
                "nohiki_db_utils.migrations.version.is_transient_error",
                return_value=True,
            ),
            pytest.raises(MigrationError, match="Cannot connect to database"),
        ):
            _get_db_version_info(
                "postgresql+psycopg://localhost/db",
                "alembic.ini",
                max_retries=2,
                retry_delay=0.01,
            )

    @patch("nohiki_db_utils.migrations.version.create_engine")
    @patch("nohiki_db_utils.migrations.version.ScriptDirectory")
    @patch("nohiki_db_utils.migrations.executor.Config")
    def test_unexpected_error(
        self,
        mock_config_cls: MagicMock,
        mock_script_dir: MagicMock,
        mock_create_engine: MagicMock,
    ) -> None:
        """Test unexpected (non-OperationalError) raises MigrationError."""
        from nohiki_db_utils.migrations.version import (
            get_db_version_info as _get_db_version_info,
        )

        mock_cfg = MagicMock()
        mock_cfg.get_main_option.return_value = None
        mock_config_cls.return_value = mock_cfg

        mock_script = MagicMock()
        mock_script.get_current_head.return_value = "head123"
        mock_script_dir.from_config.return_value = mock_script

        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(side_effect=RuntimeError("unexpected"))
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_create_engine.return_value = mock_engine

        with pytest.raises(MigrationError, match="Failed to check DB version"):
            _get_db_version_info("postgresql+psycopg://localhost/db", "alembic.ini")


class TestRunMigrationsWithCoordinationFull:
    """Tests for run_migrations_with_coordination lock acquisition path."""

    @patch("nohiki_db_utils.migrations.coordinator.check_migration_needed")
    @patch("nohiki_db_utils.migrations.coordinator.set_migration_status")
    @patch("nohiki_db_utils.migrations.coordinator.create_async_engine_with_ssl")
    @patch("nohiki_db_utils.migrations.coordinator.ensure_lock_meta_table")
    @patch("nohiki_db_utils.migrations.coordinator.try_acquire_lock")
    @patch("nohiki_db_utils.migrations.coordinator._run_with_lock")
    @pytest.mark.asyncio
    async def test_lock_acquired_runs_migration(
        self,
        mock_run_with_lock: AsyncMock,
        mock_try_acquire: AsyncMock,
        mock_ensure_table: AsyncMock,
        mock_create_engine: MagicMock,
        mock_set_status: MagicMock,
        mock_check_needed: MagicMock,
    ) -> None:
        """Test full path when lock is acquired and migrations run."""
        mock_check_needed.return_value = (True, "head123")
        mock_try_acquire.return_value = True

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_cm.__aexit__.return_value = None
        mock_engine.connect.return_value = mock_cm
        mock_engine.dispose = AsyncMock()
        mock_create_engine.return_value = mock_engine

        await run_migrations_with_coordination(
            "test-service",
            database_url="postgresql://localhost/db",
            timeout_seconds=60,
        )

        mock_set_status.assert_any_call("in_progress", target_revision="head123")
        mock_run_with_lock.assert_called_once()

    @patch("nohiki_db_utils.migrations.coordinator.check_migration_needed")
    @patch("nohiki_db_utils.migrations.coordinator.set_migration_status")
    @patch("nohiki_db_utils.migrations.coordinator.create_async_engine_with_ssl")
    @patch("nohiki_db_utils.migrations.coordinator.ensure_lock_meta_table")
    @patch("nohiki_db_utils.migrations.coordinator.try_acquire_lock")
    @patch("nohiki_db_utils.migrations.coordinator._handle_lock_not_acquired")
    @pytest.mark.asyncio
    async def test_lock_not_acquired_delegates(
        self,
        mock_handle_not_acquired: AsyncMock,
        mock_try_acquire: AsyncMock,
        mock_ensure_table: AsyncMock,
        mock_create_engine: MagicMock,
        mock_set_status: MagicMock,
        mock_check_needed: MagicMock,
    ) -> None:
        """Test delegation when lock is not acquired."""
        mock_check_needed.return_value = (True, "head123")
        mock_try_acquire.return_value = False

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_cm.__aexit__.return_value = None
        mock_engine.connect.return_value = mock_cm
        mock_engine.dispose = AsyncMock()
        mock_create_engine.return_value = mock_engine

        await run_migrations_with_coordination(
            "test-service",
            database_url="postgresql://localhost/db",
            timeout_seconds=60,
        )

        mock_handle_not_acquired.assert_called_once()

    @patch("nohiki_db_utils.migrations.coordinator.check_migration_needed")
    @patch("nohiki_db_utils.migrations.coordinator.set_migration_status")
    @patch("nohiki_db_utils.migrations.coordinator.create_async_engine_with_ssl")
    @pytest.mark.asyncio
    async def test_sqlalchemy_error_wrapping(
        self,
        mock_create_engine: MagicMock,
        mock_set_status: MagicMock,
        mock_check_needed: MagicMock,
    ) -> None:
        """Test SQLAlchemyError is wrapped in MigrationError."""
        from sqlalchemy.exc import SQLAlchemyError

        mock_check_needed.return_value = (True, "head123")

        mock_engine = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.side_effect = SQLAlchemyError("db error")
        mock_cm.__aexit__.return_value = None
        mock_engine.connect.return_value = mock_cm
        mock_engine.dispose = AsyncMock()
        mock_create_engine.return_value = mock_engine

        with pytest.raises(MigrationError, match="Database error"):
            await run_migrations_with_coordination(
                "test-service",
                database_url="postgresql://localhost/db",
                timeout_seconds=60,
            )


class TestWaitForLockReleasePollLogging:
    """Tests for _wait_for_lock_release poll logging branch (line 752)."""

    @pytest.mark.asyncio
    async def test_logs_progress_every_10_polls(self) -> None:
        """Test that progress is logged every 10 polls before lock is released."""
        # Return False for 10 polls, then True on 11th
        acquire_results = [False] * 10 + [True]
        call_count = 0

        def mock_try_acquire(_conn: object, _lock_id: int) -> bool:
            nonlocal call_count
            result = acquire_results[call_count]
            call_count += 1
            return result

        mock_conn = AsyncMock()

        with (
            patch(
                "nohiki_db_utils.migrations.lock.try_acquire_lock",
                side_effect=mock_try_acquire,
            ),
            patch("nohiki_db_utils.migrations.lock.release_lock", new_callable=AsyncMock),
            patch("nohiki_db_utils.migrations.lock.asyncio.sleep", new_callable=AsyncMock),
            patch("nohiki_db_utils.migrations.lock.time.monotonic") as mock_monotonic,
        ):
            # Simulate time progression
            mock_monotonic.side_effect = [0.0] + [float(i) for i in range(1, 25)]

            await _wait_for_lock_release(mock_conn, 12345, 60, "test-service")

        assert call_count == 11


class TestExecuteMigrationsSuccess:
    """Tests for _execute_migrations success path (line 781)."""

    @patch("nohiki_db_utils.migrations.executor.run_alembic_upgrade")
    @pytest.mark.asyncio
    async def test_successful_execution(self, mock_alembic_upgrade: MagicMock) -> None:
        """Test successful migration execution logs completion."""
        from nohiki_db_utils.migrations.executor import (
            execute_migrations as _execute_migrations,
        )

        await _execute_migrations("test-service", "postgresql://localhost/db", 30, "alembic.ini")

        mock_alembic_upgrade.assert_called_once_with("alembic.ini", "postgresql://localhost/db")


class TestRunAlembicUpgradeSuccess:
    """Tests for _run_alembic_upgrade success path (line 832)."""

    @patch("nohiki_db_utils.migrations.executor.alembic_command")
    @patch("nohiki_db_utils.migrations.executor.Config")
    @patch("nohiki_db_utils.migrations.executor.Path")
    def test_successful_upgrade(
        self,
        mock_path: MagicMock,
        mock_config_cls: MagicMock,
        mock_alembic_cmd: MagicMock,
    ) -> None:
        """Test successful alembic upgrade to head."""
        from nohiki_db_utils.migrations.executor import (
            run_alembic_upgrade as _run_alembic_upgrade,
        )

        mock_path.return_value.exists.return_value = True

        mock_cfg = MagicMock()
        mock_config_cls.return_value = mock_cfg

        _run_alembic_upgrade("alembic.ini", "postgresql+psycopg://localhost/db")

        mock_alembic_cmd.upgrade.assert_called_once_with(mock_cfg, "head")
