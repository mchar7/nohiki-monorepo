"""Evaluate command for benchmarking finetuned models."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final

import numpy as np
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sentence_transformers import SentenceTransformer

from job_embedding_finetuning.config.settings import get_settings

os.environ["TOKENIZERS_PARALLELISM"] = "false"

JOBBERT_MODEL: Final[str] = "TechWolf/JobBERT-v2"
BASE_QWEN_MODEL: Final[str] = "Qwen/Qwen3-Embedding-0.6B"
LOCAL_QWEN_CACHE: Final[Path] = Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen3-Embedding-0.6B/snapshots/main"

app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")
console = Console(stderr=True)


@dataclass(frozen=True, slots=True)
class SkillPair:
    """A pair of skills with expected match status."""

    skill_a: str
    skill_b: str
    should_match: bool
    category: str = ""


@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    """Metrics for a single model benchmark."""

    model_name: str
    precision: float
    recall: float
    f1: float
    best_threshold: float
    tp: int
    fp: int
    tn: int
    fn: int
    min_tp_sim: float
    max_tn_sim: float
    mean_tp_sim: float
    mean_tn_sim: float


def _get_test_pairs() -> list[SkillPair]:
    """Get test pairs for benchmark evaluation."""
    pairs: list[SkillPair] = []

    tp_data = [
        ("nodejs", "node.js"),
        ("nodejs", "node js"),
        ("c++", "cpp"),
        ("c#", "csharp"),
        ("postgresql", "postgres"),
        ("kubernetes", "k8s"),
        ("elasticsearch", "elastic search"),
        ("mongodb", "mongo db"),
        ("graphql", "graph ql"),
        ("vuejs", "vue.js"),
        ("reactjs", "react.js"),
        ("typescript", "ts"),
        ("javascript", "js"),
        ("machine learning", "ml"),
        ("artificial intelligence", "ai"),
        ("natural language processing", "nlp"),
        ("amazon web services", "aws"),
        ("google cloud platform", "gcp"),
        ("user interface", "ui"),
        ("user experience", "ux"),
        ("Python", "python"),
        ("JAVA", "java"),
        ("software engineering", "software development"),
        ("web development", "web programming"),
        ("backend development", "back-end development"),
        ("frontend development", "front-end development"),
        ("full stack", "fullstack"),
        ("devops", "dev ops"),
        ("microservices", "micro services"),
        ("python", "python3"),
        ("angular", "angular 2"),
        ("java", "java 11"),
        (".net", ".net core"),
        ("dotnet", ".net"),
        ("react", "reactjs"),
        ("react native", "react-native"),
        ("node", "nodejs"),
        ("vue", "vuejs"),
        ("express", "expressjs"),
        ("next", "nextjs"),
        ("mysql", "mariadb"),
        ("vim", "neovim"),
        ("apache kafka", "kafka"),
        ("apache spark", "spark"),
    ]

    tn_data = [
        ("python", "java"),
        ("javascript", "java"),
        ("c++", "c"),
        ("c#", "c++"),
        ("ruby", "python"),
        ("rust", "go"),
        ("kotlin", "java"),
        ("typescript", "javascript"),
        ("react", "angular"),
        ("react", "vue"),
        ("django", "flask"),
        ("django", "fastapi"),
        ("spring", "django"),
        ("nextjs", "nuxtjs"),
        ("postgresql", "mysql"),
        ("postgresql", "mongodb"),
        ("mongodb", "redis"),
        ("elasticsearch", "mongodb"),
        ("redis", "memcached"),
        ("aws", "gcp"),
        ("aws", "azure"),
        ("s3", "gcs"),
        ("tensorflow", "pytorch"),
        ("keras", "pytorch"),
        ("pandas", "numpy"),
        ("docker", "kubernetes"),
        ("jenkins", "github actions"),
        ("terraform", "ansible"),
        ("prometheus", "grafana"),
        ("machine learning", "web development"),
        ("frontend", "backend"),
        ("python", "excel"),
        ("docker", "communication"),
        ("kubernetes", "leadership"),
        ("react", "agile"),
        ("react", "react native"),
        ("node", "deno"),
        ("nginx", "apache"),
        ("rest api", "graphql"),
        ("git", "github"),
        ("linux", "ubuntu"),
    ]

    for a, b in tp_data:
        pairs.append(SkillPair(a, b, should_match=True, category="tp"))
    for a, b in tn_data:
        pairs.append(SkillPair(a, b, should_match=False, category="tn"))

    return pairs


def _compute_similarities(
    model: SentenceTransformer,
    pairs: list[SkillPair],
) -> list[tuple[SkillPair, float]]:
    """Compute cosine similarities for all pairs efficiently."""
    cache: dict[str, np.ndarray] = {}
    results: list[tuple[SkillPair, float]] = []

    all_texts = set()
    for p in pairs:
        all_texts.add(p.skill_a.lower())
        all_texts.add(p.skill_b.lower())

    texts_list = list(all_texts)
    embeddings = model.encode(texts_list, normalize_embeddings=True, show_progress_bar=False)
    cache = dict(zip(texts_list, embeddings, strict=True))

    for pair in pairs:
        emb_a = cache[pair.skill_a.lower()]
        emb_b = cache[pair.skill_b.lower()]
        sim = float(np.dot(emb_a, emb_b))
        results.append((pair, sim))

    return results


def _find_best_threshold(
    results: list[tuple[SkillPair, float]],
) -> tuple[float, float, int, int, int, int]:
    """Find optimal threshold via F1 maximization."""
    tp_sims = [sim for p, sim in results if p.should_match]
    tn_sims = [sim for p, sim in results if not p.should_match]

    best_threshold, best_f1 = 0.80, 0.0
    best_tp, best_fp, best_tn, best_fn = 0, 0, 0, 0

    for threshold in np.arange(0.50, 0.95, 0.01):
        tp = sum(1 for s in tp_sims if s >= threshold)
        fn = sum(1 for s in tp_sims if s < threshold)
        tn = sum(1 for s in tn_sims if s < threshold)
        fp = sum(1 for s in tn_sims if s >= threshold)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        if f1 > best_f1:
            best_f1 = f1
            best_threshold = float(threshold)
            best_tp, best_fp, best_tn, best_fn = tp, fp, tn, fn

    return best_threshold, best_f1, best_tp, best_fp, best_tn, best_fn


def _benchmark_model(
    model_name: str,
    pairs: list[SkillPair],
    *,
    model_path: Path | None = None,
) -> BenchmarkMetrics:
    """Run benchmark on a single model."""
    load_path = str(model_path) if model_path else model_name
    console.print(f"  Loading [cyan]{load_path}[/cyan]...")

    model = SentenceTransformer(load_path, device="cpu")
    console.print(f"  Embedding dim: {model.get_sentence_embedding_dimension()}")

    console.print(f"  Computing similarities for {len(pairs)} pairs...")
    results = _compute_similarities(model, pairs)

    tp_sims = [sim for p, sim in results if p.should_match]
    tn_sims = [sim for p, sim in results if not p.should_match]

    threshold, _, tp, fp, tn, fn = _find_best_threshold(results)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return BenchmarkMetrics(
        model_name=model_name if not model_path else f"LoRA ({model_path.name})",
        precision=precision,
        recall=recall,
        f1=f1,
        best_threshold=threshold,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        min_tp_sim=min(tp_sims) if tp_sims else 0.0,
        max_tn_sim=max(tn_sims) if tn_sims else 0.0,
        mean_tp_sim=float(np.mean(tp_sims)) if tp_sims else 0.0,
        mean_tn_sim=float(np.mean(tn_sims)) if tn_sims else 0.0,
    )


def _display_comparison_table(metrics_list: list[BenchmarkMetrics]) -> None:
    """Display comparison table of all benchmarked models."""
    table = Table(title="Model Comparison Results", show_header=True)
    table.add_column("Model", style="bold cyan")
    table.add_column("F1", justify="right")
    table.add_column("Precision", justify="right")
    table.add_column("Recall", justify="right")
    table.add_column("Threshold", justify="right")
    table.add_column("TP/FN/TN/FP", justify="center")
    table.add_column("Mean TP Sim", justify="right")
    table.add_column("Mean TN Sim", justify="right")

    best_f1 = max(m.f1 for m in metrics_list)

    for m in metrics_list:
        f1_str = f"[green bold]{m.f1:.3f}[/]" if m.f1 == best_f1 else f"{m.f1:.3f}"
        table.add_row(
            m.model_name,
            f1_str,
            f"{m.precision:.3f}",
            f"{m.recall:.3f}",
            f"{m.best_threshold:.2f}",
            f"{m.tp}/{m.fn}/{m.tn}/{m.fp}",
            f"{m.mean_tp_sim:.3f}",
            f"{m.mean_tn_sim:.3f}",
        )

    console.print()
    console.print(table)
    console.print()

    best_model = max(metrics_list, key=lambda x: x.f1)
    console.print(f"[bold green]Winner:[/bold green] {best_model.model_name} (F1={best_model.f1:.3f})")

    if len(metrics_list) > 1:
        console.print("\n[bold]Analysis:[/bold]")
        for m in metrics_list:
            gap = m.min_tp_sim - m.max_tn_sim
            console.print(f"  • {m.model_name}: separation gap = {gap:.3f}")


@app.command("benchmark")
def run_benchmark(
    model_path: Annotated[
        Path | None,
        typer.Option("--model", "-m", help="Path to finetuned model."),
    ] = None,
    include_base: Annotated[
        bool,
        typer.Option("--include-base/--no-base", help="Include base Qwen3 model."),
    ] = True,
    include_jobbert: Annotated[
        bool,
        typer.Option("--include-jobbert/--no-jobbert", help="Include JobBERT-v2."),
    ] = True,
) -> None:
    """Benchmark embedding models on skill similarity task.

    Compares finetuned LoRA model against JobBERT-v2 and base Qwen3.

    Example:
        finetune evaluate benchmark --model ./models/job_finetune/final_model
        finetune evaluate benchmark --no-base  # Skip base Qwen3

    """
    settings = get_settings()
    target_model = model_path or settings.output_dir / "model" / "final_model"

    if not target_model.exists():
        console.print(f"[red]Model not found: {target_model}[/red]")
        console.print("[dim]Run 'finetune train run' first to train a model.[/dim]")
        raise typer.Exit(1)

    console.print()
    console.print(
        Panel.fit(
            "[bold blue]Embedding Model Benchmark[/bold blue]\n[dim]Skill Similarity Evaluation[/dim]",
            border_style="blue",
        )
    )
    console.print()

    pairs = _get_test_pairs()
    tp_count = sum(1 for p in pairs if p.should_match)
    tn_count = len(pairs) - tp_count
    console.print(f"[bold]Test pairs:[/bold] {len(pairs)} ({tp_count} TP, {tn_count} TN)")
    console.print()

    all_metrics: list[BenchmarkMetrics] = []

    if include_jobbert:
        console.print("[bold cyan]1. JobBERT-v2[/bold cyan]")
        metrics = _benchmark_model(JOBBERT_MODEL, pairs)
        all_metrics.append(metrics)
        console.print(f"  ✓ F1={metrics.f1:.3f} @ threshold={metrics.best_threshold:.2f}\n")

    if include_base:
        console.print("[bold cyan]2. Base Qwen3 0.6B[/bold cyan]")
        qwen_path = LOCAL_QWEN_CACHE if LOCAL_QWEN_CACHE.exists() else None
        metrics = _benchmark_model(BASE_QWEN_MODEL, pairs, model_path=qwen_path)
        all_metrics.append(metrics)
        console.print(f"  ✓ F1={metrics.f1:.3f} @ threshold={metrics.best_threshold:.2f}\n")

    console.print("[bold cyan]3. Fine-tuned LoRA Model[/bold cyan]")
    metrics = _benchmark_model("LoRA", pairs, model_path=target_model)
    all_metrics.append(metrics)
    console.print(f"  ✓ F1={metrics.f1:.3f} @ threshold={metrics.best_threshold:.2f}\n")

    _display_comparison_table(all_metrics)
