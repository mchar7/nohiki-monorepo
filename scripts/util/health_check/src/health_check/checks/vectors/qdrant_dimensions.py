"""Health check: Qdrant collections have correct vector dimensions."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Final

from health_check.config.thresholds import HTTP_CHECK_TIMEOUT_SECONDS, QDRANT_PORT
from health_check.config.vectors import load_expected_dimensions
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="qdrant_dimensions",
    name="Qdrant Dimensions",
    category=CheckCategory.VECTORS,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"core_services"}),
    timeout_seconds=30.0,
    description="Verify Qdrant collection vector dimensions match the manifest.",
)

_TIMEOUT: Final[int] = int(HTTP_CHECK_TIMEOUT_SECONDS)


async def _fetch_existing_collections(platform: Platform) -> frozenset[str] | None:
    """Fetch the set of existing Qdrant collection names.

    Returns:
        Frozenset of names, or ``None`` if Qdrant is unreachable.
    """
    base = platform.service_url("qdrant", QDRANT_PORT)
    code, stdout, _ = await asyncio.to_thread(
        platform.curl,
        f"{base}/collections",
        timeout=_TIMEOUT,
    )
    if code != 0:
        return None
    try:
        data = json.loads(stdout)
        names = {c["name"] for c in data.get("result", {}).get("collections", [])}
        return frozenset(names)
    except json.JSONDecodeError, ValueError, KeyError, TypeError:
        return None


async def _check_vector_dim(
    platform: Platform,
    collection: str,
    vector_name: str,
    expected_dim: int,
) -> str | None:
    """Check a single named vector's dimension for a collection.

    Args:
        platform: Active platform for HTTP curl.
        collection: Qdrant collection name.
        vector_name: Named vector key within the collection.
        expected_dim: Expected dimension size.

    Returns:
        Failure message if dimensions mismatch, else ``None``.
    """
    base = platform.service_url("qdrant", QDRANT_PORT)
    code, stdout, _ = await asyncio.to_thread(
        platform.curl,
        f"{base}/collections/{collection}",
        timeout=_TIMEOUT,
    )
    if code != 0:
        return f"{collection}: cannot query"

    try:
        info = json.loads(stdout)
        vectors = info.get("result", {}).get("config", {}).get("params", {}).get("vectors", {})
        if not isinstance(vectors, dict):
            return f"{collection}: invalid named-vector schema"
        vec = vectors.get(vector_name)
        if not isinstance(vec, dict):
            return f"{collection}.{vector_name}: required vector missing"
        actual = vec.get("size")
        if actual != expected_dim:
            return f"{collection}.{vector_name}: dim={actual}, expected={expected_dim}"
    except json.JSONDecodeError, ValueError, AttributeError, TypeError:
        return f"{collection}: cannot parse collection info"
    return None


class QdrantDimensionsCheck(HealthCheck):
    """Verify Qdrant collection vector dimensions match manifest-declared values."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the Qdrant dimensions check."""
        existing = await _fetch_existing_collections(platform)
        if existing is None:
            return self._make_result(
                CheckStatus.ERROR,
                f"Cannot connect to Qdrant on port {QDRANT_PORT}",
                remediation_hint="Ensure Qdrant container is running",
            )

        expected = load_expected_dimensions()
        missing = sorted(expected.keys() - existing)
        if missing:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(missing)} required Qdrant collection(s) missing",
                details=tuple(f"{name}: missing" for name in missing),
                remediation_hint="Create required collections: just qdrant-init",
            )
        checks = [
            (collection, vec_name, dim)
            for collection, vectors in expected.items()
            if collection in existing
            for vec_name, dim in vectors.items()
        ]

        if not checks:
            return self._make_result(CheckStatus.SKIPPED, "Manifest declares no Qdrant vectors")

        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_check_vector_dim(platform, col, vec, dim)) for col, vec, dim in checks]

        failures = [msg for t in tasks if (msg := t.result()) is not None]

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} vector dimension mismatch(es)",
                details=tuple(failures),
                remediation_hint="Re-index collections after manifest update: just qdrant-init",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(checks)} checked vector dimensions correct",
        )
