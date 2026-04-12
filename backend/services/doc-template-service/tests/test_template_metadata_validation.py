"""Tests for template metadata validation."""

import pytest
from doc_template_service.core.metadata import parse_template_metadata
from nohiki.common.v1 import AccessScope


def test_parse_template_metadata_valid() -> None:
    """Test parsing valid template metadata."""
    template_content = (
        '<!-- TMPL_META {"name": "test_layout", "title": "Test Layout", "version": "1.0.0", '
        '"description": "Test template", "access_scope": "PUBLIC", "visibility": "document"} -->'
        "<h1>{{ title }}</h1>"
    )

    metadata = parse_template_metadata(template_content)
    assert metadata is not None
    assert metadata["name"] == "test_layout"
    assert metadata["title"] == "Test Layout"
    assert metadata["version"] == "1.0.0"
    assert metadata["description"] == "Test template"
    assert metadata["access_scope"] == AccessScope.PUBLIC


def test_parse_template_metadata_missing_block() -> None:
    """Test parsing template without metadata block."""
    template_content = "<div><h1>{{ title }}</h1></div>"

    with pytest.raises(ValueError, match="No TMPL_META comment found"):
        parse_template_metadata(template_content)


def test_parse_template_metadata_multiple_blocks() -> None:
    """Test parsing template with multiple metadata blocks - uses first complete block."""
    template_content = (
        '<!-- TMPL_META {"name": "test_layout", "title": "Test Layout", "version": "1.0.0", '
        '"description": "First template", "access_scope": "PUBLIC", "visibility": "document"} -->'
        "<h1>{{ title }}</h1>"
        '<!-- TMPL_META {"name": "another_layout", "title": "Another Layout", "version": "2.0.0", '
        '"description": "Second template", "access_scope": "PRIVATE", "visibility": "document"} -->'
    )

    metadata = parse_template_metadata(template_content)
    assert metadata is not None
    assert metadata["name"] == "test_layout"
    assert metadata["version"] == "1.0.0"


def test_parse_template_metadata_invalid_json() -> None:
    """Test parsing template with invalid JSON in metadata block."""
    template_content = "<!-- TMPL_META {invalid json} --><h1>{{ title }}</h1>"

    with pytest.raises(ValueError, match="Invalid JSON in TMPL_META comment"):
        parse_template_metadata(template_content)


def test_parse_template_metadata_missing_required_fields() -> None:
    """Test parsing template with missing required fields."""
    template_content = '<!-- TMPL_META {"name": "test_layout"} --><h1>{{ title }}</h1>'

    with pytest.raises(ValueError, match="Missing required fields in TMPL_META"):
        parse_template_metadata(template_content)


def test_parse_template_metadata_invalid_access_scope() -> None:
    """Test parsing template with invalid access_scope."""
    template_content = (
        '<!-- TMPL_META {"name": "test_layout", "title": "Test Layout", "version": "1.0.0", '
        '"description": "Test template", "access_scope": "invalid", "visibility": "document"} -->'
        "<h1>{{ title }}</h1>"
    )

    with pytest.raises(ValueError, match="access_scope"):
        parse_template_metadata(template_content)


def test_parse_template_metadata_with_js_requirement_object() -> None:
    """Test parsing metadata with structured requires_javascript object."""
    template_content = (
        '<!-- TMPL_META {"name": "js_layout", "title": "JS Layout", "version": "1.0.0", '
        '"description": "JS template", "access_scope": "PUBLIC", "visibility": "document", '
        '"requires_javascript": {"required": true, "reason": "Layout"}} -->'
        "<h1>{{ title }}</h1>"
    )

    metadata = parse_template_metadata(template_content)
    assert metadata["requires_javascript"] == {"required": True, "reason": "Layout"}
