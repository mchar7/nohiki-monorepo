"""Context dataclass for tailoring operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tailor.core.types import OutputSpec


@dataclass
class TailorContext:
    """Complete context for a tailoring operation.

    This dataclass holds all the state needed to execute a full tailoring pipeline,
    and is used by both interactive and CLI modes.
    """

    context_file_paths: list[Path] = field(default_factory=list)
    job_file_paths: list[Path] = field(default_factory=list)
    data_file_path: Path | None = None
    template_name: str = ""
    schema_name: str = ""
    outputs: list[OutputSpec] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """Check if all required fields are set."""
        if self.is_manual_mode:
            return bool(self.data_file_path and self.template_name and self.schema_name and self.outputs)
        return bool(
            self.context_file_paths and self.job_file_paths and self.template_name and self.schema_name and self.outputs
        )

    @property
    def is_manual_mode(self) -> bool:
        """Check if manual JSON data mode is enabled."""
        return self.data_file_path is not None

    @property
    def missing_fields(self) -> list[str]:
        """Get list of missing required fields."""
        missing = []
        if self.is_manual_mode:
            if self.data_file_path is None:
                missing.append("data_file_path")
        else:
            if not self.context_file_paths:
                missing.append("context_file_paths")
            if not self.job_file_paths:
                missing.append("job_file_paths")
        if not self.template_name:
            missing.append("template_name")
        if not self.schema_name:
            missing.append("schema_name")
        if not self.outputs:
            missing.append("outputs")
        return missing
