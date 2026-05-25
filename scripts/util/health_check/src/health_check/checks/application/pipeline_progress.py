"""Ingest pipeline progress from durable saga state."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="pipeline_progress",
    name="Pipeline Progress",
    category=CheckCategory.APPLICATION,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"core_services"}),
    timeout_seconds=20.0,
    description="Detect pending ingest sagas that exceed the normal processing window.",
)
_NORMAL_PROCESSING_MINUTES: Final[int] = 10
_FIELD_SEPARATOR: Final[str] = "|"
_QUERY: Final[str] = f"""
SELECT
    (SELECT count(*) FROM job_storage_schema.listing_ingest_saga WHERE status = 'PENDING'),
    (SELECT count(*) FROM job_storage_schema.listing_ingest_saga
        WHERE status = 'PENDING'
          AND created_at < now() - interval '{_NORMAL_PROCESSING_MINUTES} minutes'),
    (SELECT coalesce(extract(epoch FROM now() - min(created_at))::bigint, 0)
        FROM job_storage_schema.listing_ingest_saga WHERE status = 'PENDING'),
    (SELECT count(*) FROM job_ingest_enrichment_schema.enrichment_embedding_saga WHERE status = 'PENDING'),
    (SELECT count(*) FROM job_ingest_enrichment_schema.enrichment_embedding_saga
        WHERE status = 'PENDING'
          AND created_at < now() - interval '{_NORMAL_PROCESSING_MINUTES} minutes'),
    (SELECT coalesce(extract(epoch FROM now() - min(created_at))::bigint, 0)
        FROM job_ingest_enrichment_schema.enrichment_embedding_saga WHERE status = 'PENDING')
"""


@dataclass(frozen=True, slots=True)
class _PipelineState:
    """Aggregate pending-state evidence for one logical ingest stage."""

    name: str
    pending: int
    stalled: int
    oldest_seconds: int


def _parse_states(stdout: str) -> tuple[_PipelineState, _PipelineState]:
    """Parse the single aggregate psql row."""
    values = tuple(int(value.strip()) for value in stdout.strip().split(_FIELD_SEPARATOR))
    if len(values) != 6 or any(value < 0 for value in values):
        msg = "expected six non-negative aggregate values"
        raise ValueError(msg)
    return (
        _PipelineState("listing ingest", values[0], values[1], values[2]),
        _PipelineState("enrichment embedding", values[3], values[4], values[5]),
    )


def _detail(state: _PipelineState) -> str:
    """Format aggregate evidence without row identifiers or topology."""
    oldest_minutes = state.oldest_seconds // 60
    return f"{state.name}: pending={state.pending}, stalled={state.stalled}, oldest_minutes={oldest_minutes}"


class PipelineProgressCheck(HealthCheck):
    """Fail early when durable pending work stops progressing."""

    metadata = _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Query aggregate saga progress without mutating or waiting for expiry."""
        code, stdout, _ = await asyncio.to_thread(
            platform.exec_psql,
            _QUERY,
            field_separator=_FIELD_SEPARATOR,
        )
        if code != 0:
            return self._make_result(
                CheckStatus.ERROR,
                "Unable to inspect ingest pipeline progress",
                remediation_hint="Verify database availability and ingest service migrations",
            )
        try:
            states = _parse_states(stdout)
        except ValueError:
            return self._make_result(CheckStatus.ERROR, "Invalid ingest pipeline aggregate response")

        pending = sum(state.pending for state in states)
        if pending == 0:
            return self._make_result(CheckStatus.SKIPPED, "No pending ingest work")

        details = tuple(_detail(state) for state in states if state.pending > 0)
        stalled = sum(state.stalled for state in states)
        if stalled:
            return self._make_result(
                CheckStatus.FAILED,
                f"{stalled} pending ingest item(s) exceeded the normal processing window",
                details=details,
                remediation_hint="Inspect the named pipeline stage's consumers and replay blocked events",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"{pending} pending ingest item(s) remain within the normal processing window",
            details=details,
        )
