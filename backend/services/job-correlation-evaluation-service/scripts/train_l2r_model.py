#!/usr/bin/env python
"""L2R Model Training Pipeline.

Train a LightGBM LambdaMART model from collected user feedback data.
Run periodically (e.g., weekly) to incorporate new feedback.

Pipeline Steps:
    1. DATA EXPORT       → Export labeled feedback from correlations table
    2. DATA PREPARATION  → Convert to LightGBM Dataset, group by user
    3. MODEL TRAINING    → LightGBM LambdaMART with early stopping
    4. CALIBRATION       → Fit isotonic regression on validation set
    5. EVALUATION        → Compute NDCG metrics
    6. DEPLOYMENT        → Save versioned files, update metadata
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Final, cast

import joblib
import lightgbm as lgb
import numpy as np
import typer
from job_correlation_evaluation_service.services.scoring.constants import (
    FEATURE_COUNT,
    FEATURE_NAMES,
    FeatureIndex,
)
from rich.console import Console
from rich.table import Table
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import ndcg_score
from sklearn.model_selection import GroupKFold

CALIBRATOR_TYPE_ISOTONIC: Final = "isotonic"
CALIBRATOR_VERSION_ISOTONIC: Final = "2.0.0"

if TYPE_CHECKING:
    from numpy.typing import NDArray

console = Console(stderr=True)
app = typer.Typer(
    name="train-l2r-model",
    help="Train L2R model from feedback data.",
    no_args_is_help=False,
)


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    """Training configuration constants."""

    DEFAULT_MIN_SAMPLES: int = 1000
    DEFAULT_MAX_SAMPLES: int = 100000
    DEFAULT_NUM_BOOST_ROUND: int = 500
    DEFAULT_EARLY_STOPPING: int = 50
    TRAIN_RATIO: float = 0.8
    MIN_GROUPS_FOR_SPLIT: int = 2
    LABEL_DIVISOR: float = 5.0
    SEED: int = 42


CONFIG = TrainingConfig()

LABEL_MAP: Final[dict[str, float]] = {
    "applied": 5.0,
    "liked": 4.0,
    "saved": 3.5,
    "viewed": 2.0,
    "dismissed": 0.5,
    "disliked": 0.0,
    "not_interested": 0.0,
}

LABEL_TO_INT: Final[dict[float, int]] = {
    0.0: 0,
    0.5: 1,
    2.0: 2,
    3.5: 3,
    4.0: 4,
    5.0: 5,
}

LABEL_GAINS: Final[list[float]] = [0.0, 0.5, 2.0, 3.5, 4.0, 5.0]


def _get_feature_names() -> list[str]:
    """Get ordered list of feature names for LightGBM."""
    return [FEATURE_NAMES[FeatureIndex(i)] for i in range(FEATURE_COUNT)]


async def _export_from_db(
    min_date: datetime | None,
    max_date: datetime | None,
    limit: int,
) -> list[dict[str, str | float | list[float]]]:
    """Export training data from database."""
    from job_correlation_evaluation_service.repositories.correlation_repository import (
        CorrelationRepository,
    )
    from job_correlation_evaluation_service.services.feedback_service import (
        CorrelationFeedbackService,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/nohiki",
    )

    engine = create_async_engine(database_url, echo=False)
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session_maker() as session:
        repo = CorrelationRepository(session)
        feedback_service = CorrelationFeedbackService(repo)
        samples = await feedback_service.export_training_data(min_date=min_date, max_date=max_date, limit=limit)

    await engine.dispose()
    return samples


def _export_from_file(data_file: Path) -> list[dict[str, str | float | list[float]]]:
    """Load training data from JSON file."""
    if not data_file.exists():
        msg = f"Training data file not found: {data_file}"
        raise typer.BadParameter(msg)

    return json.loads(data_file.read_text())


def _group_samples_by_query(
    samples: Sequence[dict[str, str | float | list[float]]],
) -> dict[str, list[dict[str, str | float | list[float]]]]:
    """Group samples by query_id."""
    query_samples: dict[str, list[dict[str, str | float | list[float]]]] = {}
    for sample in samples:
        query_id = str(sample["query_id"])
        if query_id not in query_samples:
            query_samples[query_id] = []
        query_samples[query_id].append(sample)
    return query_samples


def _extract_and_convert_label(sample: dict[str, str | float | list[float]]) -> int:
    """Extract label and convert to integer for LightGBM ranking."""
    label = sample["label"]
    if not isinstance(label, (int, float)):
        msg = f"Invalid label type: {type(label)}"
        raise TypeError(msg)

    float_label = float(label)
    int_label = LABEL_TO_INT.get(float_label)

    if int_label is None:
        closest_key = min(LABEL_TO_INT.keys(), key=lambda x: abs(x - float_label))
        int_label = LABEL_TO_INT[closest_key]

    return int_label


def _prepare_training_data(
    samples: Sequence[dict[str, str | float | list[float]]],
) -> tuple[NDArray[np.floating[Any]], NDArray[np.signedinteger[Any]], list[int], list[str]]:
    """Convert samples to numpy arrays for LightGBM training."""
    if not samples:
        return (
            np.array([], dtype=np.float64).reshape(0, FEATURE_COUNT),
            np.array([], dtype=np.int32),
            [],
            [],
        )

    query_samples = _group_samples_by_query(samples)

    features_list: list[list[float]] = []
    labels_list: list[int] = []
    groups: list[int] = []
    query_ids: list[str] = []

    for query_id in sorted(query_samples.keys()):
        group_samples = query_samples[query_id]
        groups.append(len(group_samples))
        query_ids.append(query_id)

        for sample in group_samples:
            features = sample["features"]
            if isinstance(features, list):
                features_list.append(features)
            labels_list.append(_extract_and_convert_label(sample))

    feature_matrix = np.array(features_list, dtype=np.float64)
    label_vector = np.array(labels_list, dtype=np.int32)

    if feature_matrix.shape[1] != FEATURE_COUNT:
        msg = f"Feature count mismatch: expected {FEATURE_COUNT}, got {feature_matrix.shape[1]}"
        raise ValueError(msg)

    return feature_matrix, label_vector, groups, query_ids


def _split_by_groups(
    features: NDArray[np.floating],
    labels: NDArray[np.floating],
    groups: list[int],
) -> tuple[
    NDArray[np.floating],
    NDArray[np.floating],
    list[int],
    NDArray[np.floating],
    NDArray[np.floating],
    list[int],
]:
    """Split data by query groups for train/validation."""
    if len(groups) < CONFIG.MIN_GROUPS_FOR_SPLIT:
        return features, labels, groups, np.array([]), np.array([]), []

    query_assignments = np.repeat(range(len(groups)), groups)
    n_splits = max(2, int(1.0 / (1.0 - CONFIG.TRAIN_RATIO)))
    kfold = GroupKFold(n_splits=n_splits)

    train_idx, val_idx = next(kfold.split(features, labels, query_assignments))

    train_query_ids = set(query_assignments[train_idx])
    val_query_ids = set(query_assignments[val_idx])

    return (
        features[train_idx],
        labels[train_idx],
        [groups[i] for i in sorted(train_query_ids)],
        features[val_idx],
        labels[val_idx],
        [groups[i] for i in sorted(val_query_ids)],
    )


def _train_model(
    train_features: NDArray[np.floating],
    train_labels: NDArray[np.floating],
    train_groups: list[int],
    val_features: NDArray[np.floating] | None,
    val_labels: NDArray[np.floating] | None,
    val_groups: list[int] | None,
    *,
    verbose: bool = True,
) -> lgb.Booster:
    """Train LightGBM LambdaMART model."""
    params: dict[str, str | int | float | list[int] | list[float]] = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "ndcg_eval_at": [5, 10],
        "label_gain": LABEL_GAINS,
        "num_leaves": 31,
        "learning_rate": 0.05,
        "min_data_in_leaf": 20,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
        "seed": CONFIG.SEED,
    }

    feature_names = _get_feature_names()

    train_data = lgb.Dataset(
        train_features,
        label=train_labels,
        group=train_groups,
        feature_name=feature_names,
    )

    valid_sets: list[lgb.Dataset] = [train_data]
    valid_names: list[str] = ["train"]

    if val_features is not None and val_labels is not None and val_groups:
        val_data = lgb.Dataset(
            val_features,
            label=val_labels,
            group=val_groups,
            feature_name=feature_names,
            reference=train_data,
        )
        valid_sets.append(val_data)
        valid_names.append("valid")

    callbacks: list[Any] = []
    if verbose:
        callbacks.append(lgb.log_evaluation(period=50))
    if len(valid_sets) > 1:
        callbacks.append(lgb.early_stopping(stopping_rounds=CONFIG.DEFAULT_EARLY_STOPPING))

    return lgb.train(
        params,
        train_data,
        num_boost_round=CONFIG.DEFAULT_NUM_BOOST_ROUND,
        valid_sets=valid_sets,
        valid_names=valid_names,
        callbacks=callbacks,
    )


def _train_calibrator(
    model: lgb.Booster,
    features: NDArray[np.floating],
    labels: NDArray[np.floating],
) -> IsotonicRegression:
    """Train isotonic regression calibrator."""
    raw_scores = model.predict(features)
    probabilities = labels / CONFIG.LABEL_DIVISOR

    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_scores, probabilities)

    return calibrator


def _compute_ndcg(
    true_labels: NDArray[np.floating],
    predicted_scores: NDArray[np.floating],
    groups: list[int],
    k: int = 10,
) -> float:
    """Compute NDCG@k for grouped ranking results."""
    ndcg_scores: list[float] = []
    current_idx = 0

    for size in groups:
        if size < k:
            current_idx += size
            continue

        group_labels = true_labels[current_idx : current_idx + size]
        group_predictions = predicted_scores[current_idx : current_idx + size]

        score = ndcg_score([group_labels], [group_predictions], k=k)
        ndcg_scores.append(float(score))

        current_idx += size

    if not ndcg_scores:
        return 0.0

    return float(np.mean(ndcg_scores))


def _evaluate_model(
    model: lgb.Booster,
    features: NDArray[np.floating],
    labels: NDArray[np.floating],
    groups: list[int],
) -> dict[str, float | int]:
    """Evaluate model performance with NDCG metrics."""
    raw_scores = np.asarray(model.predict(features), dtype=np.float64)

    return {
        "ndcg_at_5": _compute_ndcg(labels, raw_scores, groups, k=5),
        "ndcg_at_10": _compute_ndcg(labels, raw_scores, groups, k=10),
        "num_query_groups": len(groups),
        "total_samples": len(labels),
    }


def _save_model(
    model: lgb.Booster,
    calibrator: IsotonicRegression,
    metrics: dict[str, float | int],
    version: str,
    output_dir: Path,
) -> dict[str, Path]:
    """Save model, calibrator, and update metadata.

    Produces three versioned artifacts:
    - LightGBM model text file
    - Calibrator as self-describing dict (type + version + sklearn object)
    - Updated model_metadata.json with version entry

    Args:
        model: Trained LightGBM booster.
        calibrator: Fitted isotonic regression calibrator.
        metrics: Training metrics (NDCG, sample counts).
        version: Version string for filenames and metadata.
        output_dir: Directory to save artifacts.

    Returns:
        Mapping of artifact names to their paths.

    """
    output_dir.mkdir(parents=True, exist_ok=True)

    model_filename = f"l2r_lightgbm_{version}.txt"
    calibrator_filename = f"calibrator_{version}.joblib"

    model_path = output_dir / model_filename
    calibrator_path = output_dir / calibrator_filename
    metadata_path = output_dir / "model_metadata.json"

    model.save_model(model_path)
    joblib.dump(
        {
            "type": CALIBRATOR_TYPE_ISOTONIC,
            "version": CALIBRATOR_VERSION_ISOTONIC,
            "calibrator": calibrator,
        },
        calibrator_path,
    )

    _update_metadata(metadata_path, version, model_filename, calibrator_filename, metrics)

    return {
        "model_path": model_path,
        "calibrator_path": calibrator_path,
        "metadata_path": metadata_path,
    }


def _update_metadata(
    metadata_path: Path,
    version: str,
    model_filename: str,
    calibrator_filename: str,
    metrics: dict[str, float | int],
) -> None:
    """Append a version entry to model_metadata.json."""
    if metadata_path.exists():
        raw = json.loads(metadata_path.read_text())
        if not isinstance(raw, dict):
            msg = f"Invalid metadata format: expected dict, got {type(raw).__name__}"
            raise TypeError(msg)
        metadata: dict[str, object] = raw
    else:
        metadata = {"current_version": None, "versions": {}}

    existing = metadata.get("versions")
    versions = cast("dict[str, object]", existing) if isinstance(existing, dict) else {}
    versions[version] = {
        "l2r_model": model_filename,
        "calibrator": calibrator_filename,
        "calibrator_type": CALIBRATOR_TYPE_ISOTONIC,
        "created_at": datetime.now(UTC).isoformat(),
        "training_samples": metrics.get("total_samples", 0),
        "ndcg_at_5": metrics.get("ndcg_at_5", 0.0),
        "ndcg_at_10": metrics.get("ndcg_at_10", 0.0),
        "num_query_groups": metrics.get("num_query_groups", 0),
    }

    metadata_path.write_text(json.dumps(metadata, indent=2))


def _generate_version_string() -> str:
    """Generate version string from current date."""
    return f"v{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"


def _display_metrics(metrics: dict[str, float | int], *, is_validation: bool) -> None:
    """Display evaluation metrics in a table."""
    label = "Validation" if is_validation else "Training (no validation set)"
    console.print(f"\n[bold]{label} metrics:[/bold]")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    table.add_row("NDCG@5", f"{metrics['ndcg_at_5']:.4f}")
    table.add_row("NDCG@10", f"{metrics['ndcg_at_10']:.4f}")
    table.add_row("Query groups", str(metrics["num_query_groups"]))
    table.add_row("Total samples", str(metrics["total_samples"]))

    console.print(table)


async def _run_training_pipeline(
    data_file: Path | None,
    min_date: datetime | None,
    max_date: datetime | None,
    min_samples: int,
    max_samples: int,
    output_dir: Path,
    version: str | None,
    *,
    quiet: bool = False,
) -> int:
    """Execute the full training pipeline."""
    console.rule("[bold blue]L2R Model Training Pipeline[/bold blue]")

    console.print("\n[bold]Step 1/6:[/bold] Exporting training data...")
    samples: list[dict[str, str | float | list[float]]]
    if data_file:
        console.print(f"  Loading from file: {data_file}")
        samples = _export_from_file(data_file)
    else:
        console.print("  Querying database...")
        samples = await _export_from_db(min_date, max_date, max_samples)

    console.print(f"  Exported {len(samples)} samples")

    if len(samples) < min_samples:
        console.print(f"\n[red]❌ Insufficient samples: {len(samples)} < {min_samples}[/red]")
        console.print("   Training aborted. Collect more feedback before retraining.")
        return 1

    console.print("\n[bold]Step 2/6:[/bold] Preparing training data...")
    features, labels, groups, _ = _prepare_training_data(samples)
    console.print(f"  Features: {features.shape}")
    console.print(f"  Labels: {labels.shape}")
    console.print(f"  Query groups: {len(groups)}")

    labels_float = labels.astype(np.float64)
    train_f, train_l, train_g, val_f, val_l, val_g = _split_by_groups(features, labels_float, groups)
    console.print(f"  Training samples: {len(train_l)}")
    console.print(f"  Validation samples: {len(val_l)}")

    console.print("\n[bold]Step 3/6:[/bold] Training LightGBM LambdaMART model...")
    model = _train_model(
        train_f,
        train_l,
        train_g,
        val_f if len(val_l) > 0 else None,
        val_l if len(val_l) > 0 else None,
        val_g or None,
        verbose=not quiet,
    )
    console.print(f"  Best iteration: {model.best_iteration}")
    console.print(f"  Number of trees: {model.num_trees()}")

    console.print("\n[bold]Step 4/6:[/bold] Training isotonic calibrator...")
    calibrator = _train_calibrator(model, features, labels_float)
    console.print("  [green]Calibrator fitted successfully[/green]")

    console.print("\n[bold]Step 5/6:[/bold] Evaluating model...")
    if len(val_l) > 0:
        metrics = _evaluate_model(model, val_f, val_l, val_g)
        _display_metrics(metrics, is_validation=True)
    else:
        metrics = _evaluate_model(model, features, labels_float, groups)
        _display_metrics(metrics, is_validation=False)

    console.print("\n[bold]Step 6/6:[/bold] Saving model...")
    final_version = version or _generate_version_string()
    paths = _save_model(model, calibrator, metrics, final_version, output_dir)

    console.print(f"  Version: {final_version}")
    console.print(f"  Model: {paths['model_path']}")
    console.print(f"  Calibrator: {paths['calibrator_path']}")
    console.print(f"  Metadata: {paths['metadata_path']}")

    console.rule("[bold green]Training complete![/bold green]")
    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  1. Review metrics (NDCG@10: {metrics['ndcg_at_10']:.4f})")
    console.print("  2. Compare with production model using evaluate_model.py")
    console.print(f"  3. Deploy with: [cyan]deploy_model.py deploy {final_version}[/cyan]")

    return 0


@app.command()
def main(
    min_samples: Annotated[
        int,
        typer.Option("--min-samples", help="Minimum samples required for training."),
    ] = CONFIG.DEFAULT_MIN_SAMPLES,
    max_samples: Annotated[
        int,
        typer.Option("--max-samples", help="Maximum samples to export from database."),
    ] = CONFIG.DEFAULT_MAX_SAMPLES,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", "-o", help="Output directory for model files."),
    ] = Path("models"),
    version: Annotated[
        str | None,
        typer.Option("--version", "-v", help="Model version string (auto-generated if not specified)."),
    ] = None,
    data_file: Annotated[
        Path | None,
        typer.Option("--data-file", "-d", help="Load training data from JSON file instead of database."),
    ] = None,
    min_date: Annotated[
        str | None,
        typer.Option("--min-date", help="Minimum date for training data (ISO format)."),
    ] = None,
    max_date: Annotated[
        str | None,
        typer.Option("--max-date", help="Maximum date for training data (ISO format)."),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress training progress output."),
    ] = False,
) -> None:
    """Train L2R model from feedback data."""
    parsed_min_date = datetime.fromisoformat(min_date).replace(tzinfo=UTC) if min_date else None
    parsed_max_date = datetime.fromisoformat(max_date).replace(tzinfo=UTC) if max_date else None

    exit_code = asyncio.run(
        _run_training_pipeline(
            data_file=data_file,
            min_date=parsed_min_date,
            max_date=parsed_max_date,
            min_samples=min_samples,
            max_samples=max_samples,
            output_dir=output_dir,
            version=version,
            quiet=quiet,
        )
    )

    if exit_code != 0:
        raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()
