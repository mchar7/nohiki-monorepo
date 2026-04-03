"""Unit tests for nohiki_db_utils.saga.repository and stale modules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from nohiki_db_utils.saga.models import SagaBaseMixin, SagaStatus
from nohiki_db_utils.saga.repository import SagaRepository
from nohiki_db_utils.saga.stale import StaleSagaDetector
from nohiki_db_utils.state_machine import InvalidTransitionError
from sqlalchemy import String
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

_SAGA_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


class SagaTestBase(DeclarativeBase):
    """Test-only declarative base."""


class ConcreteTestSaga(SagaBaseMixin, SagaTestBase):
    """Concrete saga model for repository tests."""

    __tablename__ = "concrete_test_saga_repo"
    listing_id: Mapped[str] = mapped_column(String(36), nullable=False, default="test")


class FakeSaga(SagaBaseMixin, SagaTestBase):
    """Lightweight saga for in-memory repository operation tests."""

    __tablename__ = "fake_saga"
    __status_field__: ClassVar[str] = "status"
    __transitions__: ClassVar[dict[str, frozenset[str]]] = {
        "PENDING": frozenset({"COMPLETED", "FAILED", "EXPIRED"}),
        "COMPLETED": frozenset(),
        "FAILED": frozenset(),
        "EXPIRED": frozenset(),
    }

    def __init__(
        self,
        *,
        status: SagaStatus = SagaStatus.PENDING,
        expected_callbacks: int = 2,
        received_callbacks: int = 0,
        saga_id: UUID = _SAGA_ID,
        version: int = 1,
    ) -> None:
        """Initialise fake saga."""
        self.id = saga_id
        self.status = status
        self.expected_callbacks = expected_callbacks
        self.received_callbacks = received_callbacks
        self.version = version
        self.expires_at = datetime.now(UTC) + timedelta(minutes=30)

    @property
    def is_complete(self) -> bool:
        """Mirror SagaBaseMixin.is_complete."""
        return self.received_callbacks >= self.expected_callbacks


_REPO: SagaRepository[ConcreteTestSaga] = SagaRepository(ConcreteTestSaga)
_FAKE_REPO: SagaRepository[FakeSaga] = SagaRepository(FakeSaga)


def _scalar(value: object) -> MagicMock:
    m = MagicMock()
    m.scalar_one_or_none.return_value = value
    return m


def _scalars_all(items: list[object]) -> MagicMock:
    sc = MagicMock()
    sc.all.return_value = items
    m = MagicMock()
    m.scalars.return_value = sc
    return m


def _mock_db(side_effects: list[MagicMock] | None = None) -> MagicMock:
    db = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effects) if side_effects is not None else AsyncMock()
    db.scalars = AsyncMock()
    return db


class TestCreate:
    """Tests for SagaRepository.create."""

    @pytest.mark.anyio
    async def test_adds_flushes_refreshes_returns(self) -> None:
        """Create adds saga, flushes, refreshes, returns saga."""
        saga = FakeSaga()
        db = _mock_db()
        result = await _FAKE_REPO.create(db, saga)
        db.add.assert_called_once_with(saga)
        db.flush.assert_awaited_once()
        db.refresh.assert_awaited_once_with(saga)
        assert result is saga


class TestLoad:
    """Tests for SagaRepository.load."""

    @pytest.mark.anyio
    async def test_returns_saga_when_found(self) -> None:
        """Load returns the saga when it exists."""
        saga = FakeSaga()
        db = _mock_db(side_effects=[_scalar(saga)])
        result = await _FAKE_REPO.load(db, _SAGA_ID)
        assert result is saga

    @pytest.mark.anyio
    async def test_returns_none_when_not_found(self) -> None:
        """Load returns None for missing saga."""
        db = _mock_db(side_effects=[_scalar(None)])
        assert await _FAKE_REPO.load(db, _SAGA_ID) is None


class TestRecordCallback:
    """Tests for SagaRepository.record_callback."""

    @pytest.mark.anyio
    async def test_increments_received_and_version(self) -> None:
        """record_callback increments received_callbacks and version."""
        saga = FakeSaga(expected_callbacks=2, received_callbacks=0, version=1)
        db = _mock_db(side_effects=[_scalar(saga), _scalar(saga.id)])

        _, _ = await _FAKE_REPO.record_callback(db, _SAGA_ID, update_fn=lambda _: None)

        assert saga.received_callbacks == 1
        assert saga.version == 2

    @pytest.mark.anyio
    async def test_returns_is_complete_false_when_pending(self) -> None:
        """Returns (saga, False) when not all callbacks received."""
        saga = FakeSaga(expected_callbacks=2, received_callbacks=0)
        db = _mock_db(side_effects=[_scalar(saga), _scalar(saga.id)])

        _, is_complete = await _FAKE_REPO.record_callback(db, _SAGA_ID, update_fn=lambda _: None)

        assert is_complete is False

    @pytest.mark.anyio
    async def test_returns_is_complete_true_when_all_received(self) -> None:
        """Returns (saga, True) when all callbacks received."""
        saga = FakeSaga(expected_callbacks=2, received_callbacks=1)
        db = _mock_db(side_effects=[_scalar(saga), _scalar(saga.id)])

        _, is_complete = await _FAKE_REPO.record_callback(db, _SAGA_ID, update_fn=lambda _: None)

        assert is_complete is True

    @pytest.mark.anyio
    async def test_applies_update_fn(self) -> None:
        """record_callback calls update_fn with the saga."""
        saga = FakeSaga()
        db = _mock_db(side_effects=[_scalar(saga), _scalar(saga.id)])
        called_with: list[object] = []

        await _FAKE_REPO.record_callback(db, _SAGA_ID, update_fn=called_with.append)

        assert len(called_with) == 1
        assert called_with[0] is saga

    @pytest.mark.anyio
    async def test_raises_when_saga_not_found(self) -> None:
        """record_callback raises NoResultFound when saga does not exist."""
        db = _mock_db(side_effects=[_scalar(None)])

        with pytest.raises(NoResultFound):
            await _FAKE_REPO.record_callback(db, _SAGA_ID, update_fn=lambda _: None)

    @pytest.mark.anyio
    async def test_raises_when_not_pending(self) -> None:
        """record_callback raises InvalidTransitionError when not PENDING."""
        saga = FakeSaga(status=SagaStatus.COMPLETED)
        db = _mock_db(side_effects=[_scalar(saga)])

        with pytest.raises(InvalidTransitionError):
            await _FAKE_REPO.record_callback(db, _SAGA_ID, update_fn=lambda _: None)


class TestComplete:
    """Tests for SagaRepository.complete."""

    @pytest.mark.anyio
    async def test_transitions_to_completed(self) -> None:
        """Complete transitions saga to COMPLETED."""
        saga = FakeSaga(status=SagaStatus.PENDING, received_callbacks=2)
        db = _mock_db()
        mock_outbox = AsyncMock()
        mock_params = MagicMock()
        mock_event = MagicMock()

        await _FAKE_REPO.complete(
            db,
            saga,
            outbox_writer=mock_outbox,
            outbox_params=mock_params,
            outbox_event=mock_event,
        )

        assert saga.status == SagaStatus.COMPLETED
        mock_outbox.write_event.assert_awaited_once()
        db.flush.assert_awaited_once()

    @pytest.mark.anyio
    async def test_rejects_completion_before_all_callbacks_arrive(self) -> None:
        """Incomplete sagas remain pending and emit no completion event."""
        saga = FakeSaga(status=SagaStatus.PENDING, expected_callbacks=2, received_callbacks=1)
        db = _mock_db()
        mock_outbox = AsyncMock()

        with pytest.raises(InvalidTransitionError, match=r"1/2 callbacks"):
            await _FAKE_REPO.complete(
                db,
                saga,
                outbox_writer=mock_outbox,
                outbox_params=MagicMock(),
                outbox_event=MagicMock(),
            )

        assert saga.status == SagaStatus.PENDING
        mock_outbox.write_event.assert_not_awaited()
        db.flush.assert_not_awaited()

    @pytest.mark.anyio
    async def test_raises_when_not_pending(self) -> None:
        """Complete raises InvalidTransitionError when saga is already completed."""
        saga = FakeSaga(status=SagaStatus.COMPLETED)
        db = _mock_db()

        with pytest.raises(InvalidTransitionError):
            await _FAKE_REPO.complete(
                db,
                saga,
                outbox_writer=AsyncMock(),
                outbox_params=MagicMock(),
                outbox_event=MagicMock(),
            )


class TestFail:
    """Tests for SagaRepository.fail."""

    @pytest.mark.anyio
    async def test_transitions_to_failed(self) -> None:
        """Fail transitions saga to FAILED."""
        saga = FakeSaga(status=SagaStatus.PENDING)
        db = _mock_db(side_effects=[_scalar(saga)])

        await _FAKE_REPO.fail(db, _SAGA_ID, reason="test failure")

        assert saga.status == SagaStatus.FAILED
        db.flush.assert_awaited_once()

    @pytest.mark.anyio
    async def test_raises_when_saga_not_found(self) -> None:
        """Fail raises NoResultFound when saga does not exist."""
        db = _mock_db(side_effects=[_scalar(None)])

        with pytest.raises(NoResultFound):
            await _FAKE_REPO.fail(db, _SAGA_ID, reason="not found")


class TestFindStale:
    """Tests for SagaRepository.find_stale."""

    @pytest.mark.anyio
    async def test_returns_stale_sagas(self) -> None:
        """find_stale returns all PENDING sagas past the cutoff."""
        saga1 = FakeSaga()
        saga2 = FakeSaga()
        db = _mock_db(side_effects=[_scalars_all([saga1, saga2])])

        cutoff = datetime.now(UTC)
        results = await _FAKE_REPO.find_stale(db, cutoff=cutoff)

        assert list(results) == [saga1, saga2]

    @pytest.mark.anyio
    async def test_locks_a_bounded_deterministic_stale_batch(self) -> None:
        """Concurrent sweepers claim at most the oldest requested rows without blocking."""
        db = _mock_db(side_effects=[_scalars_all([])])

        await _FAKE_REPO.find_stale(
            db,
            cutoff=datetime(2026, 1, 2, tzinfo=UTC),
            limit=7,
        )

        statement = db.execute.await_args.args[0]
        sql = " ".join(
            str(
                statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            ).split()
        )
        assert "ORDER BY fake_saga.expires_at, fake_saga.id" in sql
        assert "LIMIT 7 FOR UPDATE SKIP LOCKED" in sql

    @pytest.mark.anyio
    async def test_returns_empty_when_none_stale(self) -> None:
        """find_stale returns empty list when no stale sagas."""
        db = _mock_db(side_effects=[_scalars_all([])])

        results = await _FAKE_REPO.find_stale(db, cutoff=datetime.now(UTC))

        assert list(results) == []


class TestExpireStale:
    """Tests for SagaRepository.expire_stale."""

    @pytest.mark.anyio
    async def test_expires_stale_sagas(self) -> None:
        """expire_stale transitions all stale sagas to EXPIRED and returns count."""
        saga1 = FakeSaga()
        saga2 = FakeSaga()
        db = _mock_db(side_effects=[_scalars_all([saga1, saga2])])

        count = await _FAKE_REPO.expire_stale(db, max_age=timedelta(minutes=30))

        assert count == 2
        assert saga1.status == SagaStatus.EXPIRED
        assert saga2.status == SagaStatus.EXPIRED
        db.flush.assert_awaited_once()

    @pytest.mark.anyio
    async def test_returns_zero_when_no_stale(self) -> None:
        """expire_stale returns 0 and does not flush when nothing expired."""
        db = _mock_db(side_effects=[_scalars_all([])])

        count = await _FAKE_REPO.expire_stale(db, max_age=timedelta(minutes=30))

        assert count == 0
        db.flush.assert_not_awaited()


class TestStaleSagaDetector:
    """Tests for StaleSagaDetector."""

    def test_init_sets_max_age(self) -> None:
        """StaleSagaDetector stores model class and max_age."""
        detector = StaleSagaDetector(ConcreteTestSaga, max_age=timedelta(hours=1))
        assert detector._max_age == timedelta(hours=1)
        assert detector._model_name == "ConcreteTestSaga"

    def test_default_max_age(self) -> None:
        """Default max_age is 30 minutes."""
        detector = StaleSagaDetector(ConcreteTestSaga)
        assert detector._max_age == timedelta(minutes=30)

    @pytest.mark.anyio
    async def test_run_returns_expired_count(self) -> None:
        """Run delegates to repo.expire_stale and returns count."""
        detector = StaleSagaDetector(ConcreteTestSaga, max_age=timedelta(minutes=15))
        db = _mock_db(side_effects=[_scalars_all([])])

        count = await detector.run(db)

        assert count == 0

    @pytest.mark.anyio
    async def test_run_returns_count_when_expired(self) -> None:
        """Run logs warning and returns count when sagas are expired."""
        detector = StaleSagaDetector(ConcreteTestSaga, max_age=timedelta(minutes=5))
        saga = FakeSaga()
        db = _mock_db(side_effects=[_scalars_all([saga])])

        count = await detector.run(db)

        assert count == 1
        assert saga.status == SagaStatus.EXPIRED
