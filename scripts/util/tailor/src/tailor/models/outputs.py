"""Output data models for tailor CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from tailor.core.types import JsonDict, OutputSpec
from tailor.lint.models import LintIssue, Severity

# Approximate per-token cost rates for rough estimates (Claude-class models)
_INPUT_COST_PER_MILLION: Final[float] = 3.0
_OUTPUT_COST_PER_MILLION: Final[float] = 15.0
_CACHE_COST_PER_MILLION: Final[float] = 0.30
_MILLION: Final[int] = 1_000_000


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Result from LLM content generation."""

    content: JsonDict
    prompt_tokens: int
    completion_tokens: int
    model_used: str
    duration_seconds: float
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.prompt_tokens + self.completion_tokens

    @property
    def cache_hit_ratio(self) -> float:
        """Cache hit ratio (0.0-1.0)."""
        if self.prompt_tokens == 0:
            return 0.0
        return self.cache_read_tokens / self.prompt_tokens

    @property
    def estimated_cost_usd(self) -> float:
        """Rough cost estimate in USD based on approximate token pricing."""
        input_cost = (self.prompt_tokens - self.cache_read_tokens) * _INPUT_COST_PER_MILLION / _MILLION
        output_cost = self.completion_tokens * _OUTPUT_COST_PER_MILLION / _MILLION
        cache_cost = self.cache_read_tokens * _CACHE_COST_PER_MILLION / _MILLION
        return input_cost + output_cost + cache_cost


@dataclass(frozen=True, slots=True)
class RenderResult:
    """Result from template rendering."""

    content: bytes | str
    content_type: str
    size_bytes: int

    @property
    def is_binary(self) -> bool:
        """Check if content is binary (PDF, image)."""
        return isinstance(self.content, bytes)


@dataclass(frozen=True, slots=True)
class OutputResult:
    """Result for a single rendered output.

    Args:
        spec: The output specification (path + format).
        render_result: The render result for this output.
        written_path: The actual path the file was written to.
    """

    spec: OutputSpec
    render_result: RenderResult
    written_path: Path


@dataclass(frozen=True, slots=True)
class TailorOutput:
    """Complete output from a tailoring operation."""

    outputs: list[OutputResult]
    generation_result: GenerationResult
    lint_issues: list[LintIssue] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        """Total tokens used in generation."""
        return self.generation_result.total_tokens

    @property
    def estimated_cost_usd(self) -> float:
        """Estimated cost in USD."""
        return self.generation_result.estimated_cost_usd

    @property
    def total_duration_seconds(self) -> float:
        """Total generation duration."""
        return self.generation_result.duration_seconds

    @property
    def total_output_size_bytes(self) -> int:
        """Total size of all rendered outputs in bytes."""
        return sum(o.render_result.size_bytes for o in self.outputs)

    @property
    def has_lint_errors(self) -> bool:
        """Check if any lint issues have ERROR severity."""
        return any(i.severity == Severity.ERROR for i in self.lint_issues)

    @property
    def lint_error_count(self) -> int:
        """Count of ERROR-severity lint issues."""
        return sum(1 for i in self.lint_issues if i.severity == Severity.ERROR)

    @property
    def lint_warning_count(self) -> int:
        """Count of WARNING-severity lint issues."""
        return sum(1 for i in self.lint_issues if i.severity == Severity.WARNING)
