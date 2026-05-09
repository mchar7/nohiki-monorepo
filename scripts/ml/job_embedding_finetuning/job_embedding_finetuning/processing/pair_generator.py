"""Training pair generation pipeline.

Orchestrates loading datasets, generating pairs, and saving
to disk for training with parallel processing support.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import TYPE_CHECKING

from job_embedding_finetuning.dataset_adapters.base import DatasetTier, TrainingPair
from job_embedding_finetuning.processing.filters import FilterConfig, apply_filters
from job_embedding_finetuning.processing.instruction_prefix import apply_instruction_prefix

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from rich.progress import Progress

    from job_embedding_finetuning.dataset_adapters.base import DatasetAdapter

# Number of parallel workers for dataset processing
MAX_WORKERS = 4

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PairGeneratorConfig:
    """Configuration for pair generation.

    Attributes:
        include_tiers: Dataset tiers to include.
        filter_config: Configuration for quality filters.
        include_hard_negatives: Include hard negative pairs.
        shuffle_output: Shuffle output pairs.
        random_seed: Random seed for shuffling.

    """

    include_tiers: tuple[DatasetTier, ...] = (DatasetTier.GOLD, DatasetTier.CORE)
    filter_config: FilterConfig = dataclass_field(default_factory=FilterConfig)
    include_hard_negatives: bool = True
    shuffle_output: bool = True
    random_seed: int = 42


@dataclass(slots=True)
class GenerationStats:
    """Statistics from pair generation.

    Attributes:
        datasets_processed: Number of datasets processed.
        datasets_failed: Number of datasets that failed to load.
        total_pairs: Total pairs generated before filtering.
        filtered_pairs: Pairs after filtering.
        pairs_by_type: Breakdown by pair type.
        pairs_by_dataset: Breakdown by source dataset.

    """

    datasets_processed: int = 0
    datasets_failed: int = 0
    total_pairs: int = 0
    filtered_pairs: int = 0
    pairs_by_type: dict[str, int] | None = None
    pairs_by_dataset: dict[str, int] | None = None

    def __post_init__(self) -> None:
        """Initialize mutable defaults."""
        if self.pairs_by_type is None:
            self.pairs_by_type = {}
        if self.pairs_by_dataset is None:
            self.pairs_by_dataset = {}


def generate_pairs_from_adapter(
    adapter: DatasetAdapter,
    config: PairGeneratorConfig,
) -> Iterator[TrainingPair]:
    """Generate training pairs from a single adapter.

    Args:
        adapter: The dataset adapter to use.
        config: Generation configuration.

    Yields:
        Training pairs from the adapter.

    Raises:
        RuntimeError: If the adapter fails to load.

    """
    # Load the dataset
    if not adapter.is_downloaded():
        logger.warning("Dataset %s not downloaded, skipping", adapter.info.name)
        return

    try:
        adapter.load()
    except FileNotFoundError:
        logger.warning("Dataset %s files not found, skipping", adapter.info.name)
        return
    except ValueError as e:
        logger.warning("Dataset %s has invalid format: %s", adapter.info.name, e)
        return

    # Generate and filter pairs
    raw_pairs = adapter.generate_pairs()

    # Filter out hard negatives if not wanted
    if not config.include_hard_negatives:
        raw_pairs = (p for p in raw_pairs if p.positive)

    # Apply quality filters and instruction prefixes
    for pair in apply_filters(raw_pairs, config.filter_config):
        yield apply_instruction_prefix(pair)


def generate_all_pairs(
    adapters: Sequence[DatasetAdapter],
    config: PairGeneratorConfig,
) -> tuple[list[TrainingPair], GenerationStats]:
    """Generate training pairs from all adapters.

    Args:
        adapters: Sequence of dataset adapters.
        config: Generation configuration.

    Returns:
        Tuple of (list of training pairs, generation statistics).

    """
    stats = GenerationStats()
    all_pairs: list[TrainingPair] = []

    for adapter in adapters:
        # Skip if tier not included
        if adapter.info.tier not in config.include_tiers:
            continue

        logger.info("Processing dataset: %s", adapter.info.name)

        try:
            pairs = list(generate_pairs_from_adapter(adapter, config))
            all_pairs.extend(pairs)

            # Update stats
            stats.datasets_processed += 1
            pair_count = len(pairs)
            stats.total_pairs += pair_count

            dataset_name = adapter.info.name
            if stats.pairs_by_dataset is not None:
                stats.pairs_by_dataset[dataset_name] = pair_count

            # Count by type
            if stats.pairs_by_type is not None:
                for pair in pairs:
                    pair_type = pair.pair_type
                    stats.pairs_by_type[pair_type] = stats.pairs_by_type.get(pair_type, 0) + 1

            logger.info("Generated %d pairs from %s", pair_count, dataset_name)

        except Exception:
            logger.exception("Failed to process dataset %s", adapter.info.name)
            stats.datasets_failed += 1

    stats.filtered_pairs = len(all_pairs)

    # Shuffle if requested
    if config.shuffle_output:
        import random

        random.seed(config.random_seed)
        random.shuffle(all_pairs)

    return all_pairs, stats


def generate_all_pairs_with_progress(
    adapters: Sequence[DatasetAdapter],
    config: PairGeneratorConfig,
    progress: Progress,
) -> tuple[list[TrainingPair], GenerationStats]:
    """Generate training pairs with progress tracking.

    Args:
        adapters: Sequence of dataset adapters.
        config: Generation configuration.
        progress: Rich Progress instance for tracking.

    Returns:
        Tuple of (list of training pairs, generation statistics).

    """
    stats = GenerationStats()
    all_pairs: list[TrainingPair] = []

    # Main task for overall progress
    main_task = progress.add_task(
        "[cyan]Processing datasets...[/cyan]",
        total=len(adapters),
    )

    for adapter in adapters:
        dataset_name = adapter.info.name
        progress.update(main_task, description=f"[cyan]{dataset_name}[/cyan]")

        try:
            pairs = list(generate_pairs_from_adapter(adapter, config))
            all_pairs.extend(pairs)

            # Update stats
            stats.datasets_processed += 1
            pair_count = len(pairs)
            stats.total_pairs += pair_count

            if stats.pairs_by_dataset is not None:
                stats.pairs_by_dataset[dataset_name] = pair_count

            # Count by type
            if stats.pairs_by_type is not None:
                for pair in pairs:
                    pair_type = pair.pair_type
                    stats.pairs_by_type[pair_type] = stats.pairs_by_type.get(pair_type, 0) + 1

        except Exception:
            logger.exception("Failed to process dataset %s", dataset_name)
            stats.datasets_failed += 1

        progress.advance(main_task)

    stats.filtered_pairs = len(all_pairs)

    # Shuffle with progress indicator
    if config.shuffle_output and all_pairs:
        progress.update(main_task, description="[cyan]Shuffling pairs...[/cyan]")
        import random

        random.seed(config.random_seed)
        random.shuffle(all_pairs)

    progress.update(main_task, description="[green]Complete![/green]")
    return all_pairs, stats


def save_pairs_arrow(pairs: Sequence[TrainingPair], output_dir: Path) -> Path:
    """Atomically replace the Arrow training-pair dataset."""
    import shutil

    from datasets import Dataset

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "training_pairs"
    staging_path = output_dir / ".training_pairs.tmp"
    backup_path = output_dir / ".training_pairs.backup"

    def remove_generated_path(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)

    if output_path.is_symlink() or (output_path.exists() and not output_path.is_dir()):
        message = f"Training-pair output is not a directory: {output_path}"
        raise ValueError(message)
    if backup_path.is_dir() and not backup_path.is_symlink() and not output_path.exists():
        backup_path.replace(output_path)
    else:
        remove_generated_path(backup_path)
    remove_generated_path(staging_path)

    data = {
        "anchor": [p.anchor for p in pairs],
        "positive": [p.positive for p in pairs],
    }
    Dataset.from_dict(data).save_to_disk(str(staging_path))

    if output_path.exists():
        output_path.replace(backup_path)
    try:
        staging_path.replace(output_path)
    except BaseException:
        if backup_path.exists():
            backup_path.replace(output_path)
        raise
    if backup_path.exists():
        shutil.rmtree(backup_path)

    logger.info("Saved %d pairs to %s", len(pairs), output_path)
    return output_path
