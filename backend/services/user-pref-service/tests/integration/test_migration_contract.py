"""PostgreSQL regression coverage for empty repeated preference updates."""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.common.v1 import WorkArrangement
from nohiki.user.pref.v1 import PrefUpdateRequested
from nohiki_db_utils import create_event_metadata
from nohiki_kafka_client import MessageContext
from user_pref_service.db.models import SearchPref
from user_pref_service.events.commands import handle_pref_update_requested

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
@pytest.mark.requires_docker
@pytest.mark.asyncio
@pytest.mark.parametrize("updated_field", ["search_keywords", "work_arrangements"])
async def test_empty_repeated_update_completes_through_consumer(
    updated_field: str,
    async_session: AsyncSession,
    setup_database_schema: None,
) -> None:
    """The canonical empty repeated values persist through the command consumer."""
    _ = setup_database_schema
    user_id = uuid4()
    request_id = str(uuid4())
    profile = SearchPref(
        id=uuid4(),
        user_id=user_id,
        pref_name="Empty update profile",
        search_keywords=["python"],
        work_arrangements=[WorkArrangement.REMOTE],
    )
    async_session.add(profile)
    await async_session.flush()

    command = PrefUpdateRequested(
        metadata=create_event_metadata("user-pref-service-test", request_id),
        request_id=request_id,
        user_id=str(user_id),
        pref_id=str(profile.id),
        updated_fields=[updated_field],
    )
    context = MessageContext(
        topic="user-pref.cmd.update-requested.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=async_session,
        outbox=MagicMock(),
    )

    with patch(
        "user_pref_service.events.commands._start_enrichment_saga",
        new_callable=AsyncMock,
    ):
        await handle_pref_update_requested(command, context)

    await async_session.refresh(profile)
    assert getattr(profile, updated_field) == []
