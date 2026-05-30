"""Input data models for tailor CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tailor.core.types import JsonDict, OutputSpec


@dataclass(frozen=True, slots=True)
class ContextFile:
    """A loaded context file (personal information, examples, etc.)."""

    path: Path
    content: str
    size_bytes: int
    word_count: int

    @property
    def filename(self) -> str:
        """Get the filename without directory."""
        return self.path.name


@dataclass(frozen=True, slots=True)
class JobFile:
    """A loaded job listing file."""

    path: Path
    content: str
    size_bytes: int

    @property
    def filename(self) -> str:
        """Get the filename without directory."""
        return self.path.name


@dataclass(slots=True)
class TailorInput:
    """Complete input for a tailoring operation."""

    context_files: list[ContextFile] = field(default_factory=list)
    job_files: list[JobFile] = field(default_factory=list)
    template_name: str = ""
    schema_name: str = ""
    outputs: list[OutputSpec] = field(default_factory=list)
    template_content: str = ""
    schema_content: JsonDict = field(default_factory=dict)
    template_path: Path | None = None

    @property
    def total_context_size(self) -> int:
        """Total size of all context files in bytes."""
        return sum(f.size_bytes for f in self.context_files)

    @property
    def total_job_size(self) -> int:
        """Total size of all job files in bytes."""
        return sum(f.size_bytes for f in self.job_files)

    @property
    def combined_context_content(self) -> str:
        """Combine all context file contents with separators."""
        if not self.context_files:
            return ""
        parts: list[str] = []
        for f in self.context_files:
            parts.append(f"--- {f.filename} ---")
            parts.append(f.content)
            parts.append("")
        return "\n".join(parts)

    @property
    def combined_job_content(self) -> str:
        """Combine all job file contents with separators."""
        if not self.job_files:
            return ""
        parts: list[str] = []
        for f in self.job_files:
            parts.append(f"--- {f.filename} ---")
            parts.append(f.content)
            parts.append("")
        return "\n".join(parts)
