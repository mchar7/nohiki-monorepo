"""Correlation pipeline viability invariant."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final = CheckMetadata(
    check_id="correlation_viability",
    name="Correlation Viability",
    category=CheckCategory.APPLICATION,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"job_vector_population", "profile_vector_population", "model_readiness"}),
    description="Require Qdrant ownership, warmed models, and observable correlation output for eligible inputs.",
)
_QUERY: Final = """
SELECT
 (SELECT count(*) FROM job_storage_schema.listings
  WHERE skills_embedding IS NOT NULL OR title_embedding IS NOT NULL),
 (SELECT count(*) FROM user_pref_schema.search_prefs
  WHERE user_skills_embedding IS NOT NULL OR query_embedding IS NOT NULL),
 (SELECT count(*) FROM job_correlation_schema.correlations)
"""


class CorrelationViabilityCheck(HealthCheck):
    """Require observable correlation output only when both inputs are eligible."""

    metadata = _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the correlation viability check."""
        code, stdout, stderr = await asyncio.to_thread(platform.exec_psql, _QUERY, field_separator="|")
        if code != 0:
            return self._make_result(CheckStatus.ERROR, "Cannot query correlation aggregates", details=(stderr[:200],))
        try:
            jobs, profiles, correlations = map(int, stdout.strip().split("|"))
        except ValueError:
            return self._make_result(CheckStatus.ERROR, "Invalid correlation aggregate response")
        evidence = (f"eligible_jobs={jobs}", f"eligible_profiles={profiles}", f"correlations={correlations}")
        if jobs == 0 or profiles == 0:
            return self._make_result(CheckStatus.SKIPPED, "Correlation inputs are not both ready", details=evidence)
        if correlations == 0:
            return self._make_result(
                CheckStatus.FAILED,
                "Zero correlations despite eligible vectors on both sides",
                details=evidence,
                remediation_hint=(
                    "Inspect correlation consumer membership/retrieval and replay pending profile or listing events"
                ),
            )
        return self._make_result(CheckStatus.PASSED, "Correlation output is viable", details=evidence)
