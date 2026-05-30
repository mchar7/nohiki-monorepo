"""Rich panels and tables for tailor CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tailor.display.console import (
    ICON_BULLET,
    ICON_ERROR,
    ICON_INFO,
    ICON_SUCCESS,
    ICON_WARNING,
    STYLE_DIM,
    STYLE_ERROR,
    STYLE_HIGHLIGHT,
    STYLE_INFO,
    STYLE_SUCCESS,
    STYLE_WARNING,
    console,
    format_cost,
    format_duration,
    format_size,
    format_tokens,
)
from tailor.lint.models import Severity

if TYPE_CHECKING:
    from tailor.lint.models import LintIssue
    from tailor.models.inputs import TailorInput
    from tailor.models.outputs import TailorOutput
    from tailor.models.templates import TemplateInfo


# Lint display constants: severity ordering, icons, and Rich styles.
_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.ERROR: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}
_SEVERITY_ICON: dict[Severity, str] = {
    Severity.ERROR: ICON_ERROR,
    Severity.WARNING: ICON_WARNING,
    Severity.INFO: ICON_INFO,
}
_SEVERITY_STYLE: dict[Severity, str] = {
    Severity.ERROR: STYLE_ERROR,
    Severity.WARNING: STYLE_WARNING,
    Severity.INFO: STYLE_INFO,
}


def display_success(output: TailorOutput) -> None:
    """Display success panel with output details."""
    gen = output.generation_result

    content = Text()
    for out in output.outputs:
        content.append(f"{ICON_SUCCESS} ", style=STYLE_SUCCESS)
        content.append(str(out.written_path), style=STYLE_HIGHLIGHT)
        content.append(f" ({format_size(out.render_result.size_bytes)})\n")

    panel = Panel(
        content,
        title="[bold green]Success[/bold green]",
        border_style="green",
        padding=(0, 1),
    )
    console.print(panel)

    display_metrics(
        gen.prompt_tokens,
        gen.completion_tokens,
        gen.duration_seconds,
        gen.estimated_cost_usd,
    )

    if gen.cache_read_tokens > 0 or gen.cache_write_tokens > 0:
        cache_text = Text()
        cache_text.append(f"  {ICON_BULLET} Cache: ", style=STYLE_DIM)
        cache_text.append(f"{format_tokens(gen.cache_read_tokens)} read", style=STYLE_HIGHLIGHT)
        cache_text.append(" / ", style=STYLE_DIM)
        cache_text.append(f"{format_tokens(gen.cache_write_tokens)} write", style=STYLE_HIGHLIGHT)
        cache_text.append(f" ({gen.cache_hit_ratio * 100:.1f}% hit rate)", style=STYLE_DIM)
        console.print(cache_text)


def display_error(message: str, *, title: str = "Error") -> None:
    """Display error panel."""
    panel = Panel(
        Text(message, style=STYLE_ERROR),
        title=f"[bold red]{title}[/bold red]",
        border_style="red",
        padding=(0, 1),
    )
    console.print(panel)


def display_metrics(
    prompt_tokens: int,
    completion_tokens: int,
    duration_seconds: float,
    cost_usd: float,
) -> None:
    """Display token metrics."""
    text = Text()
    text.append(f"  {ICON_BULLET} Tokens: ", style=STYLE_DIM)
    text.append(format_tokens(prompt_tokens), style=STYLE_HIGHLIGHT)
    text.append(" (prompt) + ", style=STYLE_DIM)
    text.append(format_tokens(completion_tokens), style=STYLE_HIGHLIGHT)
    text.append(" (completion) = ", style=STYLE_DIM)
    text.append(format_tokens(prompt_tokens + completion_tokens), style=STYLE_HIGHLIGHT)
    text.append(" total", style=STYLE_DIM)
    console.print(text)

    text2 = Text()
    text2.append(f"  {ICON_BULLET} Duration: ", style=STYLE_DIM)
    text2.append(format_duration(duration_seconds), style=STYLE_HIGHLIGHT)
    text2.append(f"  {ICON_BULLET} Est. cost: ", style=STYLE_DIM)
    text2.append(format_cost(cost_usd), style=STYLE_HIGHLIGHT)
    console.print(text2)


def display_summary(tailor_input: TailorInput, model: str) -> None:
    """Display pre-generation summary panel."""
    content = Text()

    content.append("Context: ", style="bold")
    content.append(f"{len(tailor_input.context_files)} files ")
    content.append(f"({format_size(tailor_input.total_context_size)})", style=STYLE_DIM)
    content.append("\n")

    content.append("Job: ", style="bold")
    content.append(f"{len(tailor_input.job_files)} file(s) ")
    content.append(f"({format_size(tailor_input.total_job_size)})", style=STYLE_DIM)
    content.append("\n")

    content.append("Template: ", style="bold")
    content.append(tailor_input.template_name, style=STYLE_HIGHLIGHT)
    content.append("\n")

    for spec in tailor_input.outputs:
        content.append("Output: ", style="bold")
        content.append(f"{spec.path} ", style=STYLE_HIGHLIGHT)
        content.append(f"({spec.format})", style=STYLE_DIM)
        content.append("\n")

    content.append("Model: ", style="bold")
    content.append(model, style=STYLE_HIGHLIGHT)

    panel = Panel(
        content,
        title="[bold]Summary[/bold]",
        border_style="cyan",
        padding=(0, 1),
    )
    console.print(panel)


def display_templates_table(templates: list[TemplateInfo]) -> None:
    """Display a table of available templates."""
    table = Table(
        title="[bold]Available Templates[/bold]",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("#", justify="center", width=4)
    table.add_column("Name", style="cyan bold")
    table.add_column("Description")
    table.add_column("Version", justify="center", width=10)

    for i, template in enumerate(templates, 1):
        table.add_row(
            f"[{i}]",
            template.name,
            template.description or "-",
            template.version,
        )

    console.print(table)


def display_lint_issues(issues: list[LintIssue]) -> None:
    """Display lint issues as a sorted table, grouped by severity.

    Silently returns when the issues list is empty — no noise when clean.
    Issues are sorted ERROR → WARNING → INFO for visual clarity.

    Args:
        issues: Lint issues from the content lint pipeline.
    """
    if not issues:
        return

    sorted_issues = sorted(issues, key=lambda i: _SEVERITY_ORDER.get(i.severity, 99))

    error_count = sum(1 for i in issues if i.severity == Severity.ERROR)
    warning_count = sum(1 for i in issues if i.severity == Severity.WARNING)

    table = Table(
        title="[bold]Lint Issues[/bold]",
        show_header=True,
        header_style="bold dim",
        border_style="dim",
        expand=False,
    )
    table.add_column("Level", width=10)
    table.add_column("Rule", style=STYLE_DIM)
    table.add_column("Path", style=STYLE_DIM)
    table.add_column("Message")

    for issue in sorted_issues:
        icon = _SEVERITY_ICON.get(issue.severity, "")
        style = _SEVERITY_STYLE.get(issue.severity, "")
        table.add_row(
            f"{icon} {issue.severity.upper()}",
            issue.rule,
            issue.path or "—",
            issue.message,
            style=style,
        )

    console.print(table)

    parts: list[str] = []
    if error_count:
        parts.append(f"[bold red]{error_count} error(s)[/bold red]")
    if warning_count:
        parts.append(f"[bold yellow]{warning_count} warning(s)[/bold yellow]")
    info_count = len(issues) - error_count - warning_count
    if info_count:
        parts.append(f"[cyan]{info_count} note(s)[/cyan]")
    if parts:
        console.print(f"  {ICON_BULLET} Lint: " + ", ".join(parts))
