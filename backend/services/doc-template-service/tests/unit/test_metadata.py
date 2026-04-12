"""Tests for template metadata parsing."""

import pytest
from doc_template_service.core.metadata import parse_template_metadata
from nohiki.common.v1 import AccessScope


class TestParseLayoutMetadata:
    """Tests for parse_template_metadata function."""

    def test_parse_valid_metadata(self) -> None:
        """Test parsing valid template metadata."""
        template = (
            '<!-- TMPL_META {"name": "test-template", "title": "Test Template", "version": "1.0.0", '
            '"description": "A test template", "access_scope": "PUBLIC", "visibility": "document"} -->'
            "<html><body>Content</body></html>"
        )
        metadata = parse_template_metadata(template)
        assert metadata["name"] == "test-template"
        assert metadata["title"] == "Test Template"
        assert metadata["version"] == "1.0.0"
        assert metadata["description"] == "A test template"
        assert metadata["access_scope"] == AccessScope.PUBLIC

    def test_parse_metadata_private_access_scope(self) -> None:
        """Test parsing metadata with private access scope."""
        template = (
            '<!-- TMPL_META {"name": "user-template", "title": "User Template", "version": "1.0.0", '
            '"description": "Account-only", "access_scope": "PRIVATE", "visibility": "document"} -->'
            "<html></html>"
        )
        metadata = parse_template_metadata(template)
        assert metadata["access_scope"] == AccessScope.PRIVATE

    def test_parse_metadata_with_owner_id(self) -> None:
        """Test parsing metadata with owner_id."""
        template = (
            '<!-- TMPL_META {"name": "owned-template", "title": "Owned Template", "version": "1.0.0", '
            '"description": "Owned", "access_scope": "PRIVATE", "visibility": "document", '
            '"owner_id": "11111111-1111-1111-1111-111111111111"} -->'
            "<html></html>"
        )
        metadata = parse_template_metadata(template)
        assert metadata["owner_id"] == "11111111-1111-1111-1111-111111111111"

    def test_parse_metadata_with_js_requirement_object(self) -> None:
        """Test parsing metadata with structured requires_javascript object."""
        template = (
            '<!-- TMPL_META {"name": "js-template", "title": "JS Template", "version": "1.0.0", '
            '"description": "Uses JS", "access_scope": "PUBLIC", "visibility": "document", '
            '"requires_javascript": {"required": true, "reason": "Layout"}} -->'
            "<html></html>"
        )
        metadata = parse_template_metadata(template)
        assert metadata["requires_javascript"] == {"required": True, "reason": "Layout"}

    def test_parse_metadata_missing_block_raises_error(self) -> None:
        """Test that missing TMPL_META block raises error."""
        template = "<html><body>No metadata</body></html>"
        with pytest.raises(ValueError, match="TMPL_META"):
            parse_template_metadata(template)

    def test_parse_metadata_invalid_json_raises_error(self) -> None:
        """Test that invalid JSON raises error."""
        template = "<!-- TMPL_META {invalid json} --><html></html>"
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_template_metadata(template)

    def test_parse_metadata_missing_required_field_raises_error(self) -> None:
        """Test that missing required field raises error."""
        template = '<!-- TMPL_META {"name": "test", "version": "1.0.0"} --><html></html>'
        with pytest.raises(ValueError, match="Missing required fields"):
            parse_template_metadata(template)

    def test_parse_metadata_invalid_access_scope_raises_error(self) -> None:
        """Test that invalid access_scope raises error."""
        template = (
            '<!-- TMPL_META {"name": "test", "title": "Test", "version": "1.0.0", '
            '"description": "Test", "access_scope": "invalid", "visibility": "document"} -->'
            "<html></html>"
        )
        with pytest.raises(ValueError, match="access_scope"):
            parse_template_metadata(template)
