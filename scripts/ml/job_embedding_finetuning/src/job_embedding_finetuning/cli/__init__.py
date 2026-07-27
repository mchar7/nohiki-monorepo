"""CLI entry point for Job Embedding Finetuning tool."""

from __future__ import annotations

import typer
from rich.console import Console

from job_embedding_finetuning.cli.commands import download, evaluate, prepare, status, train

console = Console(stderr=True)

app = typer.Typer(
    name="job-embedding-finetune",
    help="[bold blue]Job Embedding Finetuning CLI[/bold blue]\n\nFinetune Qwen3-Embedding-0.6B on job domain data.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(download.app, name="download", help="Download datasets from HuggingFace.")
app.add_typer(prepare.app, name="prepare", help="Generate training pairs from datasets.")
app.add_typer(train.app, name="train", help="Finetune the embedding model.")
app.add_typer(evaluate.app, name="evaluate", help="Evaluate model against benchmarks.")
app.add_typer(status.app, name="status", help="Check dataset and training status.")

__all__ = ["app", "console"]
