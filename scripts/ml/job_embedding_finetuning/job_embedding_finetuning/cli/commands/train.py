"""Train command for embedding model finetuning."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from job_embedding_finetuning.config.settings import get_settings

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("run")
def train_model(
    dataset_path: Annotated[
        Path,
        typer.Argument(help="Path to dataset (Arrow directory or JSONL file)."),
    ],
    output_dir: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output directory for model."),
    ] = None,
    model_name: Annotated[
        str,
        typer.Option("--model", "-m", help="Base model to finetune."),
    ] = "Qwen/Qwen3-Embedding-0.6B",
    epochs: Annotated[
        int,
        typer.Option("--epochs", "-e", help="Number of training epochs."),
    ] = 3,
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", "-b", help="Per-device batch size."),
    ] = 32,
    gradient_accumulation: Annotated[
        int,
        typer.Option("--grad-accum", "-g", help="Gradient accumulation steps."),
    ] = 8,
    learning_rate: Annotated[
        float,
        typer.Option("--lr", help="Learning rate."),
    ] = 5e-6,
    max_seq_length: Annotated[
        int,
        typer.Option("--max-seq", help="Maximum sequence length."),
    ] = 512,
    seed: Annotated[
        int,
        typer.Option("--seed", help="Random seed."),
    ] = 42,
    resume: Annotated[
        bool,
        typer.Option("--resume/--no-resume", help="Resume from latest checkpoint."),
    ] = False,
    use_matryoshka: Annotated[
        bool,
        typer.Option("--matryoshka/--no-matryoshka", help="Use MatryoshkaLoss to preserve MRL."),
    ] = True,
    temperature: Annotated[
        float,
        typer.Option("--temperature", "-t", help="Temperature for contrastive loss (0.2 optimal per arxiv research)."),
    ] = 0.2,
) -> None:
    """Train an embedding model using SentenceTransformers.

    Example:
        finetune train run training_pairs.jsonl --batch-size 32
        finetune train run training_pairs_arrow --batch-size 32
    """
    if not dataset_path.exists():
        console.print(f"[red]Dataset not found: {dataset_path}[/red]")
        raise typer.Exit(1)

    # Lazy import keeps training dependencies out of non-training commands.
    from job_embedding_finetuning.training.trainer import (
        TrainingConfig,
        run_training,
    )

    settings = get_settings()
    target_dir = output_dir or settings.output_dir / "model"

    try:
        config = TrainingConfig(
            model_name=model_name,
            output_dir=target_dir,
            epochs=epochs,
            batch_size=batch_size,
            gradient_accumulation_steps=gradient_accumulation,
            learning_rate=learning_rate,
            max_seq_length=max_seq_length,
            seed=seed,
            resume_from_checkpoint=resume,
            use_matryoshka=use_matryoshka,
            temperature=temperature,
        )
    except ValueError as error:
        console.print(f"[red]Invalid training configuration: {error}[/red]")
        raise typer.Exit(2) from error

    effective_batch = batch_size * gradient_accumulation
    console.print("\n[bold cyan]Training Configuration:[/bold cyan]")
    console.print(f"  [bold]Dataset:[/bold] {dataset_path}")
    console.print(f"  [bold]Model:[/bold] {config.model_name}")
    console.print(f"  [bold]Epochs:[/bold] {config.epochs}")
    console.print(f"  [bold]Batch:[/bold] {batch_size} x {gradient_accumulation} = {effective_batch}")
    console.print(f"  [bold]Learning rate:[/bold] {config.learning_rate}")
    console.print(f"  [bold]Matryoshka:[/bold] {use_matryoshka} (temp={temperature})")
    console.print(f"  [bold]Resume:[/bold] {resume}")

    console.print("\n[bold green]Starting training...[/bold green]")

    result = run_training(dataset_path, config)

    console.print("\n[bold green]Training Complete![/bold green]")
    console.print(f"  [bold]Model saved to:[/bold] {result.model_path}")
    console.print(f"  [bold]Final loss:[/bold] {result.final_loss:.4f}")
    console.print(f"  [bold]Total steps:[/bold] {result.total_steps:,}")
