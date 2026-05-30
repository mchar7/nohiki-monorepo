"""File I/O adapter for loading context files, job files, templates, and schemas."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from doc_template_service.core.metadata import parse_template_metadata

from tailor.core.types import JsonDict, OutputFormat
from tailor.exceptions import DataError, FileLoadError, SchemaError, TemplateError
from tailor.models.inputs import ContextFile, JobFile
from tailor.models.templates import SchemaInfo, TemplateInfo

if TYPE_CHECKING:
    from tailor.core.config import TailorSettings


class TailorFileAdapter:
    """Adapter for file I/O operations via cached indices."""

    def __init__(self, settings: TailorSettings) -> None:
        """Initialize with settings."""
        self._settings = settings
        self._templates_dir = settings.resolved_templates_dir
        self._schemas_dir = settings.resolved_schemas_dir

    @cached_property
    def _template_index(self) -> dict[str, TemplateInfo]:
        """Build template index once for O(1) lookups."""
        return {t.name: t for t in self._discover_templates_internal()}

    @cached_property
    def _schema_index(self) -> dict[str, SchemaInfo]:
        """Build schema index once for O(1) lookups."""
        return {s.name: s for s in self._discover_schemas_internal()}

    def load_context_files(self, paths: list[Path]) -> list[ContextFile]:
        """Load and validate context files."""
        return [self._load_context_file(p) for p in paths]

    def load_job_files(self, paths: list[Path]) -> list[JobFile]:
        """Load and validate job listing files."""
        return [self._load_job_file(p) for p in paths]

    def load_data_file(self, path: Path) -> JsonDict:
        """Load and validate manual JSON data file."""
        resolved = path if path.is_absolute() else Path.cwd() / path
        content = self._read_text_file(resolved)
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            msg = f"Invalid JSON in data file {resolved.name}: {e}"
            raise DataError(msg) from e

        if isinstance(data, dict):
            return data
        msg = f"Data file {resolved.name} must contain a JSON object"
        raise DataError(msg)

    def discover_templates(self) -> list[TemplateInfo]:
        """Return cached list of templates."""
        return list(self._template_index.values())

    def discover_schemas(self) -> list[SchemaInfo]:
        """Return cached list of schemas."""
        return list(self._schema_index.values())

    def load_template(self, name: str) -> TemplateInfo:
        """Load template by name with O(1) lookup."""
        if (template := self._template_index.get(name)) is not None:
            return template

        msg = f"Template not found: {name}"
        raise TemplateError(msg)

    def load_schema(self, name: str) -> SchemaInfo:
        """Load schema by name with O(1) lookup."""
        if (schema := self._schema_index.get(name)) is not None:
            return schema

        msg = f"Schema not found: {name}"
        raise SchemaError(msg)

    def resolve_schema_for_template(self, template_name: str) -> str:
        """Resolve the best-matching schema name for a template.

        Resolution order (first match wins):
        1. Template metadata ``content_schema`` field  (O(1))
        2. Exact schema name match on ``template_name``  (O(1))
        3. Substring match between template and schema names  (O(n))
        4. First discovered schema as fallback  (O(1))

        Raises:
            SchemaError: If no schemas are available at all.
        """
        template = self.load_template(template_name)
        if template.schema_name:
            return template.schema_name

        if template_name in self._schema_index:
            return template_name

        for schema in self._schema_index.values():
            if template_name in schema.name or schema.name in template_name:
                return schema.name

        if self._schema_index:
            return next(iter(self._schema_index))

        msg = f"No schemas available to resolve for template '{template_name}'"
        raise SchemaError(msg)

    def write_output(
        self,
        content: bytes | str,
        output_path: Path,
        *,
        create_dirs: bool = True,
    ) -> Path:
        """Write content to output path."""
        resolved = output_path if output_path.is_absolute() else self._settings.resolved_output_dir / output_path

        if create_dirs:
            resolved.parent.mkdir(parents=True, exist_ok=True)

        match content:
            case str():
                resolved.write_text(content, encoding="utf-8")
            case bytes():
                resolved.write_bytes(content)

        return resolved

    def generate_filename(
        self,
        template_name: str,
        output_format: OutputFormat,
        *,
        suffix: str | None = None,
    ) -> str:
        """Generate a filename for the output document."""
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        base = f"{template_name}_{date_str}_{suffix}" if suffix else f"{template_name}_{date_str}"
        return f"{base}.{output_format}"

    def _load_context_file(self, path: Path) -> ContextFile:
        """Load single context file."""
        resolved = path if path.is_absolute() else Path.cwd() / path
        content = self._read_text_file(resolved)
        return ContextFile(
            path=resolved,
            content=content,
            size_bytes=len(content.encode("utf-8")),
            word_count=len(content.split()),
        )

    def _load_job_file(self, path: Path) -> JobFile:
        """Load single job file."""
        resolved = path if path.is_absolute() else Path.cwd() / path
        content = self._read_text_file(resolved)
        return JobFile(
            path=resolved,
            content=content,
            size_bytes=len(content.encode("utf-8")),
        )

    def _discover_templates_internal(self) -> list[TemplateInfo]:
        """Internal template discovery (unsorted, for index building)."""
        if not self._templates_dir.exists():
            return []
        return [t for path in self._templates_dir.glob("*.html") if (t := self._try_load_template(path)) is not None]

    def _discover_schemas_internal(self) -> list[SchemaInfo]:
        """Internal schema discovery (unsorted, for index building)."""
        if not self._schemas_dir.exists():
            return []
        return [s for path in self._schemas_dir.glob("*.json") if (s := self._try_load_schema(path)) is not None]

    def _try_load_template(self, path: Path) -> TemplateInfo | None:
        """Attempt to load template, returning None on failure."""
        try:
            return self._load_template_from_path(path)
        except TemplateError:
            return None

    def _try_load_schema(self, path: Path) -> SchemaInfo | None:
        """Attempt to load schema, returning None on failure."""
        try:
            return self._load_schema_from_path(path)
        except SchemaError:
            return None

    def _load_template_from_path(self, path: Path) -> TemplateInfo:
        """Load template from file path."""
        content = self._read_template_content(path)
        metadata = self._parse_template_metadata(path, content)
        schema_name_val = metadata.get("content_schema")
        return TemplateInfo(
            path=path,
            name=str(metadata["name"]),
            content=content,
            version=str(metadata.get("version", "1.0.0")),
            description=str(metadata.get("description", "")),
            access_scope=str(metadata.get("access_scope", "PUBLIC")),
            namespace=str(metadata.get("namespace", "default")),
            schema_name=schema_name_val if isinstance(schema_name_val, str) else None,
        )

    def _load_schema_from_path(self, path: Path) -> SchemaInfo:
        """Load schema from file path."""
        schema_dict = self._read_schema_content(path)
        name = self._extract_schema_name(path.stem)
        title_val = schema_dict.get("title")
        desc_val = schema_dict.get("description")
        return SchemaInfo(
            path=path,
            name=name,
            content=schema_dict,
            title=title_val if isinstance(title_val, str) else None,
            description=desc_val if isinstance(desc_val, str) else None,
        )

    def _read_template_content(self, path: Path) -> str:
        """Read template file content."""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            msg = f"Failed to read template: {e}"
            raise TemplateError(msg) from e

    def _parse_template_metadata(self, path: Path, content: str) -> JsonDict:
        """Parse template metadata from content."""
        try:
            return parse_template_metadata(content)
        except ValueError as e:
            msg = f"Invalid template metadata in {path.name}: {e}"
            raise TemplateError(msg) from e

    def _read_schema_content(self, path: Path) -> JsonDict:
        """Read and parse schema JSON content."""
        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                return data
            msg = f"Schema {path.name} must contain a JSON object"
            raise SchemaError(msg)
        except OSError as e:
            msg = f"Failed to read schema: {e}"
            raise SchemaError(msg) from e
        except json.JSONDecodeError as e:
            msg = f"Invalid JSON in schema {path.name}: {e}"
            raise SchemaError(msg) from e

    @staticmethod
    def _extract_schema_name(stem: str) -> str:
        """Extract clean schema name from filename stem."""
        return stem.removeprefix("default_").removesuffix("_schema")

    def _read_text_file(self, path: Path) -> str:
        """Read text file content."""
        if not path.exists():
            msg = f"File not found: {path}"
            raise FileLoadError(msg, path=str(path))
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            msg = f"Failed to read file: {e}"
            raise FileLoadError(msg, path=str(path)) from e
