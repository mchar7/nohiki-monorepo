"""Periodic bounded retry and expiry entry point for preference enrichment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nohiki_db_utils import OutboxWriter

from user_pref_service.db.models import SCHEMA_NAME
from user_pref_service.services.saga_service import sweep_due_enrichment_sagas

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def sweep_pref_enrichment_sagas(db: AsyncSession) -> int:
    """Retry or expire due sagas in the caller-owned transaction."""
    return await sweep_due_enrichment_sagas(db, OutboxWriter(schema=SCHEMA_NAME))
