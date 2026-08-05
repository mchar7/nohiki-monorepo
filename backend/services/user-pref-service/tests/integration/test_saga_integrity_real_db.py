"""Real PostgreSQL regressions for preference saga ownership and deadlines."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from nohiki.ml.v1 import EntityType
from nohiki.user.pref.v1 import PrefUpdateRequested
from nohiki_db_utils import OutboxWriter, SagaStatus
from nohiki_kafka_client import MessageContext, Topics, create_event_metadata
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from user_pref_service.core.config import get_manifest
from user_pref_service.core.embedding import PREF_EMBEDDING_SPEC, PrefEnrichmentSagaContext
from user_pref_service.core.saga_policy import WALL_CLOCK_CAP, NewEnrichmentSaga
from user_pref_service.db.models import PrefEnrichmentAction, SearchPref
from user_pref_service.events.callbacks import handle_embedding_callback
from user_pref_service.events.commands import handle_pref_update_requested
from user_pref_service.services import saga_service
from user_pref_service.services.saga_service import (
    create_enrichment_saga,
    dispatch_next_step,
    load_saga_for_update,
    record_retryable_error,
    sweep_due_enrichment_sagas,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]


async def _insert_profile(connection: AsyncConnection, *, user_id: UUID) -> UUID:
    pref_id = uuid4()
    await connection.execute(
        text(
            """
            INSERT INTO user_pref_schema.search_prefs (
                id, user_id, pref_name, search_keywords, work_arrangements,
                semantic_content_generation, semantic_content_hash
            ) VALUES (
                :pref_id, :user_id, 'Saga profile', ARRAY['python'],
                ARRAY['REMOTE']::user_pref_schema.work_arrangement_enum[], 1, :semantic_hash
            )
            """
        ),
        {"pref_id": pref_id, "user_id": user_id, "semantic_hash": "a" * 64},
    )
    return pref_id


async def _insert_saga(
    connection: AsyncConnection,
    *,
    pref_id: UUID,
    user_id: UUID,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
    action: str = "UPDATE",
) -> UUID:
    saga_id = uuid4()
    await connection.execute(
        text(
            """
            INSERT INTO user_pref_schema.pref_enrichment_saga (
                id, expected_callbacks, created_at, expires_at, pref_id, user_id,
                request_id, action, correlation_id, semantic_generation,
                semantic_hash, attempts_remaining
            ) VALUES (
                :saga_id, 1, :created_at, :expires_at, :pref_id, :user_id,
                :request_id, :action, :correlation_id, 1, :semantic_hash, 2
            )
            """
        ),
        {
            "saga_id": saga_id,
            "created_at": created_at or datetime.now(UTC),
            "expires_at": expires_at or datetime.now(UTC) + timedelta(minutes=2),
            "pref_id": pref_id,
            "user_id": user_id,
            "request_id": uuid4(),
            "action": action,
            "correlation_id": str(uuid4()),
            "semantic_hash": "a" * 64,
        },
    )
    return saga_id


@pytest.mark.asyncio
async def test_saga_action_rejects_unknown_domain_value(
    async_engine: AsyncEngine,
    setup_database_schema: None,
) -> None:
    """The baseline schema rejects actions that cannot map to lifecycle facts."""
    _ = setup_database_schema
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        pref_id = await _insert_profile(connection, user_id=(user_id := uuid4()))
        with pytest.raises(IntegrityError, match="pref_enrichment_saga_action_check"):
            await _insert_saga(
                connection,
                pref_id=pref_id,
                user_id=user_id,
                action="DELETE",
            )
        await transaction.rollback()


async def test_profile_delete_cascades_owned_saga(
    async_engine: AsyncEngine,
    setup_database_schema: None,
) -> None:
    """Deleting the owner cannot leave an orphaned sweeper row."""
    _ = setup_database_schema
    user_id = uuid4()
    async with async_engine.begin() as connection:
        pref_id = await _insert_profile(connection, user_id=user_id)
        saga_id = await _insert_saga(connection, pref_id=pref_id, user_id=user_id)
        await connection.execute(
            text("DELETE FROM user_pref_schema.search_prefs WHERE id = :pref_id"),
            {"pref_id": pref_id},
        )
        remaining = await connection.scalar(
            text("SELECT count(*) FROM user_pref_schema.pref_enrichment_saga WHERE id = :saga_id"),
            {"saga_id": saga_id},
        )

    assert remaining == 0


async def test_sweeper_selects_absolute_deadline_even_when_relative_expiry_is_future(
    async_engine: AsyncEngine,
    setup_database_schema: None,
) -> None:
    """A future retry timeout cannot hide a saga that exceeded its absolute cap."""
    _ = setup_database_schema
    user_id = uuid4()
    saga_id: UUID
    async with async_engine.begin() as connection:
        pref_id = await _insert_profile(connection, user_id=user_id)
        saga_id = await _insert_saga(
            connection,
            pref_id=pref_id,
            user_id=user_id,
            created_at=datetime.now(UTC) - WALL_CLOCK_CAP - timedelta(seconds=1),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        count = await sweep_due_enrichment_sagas(
            session,
            OutboxWriter(schema="user_pref_schema"),
        )

    async with async_engine.connect() as connection:
        status = await connection.scalar(
            text("SELECT status FROM user_pref_schema.pref_enrichment_saga WHERE id = :saga_id"),
            {"saga_id": saga_id},
        )

    assert count == 1
    assert status == SagaStatus.EXPIRED.value


async def test_dispatch_identity_and_outbound_record_become_visible_together(
    async_engine: AsyncEngine,
    setup_database_schema: None,
) -> None:
    """A concurrent observer cannot receive work without its durable identity."""
    _ = setup_database_schema
    user_id = uuid4()
    request_id = uuid4()
    async with async_engine.begin() as connection:
        pref_id = await _insert_profile(connection, user_id=user_id)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory() as owner:
        owner_transaction = await owner.begin()
        saga = await create_enrichment_saga(
            owner,
            NewEnrichmentSaga(
                pref_id=pref_id,
                user_id=user_id,
                request_id=request_id,
                correlation_id=str(request_id),
                action=PrefEnrichmentAction.UPDATE,
                raw_skills=[],
                semantic_generation=1,
                semantic_hash="a" * 64,
            ),
        )
        operation_id = await dispatch_next_step(
            owner,
            OutboxWriter(schema="user_pref_schema"),
            saga,
        )

        async with async_engine.connect() as observer:
            saga_before = await observer.scalar(
                text("SELECT count(*) FROM user_pref_schema.pref_enrichment_saga WHERE request_id = :request_id"),
                {"request_id": request_id},
            )
            outbound_before = await observer.scalar(
                text(
                    "SELECT count(*) FROM user_pref_schema.outbox WHERE aggregateid = :saga_id AND type = :event_type"
                ),
                {
                    "saga_id": str(saga.id),
                    "event_type": Topics.ML_EMBEDDING_REQUESTED,
                },
            )
            assert (saga_before, outbound_before) == (0, 0)

            await owner_transaction.commit()

            identity_after = await observer.scalar(
                text(
                    "SELECT last_dispatch_ids ->> 'embedding' "
                    "FROM user_pref_schema.pref_enrichment_saga "
                    "WHERE request_id = :request_id"
                ),
                {"request_id": request_id},
            )
            outbound_after = await observer.scalar(
                text(
                    "SELECT count(*) FROM user_pref_schema.outbox WHERE aggregateid = :saga_id AND type = :event_type"
                ),
                {
                    "saga_id": str(saga.id),
                    "event_type": Topics.ML_EMBEDDING_REQUESTED,
                },
            )

    assert identity_after == operation_id
    assert outbound_after == 1


async def test_concurrent_duplicate_callbacks_cannot_extend_absolute_deadline(
    async_engine: AsyncEngine,
    setup_database_schema: None,
) -> None:
    """Serialized duplicate callbacks remain bounded by the creation-time cap."""
    _ = setup_database_schema
    user_id = uuid4()
    created_at = datetime.now(UTC) - WALL_CLOCK_CAP + timedelta(seconds=5)
    original_deadline = datetime.now(UTC) + timedelta(minutes=1)
    async with async_engine.begin() as connection:
        pref_id = await _insert_profile(connection, user_id=user_id)
        saga_id = await _insert_saga(
            connection,
            pref_id=pref_id,
            user_id=user_id,
            created_at=created_at,
            expires_at=original_deadline,
        )

    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    first_locked = asyncio.Event()
    release_first = asyncio.Event()
    second_attempting = asyncio.Event()

    async def deliver_duplicate(name: str) -> None:
        async with session_factory.begin() as session:
            if name == "second":
                second_attempting.set()
            saga = await load_saga_for_update(session, saga_id)
            assert saga is not None
            if name == "first":
                first_locked.set()
                await release_first.wait()
            await record_retryable_error(
                session,
                saga,
                step="embedding",
                error_code="TEMPORARY",
                error_message="duplicate callback",
            )

    first = asyncio.create_task(deliver_duplicate("first"))
    await asyncio.wait_for(first_locked.wait(), timeout=5)
    second = asyncio.create_task(deliver_duplicate("second"))
    await asyncio.wait_for(second_attempting.wait(), timeout=5)
    await asyncio.sleep(0.05)
    assert not second.done()
    release_first.set()
    await asyncio.gather(first, second)

    async with async_engine.connect() as connection:
        expires_at = await connection.scalar(
            text("SELECT expires_at FROM user_pref_schema.pref_enrichment_saga WHERE id = :saga_id"),
            {"saga_id": saga_id},
        )

    assert expires_at == original_deadline


async def test_concurrent_updates_serialize_supersession_on_profile_owner(
    async_engine: AsyncEngine,
    setup_database_schema: None,
) -> None:
    """Two racing accepted updates leave exactly the newest saga pending."""
    _ = setup_database_schema
    user_id = uuid4()
    async with async_engine.begin() as connection:
        pref_id = await _insert_profile(connection, user_id=user_id)

    first_request_id = uuid4()
    second_request_id = uuid4()
    first_message = PrefUpdateRequested(
        metadata=create_event_metadata("test-service", str(first_request_id)),
        request_id=str(first_request_id),
        user_id=str(user_id),
        pref_id=str(pref_id),
        updated_fields=["pref_name"],
        pref_name="First racing update",
    )
    second_message = PrefUpdateRequested(
        metadata=create_event_metadata("test-service", str(second_request_id)),
        request_id=str(second_request_id),
        user_id=str(user_id),
        pref_id=str(pref_id),
        updated_fields=["pref_name"],
        pref_name="Second racing update",
    )

    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    first_cancel_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_cancel_entered = asyncio.Event()
    original_cancel = saga_service.cancel_pending_enrichment

    async def controlled_cancel(
        db: AsyncSession,
        outbox: OutboxWriter,
        profile: SearchPref,
        *,
        message: str,
    ) -> None:
        task = asyncio.current_task()
        if task is not None and task.get_name() == "first-profile-update":
            first_cancel_entered.set()
            await release_first.wait()
        elif task is not None and task.get_name() == "second-profile-update":
            second_cancel_entered.set()
        await original_cancel(db, outbox, profile, message=message)

    async def run_update(message: PrefUpdateRequested) -> None:
        async with session_factory.begin() as session:
            await handle_pref_update_requested(
                message,
                MessageContext(
                    topic="test.topic.v1",
                    partition=0,
                    offset=0,
                    timestamp=0,
                    headers={},
                    key=message.request_id,
                    db_session=session,
                    outbox=OutboxWriter(schema="user_pref_schema"),
                ),
            )

    with patch(
        "user_pref_service.events.commands.saga_service.cancel_pending_enrichment",
        side_effect=controlled_cancel,
    ):
        first = asyncio.create_task(run_update(first_message), name="first-profile-update")
        await asyncio.wait_for(first_cancel_entered.wait(), timeout=5)
        second = asyncio.create_task(run_update(second_message), name="second-profile-update")
        await asyncio.sleep(0.05)
        assert not second_cancel_entered.is_set()
        release_first.set()
        await asyncio.gather(first, second)
        assert second_cancel_entered.is_set()

    async with async_engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    SELECT request_id, status
                    FROM user_pref_schema.pref_enrichment_saga
                    WHERE pref_id = :pref_id
                    ORDER BY created_at, id
                    """
                ),
                {"pref_id": pref_id},
            )
        ).all()

    assert rows == [
        (first_request_id, SagaStatus.CANCELLED.value),
        (second_request_id, SagaStatus.PENDING.value),
    ]


async def test_concurrent_update_and_late_callback_follow_profile_then_saga_order(
    async_engine: AsyncEngine,
    setup_database_schema: None,
) -> None:
    """An update and late callback complete without preserving two current workflows."""
    _ = setup_database_schema
    user_id = uuid4()
    async with async_engine.begin() as connection:
        pref_id = await _insert_profile(connection, user_id=user_id)
        old_saga_id = await _insert_saga(connection, pref_id=pref_id, user_id=user_id)
        await connection.execute(
            text(
                """
                UPDATE user_pref_schema.pref_enrichment_saga
                SET last_dispatch_ids = '{"embedding": "old-operation"}'::jsonb
                WHERE id = :saga_id
                """
            ),
            {"saga_id": old_saga_id},
        )

    request_id = uuid4()
    update = PrefUpdateRequested(
        metadata=create_event_metadata("test-service", str(request_id)),
        request_id=str(request_id),
        user_id=str(user_id),
        pref_id=str(pref_id),
        updated_fields=["pref_name"],
        pref_name="Concurrent update wins",
    )
    callback = MagicMock()
    callback.callback.caller_context = PrefEnrichmentSagaContext(saga_id=str(old_saga_id)).to_bytes()
    callback.callback.operation_id = "old-operation"
    callback.error = None
    callback.success = MagicMock(
        collection_version=get_manifest().get_entity_version(EntityType.PROFILE),
        content_hash="a" * 64,
        embeddings=[MagicMock(embedding_type=embedding_type) for embedding_type in PREF_EMBEDDING_SPEC.requested_types],
    )

    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    callback_about_to_lock_profile = asyncio.Event()
    allow_callback_profile_lock = asyncio.Event()
    update_holds_profile = asyncio.Event()
    allow_update_cancel = asyncio.Event()
    original_profile_lock = saga_service.profile_service.get_profile_by_id_for_update
    original_cancel = saga_service.cancel_pending_enrichment

    async def coordinated_profile_lock(db: AsyncSession, lock_pref_id: UUID) -> SearchPref:
        task = asyncio.current_task()
        if task is not None and task.get_name() == "late-callback":
            callback_about_to_lock_profile.set()
            await allow_callback_profile_lock.wait()
        return await original_profile_lock(db, lock_pref_id)

    async def controlled_cancel(
        db: AsyncSession,
        outbox: OutboxWriter,
        profile: SearchPref,
        *,
        message: str,
    ) -> None:
        update_holds_profile.set()
        await allow_update_cancel.wait()
        await original_cancel(db, outbox, profile, message=message)

    async def run_callback() -> None:
        async with session_factory.begin() as session:
            await handle_embedding_callback(
                callback,
                MessageContext(
                    topic=Topics.USER_PREF_EMBEDDING_CALLBACK,
                    partition=0,
                    offset=0,
                    timestamp=0,
                    headers={},
                    key=str(old_saga_id),
                    db_session=session,
                    outbox=OutboxWriter(schema="user_pref_schema"),
                ),
            )

    async def run_update() -> None:
        async with session_factory.begin() as session:
            await handle_pref_update_requested(
                update,
                MessageContext(
                    topic=Topics.USER_PREF_UPDATE_REQUESTED,
                    partition=0,
                    offset=0,
                    timestamp=0,
                    headers={},
                    key=str(request_id),
                    db_session=session,
                    outbox=OutboxWriter(schema="user_pref_schema"),
                ),
            )

    with (
        patch(
            "user_pref_service.services.profile_service.get_profile_by_id_for_update",
            side_effect=coordinated_profile_lock,
        ),
        patch(
            "user_pref_service.events.commands.saga_service.cancel_pending_enrichment",
            side_effect=controlled_cancel,
        ),
    ):
        callback_task = asyncio.create_task(run_callback(), name="late-callback")
        await asyncio.wait_for(callback_about_to_lock_profile.wait(), timeout=5)
        update_task = asyncio.create_task(run_update(), name="profile-update")
        await asyncio.wait_for(update_holds_profile.wait(), timeout=5)
        allow_callback_profile_lock.set()
        allow_update_cancel.set()
        await asyncio.wait_for(asyncio.gather(update_task, callback_task), timeout=5)

    async with async_engine.connect() as connection:
        profile_state = (
            await connection.execute(
                text(
                    """
                    SELECT pref_name, semantic_content_generation, enrichment_terminal_status
                    FROM user_pref_schema.search_prefs
                    WHERE id = :pref_id
                    """
                ),
                {"pref_id": pref_id},
            )
        ).one()
        saga_states = (
            await connection.execute(
                text(
                    """
                    SELECT id, request_id, status
                    FROM user_pref_schema.pref_enrichment_saga
                    WHERE pref_id = :pref_id
                    """
                ),
                {"pref_id": pref_id},
            )
        ).all()

    assert profile_state == ("Concurrent update wins", 2, None)
    states_by_id = {saga_id: status for saga_id, _request_id, status in saga_states}
    pending = [
        (saga_id, saga_request_id)
        for saga_id, saga_request_id, status in saga_states
        if status == SagaStatus.PENDING.value
    ]
    assert states_by_id[old_saga_id] == SagaStatus.CANCELLED.value
    assert len(pending) == 1
    assert pending[0][1] == request_id
    assert len(saga_states) == 2
