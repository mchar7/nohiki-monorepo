"""Health check: system templates are projected in the BFF schema."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.services import REQUIRED_SYSTEM_TEMPLATES
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="template_projections",
    name="Template Projections",
    category=CheckCategory.APPLICATION,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"core_services"}),
    timeout_seconds=20.0,
    description="Verify system templates are projected into bff_schema.template_projections.",
)

_PROJECTION_QUERY: Final[str] = (
    "SELECT namespace, name FROM bff_schema.template_projections WHERE access_scope = 'SYSTEM'"
)
_FIELD_SEP: Final[str] = ","


def _parse_projection_rows(stdout: str) -> frozenset[tuple[str, str]]:
    """Parse psql CSV output into (namespace, name) pairs."""
    result: set[tuple[str, str]] = set()
    for line in stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split(_FIELD_SEP)
        if len(parts) >= 2:
            result.add((parts[0].strip(), parts[1].strip()))
    return frozenset(result)


class TemplateProjectionsCheck(HealthCheck):
    """Verify all required system templates are present in the BFF projection table."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the template projections check."""
        code, stdout, stderr = await asyncio.to_thread(
            platform.exec_psql,
            _PROJECTION_QUERY,
            field_separator=_FIELD_SEP,
        )

        if code != 0:
            return self._make_result(
                CheckStatus.ERROR,
                "Failed to query template projections",
                details=(stderr[:200] if stderr else "Unknown error",),
                remediation_hint="Ensure bff_schema exists and BFF migrations ran",
            )

        found = _parse_projection_rows(stdout)
        missing = REQUIRED_SYSTEM_TEMPLATES - found

        if missing:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(missing)} system template(s) not projected",
                details=tuple(f"{ns}/{name}" for ns, name in sorted(missing)),
                remediation_hint="Ensure doc-template-service seeded templates and BFF consumed the events",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(REQUIRED_SYSTEM_TEMPLATES)} system templates projected",
        )
