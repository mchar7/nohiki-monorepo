"""Template and schema info models for tailor CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tailor.core.types import JsonDict


@dataclass(frozen=True, slots=True)
class TemplateInfo:
    """Information about a document template."""

    path: Path
    name: str
    content: str
    version: str
    description: str
    access_scope: str
    namespace: str = "default"
    schema_name: str | None = None

    @property
    def filename(self) -> str:
        """Get the filename."""
        return self.path.name

    @property
    def display_name(self) -> str:
        """Human-readable display name."""
        return self.name.replace("_", " ").replace("-", " ").title()


@dataclass(frozen=True, slots=True)
class SchemaInfo:
    """Information about a JSON schema."""

    path: Path
    name: str
    content: JsonDict
    title: str | None = None
    description: str | None = None

    @property
    def filename(self) -> str:
        """Get the filename."""
        return self.path.name

    @property
    def display_name(self) -> str:
        """Human-readable display name."""
        if self.title:
            return self.title
        return self.name.replace("_", " ").replace("-", " ").title()

    @property
    def required_fields(self) -> list[str]:
        """Get list of required top-level fields."""
        required = self.content.get("required", [])
        if not isinstance(required, list):
            return []
        return [item for item in required if isinstance(item, str)]

    @property
    def properties(self) -> JsonDict:
        """Get schema properties."""
        props = self.content.get("properties", {})
        if not isinstance(props, dict):
            return {}
        return props
