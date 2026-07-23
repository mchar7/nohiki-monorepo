"""Tests for application checks."""

from __future__ import annotations

import json
from collections.abc import Generator
from unittest.mock import patch

import pytest
from health_check.checks.application.skill_graph_seeded import SkillGraphSeededCheck
from health_check.checks.application.template_projections import (
    TemplateProjectionsCheck,
    _parse_projection_rows,
)
from health_check.config.services import REQUIRED_SYSTEM_TEMPLATES
from health_check.core.models import CheckStatus
from health_check.platform.models import PlatformTarget

from .._helpers import MockPlatform

_SKILL_COLLECTION = "skills_v1"
_PG_SUFFICIENT = "13896\n"
_PG_EMPTY = "0\n"
_QDRANT_SUFFICIENT = json.dumps({"result": {"points_count": 13896}})
_QDRANT_EMPTY = json.dumps({"result": {"points_count": 0}})


@pytest.fixture(autouse=True)
def _mock_collection_name() -> Generator[None]:
    with patch(
        "health_check.checks.application.skill_graph_seeded.load_skill_collection_name",
        return_value=_SKILL_COLLECTION,
    ):
        yield


class TestSkillGraphSeededCheck:
    async def test_passes_when_both_seeded(self) -> None:
        platform = MockPlatform(
            _psql_result=(0, _PG_SUFFICIENT, ""),
            _curl_result=(0, _QDRANT_SUFFICIENT, ""),
        )
        result = await SkillGraphSeededCheck().execute(platform)

        assert result.status == CheckStatus.PASSED
        assert "13,896" in result.summary

    async def test_fails_when_qdrant_empty(self) -> None:
        platform = MockPlatform(
            _psql_result=(0, _PG_SUFFICIENT, ""),
            _curl_result=(0, _QDRANT_EMPTY, ""),
        )
        result = await SkillGraphSeededCheck().execute(platform)

        assert result.status == CheckStatus.FAILED
        assert any("Qdrant" in d for d in result.details)

    async def test_fails_when_postgres_empty(self) -> None:
        platform = MockPlatform(
            _psql_result=(0, _PG_EMPTY, ""),
            _curl_result=(0, _QDRANT_SUFFICIENT, ""),
        )
        result = await SkillGraphSeededCheck().execute(platform)

        assert result.status == CheckStatus.FAILED
        assert any("PostgreSQL" in d for d in result.details)

    async def test_error_when_postgres_unreachable(self) -> None:
        platform = MockPlatform(
            _psql_result=(1, "", "connection refused"),
            _curl_result=(0, _QDRANT_SUFFICIENT, ""),
        )
        result = await SkillGraphSeededCheck().execute(platform)

        assert result.status == CheckStatus.ERROR

    async def test_fails_when_qdrant_unreachable(self) -> None:
        platform = MockPlatform(
            _psql_result=(0, _PG_SUFFICIENT, ""),
            _curl_result=(1, "", "connection refused"),
        )
        result = await SkillGraphSeededCheck().execute(platform)

        assert result.status == CheckStatus.FAILED
        assert any("unreachable" in d for d in result.details)

    async def test_fails_with_both_insufficient(self) -> None:
        platform = MockPlatform(
            _psql_result=(0, _PG_EMPTY, ""),
            _curl_result=(0, _QDRANT_EMPTY, ""),
        )
        result = await SkillGraphSeededCheck().execute(platform)

        assert result.status == CheckStatus.FAILED
        assert len(result.details) == 2

    async def test_remediation_hint_present_on_failure(self) -> None:
        platform = MockPlatform(
            _psql_result=(0, _PG_EMPTY, ""),
            _curl_result=(0, _QDRANT_EMPTY, ""),
        )
        result = await SkillGraphSeededCheck().execute(platform)

        assert result.remediation_hint is not None
        assert "seed" in result.remediation_hint.lower()

    async def test_qdrant_malformed_json_treated_as_unreachable(self) -> None:
        platform = MockPlatform(
            _psql_result=(0, _PG_SUFFICIENT, ""),
            _curl_result=(0, "not-json", ""),
        )
        result = await SkillGraphSeededCheck().execute(platform)

        assert result.status == CheckStatus.FAILED
        assert any("unreachable" in d for d in result.details)

    def test_metadata_check_id(self) -> None:
        assert SkillGraphSeededCheck().metadata.check_id == "skill_graph_seeded"

    def test_metadata_platforms(self) -> None:
        meta = SkillGraphSeededCheck().metadata

        assert PlatformTarget.COMPOSE in meta.platforms
        assert PlatformTarget.KUBERNETES in meta.platforms

    def test_metadata_has_postgres_dependency(self) -> None:
        assert "postgres_connectivity" in SkillGraphSeededCheck().metadata.depends_on

    def test_metadata_category_is_application(self) -> None:
        from health_check.core.models import CheckCategory

        assert SkillGraphSeededCheck().metadata.category == CheckCategory.APPLICATION


class TestParseProjectionRows:
    """Unit tests for _parse_projection_rows()."""

    def _all_required_csv(self) -> str:
        return "\n".join(f"{ns},{name}" for ns, name in REQUIRED_SYSTEM_TEMPLATES)

    def test_parses_all_required_templates(self) -> None:
        csv = self._all_required_csv()
        result = _parse_projection_rows(csv)
        assert result == REQUIRED_SYSTEM_TEMPLATES

    def test_empty_string_returns_empty(self) -> None:
        assert _parse_projection_rows("") == frozenset()

    def test_blank_lines_skipped(self) -> None:
        csv = "\n\nresume,resume\n\n"
        result = _parse_projection_rows(csv)
        assert ("resume", "resume") in result

    def test_lines_without_comma_skipped(self) -> None:
        csv = "no-comma-here\nresume,resume"
        result = _parse_projection_rows(csv)
        assert result == frozenset({("resume", "resume")})

    def test_whitespace_stripped(self) -> None:
        csv = "  resume ,  resume  "
        result = _parse_projection_rows(csv)
        assert ("resume", "resume") in result

    def test_extra_columns_ignored(self) -> None:
        csv = "resume,resume,extra_col"
        result = _parse_projection_rows(csv)
        assert ("resume", "resume") in result


class TestTemplateProjectionsCheck:
    """Tests for TemplateProjectionsCheck.execute()."""

    def _all_required_csv(self) -> str:
        return "\n".join(f"{ns},{name}" for ns, name in REQUIRED_SYSTEM_TEMPLATES)

    async def test_passes_when_all_templates_present(self) -> None:
        platform = MockPlatform(_psql_result=(0, self._all_required_csv(), ""))
        result = await TemplateProjectionsCheck().execute(platform)
        assert result.status == CheckStatus.PASSED
        assert str(len(REQUIRED_SYSTEM_TEMPLATES)) in result.summary

    async def test_fails_when_template_missing(self) -> None:
        platform = MockPlatform(_psql_result=(0, "", ""))
        result = await TemplateProjectionsCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert len(result.details) == len(REQUIRED_SYSTEM_TEMPLATES)

    async def test_fails_with_partial_templates(self) -> None:
        first = next(iter(REQUIRED_SYSTEM_TEMPLATES))
        partial_csv = f"{first[0]},{first[1]}"
        platform = MockPlatform(_psql_result=(0, partial_csv, ""))
        result = await TemplateProjectionsCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert len(result.details) == len(REQUIRED_SYSTEM_TEMPLATES) - 1

    async def test_error_when_psql_fails(self) -> None:
        platform = MockPlatform(_psql_result=(1, "", "FATAL: schema does not exist"))
        result = await TemplateProjectionsCheck().execute(platform)
        assert result.status == CheckStatus.ERROR
        assert "FATAL" in str(result.details)

    async def test_error_truncates_stderr_to_200(self) -> None:
        long_err = "x" * 300
        platform = MockPlatform(_psql_result=(1, "", long_err))
        result = await TemplateProjectionsCheck().execute(platform)
        assert result.status == CheckStatus.ERROR
        assert len(result.details[0]) <= 200

    async def test_error_when_psql_fails_empty_stderr(self) -> None:
        platform = MockPlatform(_psql_result=(1, "", ""))
        result = await TemplateProjectionsCheck().execute(platform)
        assert result.status == CheckStatus.ERROR
        assert "Unknown error" in result.details[0]

    async def test_remediation_hint_on_failure(self) -> None:
        platform = MockPlatform(_psql_result=(0, "", ""))
        result = await TemplateProjectionsCheck().execute(platform)
        assert result.remediation_hint is not None

    def test_metadata_check_id(self) -> None:
        assert TemplateProjectionsCheck().metadata.check_id == "template_projections"

    def test_metadata_depends_on_core_services(self) -> None:
        assert "core_services" in TemplateProjectionsCheck().metadata.depends_on

    def test_metadata_platforms(self) -> None:
        meta = TemplateProjectionsCheck().metadata
        assert PlatformTarget.COMPOSE in meta.platforms
        assert PlatformTarget.KUBERNETES in meta.platforms
