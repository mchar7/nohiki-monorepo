#!/usr/bin/env python
"""L2R Model Evaluation Script.

Evaluate model versions against validation data to assess performance
before deployment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

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
from sklearn.metrics import ndcg_score

if TYPE_CHECKING:
    from numpy.typing import NDArray

console = Console(stderr=True)
app = typer.Typer(
    name="evaluate-model",
    help="Evaluate L2R model performance.",
    no_args_is_help=True,
)


def _load_model(model_path: Path) -> lgb.Booster:
    """Load a LightGBM model from file."""
    if not model_path.exists():
        msg = f"Model file not found: {model_path}"
        raise typer.BadParameter(msg)
    return lgb.Booster(model_file=str(model_path))


def _load_test_data(
    data_file: Path,
) -> tuple[NDArray[np.floating], NDArray[np.floating], list[int]]:
    """Load test data from JSON file."""
    if not data_file.exists():
        msg = f"Test data file not found: {data_file}"
        raise typer.BadParameter(msg)

    samples: list[dict[str, str | float | list[float]]] = json.loads(data_file.read_text())

    query_samples: dict[str, list[dict[str, str | float | list[float]]]] = {}
    for sample in samples:
        query_id = str(sample["query_id"])
        if query_id not in query_samples:
            query_samples[query_id] = []
        query_samples[query_id].append(sample)

    features_list: list[list[float]] = []
    labels_list: list[float] = []
    groups: list[int] = []

    for query_id in sorted(query_samples.keys()):
        group_samples = query_samples[query_id]
        groups.append(len(group_samples))

        for sample in group_samples:
            features = sample["features"]
            if isinstance(features, list):
                features_list.append(features)
            label = sample["label"]
            if isinstance(label, (int, float)):
                labels_list.append(float(label))

    features_arr = np.array(features_list, dtype=np.float64)
    labels_arr = np.array(labels_list, dtype=np.float64)

    return features_arr, labels_arr, groups


def _compute_ndcg(
    y_true: NDArray[np.floating],
    y_pred: NDArray[np.floating],
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

        group_y = y_true[current_idx : current_idx + size]
        group_pred = y_pred[current_idx : current_idx + size]

        score = ndcg_score([group_y], [group_pred], k=k)
        ndcg_scores.append(float(score))

        current_idx += size

    if not ndcg_scores:
        return 0.0

    return float(np.mean(ndcg_scores))


def _compute_mrr(
    y_true: NDArray[np.floating],
    y_pred: NDArray[np.floating],
    groups: list[int],
    relevance_threshold: float = 3.0,
) -> float:
    """Compute Mean Reciprocal Rank."""
    mrr_scores: list[float] = []
    current_idx = 0

    for size in groups:
        group_y = y_true[current_idx : current_idx + size]
        group_pred = y_pred[current_idx : current_idx + size]

        sorted_indices = np.argsort(group_pred)[::-1]
        sorted_labels = group_y[sorted_indices]

        for rank, label in enumerate(sorted_labels, start=1):
            if label >= relevance_threshold:
                mrr_scores.append(1.0 / rank)
                break
        else:
            mrr_scores.append(0.0)

        current_idx += size

    if not mrr_scores:
        return 0.0

    return float(np.mean(mrr_scores))


def _compute_precision_at_k(
    y_true: NDArray[np.floating],
    y_pred: NDArray[np.floating],
    groups: list[int],
    k: int = 10,
    relevance_threshold: float = 3.0,
) -> float:
    """Compute Precision@k."""
    precision_scores: list[float] = []
    current_idx = 0

    for size in groups:
        if size < k:
            current_idx += size
            continue

        group_y = y_true[current_idx : current_idx + size]
        group_pred = y_pred[current_idx : current_idx + size]

        top_k_indices = np.argsort(group_pred)[::-1][:k]
        top_k_labels = group_y[top_k_indices]

        relevant_count = np.sum(top_k_labels >= relevance_threshold)
        precision_scores.append(float(relevant_count) / k)

        current_idx += size

    if not precision_scores:
        return 0.0

    return float(np.mean(precision_scores))


def _evaluate_model(
    model: lgb.Booster,
    features: NDArray[np.floating],
    labels: NDArray[np.floating],
    groups: list[int],
) -> dict[str, float]:
    """Compute all evaluation metrics for a model."""
    predictions = np.asarray(model.predict(features), dtype=np.float64)

    return {
        "ndcg_at_5": _compute_ndcg(labels, predictions, groups, k=5),
        "ndcg_at_10": _compute_ndcg(labels, predictions, groups, k=10),
        "mrr": _compute_mrr(labels, predictions, groups),
        "precision_at_5": _compute_precision_at_k(labels, predictions, groups, k=5),
        "precision_at_10": _compute_precision_at_k(labels, predictions, groups, k=10),
        "num_queries": len(groups),
        "num_samples": len(labels),
    }


def _get_feature_importance(model: lgb.Booster) -> dict[str, float]:
    """Get feature importance from model."""
    importance = model.feature_importance(importance_type="gain")
    feature_names = [FEATURE_NAMES[FeatureIndex(i)] for i in range(FEATURE_COUNT)]

    total = sum(importance)
    if total > 0:
        importance = importance / total

    return dict(zip(feature_names, importance, strict=True))


def _print_evaluation_results(
    model_name: str,
    metrics: dict[str, float],
    feature_importance: dict[str, float] | None = None,
) -> None:
    """Print formatted evaluation results."""
    console.rule(f"[bold]Model: {model_name}[/bold]")

    console.print("\n[bold]Ranking Metrics:[/bold]")
    metrics_table = Table(show_header=True, header_style="bold")
    metrics_table.add_column("Metric")
    metrics_table.add_column("Value", justify="right")

    metrics_table.add_row("NDCG@5", f"{metrics['ndcg_at_5']:.4f}")
    metrics_table.add_row("NDCG@10", f"{metrics['ndcg_at_10']:.4f}")
    metrics_table.add_row("MRR", f"{metrics['mrr']:.4f}")
    metrics_table.add_row("Precision@5", f"{metrics['precision_at_5']:.4f}")
    metrics_table.add_row("Precision@10", f"{metrics['precision_at_10']:.4f}")
    console.print(metrics_table)

    console.print("\n[bold]Data Statistics:[/bold]")
    console.print(f"  Queries: {int(metrics['num_queries'])}")
    console.print(f"  Samples: {int(metrics['num_samples'])}")

    if feature_importance:
        console.print("\n[bold]Feature Importance (normalized):[/bold]")
        importance_table = Table(show_header=True, header_style="bold")
        importance_table.add_column("Feature")
        importance_table.add_column("Importance", justify="right")
        importance_table.add_column("Bar")

        sorted_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)
        for name, imp in sorted_features:
            bar = "█" * int(imp * 40)
            importance_table.add_row(name, f"{imp:.4f}", bar)
        console.print(importance_table)


def _compare_models(
    models: list[tuple[str, lgb.Booster]],
    features: NDArray[np.floating],
    labels: NDArray[np.floating],
    groups: list[int],
) -> list[tuple[str, dict[str, float]]]:
    """Compare multiple models and print comparison table."""
    results: list[tuple[str, dict[str, float]]] = []

    for name, model in models:
        metrics = _evaluate_model(model, features, labels, groups)
        results.append((name, metrics))

    console.rule("[bold]Model Comparison[/bold]")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Model")
    table.add_column("NDCG@5", justify="right")
    table.add_column("NDCG@10", justify="right")
    table.add_column("MRR", justify="right")
    table.add_column("P@5", justify="right")
    table.add_column("P@10", justify="right")

    for name, metrics in results:
        table.add_row(
            name,
            f"{metrics['ndcg_at_5']:.4f}",
            f"{metrics['ndcg_at_10']:.4f}",
            f"{metrics['mrr']:.4f}",
            f"{metrics['precision_at_5']:.4f}",
            f"{metrics['precision_at_10']:.4f}",
        )

    console.print(table)

    console.print("\n[bold]Best model per metric:[/bold]")
    metric_names = ["ndcg_at_5", "ndcg_at_10", "mrr", "precision_at_5", "precision_at_10"]
    for metric in metric_names:
        best_name = max(results, key=lambda x, m=metric: x[1][m])[0]
        best_value = max(results, key=lambda x, m=metric: x[1][m])[1][metric]
        console.print(f"  {metric}: [green]{best_name}[/green] ({best_value:.4f})")

    return results


@app.command("evaluate")
def evaluate_cmd(
    model_path: Annotated[Path, typer.Argument(help="Path to LightGBM model file (.txt)")],
    test_data: Annotated[Path, typer.Option("--test-data", "-t", help="Path to test data JSON file.")],
    show_importance: Annotated[
        bool,
        typer.Option("--show-importance", "-i", help="Show feature importance."),
    ] = False,
    output_json: Annotated[
        Path | None,
        typer.Option("--output-json", "-o", help="Write results to JSON file."),
    ] = None,
) -> None:
    """Evaluate a single model against test data."""
    console.print("[blue]Loading test data...[/blue]")
    features, labels, groups = _load_test_data(test_data)
    console.print(f"  Loaded {len(labels)} samples in {len(groups)} queries")

    if features.shape[1] != FEATURE_COUNT:
        console.print(f"[red]Error: Expected {FEATURE_COUNT} features, got {features.shape[1]}[/red]")
        raise typer.Exit(1)

    model = _load_model(model_path)
    metrics = _evaluate_model(model, features, labels, groups)

    importance = _get_feature_importance(model) if show_importance else None
    _print_evaluation_results(model_path.stem, metrics, importance)

    if output_json:
        results_output = {
            model_path.stem: {
                "metrics": metrics,
                "feature_importance": importance,
            }
        }
        output_json.write_text(json.dumps(results_output, indent=2))
        console.print(f"\n[green]Results written to: {output_json}[/green]")


@app.command("compare")
def compare_cmd(
    model_paths: Annotated[list[Path], typer.Argument(help="Paths to model files to compare.")],
    test_data: Annotated[Path, typer.Option("--test-data", "-t", help="Path to test data JSON file.")],
    output_json: Annotated[
        Path | None,
        typer.Option("--output-json", "-o", help="Write results to JSON file."),
    ] = None,
) -> None:
    """Compare multiple models against test data."""
    console.print("[blue]Loading test data...[/blue]")
    features, labels, groups = _load_test_data(test_data)
    console.print(f"  Loaded {len(labels)} samples in {len(groups)} queries")

    if features.shape[1] != FEATURE_COUNT:
        console.print(f"[red]Error: Expected {FEATURE_COUNT} features, got {features.shape[1]}[/red]")
        raise typer.Exit(1)

    models: list[tuple[str, lgb.Booster]] = []
    for path in model_paths:
        model = _load_model(path)
        models.append((path.stem, model))

    results = _compare_models(models, features, labels, groups)

    if output_json:
        results_output = dict(results)
        output_json.write_text(json.dumps(results_output, indent=2))
        console.print(f"\n[green]Results written to: {output_json}[/green]")


if __name__ == "__main__":
    app()
