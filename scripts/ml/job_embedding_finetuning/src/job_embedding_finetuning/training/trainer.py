"""Embedding model fine-tuning using Full SFT + SentenceTransformers."""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datasets import Dataset as HFDataset
    from sentence_transformers import SentenceTransformer

import numpy as np
import sentence_transformers
import sentence_transformers.models
import torch
from rich.console import Console

console = Console(stderr=True)


@dataclass(slots=True)
class TrainingConfig:
    """Configuration for full SFT embedding training."""

    model_name: str = "Qwen/Qwen3-Embedding-0.6B"
    output_dir: Path = field(default_factory=lambda: Path("./output/model"))
    epochs: int = 3
    batch_size: int = 32
    gradient_accumulation_steps: int = 8
    learning_rate: float = 5e-6
    warmup_ratio: float = 0.05
    weight_decay: float = 0.01
    max_seq_length: int = 512
    max_samples: int | None = None
    seed: int = 42
    resume_from_checkpoint: bool = False
    use_matryoshka: bool = True
    matryoshka_dims: tuple[int, ...] = field(default_factory=lambda: (64, 128, 256, 512, 768, 1024))
    temperature: float = 0.2
    eval_split_ratio: float = 0.05  # 5% of data for evaluation
    eval_steps: int = 250  # Evaluate every N steps

    def __post_init__(self) -> None:
        """Reject configurations that would fail late or allocate without bound."""
        if not self.model_name.strip():
            message = "model_name must not be empty"
            raise ValueError(message)
        positive_values = {
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "gradient_accumulation_steps": self.gradient_accumulation_steps,
            "learning_rate": self.learning_rate,
            "max_seq_length": self.max_seq_length,
            "temperature": self.temperature,
            "eval_steps": self.eval_steps,
        }
        for name, value in positive_values.items():
            if not np.isfinite(value) or value <= 0:
                message = f"{name} must be finite and greater than zero"
                raise ValueError(message)
        if not 0 <= self.warmup_ratio < 1:
            message = "warmup_ratio must be in [0, 1)"
            raise ValueError(message)
        if not 0 <= self.eval_split_ratio < 1:
            message = "eval_split_ratio must be in [0, 1)"
            raise ValueError(message)
        if self.weight_decay < 0:
            message = "weight_decay must not be negative"
            raise ValueError(message)
        if self.max_samples is not None and self.max_samples <= 0:
            message = "max_samples must be greater than zero"
            raise ValueError(message)
        if not self.matryoshka_dims or any(dimension <= 0 for dimension in self.matryoshka_dims):
            message = "matryoshka_dims must contain positive dimensions"
            raise ValueError(message)


@dataclass(slots=True)
class TrainingResult:
    """Results from training run."""

    model_path: Path
    final_loss: float
    total_steps: int


def _find_latest_checkpoint(output_dir: Path) -> Path | None:
    """Find the latest checkpoint directory."""
    checkpoints = sorted(
        output_dir.glob("checkpoint-*"),
        key=lambda p: int(p.name.split("-")[1]) if p.name.split("-")[1].isdigit() else 0,
    )
    return checkpoints[-1] if checkpoints else None


def _set_seed(seed: int) -> None:
    """Set random seeds for reproducibility."""
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _load_dataset(dataset_path: Path, config: TrainingConfig) -> tuple[HFDataset, HFDataset | None]:
    """Load and optionally split dataset for training and evaluation."""
    from datasets import Dataset as HFDataset
    from datasets import DatasetDict as HFDatasetDict
    from datasets import load_from_disk

    console.print(f"[dim]Loading dataset from {dataset_path}[/dim]")

    if dataset_path.is_dir():
        loaded = load_from_disk(str(dataset_path))
        dataset: HFDataset = loaded["train"] if isinstance(loaded, HFDatasetDict) else loaded
    else:
        data: dict[str, list[str]] = {"anchor": [], "positive": []}
        with dataset_path.open(encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                row = json.loads(line)
                match row:
                    case {"anchor": str(anchor), "positive": str(positive)}:
                        data["anchor"].append(anchor)
                        data["positive"].append(positive)
                    case _:
                        message = f"Invalid training pair at line {line_number}: anchor and positive must be strings"
                        raise ValueError(message)
        dataset = HFDataset.from_dict(data)

    required_columns = {"anchor", "positive"}
    missing_columns = required_columns.difference(dataset.column_names)
    if missing_columns:
        message = f"Dataset is missing required columns: {', '.join(sorted(missing_columns))}"
        raise ValueError(message)
    if len(dataset) == 0:
        message = "Dataset must contain at least one training pair"
        raise ValueError(message)

    if config.max_samples and len(dataset) > config.max_samples:
        console.print(f"[yellow]Limiting dataset: {len(dataset):,} → {config.max_samples:,}[/yellow]")
        dataset = dataset.shuffle(seed=config.seed).select(range(config.max_samples))

    eval_dataset = None
    if config.eval_split_ratio > 0:
        if len(dataset) < 2:
            message = "Dataset must contain at least two pairs when evaluation splitting is enabled"
            raise ValueError(message)
        split = dataset.train_test_split(test_size=config.eval_split_ratio, seed=config.seed)
        dataset = split["train"]
        eval_dataset = split["test"]
        console.print(f"[green]✓[/green] Train: {len(dataset):,} | Eval: {len(eval_dataset):,}")
    else:
        console.print(f"[green]✓[/green] Dataset: {len(dataset):,} examples")

    return dataset, eval_dataset


def _create_loss(model: SentenceTransformer, config: TrainingConfig) -> torch.nn.Module:
    """Create the loss function with proper configuration.

    Uses CachedMultipleNegativesRankingLoss for larger effective batch sizes
    without extra memory. This is critical for contrastive learning.

    Temperature guidance from arxiv research:
    - 0.05-0.1: Too low, causes vanishing gradients
    - 0.2-0.25: Sweet spot for gradient flow
    - 0.5+: Too high, poor discrimination
    """
    from sentence_transformers import losses

    # CachedMNRL decouples effective batch from GPU memory:
    # mini_batch_size=128 in GPU, effective batch = batch_size * grad_accum
    base_loss = losses.CachedMultipleNegativesRankingLoss(
        model=model,
        scale=1.0 / config.temperature,
        mini_batch_size=128,
    )
    console.print(
        f"[cyan]CachedMNRL[/cyan] scale={1.0 / config.temperature:.1f} (temp={config.temperature}), mini_batch=128"
    )

    if config.use_matryoshka:
        console.print(f"[cyan]MatryoshkaLoss[/cyan] dims: {list(config.matryoshka_dims)}")
        return losses.MatryoshkaLoss(
            model=model,
            loss=base_loss,
            matryoshka_dims=list(config.matryoshka_dims),
        )
    return base_loss


def _handle_checkpoint_resume(config: TrainingConfig) -> Path | None:
    """Check for and return checkpoint path if resuming."""
    if not config.resume_from_checkpoint:
        return None
    checkpoint_path = _find_latest_checkpoint(config.output_dir)
    if checkpoint_path:
        console.print(f"[cyan]Found checkpoint:[/cyan] {checkpoint_path.name}")
    else:
        console.print("[dim]No checkpoint found, starting fresh[/dim]")
    return checkpoint_path


def run_training(dataset_path: Path, config: TrainingConfig) -> TrainingResult:
    """Run full SFT embedding fine-tuning with SentenceTransformers.

    Args:
        dataset_path: Path to dataset (Arrow format or JSONL).
        config: Training configuration.

    Returns:
        Training results.

    """
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    from sentence_transformers import (
        SentenceTransformer,
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
    )
    from sentence_transformers.training_args import BatchSamplers

    _set_seed(config.seed)

    console.rule("[bold blue]Full SFT Embedding Fine-Tuning[/bold blue]")

    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
        console.print(f"[green]✓[/green] GPU: {gpu_name} ({gpu_mem:.1f} GB)")

    checkpoint_path = _handle_checkpoint_resume(config)

    # Load model via standard SentenceTransformer with correct Qwen3-Embedding config
    console.print(f"[dim]Loading model: {config.model_name}[/dim]")
    sbert_model = SentenceTransformer(config.model_name)

    # Qwen3-Embedding is a causal decoder: requires left padding for last-token pooling
    sbert_model[0].tokenizer.padding_side = "left"

    # Override pooling to last-token (causal decoder extracts meaning from final token)
    sbert_model[1] = sentence_transformers.models.Pooling(
        word_embedding_dimension=sbert_model.get_sentence_embedding_dimension(),
        pooling_mode="lasttoken",
    )

    console.print(f"[green]✓[/green] Embedding dim: {sbert_model.get_sentence_embedding_dimension()}")
    console.print("[green]✓[/green] Pooling: lasttoken | Padding: left")

    # Load dataset with train/eval split
    dataset, eval_dataset = _load_dataset(dataset_path, config)

    # Calculate steps, adjusting for resume if needed
    effective_batch = config.batch_size * config.gradient_accumulation_steps
    steps_per_epoch = max(1, len(dataset) // effective_batch)

    completed_epochs = 0.0
    completed_steps = 0
    if checkpoint_path:
        trainer_state_path = checkpoint_path / "trainer_state.json"
        if trainer_state_path.exists():
            trainer_state = json.loads(trainer_state_path.read_text())
            completed_steps = trainer_state.get("global_step", 0)
            completed_epochs = trainer_state.get("epoch", 0.0)
            console.print(f"[cyan]Resume:[/cyan] step {completed_steps}, epoch {completed_epochs:.4f}")

    remaining_epochs = max(0.1, config.epochs - completed_epochs)
    total_steps = int(steps_per_epoch * remaining_epochs)
    warmup_steps = int(total_steps * config.warmup_ratio) if completed_steps == 0 else 0

    console.print(f"[cyan]Training:[/cyan] {len(dataset):,} examples, {remaining_epochs:.2f} epochs")
    console.print(f"[cyan]Batch:[/cyan] {config.batch_size} x {config.gradient_accumulation_steps} = {effective_batch}")
    console.print(f"[cyan]Steps:[/cyan] {total_steps} total, {warmup_steps} warmup")
    if completed_steps > 0:
        console.print(f"[yellow]Resuming from step {completed_steps}[/yellow]")

    config.output_dir.mkdir(parents=True, exist_ok=True)

    # Loss function with temperature scaling and optional Matryoshka wrapper
    loss = _create_loss(sbert_model, config)

    # Training arguments
    use_bf16 = torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False
    console.print(f"[dim]BF16: {use_bf16}, TF32: enabled[/dim]")

    if torch.cuda.is_available():
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True

    args = SentenceTransformerTrainingArguments(
        output_dir=str(config.output_dir),
        num_train_epochs=remaining_epochs,
        per_device_train_batch_size=config.batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        learning_rate=config.learning_rate,
        lr_scheduler_type="cosine",
        warmup_steps=warmup_steps,
        weight_decay=config.weight_decay,
        # Precision: use bf16 for speed on modern GPUs
        bf16=use_bf16,
        fp16=not use_bf16 and torch.cuda.is_available(),
        bf16_full_eval=use_bf16,
        # Optimizer: standard AdamW for full SFT
        optim="adamw_torch",
        # Batch sampling
        batch_sampler=BatchSamplers.NO_DUPLICATES,
        # DataLoader: keep workers at 0 to avoid file descriptor issues
        dataloader_num_workers=0,
        dataloader_pin_memory=True,
        # Logging
        logging_steps=50,
        logging_first_step=True,
        # Checkpointing
        save_steps=500,
        save_total_limit=3,
        # Evaluation
        eval_strategy="steps" if eval_dataset else "no",
        eval_steps=config.eval_steps if eval_dataset else None,
        load_best_model_at_end=bool(eval_dataset),
        metric_for_best_model="eval_loss" if eval_dataset else None,
        greater_is_better=False if eval_dataset else None,
        # Gradient checkpointing: essential for full SFT to fit in GPU memory
        gradient_checkpointing=True,
        # Other
        seed=config.seed,
        report_to="none",
        # Disable find_unused_parameters for speed
        ddp_find_unused_parameters=False,
    )

    # Save dataset info
    dataset_info_path = config.output_dir / "dataset_info.json"
    dataset_fingerprint = dataset._fingerprint if hasattr(dataset, "_fingerprint") else str(len(dataset))
    dataset_info = {
        "path": str(dataset_path),
        "size": len(dataset),
        "fingerprint": dataset_fingerprint,
    }
    dataset_info_path.write_text(json.dumps(dataset_info, indent=2))

    console.rule("[bold green]Starting Training[/bold green]")

    trainer = SentenceTransformerTrainer(
        model=sbert_model,
        args=args,
        train_dataset=dataset,
        eval_dataset=eval_dataset,
        loss=loss,
    )

    train_result = trainer.train(resume_from_checkpoint=str(checkpoint_path) if checkpoint_path else None)

    # Save final model
    final_path = config.output_dir / "final_model"
    sbert_model.save_pretrained(str(final_path))

    # Verify padding_side persisted correctly for inference compatibility
    tokenizer_config_path = final_path / "tokenizer_config.json"
    tokenizer_config = json.loads(tokenizer_config_path.read_text())
    if tokenizer_config.get("padding_side") != "left":
        msg = f"Expected padding_side='left' in tokenizer_config.json, got {tokenizer_config.get('padding_side')!r}"
        raise ValueError(msg)

    console.rule("[bold green]Training Complete[/bold green]")
    console.print(f"[green]✓[/green] Model: {final_path}")
    console.print(f"[green]✓[/green] Loss: {train_result.training_loss:.4f}")
    console.print(f"[green]✓[/green] Steps: {train_result.global_step}")

    return TrainingResult(
        model_path=final_path,
        final_loss=train_result.training_loss,
        total_steps=train_result.global_step,
    )
