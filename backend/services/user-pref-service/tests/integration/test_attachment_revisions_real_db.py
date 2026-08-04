"""PostgreSQL integration tests for authoritative attachment revisions."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from nohiki.common.v1 import WorkArrangement
from nohiki_fastapi_utils.errors import NotFoundError
from sqlalchemy import event
from user_pref_service.db.models import SearchPref, SearchPrefUpload
from user_pref_service.services.profile_service import (
    associate_attachment,
    build_profile_snapshot,
    disassociate_attachment,
    get_profile_by_id,
    get_profiles_by_ids,
    remove_attachment_from_all_profiles,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


_INITIAL_REVISION = datetime(2099, 1, 1, tzinfo=UTC)


async def _create_profile(
    session: AsyncSession,
    *,
    revision: datetime = _INITIAL_REVISION,
) -> SearchPref:
    profile = SearchPref(
        id=uuid4(),
        user_id=uuid4(),
        pref_name="Attachment revision profile",
        search_keywords=["python"],
        work_arrangements=[WorkArrangement.REMOTE],
        created_at=revision,
        updated_at=revision,
    )
    session.add(profile)
    await session.flush()
    return profile


@pytest.mark.integration
@pytest.mark.requires_docker
class TestAttachmentRevisionLifecycle:
    """Real PostgreSQL coverage for attachment-driven ECST revisions."""

    @pytest.mark.asyncio
    async def test_attach_type_change_and_detach_advance_but_duplicate_does_not(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
    ) -> None:
        """Every real relationship mutation advances the snapshot revision exactly once."""
        _ = setup_database_schema
        profile = await _create_profile(async_session)
        upload_id = uuid4()

        attached = await associate_attachment(async_session, profile.id, upload_id, "example")
        assert attached.upload_type == "example"
        after_attach = await get_profile_by_id(async_session, profile.id)
        attach_revision = after_attach.updated_at
        assert attach_revision > _INITIAL_REVISION
        attach_snapshot = build_profile_snapshot(after_attach)
        assert attach_snapshot.timestamps is not None
        assert attach_snapshot.timestamps.updated_at == attach_revision
        assert [reference.id for reference in attach_snapshot.example_uploads] == [str(upload_id)]

        duplicate = await associate_attachment(async_session, profile.id, upload_id, "example")
        assert duplicate.upload_type == "example"
        after_duplicate = await get_profile_by_id(async_session, profile.id)
        assert after_duplicate.updated_at == attach_revision

        changed = await associate_attachment(
            async_session,
            profile.id,
            upload_id,
            "additional_context",
        )
        assert changed.upload_type == "additional_context"
        after_type_change = await get_profile_by_id(async_session, profile.id)
        type_change_revision = after_type_change.updated_at
        assert type_change_revision > attach_revision
        changed_snapshot = build_profile_snapshot(after_type_change)
        assert [reference.id for reference in changed_snapshot.context_uploads] == [str(upload_id)]
        assert list(changed_snapshot.example_uploads) == []

        await disassociate_attachment(async_session, profile.id, upload_id)
        after_detach = await get_profile_by_id(async_session, profile.id)
        detach_revision = after_detach.updated_at
        assert detach_revision > type_change_revision
        assert after_detach.attachments == []

        with pytest.raises(NotFoundError):
            await disassociate_attachment(async_session, profile.id, upload_id)
        after_missing_detach = await get_profile_by_id(async_session, profile.id)
        assert after_missing_detach.updated_at == detach_revision

    @pytest.mark.asyncio
    async def test_bulk_deletion_is_constant_statement_count_and_advances_only_affected_profiles(
        self,
        async_session: AsyncSession,
        async_engine: AsyncEngine,
        setup_database_schema: None,
    ) -> None:
        """Bulk removal stays set-based while advancing every affected parent revision."""
        _ = setup_database_schema
        upload_id = uuid4()
        affected = [await _create_profile(async_session) for _ in range(16)]
        unaffected = await _create_profile(async_session)
        async_session.add_all(
            [
                SearchPrefUpload(
                    pref_id=profile.id,
                    upload_id=upload_id,
                    upload_type="example",
                )
                for profile in affected
            ]
        )
        async_session.add(
            SearchPrefUpload(
                pref_id=unaffected.id,
                upload_id=uuid4(),
                upload_type="example",
            )
        )
        await async_session.flush()

        statements: list[str] = []

        def record_statement(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: object,
        ) -> None:
            statements.append(statement.lstrip().partition(" ")[0].upper())

        event.listen(
            async_engine.sync_engine,
            "after_cursor_execute",
            record_statement,
        )
        try:
            count = await remove_attachment_from_all_profiles(async_session, upload_id)
        finally:
            event.remove(
                async_engine.sync_engine,
                "after_cursor_execute",
                record_statement,
            )

        assert count == len(affected)
        assert statements == ["UPDATE", "DELETE"]

        refreshed = await get_profiles_by_ids(
            async_session,
            {profile.id for profile in [*affected, unaffected]},
        )
        by_id: dict[UUID, SearchPref] = {profile.id: profile for profile in refreshed}
        for profile in affected:
            current = by_id[profile.id]
            assert current.updated_at > _INITIAL_REVISION
            assert current.attachments == []
        assert by_id[unaffected.id].updated_at == _INITIAL_REVISION
        assert len(by_id[unaffected.id].attachments) == 1
