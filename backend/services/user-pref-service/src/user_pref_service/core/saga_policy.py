"""Bounded retry policy for preference enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from nohiki.user.pref.v1 import PrefEnrichmentFailedFailureReason
from nohiki_db_utils import SagaStatus

from user_pref_service.db.models import PrefEnrichmentAction

MAX_ATTEMPTS = 3
CALLBACK_TIMEOUT = timedelta(minutes=2)
WALL_CLOCK_CAP = timedelta(minutes=30)
SWEEP_INTERVAL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class NewEnrichmentSaga:
    """Identity and semantic state for one new enrichment workflow."""

    pref_id: UUID
    user_id: UUID
    request_id: UUID
    correlation_id: str
    action: PrefEnrichmentAction
    raw_skills: list[str]
    semantic_generation: int
    semantic_hash: str


@dataclass(frozen=True, slots=True)
class SagaTermination:
    """One terminal transition and its externally visible reason."""

    status: SagaStatus
    reason: PrefEnrichmentFailedFailureReason
    error_message: str
