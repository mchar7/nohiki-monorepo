"""Tests for tailor.adapters.file_adapter -- TailorFileAdapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from tailor.adapters.file_adapter import TailorFileAdapter
from tailor.core.config import TailorSettings
from tailor.exceptions import DataError, FileLoadError, SchemaError, TemplateError
from tailor.models.templates import SchemaInfo, TemplateInfo

_VALID_TEMPLATE_HTML = (
    '<!-- TMPL_META {"name": "my_template", "title": "My Template", "version": "2.0.0", "description": "Test",'
    ' "access_scope": "PUBLIC", "visibility": "public", "namespace": "default"} -->\n'
    "<html><body>Hello</body></html>\n"
)

_TEMPLATE_WITH_SCHEMA_HTML = (
    '<!-- TMPL_META {"name": "my_template", "title": "My Template", "version": "1.0.0", "description": "Test",'
    ' "access_scope": "PUBLIC", "visibility": "public", "namespace": "default", "content_schema": "resume"} -->\n'
    "<html><body>Hello</body></html>\n"
)

_MISSING_META_HTML = "<html><body>No meta here</body></html>"

_MALFORMED_META_HTML = "<!-- TMPL_META {bad json -->\n<html><body></body></html>"

_VALID_SCHEMA_JSON = json.dumps({"title": "My Schema", "type": "object", "properties": {"name": {"type": "string"}}})


def make_settings(templates_dir: Path, schemas_dir: Path, output_dir: Path | None = None) -> MagicMock:
    """Create a MagicMock settings object pointing at provided directories."""
    settings = MagicMock(spec=TailorSettings)
    settings.resolved_templates_dir = templates_dir
    settings.resolved_schemas_dir = schemas_dir
    settings.resolved_output_dir = output_dir or (templates_dir.parent / "output")
    return settings


class TestTemplateDiscovery:
    """Tests for template discovery via _discover_templates_internal / discover_templates."""

    def test_empty_templates_dir_returns_empty_list(self, tmp_path: Path) -> None:
        """Empty templates directory yields no templates."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        adapter = TailorFileAdapter(make_settings(templates_dir, tmp_path / "schemas"))
        assert adapter.discover_templates() == []

    def test_nonexistent_templates_dir_returns_empty_list(self, tmp_path: Path) -> None:
        """Non-existent templates directory yields no templates."""
        adapter = TailorFileAdapter(make_settings(tmp_path / "no_such_dir", tmp_path / "schemas"))
        assert adapter.discover_templates() == []

    def test_valid_html_template_discovered(self, tmp_path: Path) -> None:
        """A valid HTML file with TMPL_META is discovered and parsed correctly."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "my_template.html").write_text(_VALID_TEMPLATE_HTML, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(templates_dir, tmp_path / "schemas"))
        templates = adapter.discover_templates()
        assert len(templates) == 1
        t = templates[0]
        assert t.name == "my_template"
        assert t.version == "2.0.0"
        assert t.description == "Test"

    def test_html_without_tmpl_meta_silently_skipped(self, tmp_path: Path) -> None:
        """HTML file missing TMPL_META comment is silently skipped."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "no_meta.html").write_text(_MISSING_META_HTML, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(templates_dir, tmp_path / "schemas"))
        assert adapter.discover_templates() == []

    def test_html_with_malformed_tmpl_meta_silently_skipped(self, tmp_path: Path) -> None:
        """HTML file with malformed TMPL_META JSON is silently skipped."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "bad_meta.html").write_text(_MALFORMED_META_HTML, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(templates_dir, tmp_path / "schemas"))
        assert adapter.discover_templates() == []

    def test_template_index_is_cached(self, tmp_path: Path) -> None:
        """The _template_index cached_property returns the same dict object on repeated access."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "my_template.html").write_text(_VALID_TEMPLATE_HTML, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(templates_dir, tmp_path / "schemas"))
        # Access via the cached_property twice; same dict object means caching works
        first_index = adapter._template_index
        second_index = adapter._template_index
        assert first_index is second_index

    def test_template_with_schema_name_populated(self, tmp_path: Path) -> None:
        """Template TMPL_META content_schema field is stored as schema_name."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "my_template.html").write_text(_TEMPLATE_WITH_SCHEMA_HTML, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(templates_dir, tmp_path / "schemas"))
        templates = adapter.discover_templates()
        assert len(templates) == 1
        assert templates[0].schema_name == "resume"


class TestSchemaDiscovery:
    """Tests for schema discovery via _discover_schemas_internal / discover_schemas."""

    def test_empty_schemas_dir_returns_empty_list(self, tmp_path: Path) -> None:
        """Empty schemas directory yields no schemas."""
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", schemas_dir))
        assert adapter.discover_schemas() == []

    def test_nonexistent_schemas_dir_returns_empty_list(self, tmp_path: Path) -> None:
        """Non-existent schemas directory yields no schemas."""
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "no_such_dir"))
        assert adapter.discover_schemas() == []

    def test_valid_json_schema_discovered(self, tmp_path: Path) -> None:
        """A valid JSON schema file is discovered and name is derived from stem."""
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        (schemas_dir / "resume_schema.json").write_text(_VALID_SCHEMA_JSON, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", schemas_dir))
        schemas = adapter.discover_schemas()
        assert len(schemas) == 1
        assert schemas[0].name == "resume"

    def test_non_json_file_silently_skipped(self, tmp_path: Path) -> None:
        """A non-JSON file (invalid JSON) is silently skipped."""
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        (schemas_dir / "broken.json").write_text("not json at all", encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", schemas_dir))
        assert adapter.discover_schemas() == []

    def test_json_array_silently_skipped(self, tmp_path: Path) -> None:
        """A JSON file containing an array (not object) is silently skipped."""
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        (schemas_dir / "array.json").write_text("[1, 2, 3]", encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", schemas_dir))
        assert adapter.discover_schemas() == []


class TestExtractSchemaName:
    """Tests for TailorFileAdapter._extract_schema_name."""

    def test_default_prefix_and_schema_suffix_stripped(self) -> None:
        """'default_resume_schema' → 'resume'."""
        assert TailorFileAdapter._extract_schema_name("default_resume_schema") == "resume"

    def test_default_prefix_stripped_with_underscore_name(self) -> None:
        """'default_cover_letter_schema' → 'cover_letter'."""
        assert TailorFileAdapter._extract_schema_name("default_cover_letter_schema") == "cover_letter"

    def test_only_schema_suffix_stripped(self) -> None:
        """'my_schema' → 'my' (suffix only stripped)."""
        assert TailorFileAdapter._extract_schema_name("my_schema") == "my"

    def test_plain_name_unchanged(self) -> None:
        """'just_name' has no prefix or suffix to strip."""
        assert TailorFileAdapter._extract_schema_name("just_name") == "just_name"


class TestLoadTemplateAndSchema:
    """Tests for load_template and load_schema index lookups."""

    def test_load_template_returns_template_info(self, tmp_path: Path) -> None:
        """load_template returns TemplateInfo for an existing template."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "my_template.html").write_text(_VALID_TEMPLATE_HTML, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(templates_dir, tmp_path / "schemas"))
        result = adapter.load_template("my_template")
        assert isinstance(result, TemplateInfo)
        assert result.name == "my_template"

    def test_load_template_raises_template_error_for_missing(self, tmp_path: Path) -> None:
        """load_template raises TemplateError for an unknown template name."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        adapter = TailorFileAdapter(make_settings(templates_dir, tmp_path / "schemas"))
        with pytest.raises(TemplateError, match="not found"):
            adapter.load_template("nonexistent")

    def test_load_schema_returns_schema_info(self, tmp_path: Path) -> None:
        """load_schema returns SchemaInfo for an existing schema."""
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        (schemas_dir / "resume_schema.json").write_text(_VALID_SCHEMA_JSON, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", schemas_dir))
        result = adapter.load_schema("resume")
        assert isinstance(result, SchemaInfo)
        assert result.name == "resume"

    def test_load_schema_raises_schema_error_for_missing(self, tmp_path: Path) -> None:
        """load_schema raises SchemaError for an unknown schema name."""
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", schemas_dir))
        with pytest.raises(SchemaError, match="not found"):
            adapter.load_schema("nonexistent")


class TestResolveSchemaForTemplate:
    """Tests for the schema resolution priority chain."""

    def _make_adapter_with_template_and_schema(
        self,
        tmp_path: Path,
        template_html: str,
        template_filename: str = "my_template.html",
        schema_filename: str = "resume_schema.json",
    ) -> TailorFileAdapter:
        """Build adapter with one template and one schema file."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir(exist_ok=True)
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir(exist_ok=True)
        (templates_dir / template_filename).write_text(template_html, encoding="utf-8")
        (schemas_dir / schema_filename).write_text(_VALID_SCHEMA_JSON, encoding="utf-8")
        return TailorFileAdapter(make_settings(templates_dir, schemas_dir))

    def test_priority_1_template_schema_name_metadata(self, tmp_path: Path) -> None:
        """Template content_schema metadata wins (priority 1)."""
        adapter = self._make_adapter_with_template_and_schema(tmp_path, _TEMPLATE_WITH_SCHEMA_HTML)
        result = adapter.resolve_schema_for_template("my_template")
        assert result == "resume"

    def test_priority_2_exact_schema_name_match(self, tmp_path: Path) -> None:
        """Exact match on schema name wins when template has no schema_name (priority 2)."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        # Template name "resume" with no content_schema
        template_html = (
            '<!-- TMPL_META {"name": "resume", "title": "Resume", "version": "1.0.0", "description": "T",'
            ' "access_scope": "PUBLIC", "visibility": "public", "namespace": "default"} -->\n<html></html>'
        )
        (templates_dir / "resume.html").write_text(template_html, encoding="utf-8")
        (schemas_dir / "resume_schema.json").write_text(_VALID_SCHEMA_JSON, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(templates_dir, schemas_dir))
        result = adapter.resolve_schema_for_template("resume")
        assert result == "resume"

    def test_priority_3_template_name_is_substring_of_schema_name(self, tmp_path: Path) -> None:
        """Schema name containing template name matches (priority 3 substring)."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        # Template name "cover" -- no content_schema
        template_html = (
            '<!-- TMPL_META {"name": "cover", "title": "Cover", "version": "1.0.0", "description": "T",'
            ' "access_scope": "PUBLIC", "visibility": "public", "namespace": "default"} -->\n<html></html>'
        )
        (templates_dir / "cover.html").write_text(template_html, encoding="utf-8")
        # Schema named "cover_letter" -- contains "cover"
        schema = json.dumps({"title": "Cover Letter Schema", "type": "object"})
        (schemas_dir / "cover_letter_schema.json").write_text(schema, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(templates_dir, schemas_dir))
        result = adapter.resolve_schema_for_template("cover")
        assert result == "cover_letter"

    def test_priority_3_schema_name_is_substring_of_template_name(self, tmp_path: Path) -> None:
        """Template name containing schema name matches (priority 3 substring)."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        # Template name "resume_detailed" -- no content_schema
        template_html = (
            '<!-- TMPL_META {"name": "resume_detailed", "title": "Resume Detailed",'
            ' "version": "1.0.0", "description": "T",'
            ' "access_scope": "PUBLIC", "visibility": "public", "namespace": "default"} -->\n<html></html>'
        )
        (templates_dir / "resume_detailed.html").write_text(template_html, encoding="utf-8")
        (schemas_dir / "resume_schema.json").write_text(_VALID_SCHEMA_JSON, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(templates_dir, schemas_dir))
        result = adapter.resolve_schema_for_template("resume_detailed")
        assert result == "resume"

    def test_priority_4_first_schema_as_fallback(self, tmp_path: Path) -> None:
        """First available schema is returned when no match found (priority 4)."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        # Template name "zyx" with no content_schema -- no substring match possible
        template_html = (
            '<!-- TMPL_META {"name": "zyx", "title": "Zyx", "version": "1.0.0", "description": "T",'
            ' "access_scope": "PUBLIC", "visibility": "public", "namespace": "default"} -->\n<html></html>'
        )
        (templates_dir / "zyx.html").write_text(template_html, encoding="utf-8")
        (schemas_dir / "alpha_schema.json").write_text(_VALID_SCHEMA_JSON, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(templates_dir, schemas_dir))
        result = adapter.resolve_schema_for_template("zyx")
        assert result == "alpha"

    def test_raises_schema_error_when_no_schemas_available(self, tmp_path: Path) -> None:
        """SchemaError is raised when no schemas exist at all."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        template_html = (
            '<!-- TMPL_META {"name": "my_template", "title": "My Template", "version": "1.0.0", "description": "T",'
            ' "access_scope": "PUBLIC", "visibility": "public", "namespace": "default"} -->\n<html></html>'
        )
        (templates_dir / "my_template.html").write_text(template_html, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(templates_dir, schemas_dir))
        with pytest.raises(SchemaError):
            adapter.resolve_schema_for_template("my_template")

    def test_raises_template_error_for_missing_template(self, tmp_path: Path) -> None:
        """TemplateError is raised when the template does not exist."""
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        with pytest.raises(TemplateError):
            adapter.resolve_schema_for_template("nonexistent")


class TestLoadContextFiles:
    """Tests for load_context_files."""

    def test_loads_file_content_correctly(self, tmp_path: Path) -> None:
        """Context file content is correctly read."""
        f = tmp_path / "ctx.txt"
        f.write_text("hello world", encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        results = adapter.load_context_files([f])
        assert len(results) == 1
        assert results[0].content == "hello world"

    def test_size_bytes_is_utf8_length(self, tmp_path: Path) -> None:
        """size_bytes reflects the UTF-8 encoded byte count."""
        content = "caf\u00e9"  # 5 UTF-8 bytes
        f = tmp_path / "ctx.txt"
        f.write_text(content, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        results = adapter.load_context_files([f])
        assert results[0].size_bytes == len(content.encode("utf-8"))

    def test_word_count_is_correct(self, tmp_path: Path) -> None:
        """word_count matches the whitespace-split word count."""
        content = "one two three four"
        f = tmp_path / "ctx.txt"
        f.write_text(content, encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        results = adapter.load_context_files([f])
        assert results[0].word_count == 4

    def test_raises_file_load_error_for_missing_file(self, tmp_path: Path) -> None:
        """FileLoadError is raised when context file does not exist."""
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        with pytest.raises(FileLoadError):
            adapter.load_context_files([tmp_path / "missing.txt"])


class TestLoadJobFiles:
    """Tests for load_job_files."""

    def test_loads_job_file_content(self, tmp_path: Path) -> None:
        """Job file content is correctly read."""
        f = tmp_path / "job.txt"
        f.write_text("Software Engineer at Acme", encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        results = adapter.load_job_files([f])
        assert results[0].content == "Software Engineer at Acme"

    def test_raises_file_load_error_for_missing_job_file(self, tmp_path: Path) -> None:
        """FileLoadError is raised when job file does not exist."""
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        with pytest.raises(FileLoadError):
            adapter.load_job_files([tmp_path / "missing_job.txt"])


class TestLoadDataFile:
    """Tests for load_data_file."""

    def test_valid_json_dict_returned(self, tmp_path: Path) -> None:
        """Valid JSON dict file is loaded and returned."""
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}', encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        result = adapter.load_data_file(f)
        assert result == {"key": "value"}

    def test_json_array_raises_data_error(self, tmp_path: Path) -> None:
        """A JSON array (not object) raises DataError."""
        f = tmp_path / "data.json"
        f.write_text("[1, 2, 3]", encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        with pytest.raises(DataError, match="must contain a JSON object"):
            adapter.load_data_file(f)

    def test_invalid_json_raises_data_error(self, tmp_path: Path) -> None:
        """Invalid JSON content raises DataError."""
        f = tmp_path / "data.json"
        f.write_text("not json {{{", encoding="utf-8")
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        with pytest.raises(DataError, match="Invalid JSON"):
            adapter.load_data_file(f)

    def test_missing_file_raises_file_load_error(self, tmp_path: Path) -> None:
        """Missing data file raises FileLoadError."""
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        with pytest.raises(FileLoadError):
            adapter.load_data_file(tmp_path / "no_such.json")


class TestWriteOutput:
    """Tests for write_output."""

    def test_string_content_written_as_text(self, tmp_path: Path) -> None:
        """String content is written as a UTF-8 text file."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas", output_dir))
        out = adapter.write_output("hello text", output_dir / "out.html")
        assert out.read_text(encoding="utf-8") == "hello text"

    def test_bytes_content_written_as_binary(self, tmp_path: Path) -> None:
        """Bytes content is written as a binary file."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas", output_dir))
        data = b"\x25\x50\x44\x46"  # %PDF
        out = adapter.write_output(data, output_dir / "out.pdf")
        assert out.read_bytes() == data

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Parent directories are created when create_dirs=True."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas", output_dir))
        nested = output_dir / "a" / "b" / "c" / "out.txt"
        adapter.write_output("content", nested, create_dirs=True)
        assert nested.exists()

    def test_absolute_path_used_as_is(self, tmp_path: Path) -> None:
        """An absolute output path is written directly without resolving via output_dir."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        absolute_path = tmp_path / "direct.txt"
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas", output_dir))
        out = adapter.write_output("direct", absolute_path)
        assert out == absolute_path
        assert absolute_path.read_text(encoding="utf-8") == "direct"

    def test_relative_path_resolved_via_output_dir(self, tmp_path: Path) -> None:
        """A relative path is resolved against resolved_output_dir."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas", output_dir))
        out = adapter.write_output("data", Path("result.txt"))
        assert out == output_dir / "result.txt"
        assert out.read_text(encoding="utf-8") == "data"


class TestGenerateFilename:
    """Tests for generate_filename."""

    def test_returns_expected_format(self, tmp_path: Path) -> None:
        """Filename follows '{template}_{date}.{format}' pattern."""
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        result = adapter.generate_filename("my_template", "pdf")
        assert result == f"my_template_{today}.pdf"

    def test_with_suffix_included_in_filename(self, tmp_path: Path) -> None:
        """Suffix is appended between date and extension."""
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        result = adapter.generate_filename("my_template", "pdf", suffix="v1")
        assert result == f"my_template_{today}_v1.pdf"

    def test_date_is_today(self, tmp_path: Path) -> None:
        """The date portion of the filename is today's ISO date."""
        adapter = TailorFileAdapter(make_settings(tmp_path / "templates", tmp_path / "schemas"))
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        result = adapter.generate_filename("resume", "html")
        assert today in result
