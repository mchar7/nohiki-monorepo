"""Cross-store population invariants for canonical entities and Qdrant."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Final

from nohiki_ml_manifest import ManifestCache

from health_check.config.paths import MANIFEST_PATH
from health_check.config.thresholds import HTTP_CHECK_TIMEOUT_SECONDS, QDRANT_PORT
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_PLATFORMS: Final = frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES})


async def _db_count(platform: Platform, query: str) -> tuple[int | None, str]:
    code, stdout, stderr = await asyncio.to_thread(platform.exec_psql, query)
    if code != 0:
        return None, stderr[:200]
    try:
        return int(stdout.strip()), ""
    except ValueError:
        return None, "invalid aggregate count"


async def _point_count(platform: Platform, collection: str) -> tuple[int | None, str]:
    base = platform.service_url("qdrant", QDRANT_PORT)
    code, stdout, stderr = await asyncio.to_thread(
        platform.curl, f"{base}/collections/{collection}", timeout=int(HTTP_CHECK_TIMEOUT_SECONDS)
    )
    if code != 0:
        return None, stderr[:200]
    try:
        value = json.loads(stdout)["result"]["points_count"]
        return int(value), ""
    except json.JSONDecodeError, KeyError, TypeError, ValueError:
        return None, "invalid Qdrant collection response"


class _PopulationCheck(HealthCheck):
    entity: str
    sql: str

    async def execute(self, platform: Platform) -> CheckResult:
        collection = ManifestCache.get(MANIFEST_PATH).get_collection_name(self.entity)
        (entities, db_error), (points, qdrant_error) = await asyncio.gather(
            _db_count(platform, self.sql), _point_count(platform, collection)
        )
        if entities is None or points is None:
            return self._make_result(
                CheckStatus.ERROR,
                f"Cannot evaluate {self.entity} vector ownership",
                details=tuple(x for x in (db_error, qdrant_error) if x),
            )
        evidence = (f"canonical_{self.entity}={entities}", f"{collection}.points={points}")
        if entities == 0:
            status = CheckStatus.SKIPPED if points == 0 else CheckStatus.FAILED
            summary = (
                f"Fresh empty {self.entity} state"
                if points == 0
                else f"Orphan {self.entity} vectors without canonical owners"
            )
            return self._make_result(
                status,
                summary,
                details=evidence,
                remediation_hint="Remove orphan points and replay canonical lifecycle events" if points else None,
            )
        if points == 0:
            return self._make_result(
                CheckStatus.FAILED,
                f"{collection} has zero points while embedded canonical {self.entity} exist",
                details=evidence,
                remediation_hint=f"Replay {self.entity} lifecycle events and rebuild {collection}",
            )
        return self._make_result(CheckStatus.PASSED, f"{self.entity} vector population is viable", details=evidence)


class JobVectorPopulationCheck(_PopulationCheck):
    """Detect canonical embedded listings missing all Qdrant points."""

    entity = "jobs"
    sql = (
        "SELECT count(*) FROM job_storage_schema.listings "
        "WHERE skills_embedding IS NOT NULL OR title_embedding IS NOT NULL"
    )
    metadata = CheckMetadata(
        check_id="job_vector_population",
        name="Job Vector Population",
        category=CheckCategory.VECTORS,
        platforms=_PLATFORMS,
        depends_on=frozenset({"qdrant_dimensions", "postgres_connectivity"}),
        description="Compare aggregate embedded listing and jobs collection populations.",
    )


class ProfileVectorPopulationCheck(_PopulationCheck):
    """Detect embedded profiles missing all Qdrant points."""

    entity = "profiles"
    sql = (
        "SELECT count(*) FROM user_pref_schema.search_prefs "
        "WHERE user_skills_embedding IS NOT NULL OR query_embedding IS NOT NULL"
    )
    metadata = CheckMetadata(
        check_id="profile_vector_population",
        name="Profile Vector Population",
        category=CheckCategory.VECTORS,
        platforms=_PLATFORMS,
        depends_on=frozenset({"qdrant_dimensions", "postgres_connectivity"}),
        description="Compare aggregate embedded profile and profiles collection populations.",
    )
