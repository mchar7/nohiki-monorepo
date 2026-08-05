"""Tests for database seeding utilities."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_db_utils.seeding import (
    SeedContext,
    SeedingConfig,
    SeedingError,
    SeedingState,
    _acquire_lock_with_metadata,
    _clear_lock_metadata,
    _ensure_seed_tables,
    _execute_seeding,
    _get_lock_metadata,
    _get_seed_version,
    _handle_lock_not_acquired,
    _release_lock,
    _run_with_lock,
    _set_lock_metadata,
    _set_seed_version,
    _try_acquire_lock,
    _wait_for_lock_release,
)


class TestSeedingState:
    """Tests for SeedingState dataclass."""

    def test_default_values(self) -> None:
        """Test default values of SeedingState."""
        state = SeedingState()
        assert state.status == "not_started"
        assert state.error is None
        assert state.seed_name is None
        assert state.seed_version is None

    def test_is_healthy_completed(self) -> None:
        """Test is_healthy returns True for completed status."""
        state = SeedingState(status="completed")
        assert state.is_healthy() is True

    def test_is_healthy_skipped(self) -> None:
        """Test is_healthy returns True for skipped status."""
        state = SeedingState(status="skipped")
        assert state.is_healthy() is True

    def test_is_healthy_other_statuses(self) -> None:
        """Test is_healthy returns False for non-healthy statuses."""
        assert SeedingState(status="not_started").is_healthy() is False
        assert SeedingState(status="in_progress").is_healthy() is False
        assert SeedingState(status="failed").is_healthy() is False

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        state = SeedingState(
            status="completed",
            seed_name="test_seed",
            seed_version="1.0.0",
        )
        result = state.to_dict()

        assert result["status"] == "completed"
        assert result["healthy"] is True
        assert result["seed_name"] == "test_seed"
        assert result["seed_version"] == "1.0.0"


class TestSeedingError:
    """Tests for SeedingError exception."""

    def test_error_message(self) -> None:
        """Test SeedingError stores message."""
        error = SeedingError("seeding failed")
        assert str(error) == "seeding failed"
        assert error.message == "seeding failed"


class TestSeedingConfig:
    """Tests for SeedingConfig dataclass."""

    def test_creation(self) -> None:
        """Test SeedingConfig creation."""
        config = SeedingConfig(
            service_name="test-svc",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )
        assert config.service_name == "test-svc"
        assert config.database_url == "postgresql://localhost/db"
        assert config.seed_name == "test_seed"
        assert config.seed_version == "1.0.0"
        assert config.timeout_seconds == 60

    def test_default_timeout(self) -> None:
        """Test SeedingConfig default timeout."""
        config = SeedingConfig(
            service_name="test-svc",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
        )
        assert config.timeout_seconds == 120  # Default value


class TestSeedContext:
    """Tests for SeedContext dataclass."""

    def test_creation(self) -> None:
        """Test SeedContext creation."""
        ctx = SeedContext(
            service_name="test-svc",
            pod_id="pod-1",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )
        assert ctx.service_name == "test-svc"
        assert ctx.pod_id == "pod-1"


class TestLockOperations:
    """Tests for lock-related operations in seeding."""

    @pytest.mark.asyncio
    async def test_try_acquire_lock(self) -> None:
        """Test lock acquisition."""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = True
        mock_conn.execute.return_value = mock_result

        result = await _try_acquire_lock(mock_conn, 12345)

        assert result is True

    @pytest.mark.asyncio
    async def test_lock_metadata_is_published_before_contender_observes_lock(self) -> None:
        """A seed contender cannot lose the lock before holder metadata is committed."""
        guard = asyncio.Lock()
        holder_writing_metadata = asyncio.Event()
        allow_metadata_write = asyncio.Event()
        contender_tried_lock = asyncio.Event()
        metadata: dict[int, str] = {}
        holder_conn = AsyncMock()
        contender_conn = AsyncMock()
        holder_ctx = SeedContext("svc", "pod-1", "postgresql://db", "seed", "1", 30)
        contender_ctx = SeedContext("svc", "pod-2", "postgresql://db", "seed", "1", 30)

        async def acquire_guard(_conn: object, _lock_id: int) -> None:
            await guard.acquire()

        async def try_lock(conn: object, _lock_id: int) -> bool:
            if conn is contender_conn:
                contender_tried_lock.set()
                return False
            return True

        async def set_metadata(
            _conn: object,
            lock_id: int,
            holder_id: str,
            _seed_name: str,
        ) -> None:
            holder_writing_metadata.set()
            await allow_metadata_write.wait()
            metadata[lock_id] = holder_id

        async def get_metadata(
            _conn: object,
            lock_id: int,
        ) -> tuple[datetime, str, str] | None:
            holder_id = metadata.get(lock_id)
            return (datetime.now(UTC), holder_id, "seed") if holder_id else None

        async def commit() -> None:
            guard.release()

        holder_conn.commit.side_effect = commit
        contender_conn.commit.side_effect = commit

        with (
            patch("nohiki_db_utils.seeding._acquire_metadata_guard", side_effect=acquire_guard),
            patch("nohiki_db_utils.seeding._try_acquire_lock", side_effect=try_lock),
            patch("nohiki_db_utils.seeding._set_lock_metadata", side_effect=set_metadata),
            patch("nohiki_db_utils.seeding._get_lock_metadata", side_effect=get_metadata),
        ):
            holder = asyncio.create_task(_acquire_lock_with_metadata(holder_conn, 12345, holder_ctx))
            await holder_writing_metadata.wait()
            contender = asyncio.create_task(_acquire_lock_with_metadata(contender_conn, 12345, contender_ctx))
            await asyncio.sleep(0)

            assert not contender_tried_lock.is_set()
            assert metadata == {}

            allow_metadata_write.set()
            assert await holder == (True, None)
            contender_result = await contender
            assert contender_result[0] is False
            assert contender_result[1] is not None
            assert contender_result[1][1:] == ("pod-1", "seed")

        assert contender_tried_lock.is_set()
        assert metadata == {12345: "pod-1"}

    @pytest.mark.asyncio
    async def test_waiter_probe_cannot_be_observed_owning_the_lock_without_metadata(self) -> None:
        """A seed poll that momentarily takes the lock must stay invisible to a contender."""
        from nohiki_db_utils.seeding import _probe_lock_released

        guard = asyncio.Lock()
        held = False
        probe_owns_lock = asyncio.Event()
        allow_probe_release = asyncio.Event()
        contender_tried_lock = asyncio.Event()
        metadata: dict[int, str] = {}
        prober_conn = AsyncMock()
        contender_conn = AsyncMock()
        contender_ctx = SeedContext("svc", "pod-2", "postgresql://db", "seed", "1", 30)

        async def acquire_guard(_conn: object, _lock_id: int) -> None:
            await guard.acquire()

        async def try_lock(conn: object, _lock_id: int) -> bool:
            nonlocal held
            if conn is contender_conn:
                contender_tried_lock.set()
            if held:
                return False
            held = True
            return True

        async def release(conn: object, _lock_id: int) -> None:
            nonlocal held
            if conn is prober_conn:
                probe_owns_lock.set()
                await allow_probe_release.wait()
            held = False

        async def set_metadata(_conn: object, lock_id: int, holder_id: str, _seed_name: str) -> None:
            metadata[lock_id] = holder_id

        async def get_metadata(_conn: object, lock_id: int) -> tuple[datetime, str, str] | None:
            holder_id = metadata.get(lock_id)
            return (datetime.now(UTC), holder_id, "seed") if holder_id else None

        async def commit() -> None:
            guard.release()

        prober_conn.commit.side_effect = commit
        contender_conn.commit.side_effect = commit

        with (
            patch("nohiki_db_utils.seeding._acquire_metadata_guard", side_effect=acquire_guard),
            patch("nohiki_db_utils.seeding._try_acquire_lock", side_effect=try_lock),
            patch("nohiki_db_utils.seeding._release_lock", side_effect=release),
            patch("nohiki_db_utils.seeding._set_lock_metadata", side_effect=set_metadata),
            patch("nohiki_db_utils.seeding._get_lock_metadata", side_effect=get_metadata),
        ):
            prober = asyncio.create_task(_probe_lock_released(prober_conn, 12345))
            await probe_owns_lock.wait()
            contender = asyncio.create_task(_acquire_lock_with_metadata(contender_conn, 12345, contender_ctx))
            await asyncio.sleep(0)

            # The prober owns the advisory lock with no metadata row. A contender able to observe
            # this window would read (False, None) and raise "Seed lock metadata missing".
            assert not contender_tried_lock.is_set()

            allow_probe_release.set()
            assert await prober is True
            assert await contender == (True, None)

        assert metadata == {12345: "pod-2"}

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

        # Each poll issues the metadata guard, then the try, then the release.
        mock_guard = MagicMock()
        mock_result1 = MagicMock()
        mock_result1.scalar.return_value = False
        mock_result2 = MagicMock()
        mock_result2.scalar.return_value = True
        mock_result3 = MagicMock()  # For _release_lock call
        mock_conn.execute.side_effect = [mock_guard, mock_result1, mock_guard, mock_result2, mock_result3]

        ctx = SeedContext(
            service_name="test-svc",
            pod_id="pod-1",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=5,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await _wait_for_lock_release(mock_conn, 12345, 5, ctx)

    @pytest.mark.asyncio
    async def test_wait_for_lock_release_timeout(self) -> None:
        """Test that timeout is not rounded up to the polling interval."""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = False
        mock_conn.execute.return_value = mock_result

        ctx = SeedContext(
            service_name="test-svc",
            pod_id="pod-1",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=5,
        )

        started = time.monotonic()
        with pytest.raises(SeedingError, match="Timeout waiting"):
            await _wait_for_lock_release(mock_conn, 12345, 0.05, ctx)

        assert time.monotonic() - started < 0.2


class TestSeedVersionOperations:
    """Tests for seed version operations."""

    @pytest.mark.asyncio
    async def test_get_seed_version_found(self) -> None:
        """Test getting seed version when it exists."""
        mock_conn = AsyncMock()
        mock_row = MagicMock()
        mock_row.version = "1.0.0"
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_result

        result = await _get_seed_version(mock_conn, "test_seed")

        assert result == "1.0.0"

    @pytest.mark.asyncio
    async def test_get_seed_version_not_found(self) -> None:
        """Test getting seed version when it doesn't exist."""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        result = await _get_seed_version(mock_conn, "test_seed")

        assert result is None

    @pytest.mark.asyncio
    async def test_set_seed_version(self) -> None:
        """Test setting seed version."""
        mock_conn = AsyncMock()

        await _set_seed_version(mock_conn, "test_seed", "1.0.0", "pod-1")

        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()


class TestLockMetadataOperations:
    """Tests for lock metadata operations in seeding."""

    @pytest.mark.asyncio
    async def test_set_lock_metadata(self) -> None:
        """Test setting lock metadata."""
        mock_conn = AsyncMock()

        await _set_lock_metadata(mock_conn, 12345, "pod-1", "test_seed")

        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_lock_metadata_found(self) -> None:
        """Test getting lock metadata when it exists."""
        mock_conn = AsyncMock()
        mock_row = MagicMock()
        mock_row.acquired_at = datetime.now(UTC)
        mock_row.holder_id = "pod-1"
        mock_row.seed_name = "test_seed"
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_result

        result = await _get_lock_metadata(mock_conn, 12345)

        assert result is not None
        assert result[1] == "pod-1"
        assert result[2] == "test_seed"

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
        mock_conn.commit.assert_not_called()


class TestEnsureSeedTables:
    """Tests for _ensure_seed_tables."""

    @pytest.mark.asyncio
    async def test_creates_tables(self) -> None:
        """Test seed tables creation."""
        mock_conn = AsyncMock()

        await _ensure_seed_tables(mock_conn)

        assert mock_conn.execute.call_count == 2  # Two CREATE TABLE statements


class TestExecuteSeeding:
    """Tests for _execute_seeding function."""

    @pytest.mark.asyncio
    async def test_successful_seeding(self) -> None:
        """Test successful seed execution."""
        mock_conn = AsyncMock()
        mock_seed_func = AsyncMock()

        ctx = SeedContext(
            service_name="test-svc",
            pod_id="pod-1",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )

        await _execute_seeding(mock_conn, ctx, mock_seed_func)

        mock_seed_func.assert_called_once_with(mock_conn)

    @pytest.mark.asyncio
    async def test_seeding_timeout(self) -> None:
        """Test seeding timeout."""
        mock_conn = AsyncMock()
        mock_seed_func = AsyncMock(side_effect=TimeoutError())

        ctx = SeedContext(
            service_name="test-svc",
            pod_id="pod-1",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=1,
        )

        with pytest.raises(SeedingError, match="timed out"):
            await _execute_seeding(mock_conn, ctx, mock_seed_func)

    @pytest.mark.asyncio
    async def test_seeding_failure(self) -> None:
        """Test seeding failure."""
        mock_conn = AsyncMock()
        mock_seed_func = AsyncMock(side_effect=RuntimeError("seed failed"))

        ctx = SeedContext(
            service_name="test-svc",
            pod_id="pod-1",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )

        with pytest.raises(SeedingError, match="seed failed"):
            await _execute_seeding(mock_conn, ctx, mock_seed_func)


class TestRunWithLock:
    """Tests for _run_with_lock function."""

    @pytest.mark.asyncio
    @patch("nohiki_db_utils.seeding._execute_seeding")
    async def test_successful_run(self, mock_execute: AsyncMock) -> None:
        """Test successful seeding with lock."""
        mock_conn = AsyncMock()

        ctx = SeedContext(
            service_name="test-svc",
            pod_id="pod-1",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )

        mock_seed_func = AsyncMock()
        state = SeedingState()

        await _run_with_lock(mock_conn, 12345, ctx, mock_seed_func, state)

        assert state.status == "completed"
        mock_execute.assert_called_once()

    @pytest.mark.asyncio
    @patch("nohiki_db_utils.seeding._execute_seeding")
    async def test_run_with_lock_failure(self, mock_execute: AsyncMock) -> None:
        """Test seeding failure updates state correctly."""
        mock_conn = AsyncMock()

        ctx = SeedContext(
            service_name="test-svc",
            pod_id="pod-1",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )

        mock_seed_func = AsyncMock()
        state = SeedingState()

        mock_execute.side_effect = SeedingError("seed failed")

        with pytest.raises(SeedingError, match="seed failed"):
            await _run_with_lock(mock_conn, 12345, ctx, mock_seed_func, state)

        assert state.status == "failed"
        assert state.error == "seed failed"
        assert state.completed_at is not None


class TestHandleLockNotAcquiredSeeding:
    """Tests for _handle_lock_not_acquired function in seeding."""

    @patch("nohiki_db_utils.seeding._get_seed_version")
    @patch("nohiki_db_utils.seeding._wait_for_lock_release")
    @pytest.mark.asyncio
    async def test_handle_lock_not_acquired_with_metadata(
        self,
        mock_wait: AsyncMock,
        mock_get_version: AsyncMock,
    ) -> None:
        """Test handling lock not acquired with existing metadata."""
        mock_conn = AsyncMock()
        ctx = SeedContext(
            service_name="test-svc",
            pod_id="pod-1",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )
        state = SeedingState()

        acquired_at = datetime.now(UTC)
        mock_get_version.return_value = "1.0.0"  # Same version = skipped

        await _handle_lock_not_acquired(
            mock_conn,
            12345,
            ctx,
            state,
            (acquired_at, "other-pod", "test_seed"),
        )

        mock_wait.assert_called_once()
        assert state.status == "skipped"

    @patch("nohiki_db_utils.seeding._get_seed_version")
    @patch("nohiki_db_utils.seeding._wait_for_lock_release")
    @pytest.mark.asyncio
    async def test_missing_metadata_raises_without_waiting(
        self,
        mock_wait: AsyncMock,
        mock_get_version: AsyncMock,
    ) -> None:
        """A held seed lock with no metadata row is impossible under the guard, so it is an error."""
        mock_conn = AsyncMock()
        ctx = SeedContext(
            service_name="test-svc",
            pod_id="pod-1",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )
        state = SeedingState()

        with pytest.raises(SeedingError, match="Seed lock metadata missing"):
            await _handle_lock_not_acquired(mock_conn, 12345, ctx, state, None)

        mock_wait.assert_not_called()
        mock_get_version.assert_not_called()

    @patch("nohiki_db_utils.seeding._get_seed_version")
    @patch("nohiki_db_utils.seeding._wait_for_lock_release")
    @pytest.mark.asyncio
    async def test_handle_lock_not_acquired_version_mismatch(
        self,
        mock_wait: AsyncMock,
        mock_get_version: AsyncMock,
    ) -> None:
        """Test version mismatch after lock release raises error."""
        mock_conn = AsyncMock()
        ctx = SeedContext(
            service_name="test-svc",
            pod_id="pod-1",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )
        state = SeedingState()

        acquired_at = datetime.now(UTC)
        mock_get_version.return_value = "0.9.0"  # Different version = error

        with pytest.raises(SeedingError, match="version mismatch"):
            await _handle_lock_not_acquired(
                mock_conn,
                12345,
                ctx,
                state,
                (acquired_at, "other-pod", "test_seed"),
            )

        mock_wait.assert_called_once()
        assert state.status == "failed"
        assert state.error is not None
        assert "version mismatch" in state.error

    @patch("nohiki_db_utils.seeding._get_seed_version")
    @patch("nohiki_db_utils.seeding._wait_for_lock_release")
    @pytest.mark.asyncio
    async def test_handle_lock_not_acquired_stale_lock(
        self,
        mock_wait: AsyncMock,
        mock_get_version: AsyncMock,
    ) -> None:
        """Test stale lock detection when age exceeds timeout (line 421)."""
        mock_conn = AsyncMock()
        ctx = SeedContext(
            service_name="test-svc",
            pod_id="pod-1",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )
        state = SeedingState()

        from datetime import timedelta

        acquired_at = datetime.now(UTC) - timedelta(seconds=120)
        mock_get_version.return_value = "1.0.0"  # Version matches after wait

        await _handle_lock_not_acquired(
            mock_conn,
            12345,
            ctx,
            state,
            (acquired_at, "other-pod", "test_seed"),
        )

        assert state.status == "skipped"
        mock_wait.assert_called_once()


class TestWaitForLockReleaseSeeding:
    """Tests for _wait_for_lock_release poll logging (line 291)."""

    @pytest.mark.asyncio
    async def test_logs_progress_every_10_polls(self) -> None:
        """Test that progress is logged every 10 polls before lock is released."""
        acquire_results = [False] * 10 + [True]
        call_count = 0

        def mock_try_acquire(_conn: AsyncMock, _lock_id: int) -> bool:
            nonlocal call_count
            result = acquire_results[call_count]
            call_count += 1
            return result

        mock_conn = AsyncMock()
        ctx = SeedContext(
            service_name="test-svc",
            pod_id="pod-1",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )

        with (
            patch(
                "nohiki_db_utils.seeding._try_acquire_lock",
                side_effect=mock_try_acquire,
            ),
            patch("nohiki_db_utils.seeding._release_lock", new_callable=AsyncMock),
            patch("nohiki_db_utils.seeding.asyncio.sleep", new_callable=AsyncMock),
            patch("nohiki_db_utils.seeding.time.monotonic") as mock_monotonic,
        ):
            mock_monotonic.side_effect = [0.0] + [float(i) for i in range(1, 25)]
            await _wait_for_lock_release(mock_conn, 12345, 60, ctx)

        assert call_count == 11


class TestRunSeedingWithCoordinationFull:
    """Tests for run_seeding_with_coordination full path (lines 523-626)."""

    @patch("nohiki_db_utils.seeding.create_async_engine_with_ssl")
    @patch("nohiki_db_utils.seeding._ensure_seed_tables")
    @patch("nohiki_db_utils.seeding._get_seed_version")
    @pytest.mark.asyncio
    async def test_seed_already_up_to_date(
        self,
        mock_get_version: AsyncMock,
        mock_ensure_tables: AsyncMock,
        mock_create_engine: MagicMock,
    ) -> None:
        """Test early return when seed is already at target version."""
        from nohiki_db_utils.seeding import run_seeding_with_coordination

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_cm.__aexit__.return_value = None
        mock_engine.connect.return_value = mock_cm
        mock_engine.dispose = AsyncMock()
        mock_create_engine.return_value = mock_engine

        mock_get_version.return_value = "1.0.0"

        config = SeedingConfig(
            service_name="test-svc",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )

        mock_seed_func = AsyncMock()
        state = await run_seeding_with_coordination(config, mock_seed_func)

        assert state.status == "skipped"
        mock_seed_func.assert_not_called()

    @patch("nohiki_db_utils.seeding.create_async_engine_with_ssl")
    @patch("nohiki_db_utils.seeding._ensure_seed_tables")
    @patch("nohiki_db_utils.seeding._get_seed_version")
    @patch("nohiki_db_utils.seeding._acquire_lock_with_metadata")
    @patch("nohiki_db_utils.seeding._run_with_lock")
    @pytest.mark.asyncio
    async def test_seed_requires_update_lock_acquired(
        self,
        mock_run_with_lock: AsyncMock,
        mock_acquire: AsyncMock,
        mock_get_version: AsyncMock,
        mock_ensure_tables: AsyncMock,
        mock_create_engine: MagicMock,
    ) -> None:
        """Test seed update path when current version differs and lock acquired."""
        from nohiki_db_utils.seeding import run_seeding_with_coordination

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_cm.__aexit__.return_value = None
        mock_engine.connect.return_value = mock_cm
        mock_engine.dispose = AsyncMock()
        mock_create_engine.return_value = mock_engine

        mock_get_version.return_value = "0.9.0"
        mock_acquire.return_value = (True, None)

        config = SeedingConfig(
            service_name="test-svc",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )

        mock_seed_func = AsyncMock()
        await run_seeding_with_coordination(config, mock_seed_func)

        mock_run_with_lock.assert_called_once()

    @patch("nohiki_db_utils.seeding.create_async_engine_with_ssl")
    @patch("nohiki_db_utils.seeding._ensure_seed_tables")
    @patch("nohiki_db_utils.seeding._get_seed_version")
    @patch("nohiki_db_utils.seeding._acquire_lock_with_metadata")
    @patch("nohiki_db_utils.seeding._run_with_lock")
    @pytest.mark.asyncio
    async def test_seed_not_yet_applied_lock_acquired(
        self,
        mock_run_with_lock: AsyncMock,
        mock_acquire: AsyncMock,
        mock_get_version: AsyncMock,
        mock_ensure_tables: AsyncMock,
        mock_create_engine: MagicMock,
    ) -> None:
        """Test seeding when no previous version exists and lock acquired."""
        from nohiki_db_utils.seeding import run_seeding_with_coordination

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_cm.__aexit__.return_value = None
        mock_engine.connect.return_value = mock_cm
        mock_engine.dispose = AsyncMock()
        mock_create_engine.return_value = mock_engine

        mock_get_version.return_value = None
        mock_acquire.return_value = (True, None)

        config = SeedingConfig(
            service_name="test-svc",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )

        mock_seed_func = AsyncMock()
        await run_seeding_with_coordination(config, mock_seed_func)

        mock_run_with_lock.assert_called_once()

    @patch("nohiki_db_utils.seeding.create_async_engine_with_ssl")
    @patch("nohiki_db_utils.seeding._ensure_seed_tables")
    @patch("nohiki_db_utils.seeding._get_seed_version")
    @patch("nohiki_db_utils.seeding._acquire_lock_with_metadata")
    @patch("nohiki_db_utils.seeding._handle_lock_not_acquired")
    @pytest.mark.asyncio
    async def test_lock_not_acquired_delegates(
        self,
        mock_handle_not_acquired: AsyncMock,
        mock_acquire: AsyncMock,
        mock_get_version: AsyncMock,
        mock_ensure_tables: AsyncMock,
        mock_create_engine: MagicMock,
    ) -> None:
        """Test delegation when lock is not acquired."""
        from nohiki_db_utils.seeding import run_seeding_with_coordination

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_cm.__aexit__.return_value = None
        mock_engine.connect.return_value = mock_cm
        mock_engine.dispose = AsyncMock()
        mock_create_engine.return_value = mock_engine

        mock_get_version.return_value = "0.9.0"
        mock_acquire.return_value = (False, (datetime.now(UTC), "other-pod", "test_seed"))

        config = SeedingConfig(
            service_name="test-svc",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )

        mock_seed_func = AsyncMock()
        await run_seeding_with_coordination(config, mock_seed_func)

        mock_handle_not_acquired.assert_called_once()

    @patch("nohiki_db_utils.seeding.create_async_engine_with_ssl")
    @patch("nohiki_db_utils.seeding._ensure_seed_tables")
    @patch("nohiki_db_utils.seeding._get_seed_version")
    @pytest.mark.asyncio
    async def test_sqlalchemy_error_wrapping(
        self,
        mock_get_version: AsyncMock,
        mock_ensure_tables: AsyncMock,
        mock_create_engine: MagicMock,
    ) -> None:
        """Test SQLAlchemyError is wrapped in SeedingError."""
        from nohiki_db_utils.seeding import run_seeding_with_coordination
        from sqlalchemy.exc import SQLAlchemyError

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_cm.__aexit__.return_value = None
        mock_engine.connect.return_value = mock_cm
        mock_engine.dispose = AsyncMock()
        mock_create_engine.return_value = mock_engine

        mock_get_version.return_value = "0.9.0"

        config = SeedingConfig(
            service_name="test-svc",
            database_url="postgresql://localhost/db",
            seed_name="test_seed",
            seed_version="1.0.0",
            timeout_seconds=60,
        )

        mock_seed_func = AsyncMock()

        with (
            patch(
                "nohiki_db_utils.seeding._try_acquire_lock",
                new_callable=AsyncMock,
                side_effect=SQLAlchemyError("db error"),
            ),
            pytest.raises(SeedingError, match="Database error"),
        ):
            await run_seeding_with_coordination(config, mock_seed_func)
