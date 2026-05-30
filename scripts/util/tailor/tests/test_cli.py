"""Tests for tailor CLI commands via typer.testing.CliRunner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tailor.cli import app
from tailor.exceptions import TemplateError
from tailor.models.templates import SchemaInfo, TemplateInfo
from typer.testing import CliRunner

runner = CliRunner()

# Patch targets -- these commands import lazily inside function bodies,
# so patching must be done at the source module, not at tailor.cli.app.
_PATCH_GET_SETTINGS = "tailor.core.config.get_settings"
_PATCH_FILE_ADAPTER = "tailor.adapters.file_adapter.TailorFileAdapter"
_PATCH_DISPLAY_TEMPLATES_TABLE = "tailor.display.panels.display_templates_table"


def _make_template_info(name: str = "test_resume") -> TemplateInfo:
    """Build a minimal TemplateInfo for CLI tests."""
    return TemplateInfo(
        path=Path(f"/templates/{name}.html"),
        name=name,
        content="<html></html>",
        version="1.0.0",
        description="A test resume template",
        access_scope="PUBLIC",
        namespace="default",
        schema_name="resume",
    )


def _make_schema_info(name: str = "resume") -> SchemaInfo:
    """Build a minimal SchemaInfo for CLI tests."""
    return SchemaInfo(
        path=Path(f"/schemas/{name}_schema.json"),
        name=name,
        content={"title": "Resume Schema", "type": "object"},
    )


class TestTemplatesCommand:
    """Tests for the 'templates' CLI command."""

    def test_exits_with_code_1_when_no_templates_found(self) -> None:
        """Templates command must exit 1 when the adapter returns an empty list."""
        with (
            patch(_PATCH_GET_SETTINGS),
            patch(_PATCH_FILE_ADAPTER) as mock_adapter_cls,
        ):
            mock_adapter = MagicMock()
            mock_adapter.discover_templates.return_value = []
            mock_adapter_cls.return_value = mock_adapter
            result = runner.invoke(app, ["templates"])
        assert result.exit_code == 1

    def test_exits_with_code_0_when_templates_exist(self) -> None:
        """Templates command must exit 0 when at least one template is found."""
        with (
            patch(_PATCH_GET_SETTINGS),
            patch(_PATCH_FILE_ADAPTER) as mock_adapter_cls,
            patch(_PATCH_DISPLAY_TEMPLATES_TABLE),
        ):
            mock_adapter = MagicMock()
            mock_adapter.discover_templates.return_value = [_make_template_info()]
            mock_adapter_cls.return_value = mock_adapter
            result = runner.invoke(app, ["templates"])
        assert result.exit_code == 0

    def test_output_contains_no_templates_message_when_empty(self) -> None:
        """Templates command output must mention no templates when list is empty."""
        with (
            patch(_PATCH_GET_SETTINGS),
            patch(_PATCH_FILE_ADAPTER) as mock_adapter_cls,
        ):
            mock_adapter = MagicMock()
            mock_adapter.discover_templates.return_value = []
            mock_adapter_cls.return_value = mock_adapter
            result = runner.invoke(app, ["templates"])
        assert "No templates found" in result.output


class TestSchemasCommand:
    """Tests for the 'schemas' CLI command."""

    def test_exits_with_code_1_when_no_schemas_found(self) -> None:
        """Schemas command must exit 1 when the adapter returns an empty list."""
        with (
            patch(_PATCH_GET_SETTINGS),
            patch(_PATCH_FILE_ADAPTER) as mock_adapter_cls,
        ):
            mock_adapter = MagicMock()
            mock_adapter.discover_schemas.return_value = []
            mock_adapter_cls.return_value = mock_adapter
            result = runner.invoke(app, ["schemas"])
        assert result.exit_code == 1

    def test_exits_with_code_0_when_schemas_exist(self) -> None:
        """Schemas command must exit 0 when at least one schema is found."""
        schema = _make_schema_info()
        with (
            patch(_PATCH_GET_SETTINGS),
            patch(_PATCH_FILE_ADAPTER) as mock_adapter_cls,
        ):
            mock_adapter = MagicMock()
            mock_adapter.discover_schemas.return_value = [schema]
            mock_adapter_cls.return_value = mock_adapter
            result = runner.invoke(app, ["schemas"])
        assert result.exit_code == 0

    def test_output_contains_schema_name(self) -> None:
        """Schemas command output must include the schema name."""
        schema = _make_schema_info("resume")
        with (
            patch(_PATCH_GET_SETTINGS),
            patch(_PATCH_FILE_ADAPTER) as mock_adapter_cls,
        ):
            mock_adapter = MagicMock()
            mock_adapter.discover_schemas.return_value = [schema]
            mock_adapter_cls.return_value = mock_adapter
            result = runner.invoke(app, ["schemas"])
        assert "resume" in result.output

    def test_output_contains_no_schemas_message_when_empty(self) -> None:
        """Schemas command output must mention no schemas when list is empty."""
        with (
            patch(_PATCH_GET_SETTINGS),
            patch(_PATCH_FILE_ADAPTER) as mock_adapter_cls,
        ):
            mock_adapter = MagicMock()
            mock_adapter.discover_schemas.return_value = []
            mock_adapter_cls.return_value = mock_adapter
            result = runner.invoke(app, ["schemas"])
        assert "No schemas found" in result.output


class TestPreviewCommand:
    """Tests for the 'preview' CLI command."""

    def test_exits_with_code_1_for_missing_template(self) -> None:
        """Preview command must exit 1 when the template is not found."""
        with (
            patch(_PATCH_GET_SETTINGS),
            patch(_PATCH_FILE_ADAPTER) as mock_adapter_cls,
        ):
            mock_adapter = MagicMock()
            mock_adapter.load_template.side_effect = TemplateError("Template not found: missing_template")
            mock_adapter_cls.return_value = mock_adapter
            result = runner.invoke(app, ["preview", "missing_template"])
        assert result.exit_code == 1

    def test_exits_with_code_0_for_valid_template(self) -> None:
        """Preview command must exit 0 when the template exists and schema resolves."""
        template = _make_template_info("test_resume")
        with (
            patch(_PATCH_GET_SETTINGS),
            patch(_PATCH_FILE_ADAPTER) as mock_adapter_cls,
        ):
            mock_adapter = MagicMock()
            mock_adapter.load_template.return_value = template
            mock_adapter.resolve_schema_for_template.return_value = "resume"
            mock_adapter.load_schema.return_value = _make_schema_info("resume")
            mock_adapter_cls.return_value = mock_adapter
            result = runner.invoke(app, ["preview", "test_resume"])
        assert result.exit_code == 0

    def test_output_contains_template_name(self) -> None:
        """Preview command output must contain the template name."""
        template = _make_template_info("test_resume")
        with (
            patch(_PATCH_GET_SETTINGS),
            patch(_PATCH_FILE_ADAPTER) as mock_adapter_cls,
        ):
            mock_adapter = MagicMock()
            mock_adapter.load_template.return_value = template
            mock_adapter.resolve_schema_for_template.return_value = "resume"
            mock_adapter.load_schema.return_value = _make_schema_info("resume")
            mock_adapter_cls.return_value = mock_adapter
            result = runner.invoke(app, ["preview", "test_resume"])
        assert "test_resume" in result.output

    def test_error_output_contains_template_name_on_not_found(self) -> None:
        """Preview command output must mention the missing template name on failure."""
        with (
            patch(_PATCH_GET_SETTINGS),
            patch(_PATCH_FILE_ADAPTER) as mock_adapter_cls,
        ):
            mock_adapter = MagicMock()
            mock_adapter.load_template.side_effect = TemplateError("Template not found: no_such")
            mock_adapter_cls.return_value = mock_adapter
            result = runner.invoke(app, ["preview", "no_such"])
        assert "no_such" in result.output


class TestVersionFlag:
    """Tests for the --version global flag."""

    def test_exits_with_code_0(self) -> None:
        """--version flag must exit with code 0."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0

    def test_output_contains_version_string(self) -> None:
        """--version flag output must contain the version string '0.1.0'."""
        result = runner.invoke(app, ["--version"])
        assert "0.1.0" in result.output


class TestHelpFlag:
    """Tests for the --help global flag."""

    def test_exits_with_code_0(self) -> None:
        """--help flag must exit with code 0."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_output_contains_tailor(self) -> None:
        """--help flag output must mention 'tailor'."""
        result = runner.invoke(app, ["--help"])
        assert "tailor" in result.output.lower()


class TestNoSubcommand:
    """Tests for the callback path when no subcommand is provided."""

    def test_runs_wizard_when_no_subcommand(self) -> None:
        """Invoking with no subcommand must trigger the wizard."""
        with patch("tailor.display.wizard.run_wizard", return_value=0) as mock_wizard:
            result = runner.invoke(app, [])
        mock_wizard.assert_called_once()
        assert result.exit_code == 0


class TestTemplatesVerbose:
    """Tests for the templates command --verbose flag."""

    @pytest.mark.parametrize("flag", ["--verbose", "-v"])
    def test_verbose_flag_exits_0_when_templates_exist(self, flag: str) -> None:
        """Templates --verbose/-v must exit 0 when templates are found."""
        template = _make_template_info()
        with (
            patch(_PATCH_GET_SETTINGS),
            patch(_PATCH_FILE_ADAPTER) as mock_adapter_cls,
            patch(_PATCH_DISPLAY_TEMPLATES_TABLE),
        ):
            mock_adapter = MagicMock()
            mock_adapter.discover_templates.return_value = [template]
            mock_adapter_cls.return_value = mock_adapter
            result = runner.invoke(app, ["templates", flag])
        assert result.exit_code == 0
