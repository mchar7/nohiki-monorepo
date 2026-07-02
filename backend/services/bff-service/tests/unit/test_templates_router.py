"""Tests for templates router.

This module consolidates all template router tests following SOLID principles:
- Single Responsibility: Each test class focuses on one aspect
- DRY: Uses shared fixtures from conftest.py
- Organized: Test classes group related functionality
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi import HTTPException
from nohiki_db_utils.testing import create_mock_session
from pydantic import BaseModel

from tests.unit.conftest import make_scalar_all, make_template_version_projection

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

# Inline implementations of validation functions to test without imports
# These mirror the actual implementations in the router


class TemplateValidationIssue(BaseModel):
    """A single validation issue found in a template."""

    path: str
    keyword: str
    message: str


class TemplateValidationResponse(BaseModel):
    """Response for template validation."""

    valid: bool
    issues: list[TemplateValidationIssue]


_JINJA_BLOCK_OPEN = re.compile(r"\{%\s*(if|for|block|macro|call|filter)\b")
_JINJA_BLOCK_CLOSE = re.compile(r"\{%\s*end(if|for|block|macro|call|filter)\s*%\}")
_JINJA_EXPR_OPEN = re.compile(r"\{\{")
_JINJA_EXPR_CLOSE = re.compile(r"\}\}")


def _count_pattern_matches(text: str, pattern: re.Pattern[str]) -> int:
    """Count matches of a regex pattern in text."""
    return len(pattern.findall(text))


def _validate_jinja_blocks(template: str) -> list[TemplateValidationIssue]:
    """Validate that all Jinja2 block tags are properly closed."""
    issues: list[TemplateValidationIssue] = []
    open_count = _count_pattern_matches(template, _JINJA_BLOCK_OPEN)
    close_count = _count_pattern_matches(template, _JINJA_BLOCK_CLOSE)

    if open_count != close_count:
        issues.append(
            TemplateValidationIssue(
                path="$",
                keyword="jinja_block_miscorrelation",
                message=f"Mismatched Jinja2 blocks: {open_count} opened, {close_count} closed",
            )
        )
    return issues


def _validate_jinja_expressions_per_line(template: str) -> list[TemplateValidationIssue]:
    """Validate that Jinja2 expressions are properly closed on each line."""
    issues: list[TemplateValidationIssue] = []
    lines = template.split("\n")

    for line_num, line in enumerate(lines, start=1):
        open_count = _count_pattern_matches(line, _JINJA_EXPR_OPEN)
        close_count = _count_pattern_matches(line, _JINJA_EXPR_CLOSE)
        if open_count != close_count:
            issues.append(
                TemplateValidationIssue(
                    path=f"line {line_num}",
                    keyword="jinja_expression_miscorrelation",
                    message=f"Unclosed Jinja2 expression on line {line_num}",
                )
            )
    return issues


def _validate_html_structure(template: str) -> list[TemplateValidationIssue]:
    """Validate basic HTML structure."""
    issues: list[TemplateValidationIssue] = []
    template_lower = template.lower()

    if "<!doctype" not in template_lower:
        issues.append(
            TemplateValidationIssue(
                path="$",
                keyword="missing_doctype",
                message="Missing <!DOCTYPE html> declaration",
            )
        )

    if "<html" not in template_lower:
        issues.append(
            TemplateValidationIssue(
                path="$",
                keyword="missing_html_tag",
                message="Missing <html> tag",
            )
        )

    if "<head" not in template_lower:
        issues.append(
            TemplateValidationIssue(
                path="$",
                keyword="missing_head_tag",
                message="Missing <head> tag",
            )
        )

    if "<body" not in template_lower:
        issues.append(
            TemplateValidationIssue(
                path="$",
                keyword="missing_body_tag",
                message="Missing <body> tag",
            )
        )

    return issues


def validate_template_content(template: str) -> TemplateValidationResponse:
    """Validate template content for Jinja2 and HTML issues."""
    issues: list[TemplateValidationIssue] = []
    issues.extend(_validate_jinja_blocks(template))
    issues.extend(_validate_jinja_expressions_per_line(template))
    issues.extend(_validate_html_structure(template))
    return TemplateValidationResponse(valid=len(issues) == 0, issues=issues)


# Tests


class TestJinjaBlockValidation:
    """Tests for Jinja2 block validation."""

    def test_matching_blocks_pass(self) -> None:
        """Test matching Jinja2 blocks pass validation."""
        template = "{% if x %}content{% endif %}"
        issues = _validate_jinja_blocks(template)
        assert issues == []

    def test_mismatched_blocks_fail(self) -> None:
        """Test mismatched Jinja2 blocks fail validation."""
        template = "{% if x %}content"
        issues = _validate_jinja_blocks(template)
        assert len(issues) == 1
        assert "miscorrelation" in issues[0].keyword

    def test_multiple_blocks_matching(self) -> None:
        """Test multiple matching blocks pass."""
        template = "{% if x %}{% for y in z %}content{% endfor %}{% endif %}"
        issues = _validate_jinja_blocks(template)
        assert issues == []

    def test_nested_blocks_missing_close(self) -> None:
        """Test nested blocks with missing close fail."""
        template = "{% if x %}{% for y in z %}content{% endif %}"
        issues = _validate_jinja_blocks(template)
        assert len(issues) == 1


class TestJinjaExpressionValidation:
    """Tests for Jinja2 expression validation."""

    def test_valid_expressions_pass(self) -> None:
        """Test valid Jinja2 expressions pass."""
        template = "{{ name }} and {{ title }}"
        issues = _validate_jinja_expressions_per_line(template)
        assert issues == []

    def test_unclosed_expression_fails(self) -> None:
        """Test unclosed Jinja2 expressions fail."""
        template = "{{ name"
        issues = _validate_jinja_expressions_per_line(template)
        assert len(issues) == 1
        assert "expression" in issues[0].keyword

    def test_multiple_expressions_per_line(self) -> None:
        """Test multiple expressions on same line."""
        template = "{{ a }} {{ b }} {{ c }}"
        issues = _validate_jinja_expressions_per_line(template)
        assert issues == []


class TestHtmlStructureValidation:
    """Tests for HTML structure validation."""

    def test_complete_structure_passes(self) -> None:
        """Test complete HTML structure passes."""
        template = "<!DOCTYPE html><html><head></head><body></body></html>"
        issues = _validate_html_structure(template)
        assert issues == []

    def test_missing_doctype_fails(self) -> None:
        """Test missing doctype fails."""
        template = "<html><head></head><body></body></html>"
        issues = _validate_html_structure(template)
        assert any("doctype" in i.keyword for i in issues)

    def test_missing_head_fails(self) -> None:
        """Test missing head fails."""
        template = "<!DOCTYPE html><html><body></body></html>"
        issues = _validate_html_structure(template)
        assert any("head" in i.keyword for i in issues)

    def test_missing_body_fails(self) -> None:
        """Test missing body fails."""
        template = "<!DOCTYPE html><html><head></head></html>"
        issues = _validate_html_structure(template)
        assert any("body" in i.keyword for i in issues)


class TestValidateTemplateContent:
    """Tests for complete template validation."""

    def test_valid_template_passes(self) -> None:
        """Test valid template passes all checks."""
        template = """<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>{{ name }}</body>
</html>"""
        result = validate_template_content(template)
        assert result.valid is True
        assert result.issues == []

    def test_invalid_template_fails(self) -> None:
        """Test invalid template fails."""
        template = "<p>{{ name</p>"
        result = validate_template_content(template)
        assert result.valid is False
        assert len(result.issues) > 0

    def test_multiple_issues_reported(self) -> None:
        """Test multiple issues are all reported."""
        template = "{{ name"  # Missing structure AND unclosed expression
        result = validate_template_content(template)
        assert result.valid is False
        assert len(result.issues) >= 2


class TestResponseModels:
    """Tests for response model structures."""

    def test_validation_issue_model(self) -> None:
        """Test TemplateValidationIssue model."""
        issue = TemplateValidationIssue(
            path="$",
            keyword="test_issue",
            message="Test message",
        )
        assert issue.path == "$"
        assert issue.keyword == "test_issue"
        assert issue.message == "Test message"

    def test_validation_response_valid(self) -> None:
        """Test TemplateValidationResponse for valid template."""
        response = TemplateValidationResponse(valid=True, issues=[])
        assert response.valid is True
        assert response.issues == []

    def test_validation_response_invalid(self) -> None:
        """Test TemplateValidationResponse for invalid template."""
        issue = TemplateValidationIssue(path="$", keyword="test", message="Error")
        response = TemplateValidationResponse(valid=False, issues=[issue])
        assert response.valid is False
        assert len(response.issues) == 1


# Template Handler Tests


class TestTemplateHandlers:
    """Tests for template router handlers."""

    @pytest.mark.asyncio
    async def test_list_template_families_returns_all_families(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.templates import list_template_families
        from nohiki_fastapi_utils import PaginationParams

        user_id = uuid.uuid4()
        template_id = uuid.uuid4()
        mock_db = create_mock_session()
        pagination = PaginationParams(page=1, page_size=20)

        template = make_template_version_projection(
            id=template_id,
            namespace="default",
            name="resume_template",
            display_name="Professional Résumé",
            version="1.2.3",
        )

        count_result = mocker.MagicMock()
        count_result.scalar.return_value = 1

        mock_scalars = mocker.MagicMock()
        mock_scalars.all.return_value = [template]
        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.side_effect = [count_result, mock_result]

        result = await list_template_families(user_id, mock_db, pagination)

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].name == "resume_template"
        assert result.items[0].display_name == "Professional Résumé"
        assert result.items[0].latest_version is not None
        assert result.items[0].latest_version.version == "1.2.3"

    @pytest.mark.asyncio
    async def test_get_template_family_returns_single_family(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.templates import get_template_family

        user_id = uuid.uuid4()
        mock_db = create_mock_session()

        namespace = "default"
        name = "cover-letter"
        version_id = uuid.uuid4()
        version = make_template_version_projection(id=version_id, name=name, namespace=namespace, version="2.0.0")
        version.display_name = "Cover Letter"

        version_result = mocker.MagicMock()
        version_result.scalar_one_or_none.return_value = version
        mock_db.execute.return_value = version_result

        result = await get_template_family(namespace, name, user_id, mock_db)

        assert result.id == str(version_id)
        assert result.name == name
        assert result.latest_version is not None
        assert result.latest_version.version == "2.0.0"

    @pytest.mark.asyncio
    async def test_get_template_family_raises_404_when_not_found(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.templates import get_template_family

        user_id = uuid.uuid4()
        mock_db = create_mock_session()

        namespace = "default"
        name = "not-found"
        mock_result = mocker.MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await get_template_family(namespace, name, user_id, mock_db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_template_versions_returns_all_versions(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.templates import list_template_versions

        user_id = uuid.uuid4()
        mock_db = create_mock_session()

        namespace = "default"
        name = "resume-template"
        v1 = make_template_version_projection(version="1.0.0")
        v2 = make_template_version_projection(version="2.0.0")

        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value = make_scalar_all([v2, v1])
        mock_db.execute.return_value = mock_result

        result = await list_template_versions(namespace, name, user_id, mock_db)

        assert len(result) == 2
        assert result[0].version == "2.0.0"
        assert result[1].version == "1.0.0"

    @pytest.mark.asyncio
    async def test_get_template_by_id_returns_template(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.templates import get_template_by_id

        user_id = uuid.uuid4()
        template_id = uuid.uuid4()
        version_str = "1.2.3"
        mock_db = create_mock_session()

        template = make_template_version_projection(
            id=template_id,
            version=version_str,
            template_content="<html><body>Test Content</body></html>",
        )
        mock_result = mocker.MagicMock()
        mock_result.scalar_one_or_none.return_value = template
        mock_db.execute.return_value = mock_result

        result = await get_template_by_id(template_id, user_id, mock_db)

        assert result.version == version_str
        assert "Test Content" in result.template_content

    @pytest.mark.asyncio
    async def test_get_template_by_id_raises_404_when_not_found(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.templates import get_template_by_id

        user_id = uuid.uuid4()
        template_id = uuid.uuid4()
        mock_db = create_mock_session()

        mock_result = mocker.MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await get_template_by_id(template_id, user_id, mock_db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_validate_template_returns_valid_for_correct_template(self) -> None:
        from bff_service.api.routers.templates import (
            TemplateValidationRequest,
            validate_template,
        )

        user_id = uuid.uuid4()
        request = TemplateValidationRequest(template="<!DOCTYPE html><html><head></head><body>{{ name }}</body></html>")

        result = await validate_template(request, user_id)

        assert result.valid is True
        assert len(result.issues) == 0

    @pytest.mark.asyncio
    async def test_validate_template_returns_invalid_for_broken_template(self) -> None:
        from bff_service.api.routers.templates import (
            TemplateValidationRequest,
            validate_template,
        )

        user_id = uuid.uuid4()
        request = TemplateValidationRequest(template="<p>{{ unclosed</p>")

        result = await validate_template(request, user_id)

        assert result.valid is False
        assert len(result.issues) > 0

    @pytest.mark.asyncio
    async def test_create_template_family_validates_and_publishes(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bff_service.api.routers.templates import (
            TemplateCreateRequest,
            create_template_family,
        )

        user_id = uuid.uuid4()
        mock_db = create_mock_session()
        mock_db.add = mocker.Mock()
        mock_kafka = mocker.AsyncMock()
        mock_kafka_client = mocker.MagicMock()
        mock_kafka_client.publish = mock_kafka
        monkeypatch.setattr("bff_service.api.routers.templates.kafka_client", mock_kafka_client)

        request = TemplateCreateRequest(
            name="my-template",
            display_name="My Template",
            namespace="default",
            template_content="<!DOCTYPE html><html><head></head><body>Test</body></html>",
            description="A test template",
            schema_compatibility=["resume-v1"],
        )

        result = await create_template_family(request, user_id, mock_db)

        assert result.status == "accepted"
        assert result.request_id is not None
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        mock_kafka.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_template_family_raises_422_on_invalid_template(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.templates import (
            TemplateCreateRequest,
            create_template_family,
        )

        user_id = uuid.uuid4()
        mock_db = create_mock_session()

        request = TemplateCreateRequest(
            name="broken-template",
            display_name="Broken Template",
            namespace="default",
            template_content="<p>{{ unclosed</p>",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_template_family(request, user_id, mock_db)

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_add_template_version_validates_and_publishes(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bff_service.api.routers.templates import (
            TemplateVersionAddRequest,
            add_template_version,
        )

        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        mock_db = create_mock_session()
        mock_db.add = mocker.Mock()
        mock_kafka = mocker.AsyncMock()
        mock_kafka_client = mocker.MagicMock()
        mock_kafka_client.publish = mock_kafka
        monkeypatch.setattr("bff_service.api.routers.templates.kafka_client", mock_kafka_client)

        request = TemplateVersionAddRequest(
            version="2.0.0",
            template_content="<!DOCTYPE html><html><head></head><body>Updated</body></html>",
            description="Version 2",
        )

        result = await add_template_version(family_id, request, user_id, mock_db)

        assert result.status == "accepted"
        assert result.request_id is not None
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        mock_kafka.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_template_version_raises_422_on_invalid_template(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.templates import (
            TemplateVersionAddRequest,
            add_template_version,
        )

        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        mock_db = create_mock_session()

        request = TemplateVersionAddRequest(
            version="3.0.0",
            template_content="<p>{{ broken",
        )

        with pytest.raises(HTTPException) as exc_info:
            await add_template_version(family_id, request, user_id, mock_db)

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_template_family_publishes_command(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bff_service.api.routers.templates import delete_template_family

        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        mock_db = create_mock_session()
        mock_db.add = mocker.Mock()
        mock_kafka = mocker.AsyncMock()
        mock_kafka_client = mocker.MagicMock()
        mock_kafka_client.publish = mock_kafka
        monkeypatch.setattr("bff_service.api.routers.templates.kafka_client", mock_kafka_client)

        result = await delete_template_family(family_id, user_id, mock_db)

        assert result.status == "accepted"
        assert result.request_id is not None
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        mock_kafka.assert_awaited_once()

    def test_version_to_response_converts_projection(self) -> None:
        from bff_service.api.routers.templates import _version_to_response

        version_id = uuid.uuid4()
        version = make_template_version_projection(
            id=version_id,
            version="1.2.3",
            template_content="<html>Test</html>",
            content_schema={"test": "data"},
        )

        response = _version_to_response(version)

        assert response.id == str(version_id)
        assert response.version == "1.2.3"
        assert response.template_content == "<html>Test</html>"

    @pytest.mark.asyncio
    async def test_get_latest_version_returns_highest_version(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.templates import _get_latest_version

        mock_db = create_mock_session()

        namespace = "default"
        name = "test"
        latest = make_template_version_projection(version="5.0.0")
        mock_result = mocker.MagicMock()
        mock_result.scalar_one_or_none.return_value = latest
        mock_db.execute.return_value = mock_result

        result = await _get_latest_version(mock_db, namespace, name)

        assert result is not None
        assert result.version == "5.0.0"

    @pytest.mark.asyncio
    async def test_get_latest_version_returns_none_when_no_versions(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.templates import _get_latest_version

        mock_db = create_mock_session()

        namespace = "default"
        name = "none"
        mock_result = mocker.MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await _get_latest_version(mock_db, namespace, name)

        assert result is None

    def test_create_cmd_metadata_generates_metadata(self) -> None:
        from bff_service.api.routers.templates import _create_cmd_metadata

        metadata = _create_cmd_metadata()

        assert metadata.event_id is not None
        assert metadata.source_service == "bff-service"

    @pytest.mark.asyncio
    async def test_track_command_request_creates_record(self, mocker: MockerFixture) -> None:
        from bff_service.api.routers.templates import (
            CommandRequestParams,
            _track_command_request,
        )

        mock_db = create_mock_session()
        mock_db.add = mocker.Mock()
        params = CommandRequestParams(
            request_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            command_type="template_create",
            entity_type="template_family",
        )

        await _track_command_request(mock_db, params)

        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()

    def test_validate_template_content_integration(self) -> None:
        from bff_service.api.routers.templates import validate_template_content

        valid_template = "<!DOCTYPE html><html><head></head><body>{{ name }}</body></html>"
        result = validate_template_content(valid_template)
        assert result.valid is True

        invalid_template = "<p>{{ unclosed</p>"
        result = validate_template_content(invalid_template)
        assert result.valid is False
