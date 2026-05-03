"""CLI command for running LLM-as-judge evaluation on benchmark results.

Provides the ``evaluate`` command that orchestrates multi-judge pointwise
evaluation with Rich progress display, checkpoint-based resume, cost cap
enforcement, and timeout support.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated

import typer
from nohiki_llm_client import (
    ApiKeyRegistry,
    LLMProviderSettings,
    LLMSettings,
    resolve_chain,
)
from pydantic import ValidationError
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from llm_benchmark.cli._helpers import (
    load_api_keys,
    load_api_keys_optional,
    load_benchmark_result,
)
from llm_benchmark.config.constants import (
    DEFAULT_COST_CAP_USD,
    DEFAULT_EVAL_CONCURRENCY,
    DEFAULT_MAX_RUNS_PER_FIXTURE,
)
from llm_benchmark.config.models import EvaluationResumeState, JudgeConfig, model_family
from llm_benchmark.display.console import console
from llm_benchmark.display.panels import display_multi_judge_results
from llm_benchmark.engine.budget import BudgetScheduler
from llm_benchmark.engine.checkpoint import (
    CheckpointManager,
    compute_eval_config_fingerprint,
)
from llm_benchmark.engine.judge import evaluate_multi_judge
from llm_benchmark.pricing import (
    PricingRouteError,
    PricingSnapshot,
    resolve_pricing_snapshot,
)
from llm_benchmark.schemas.aggregation import JudgmentUnit, MultiJudgeEvaluationSummary
from llm_benchmark.schemas.judge import PointwiseJudgment
from llm_benchmark.schemas.metrics import BenchmarkResult


def _build_resume_states(
    judges: list[JudgeConfig],
    checkpoint_manager: CheckpointManager | None,
) -> tuple[dict[str, EvaluationResumeState] | None, int, float, float]:
    """Build per-judge resume state and accumulated actual + charged progress."""
    if checkpoint_manager is None:
        return None, 0, 0.0, 0.0

    states: dict[str, EvaluationResumeState] = {}
    completed = 0
    cost = 0.0
    charged = 0.0
    for judge in judges:
        keys = checkpoint_manager.completed_keys_for_judge(judge.model)
        if not keys:
            continue
        count = checkpoint_manager.completed_count_for_judge(judge.model)
        judge_cost = checkpoint_manager.existing_cost_for_judge(judge.model)
        judge_charged = checkpoint_manager.existing_charged_for_judge(judge.model)
        existing_units = tuple(
            JudgmentUnit(
                fixture_id=record.fixture_id,
                treatment=record.model_name,
                run_number=record.run_number,
                judge=judge.model,
                judgment=record.judgment,
            )
            for record in checkpoint_manager.existing_records_for_judge(judge.model)
        )
        states[judge.model] = EvaluationResumeState(
            skip_task_keys=keys,
            existing_judgments=checkpoint_manager.existing_judgments_for_judge(judge.model),
            existing_units=existing_units,
            existing_cost_usd=judge_cost,
            existing_charged_usd=judge_charged,
            existing_completed_count=count,
        )
        completed += count
        cost += judge_cost
        charged += judge_charged
    return states, completed, cost, charged


async def _evaluate_async_with_progress(
    benchmark: BenchmarkResult,
    api_keys: ApiKeyRegistry,
    judges: list[JudgeConfig],
    *,
    checkpoint_manager: CheckpointManager | None = None,
    cost_cap_usd: float | None = None,
    timeout_seconds: float | None = None,
    max_concurrency: int = DEFAULT_EVAL_CONCURRENCY,
    unknown_price_max_usd: float | None = None,
    pricing_snapshots: dict[str, PricingSnapshot] | None = None,
) -> tuple[MultiJudgeEvaluationSummary, bool]:
    """Run multi-judge evaluation with Rich progress display and checkpointing.

    Builds per-judge resume states from the checkpoint (if any) to skip
    already-completed evaluations. Persists each judgment incrementally
    via the checkpoint manager so interrupted runs can resume. Supports
    graceful shutdown via cost cap or timeout.

    Args:
        benchmark: Benchmark result to evaluate.
        api_keys: Provider API key registry for cloud provider authentication.
        judges: Judge model configurations.
        checkpoint_manager: Optional manager for incremental persistence.
        cost_cap_usd: Stop evaluation when accumulated cost exceeds this.
        timeout_seconds: Stop evaluation after this many seconds.
        max_concurrency: Global maximum simultaneous provider calls.
        unknown_price_max_usd: Explicit per-call maximum for unknown judge pricing.
        pricing_snapshots: Per-judge immutable route-aware pricing evidence.

    Returns:
        Tuple of (summary, whether evaluation was stopped early).
    """
    grand_total = sum(
        1
        for judge in judges
        for treatment, model_result in benchmark.models.items()
        for run in model_result.runs
        if model_family(judge.model) != model_family(treatment) and run.success and run.output_json is not None
    )

    resume_states, initial_completed, initial_cost, initial_charged = _build_resume_states(judges, checkpoint_manager)
    if cost_cap_usd is None:
        msg = "Evaluation requires an owner-approved cost cap"
        raise ValueError(msg)
    budget_scheduler = BudgetScheduler(
        cap_usd=cost_cap_usd,
        max_concurrency=max_concurrency,
        initial_charged_usd=initial_charged,
        initial_actual_usd=initial_cost,
    )
    cancel_event = asyncio.Event()
    if initial_charged >= cost_cap_usd:
        cancel_event.set()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        expand=False,
    ) as progress:
        task = progress.add_task("[bold]Evaluating judges...[/bold]", total=max(grand_total, 1))
        completed_count = initial_completed
        accumulated_cost = initial_cost

        if initial_completed > 0:
            progress.update(
                task,
                completed=initial_completed,
                description=(
                    f"[bold]Resuming ({initial_completed}/{grand_total})...[/bold] | [green]${initial_cost:.4f}[/green]"
                ),
            )

        def update_progress(
            judge_model: str,
            fixture_id: str,
            completed: int,
            total: int,
            cost_usd: float,
        ) -> None:
            nonlocal completed_count, accumulated_cost
            completed_count += 1
            accumulated_cost += cost_usd
            short_judge = judge_model.rsplit("/", maxsplit=1)[-1] if "/" in judge_model else judge_model

            if cost_cap_usd is not None and accumulated_cost >= cost_cap_usd and not cancel_event.is_set():
                cancel_event.set()
                desc = (
                    f"[bold yellow]COST CAP ${cost_cap_usd:.2f} reached[/bold yellow]"
                    f" | [green]${accumulated_cost:.4f}[/green]"
                )
            else:
                desc = (
                    f"[cyan]{short_judge}[/cyan] | {fixture_id} ({completed}/{total})"
                    f" | [green]${accumulated_cost:.4f}[/green]"
                )
            progress.update(task, completed=completed_count, description=desc)

        def on_attempt_persist(
            judge_model: str,
            reasoning_effort: str,
            model_name: str,
            fixture_id: str,
            run_number: int,
            judgment: PointwiseJudgment | None,
            actual_cost_usd: float | None,
            charged_cost_usd: float,
        ) -> None:
            if not checkpoint_manager:
                return
            if judgment is not None:
                checkpoint_manager.record_judgment(
                    judge_model,
                    reasoning_effort,
                    model_name,
                    fixture_id,
                    run_number,
                    judgment,
                    actual_cost_usd or 0.0,
                    charged_cost_usd=charged_cost_usd,
                )
            else:
                checkpoint_manager.record_failure(
                    judge_model,
                    reasoning_effort,
                    model_name,
                    fixture_id,
                    run_number,
                    charged_cost_usd=charged_cost_usd,
                )

        async def _set_cancel_after(seconds: float) -> None:
            await asyncio.sleep(seconds)
            if not cancel_event.is_set():
                cancel_event.set()

        timer_task: asyncio.Task[None] | None = None
        if timeout_seconds is not None:
            timer_task = asyncio.create_task(_set_cancel_after(timeout_seconds))

        try:
            summary = await evaluate_multi_judge(
                benchmark,
                api_keys,
                judges,
                progress_callback=update_progress,
                on_attempt=on_attempt_persist if checkpoint_manager else None,
                resume_states=resume_states,
                cancel_event=cancel_event,
                budget_scheduler=budget_scheduler,
                pricing_snapshots=pricing_snapshots,
                unknown_price_max_usd=unknown_price_max_usd,
            )
        finally:
            if timer_task and not timer_task.done():
                timer_task.cancel()

        if cancel_event.is_set():
            progress.update(
                task,
                description=(
                    f"[bold yellow]Stopped[/bold yellow]"
                    f" ({completed_count}/{grand_total})"
                    f" | [green]${accumulated_cost:.4f}[/green]"
                ),
            )

        snapshot = budget_scheduler.snapshot
        summary = summary.model_copy(
            update={
                "reserved_cost_usd": snapshot.maximum_possible_usd,
                "maximum_possible_cost_usd": snapshot.maximum_possible_usd,
            }
        )
        return summary, cancel_event.is_set()


def _save_evaluation_results(
    summary: MultiJudgeEvaluationSummary,
    result_file: Path,
) -> None:
    """Display and save multi-judge evaluation results.

    Args:
        summary: Consolidated multi-judge evaluation summary.
        result_file: Base benchmark result path used for naming the output file.
    """
    display_multi_judge_results(summary)
    eval_output = _derive_eval_output(result_file)
    tmp = eval_output.with_suffix(".tmp")
    try:
        with tmp.open("w") as eval_file:
            eval_file.write(summary.model_dump_json(indent=2))
            eval_file.flush()
            os.fsync(eval_file.fileno())
        tmp.replace(eval_output)
        directory_fd = os.open(eval_output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    console.print(f"\n[green]Evaluation saved to:[/green] {eval_output}")


def _derive_eval_output(result_file: Path) -> Path:
    """Derive the ``.eval.json`` artifact path, never colliding with the source.

    A benchmark result is a ``*.json`` file; its evaluation lands at
    ``*.eval.json``. If the input itself is already an eval artifact the derived
    path would overwrite the source, so we fail clearly rather than destroy it.
    """
    eval_output = result_file.with_suffix(".eval.json")
    if eval_output.resolve() == result_file.resolve():
        console.print(
            f"[red]Error:[/red] Refusing to overwrite the source file {result_file}; "
            "the evaluation output would collide with the input. Pass the benchmark "
            "result (*.json), not an existing *.eval.json artifact."
        )
        raise typer.Exit(code=1)
    return eval_output


def _resolve_judge_weights(
    count: int,
    judge_weights: list[float] | None,
    *,
    count_error: str,
) -> list[float]:
    """Resolve positive consensus weights, defaulting to equal weights.

    Repeated ``--judge-weight`` values map positionally onto judges. When
    omitted, every judge is weighted equally at ``1.0``.
    """
    weights = judge_weights or [1.0] * count
    if len(weights) != count:
        console.print(f"[red]Error:[/red] {count_error}")
        raise typer.Exit(code=1)
    if any(weight <= 0.0 for weight in weights):
        console.print("[red]Error:[/red] Judge weights must be greater than zero.")
        raise typer.Exit(code=1)
    return weights


def _parse_judges(
    judge_models: list[str] | None,
    judge_weights: list[float] | None,
    *,
    base_url: str | None,
    api_key: str | None,
    concurrency: int,
) -> list[JudgeConfig]:
    """Validate and parse explicitly selected judge models."""
    if not judge_models:
        console.print("[red]Error:[/red] At least one --judge-model is required.")
        raise typer.Exit(code=1)
    if len(set(judge_models)) != len(judge_models):
        console.print("[red]Error:[/red] Each --judge-model must be unique.")
        raise typer.Exit(code=1)
    weights = _resolve_judge_weights(
        len(judge_models),
        judge_weights,
        count_error="--judge-weight must be repeated once per --judge-model.",
    )
    return [
        JudgeConfig.from_string(
            model,
            base_url=base_url,
            api_key=api_key,
            concurrency=concurrency,
            weight=weight,
        )
        for model, weight in zip(judge_models, weights, strict=True)
    ]


def _reject_colliding_judges(judges: list[JudgeConfig]) -> None:
    """Reject judges that would collapse into one result key before dispatch.

    Per-judge results, checkpoints, and consensus weights are all keyed by
    ``judge.model``. Two judges sharing that key silently overwrite one another,
    so a repeated model -- whether an exact duplicate or the same model routed or
    configured differently -- is rejected here rather than losing units/weights.
    """
    seen: dict[str, JudgeConfig] = {}
    for judge in judges:
        prior = seen.get(judge.model)
        if prior is not None:
            if prior.identity_key == judge.identity_key:
                msg = f"Judge {judge.model!r} is declared more than once; remove the duplicate."
            else:
                msg = (
                    f"Colliding judge identities for model {judge.model!r} "
                    f"({prior.identity_key!r} vs {judge.identity_key!r}); results are keyed by "
                    "model, so the same model cannot be declared twice with different settings."
                )
            raise typer.BadParameter(msg)
        seen[judge.model] = judge


def _load_chain_judges(
    path: Path,
    chain: str | None,
    judge_weights: list[float] | None,
) -> tuple[list[JudgeConfig], ApiKeyRegistry]:
    """Resolve independent judges from a standard ``LLMSettings`` named chain.

    Mirrors the benchmark generation path (``run.py``): the document must not
    embed API keys, and the requested chain is resolved via ``resolve_chain``
    with the usual fallback to the default provider. Each resolved model becomes
    one ``JudgeConfig`` carrying its model id, reasoning effort, endpoint, full
    provider routing (order, fallbacks, ZDR), and the chain's timeout, retry,
    and concurrency settings.

    API keys are resolved with precedence: when the highest-priority provider
    genuinely requires a key, the shared secret registry is mandatory and its
    absence is a hard error. Otherwise (pure-local, or an OpenAI-compatible
    endpoint with an explicit ``base_url``), an available canonical registry is
    adopted so a present provider key is used automatically, while an absent
    registry leaves dispatch keyless.
    Returns the resolved judges together with the registry to use at dispatch.
    """

    def _contains_credentials(value: object) -> bool:
        if isinstance(value, dict):
            return any(
                (key in {"api_key", "api_keys"} and bool(item)) or _contains_credentials(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(_contains_credentials(item) for item in value)
        return False

    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        msg = f"Invalid LLMSettings JSON: {exc}"
        raise typer.BadParameter(msg, param_hint="--llm-settings") from exc
    if not isinstance(payload, dict):
        msg = "LLMSettings JSON must define a top-level object"
        raise typer.BadParameter(msg, param_hint="--llm-settings")
    if _contains_credentials(payload):
        msg = "LLMSettings JSON must not contain API keys; use the existing secret registry"
        raise typer.BadParameter(msg, param_hint="--llm-settings")

    def _build_settings(registry: ApiKeyRegistry) -> LLMSettings:
        data = json.loads(json.dumps(payload))
        key_values = {name: secret.get_secret_value() for name, secret in (registry.model_extra or {}).items()}
        if isinstance(provider := data.get("provider"), dict):
            provider["api_keys"] = key_values
        return LLMSettings.model_validate_json(json.dumps(data))

    api_keys = ApiKeyRegistry()
    try:
        settings = _build_settings(api_keys)
    except ValidationError as exc:
        if "api_key" not in str(exc):
            msg = f"Invalid LLMSettings configuration: {exc}"
            raise typer.BadParameter(msg, param_hint="--llm-settings") from exc
        # The highest-priority provider needs a resolvable key: load the shared registry.
        api_keys = load_api_keys()
        try:
            settings = _build_settings(api_keys)
        except ValidationError as exc2:
            msg = f"Invalid LLMSettings configuration: {exc2}"
            raise typer.BadParameter(msg, param_hint="--llm-settings") from exc2
    else:
        # Empty-registry validation passed: the chain needs no mandatory key
        # (pure-local, or an OpenAI-compatible endpoint with an explicit
        # base_url). Still adopt an available canonical registry so a present
        # provider key (e.g. OpenAI) is used automatically; an absent registry
        # keeps dispatch keyless.
        api_keys = load_api_keys_optional()

    if chain is not None and chain not in settings.chains:
        available = ", ".join(sorted(settings.chains)) or "(none defined)"
        msg = f"Unknown chain {chain!r} in --llm-settings; available chains: {available}"
        raise typer.BadParameter(msg, param_hint="--chain")
    resolved: LLMProviderSettings = resolve_chain(chain, settings)

    weights = _resolve_judge_weights(
        len(resolved.models),
        judge_weights,
        count_error="--judge-weight must be repeated once per judge in the same order.",
    )
    judges = [
        JudgeConfig(
            model=model.model,
            reasoning_effort=model.reasoning_effort,
            weight=weight,
            provider_order=model.provider_order,
            provider_allow_fallbacks=model.provider_allow_fallbacks,
            provider_zdr=model.provider_zdr,
            concurrency=resolved.concurrency_limit,
            base_url=model.base_url,
            api_key=model.api_key.get_secret_value() if model.api_key else None,
            timeout_seconds=resolved.timeout_seconds,
            max_retries=resolved.max_tool_retries,
        )
        for model, weight in zip(resolved.models, weights, strict=True)
    ]
    return judges, api_keys


def _resolve_judges(
    judge_models: list[str] | None,
    judge_weights: list[float] | None,
    llm_settings: Path | None,
    chain: str | None,
    *,
    base_url: str | None,
    api_key: str | None,
    concurrency: int,
) -> tuple[list[JudgeConfig], ApiKeyRegistry]:
    """Resolve judges and the dispatch registry from CLI options or a chain.

    A ``--llm-settings`` document is mutually exclusive with the direct
    ``--judge-model`` selection and the global ``--base-url`` / ``--api-key``
    endpoint overrides. ``--chain`` requires ``--llm-settings``. The secret
    registry is mandatory only when a judge genuinely needs it (a cloud judge
    without an explicit ``--api-key``); otherwise an available canonical
    registry is adopted when present so custom OpenAI-compatible endpoints use a
    canonical key automatically, and an absent registry stays keyless. Colliding
    judge identities are rejected before dispatch.
    """
    if llm_settings is not None:
        conflicts = [
            name
            for name, provided in (
                ("--judge-model", bool(judge_models)),
                ("--base-url", base_url is not None),
                ("--api-key", api_key is not None),
            )
            if provided
        ]
        if conflicts:
            msg = f"--llm-settings is mutually exclusive with {', '.join(conflicts)}"
            raise typer.BadParameter(msg)
        judges, api_keys = _load_chain_judges(llm_settings, chain, judge_weights)
    else:
        if chain is not None:
            msg = "--chain requires --llm-settings"
            raise typer.BadParameter(msg)
        judges = _parse_judges(
            judge_models,
            judge_weights,
            base_url=base_url,
            api_key=api_key,
            concurrency=concurrency,
        )
        # A judge that mandates a registry key must load it (absence is a hard
        # error). Otherwise adopt an available canonical registry so a custom
        # OpenAI-compatible endpoint automatically uses a present OpenAI key,
        # while an absent registry keeps dispatch keyless.
        need_registry = any(judge.requires_registry_key for judge in judges)
        api_keys = load_api_keys() if need_registry else load_api_keys_optional()
    _reject_colliding_judges(judges)
    return judges, api_keys


def _resolve_pricing_snapshots(
    judges: list[JudgeConfig],
    unknown_price_max_usd: float | None,
) -> dict[str, PricingSnapshot]:
    """Resolve one route-aware pricing snapshot per judge and validate sizing.

    Fails clearly on an unroutable OpenRouter route or when an unknown-price
    judge lacks an explicit per-call maximum. Local judges resolve to zero cost
    and need no maximum, so a pure-local judge set never requires one.
    """
    try:
        snapshots = {judge.model: resolve_pricing_snapshot(judge.to_model_config()) for judge in judges}
    except PricingRouteError as exc:
        raise typer.BadParameter(str(exc), param_hint="--judge-model") from exc
    try:
        for judge in judges:
            snapshots[judge.model].maximum_call_cost(
                max_input_tokens=0,
                max_output_tokens=0,
                unknown_price_max_usd=unknown_price_max_usd,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--unknown-price-max") from exc
    return snapshots


def evaluate(
    result_file: Annotated[Path, typer.Argument(help="Benchmark result JSON file")],
    judge_models: Annotated[
        list[str] | None,
        typer.Option(
            "--judge-model",
            "-j",
            help="Judge model(s). Format: model or model:effort (e.g. openrouter:openai/gpt-5.2:medium)",
        ),
    ] = None,
    judge_weights: Annotated[
        list[float] | None,
        typer.Option(
            "--judge-weight",
            help="Positive consensus weight; repeat once per --judge-model in the same order.",
        ),
    ] = None,
    llm_settings: Annotated[
        Path | None,
        typer.Option(
            "--llm-settings",
            exists=True,
            dir_okay=False,
            help="Standard LLMSettings JSON providing a named judge chain "
            "(mutually exclusive with --judge-model/--base-url/--api-key).",
        ),
    ] = None,
    chain: Annotated[
        str | None,
        typer.Option(
            "--chain",
            help="Named judge chain within --llm-settings (falls back to the default provider).",
        ),
    ] = None,
    max_runs: Annotated[
        int,
        typer.Option(
            "--max-runs",
            "-r",
            help="Max runs per model/fixture combo to evaluate (lowest run numbers selected)",
            min=1,
        ),
    ] = DEFAULT_MAX_RUNS_PER_FIXTURE,
    concurrency: Annotated[
        int,
        typer.Option("--concurrency", "-c", help="Max parallel judge calls per judge", min=1),
    ] = DEFAULT_EVAL_CONCURRENCY,
    min_pass_rate: Annotated[
        float,
        typer.Option(
            "--min-pass-rate",
            help="Skip models with benchmark pass rate below this threshold (0.0-1.0)",
            min=0.0,
            max=1.0,
        ),
    ] = 0.5,
    fixture_filter: Annotated[
        list[str] | None,
        typer.Option(
            "--fixture",
            "-f",
            help="Evaluate only these fixtures (repeatable). Omit to use all.",
        ),
    ] = None,
    cost_cap: Annotated[
        float,
        typer.Option(
            "--cost-cap",
            help="Stop evaluation if accumulated LLM cost (USD) exceeds this cap",
            min=0.01,
        ),
    ] = DEFAULT_COST_CAP_USD,
    unknown_price_max: Annotated[
        float | None,
        typer.Option(
            "--unknown-price-max",
            help="Explicit maximum USD per judge call when pricing cannot be resolved",
            min=0.01,
        ),
    ] = None,
    timeout: Annotated[
        float | None,
        typer.Option(
            "--timeout",
            "-t",
            help="Stop evaluation after this many seconds (safety timeout)",
            min=1.0,
        ),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            "-b",
            help="Optional API endpoint override for the judge model.",
        ),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            help="Per-model API key override for the judge. Overrides the ApiKeyRegistry lookup.",
        ),
    ] = None,
) -> None:
    """Run pointwise LLM-as-judge evaluation on stored benchmark results."""
    if not result_file.exists():
        console.print(f"[red]Error:[/red] Result file not found: {result_file}")
        raise typer.Exit(code=1)

    if result_file.name.endswith(".eval.json"):
        console.print(
            f"[red]Error:[/red] {result_file} is an evaluation artifact, not a benchmark result; "
            "pass the benchmark result (*.json)."
        )
        raise typer.Exit(code=1)

    benchmark = load_benchmark_result(result_file)

    if fixture_filter:
        unknown = set(fixture_filter) - set(benchmark.fixtures_used)
        if unknown:
            console.print(f"[red]Error:[/red] Unknown fixtures: {', '.join(sorted(unknown))}")
            raise typer.Exit(code=1)
        selected_fixtures = fixture_filter
    else:
        selected_fixtures = benchmark.fixtures_used

    filtered_benchmark, skipped_models = benchmark.filter_for_evaluation(
        selected_fixtures,
        min_pass_rate,
        max_runs_per_fixture=max_runs,
    )

    total_evaluations = sum(len(m.runs) for m in filtered_benchmark.models.values())
    if total_evaluations == 0:
        console.print("[red]Error:[/red] No successful extraction outputs to evaluate after filtering.")
        raise typer.Exit(code=1)

    judges, api_keys = _resolve_judges(
        judge_models,
        judge_weights,
        llm_settings,
        chain,
        base_url=base_url,
        api_key=api_key,
        concurrency=concurrency,
    )
    pricing_snapshots = _resolve_pricing_snapshots(judges, unknown_price_max)
    unsupported = [
        treatment
        for treatment in filtered_benchmark.models
        if all(model_family(treatment) == model_family(judge.model) for judge in judges)
    ]
    if unsupported:
        console.print(
            "[red]Error:[/red] No independent judge remains for same-family treatment(s): "
            + ", ".join(sorted(unsupported))
        )
        raise typer.Exit(code=1)
    independent_evaluations = sum(
        len(model_result.runs)
        for judge in judges
        for treatment, model_result in filtered_benchmark.models.items()
        if model_family(treatment) != model_family(judge.model)
    )
    judge_count = len(judges)
    judge_noun = "judge" if judge_count == 1 else "judges"
    judge_label = "Judge" if judge_count == 1 else "Judges"

    header_lines = [
        f"[bold]Models:[/bold] {len(filtered_benchmark.models)} loaded",
        f"[bold]Fixtures:[/bold] {len(selected_fixtures)}"
        + (f" (filtered from {len(benchmark.fixtures_used)})" if fixture_filter else ""),
        f"[bold]Max runs/fixture:[/bold] {max_runs} (of {benchmark.runs_per_fixture} available)",
        f"[bold]Evaluations:[/bold] {independent_evaluations} independent judge units "
        f"({total_evaluations} outputs; {judge_count} declared {judge_noun})",
        f"[bold]Concurrency:[/bold] {concurrency} per judge",
        f"[bold]Cost cap:[/bold] ${cost_cap:.2f}" + (f" | [bold]Timeout:[/bold] {timeout:.0f}s" if timeout else ""),
    ]
    header_lines.extend(
        f"[bold]{judge_label}:[/bold] [cyan]{judge.model}[/cyan] "
        f"(effort={judge.reasoning_effort}, weight={judge.weight:g})"
        for judge in judges
    )
    if skipped_models:
        skip_details = ", ".join(f"{name} ({rate:.0%})" for name, rate in sorted(skipped_models.items()))
        header_lines.append(
            f"[bold yellow]Skipped ({len(skipped_models)}):[/bold yellow] {skip_details}"
            f" [dim](min pass rate: {min_pass_rate:.0%})[/dim]"
        )

    console.print(
        Panel(
            "\n".join(header_lines),
            title="[bold]LLM-as-Judge Evaluation[/bold]",
            subtitle="Nohiki",
            border_style="blue",
        )
    )

    config_fingerprint = compute_eval_config_fingerprint(
        benchmark_timestamp=benchmark.timestamp,
        max_runs_per_fixture=max_runs,
        min_pass_rate=min_pass_rate,
        fixtures=list(selected_fixtures),
        judge_models=[
            f"{j.model}|effort={j.reasoning_effort}|weight={j.weight:g}|"
            f"providers={','.join(j.provider_order)}|fallbacks={j.provider_allow_fallbacks}|"
            f"zdr={j.provider_zdr}|base_url={j.base_url or ''}|"
            f"timeout={j.effective_timeout_seconds:g}|retries={j.effective_max_retries}|"
            f"concurrency={j.effective_concurrency}"
            for j in judges
        ],
        cost_cap_usd=cost_cap,
        unknown_price_max_usd=unknown_price_max,
    )
    checkpoint_mgr = CheckpointManager(result_file, config_fingerprint)

    if checkpoint_mgr.has_progress:
        console.print(
            Panel.fit(
                f"[bold yellow]Resuming from checkpoint[/bold yellow]\n"
                f"Completed: {checkpoint_mgr.total_completed} judgments\n"
                f"{checkpoint_mgr.resume_summary()}",
                border_style="yellow",
            )
        )

    multi_summary, cost_cap_hit = asyncio.run(
        _evaluate_async_with_progress(
            filtered_benchmark,
            api_keys,
            judges,
            checkpoint_manager=checkpoint_mgr,
            cost_cap_usd=cost_cap,
            timeout_seconds=timeout,
            max_concurrency=concurrency,
            unknown_price_max_usd=unknown_price_max,
            pricing_snapshots=pricing_snapshots,
        )
    )

    _save_evaluation_results(multi_summary, result_file)

    if cost_cap_hit:
        console.print(
            Panel.fit(
                "[bold yellow]Evaluation stopped early[/bold yellow]\n"
                f"Cost cap of ${cost_cap:.2f} reached or timeout expired\n"
                "Completed evaluations saved. Checkpoint preserved for resume.",
                border_style="yellow",
            )
        )
    else:
        checkpoint_mgr.cleanup()
