"""CLI command for executing LLM benchmarks.

Provides the ``run`` command that orchestrates parallel benchmark execution
across models and fixtures with incremental saving, resume support, cost
estimation, and Rich progress display.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Literal

import typer
from nohiki_llm_client import (
    ApiKeyRegistry,
    LLMModelConfig,
    LLMSettings,
    ReasoningEffort,
    resolve_chain,
)
from nohiki_llm_client.config.constants import (
    API_KEY_OPTIONAL_PROVIDERS,
    DEFAULT_MAX_TOOL_RETRIES,
    DEFAULT_REASONING_EFFORT,
    KEYLESS_PROVIDERS,
)
from pydantic import SecretStr, ValidationError
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

from llm_benchmark.cli._helpers import load_api_keys, save_timestamped_snapshot
from llm_benchmark.config.constants import (
    DEFAULT_BENCHMARK_CONCURRENCY,
    DEFAULT_COST_CAP_USD,
    DEFAULT_FIXTURES,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    DEFAULT_RUNS_PER_FIXTURE,
)
from llm_benchmark.config.models import BenchmarkConfig
from llm_benchmark.display.console import console
from llm_benchmark.display.panels import (
    display_benchmark_results,
    display_cost_estimate,
)
from llm_benchmark.engine.runner import (
    BenchmarkRunner,
    experiment_fingerprint,
    treatment_ids,
)
from llm_benchmark.fixtures import compute_fixture_checksum
from llm_benchmark.pricing import PricingRouteError, resolve_pricing_snapshot
from llm_benchmark.schemas.metrics import BenchmarkResult, ModelResult, RunResult

_VALIDATION_KEY_PLACEHOLDER = "unused-benchmark-validation-placeholder"


def _group_model_specs(group: object) -> list[tuple[str, str | None]]:
    """Extract ``(model, base_url)`` specs from one LLMSettings provider group.

    Narrows the loosely-typed parsed JSON explicitly: a non-dict group, a missing
    or non-list ``models``, and non-dict entries are skipped, and ``base_url`` is
    kept only when it is a string. Invalid shapes yield no specs rather than being
    silently coerced.
    """
    if not isinstance(group, dict):
        return []
    models = group.get("models")
    if not isinstance(models, list):
        return []
    specs: list[tuple[str, str | None]] = []
    for entry in models:
        if not isinstance(entry, dict):
            continue
        base_url = entry.get("base_url")
        specs.append(
            (
                str(entry.get("model", "")),
                base_url if isinstance(base_url, str) else None,
            )
        )
    return specs


def _referenced_key_providers(payload: object) -> set[str]:
    """Return provider names in an LLMSettings payload that need an API key.

    Scans the default provider and every named chain so structural validation of
    the whole document can be satisfied for cloud providers the registry does not
    cover (see ``_load_llm_treatments``).
    """
    if not isinstance(payload, dict):
        return set()
    groups: list[object] = [payload.get("provider")]
    chains = payload.get("chains")
    if isinstance(chains, dict):
        groups.extend(chains.values())
    providers: set[str] = set()
    for group in groups:
        for model, base_url in _group_model_specs(group):
            if _provider_needs_registry_key(model, base_url):
                providers.add(model.split(":", 1)[0] if ":" in model else model)
    return providers


def _load_llm_treatments(
    path: Path,
    chain: str | None,
    api_keys: object,
) -> tuple[tuple[LLMModelConfig, ...], object]:
    """Load a standard LLMSettings document and resolve independent treatments."""

    def contains_credentials(value: object) -> bool:
        if isinstance(value, dict):
            return any(
                (key in {"api_key", "api_keys"} and bool(item)) or contains_credentials(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(contains_credentials(item) for item in value)
        return False

    payload = json.loads(path.read_text())
    if contains_credentials(payload):
        msg = "LLMSettings JSON must not contain API keys; use the existing secret registry"
        raise typer.BadParameter(msg, param_hint="--llm-settings")
    registry = getattr(api_keys, "model_extra", None) or {}
    key_values = {name: secret.get_secret_value() for name, secret in registry.items()}
    # Whole-document validation checks the default provider and every chain's
    # highest-priority model, so a cloud default provider would block a pure-local
    # selected chain under an empty registry. Fill any cloud provider the registry
    # does not cover with a benign placeholder used solely for structural
    # validation and resolve_chain(): runtime keys come from BenchmarkConfig.api_keys
    # (never these), and run()'s preflight check rejects a selected cloud treatment
    # whose real key is genuinely absent, so a placeholder can never reach dispatch.
    for provider_name in _referenced_key_providers(payload):
        key_values.setdefault(provider_name, _VALIDATION_KEY_PLACEHOLDER)
    provider = payload.setdefault("provider", {})
    provider["api_keys"] = key_values
    settings = LLMSettings.model_validate_json(json.dumps(payload))
    resolved = resolve_chain(chain, settings)
    return tuple(resolved.models), resolved


def _load_raw_result(path: Path, *, fresh: bool, delete_on_fresh: Path | None = None) -> BenchmarkResult | None:
    """Load an unmodified benchmark result from disk, or None when starting fresh.

    This is the preservation base: callers must use the returned value for all
    incremental saves and final merges so that history is never discarded.

    Args:
        path: File to load from.
        fresh: When True, deletes ``delete_on_fresh`` (or ``path``) and returns None.
        delete_on_fresh: Optional separate path to delete on ``fresh=True``.

    Returns:
        The fully unmodified ``BenchmarkResult``, or ``None``.
    """
    if fresh:
        target = delete_on_fresh if delete_on_fresh is not None else path
        if target.exists():
            target.unlink()
            console.print(f"[yellow]Deleted existing results:[/yellow] {target}")
        return None

    if not path.exists():
        return None

    try:
        return BenchmarkResult.load(path)
    except (json.JSONDecodeError, ValidationError, OSError) as exc:
        msg = f"Cannot resume invalid benchmark result {path}: {type(exc).__name__}"
        raise typer.BadParameter(msg, param_hint="--output") from exc


def _apply_stale_fixture_filter(
    raw: BenchmarkResult,
    selected_fixtures: list[str],
    current_checksums: dict[str, str],
) -> BenchmarkResult:
    """Return a copy of ``raw`` with runs for stale fixtures stripped.

    Thin CLI wrapper around ``BenchmarkResult.strip_stale_fixture_runs``
    that adds console output when stale fixtures are detected.

    Args:
        raw: Fully loaded, unmodified benchmark result.
        selected_fixtures: Fixture IDs for the current run.
        current_checksums: Current SHA-256 checksums keyed by fixture ID.

    Returns:
        ``raw`` unchanged when no fixture is stale; a stripped copy otherwise.
    """
    filtered, stale_ids = raw.strip_stale_fixture_runs(selected_fixtures, current_checksums)
    if stale_ids:
        console.print(
            f"[yellow]Fixture content changed for:[/yellow] {', '.join(sorted(stale_ids))} \u2014 "
            "those runs will be re-executed."
        )
    return filtered


def _resolve_existing_result(
    path: Path,
    selected_fixtures: list[str],
    current_checksums: dict[str, str],
    *,
    fresh: bool,
) -> BenchmarkResult | None:
    """Load and filter an existing benchmark result in one step.

    Combines ``_load_raw_result`` and ``_apply_stale_fixture_filter`` for
    callers that need both operations together.

    Args:
        path: File to load from.
        selected_fixtures: Fixture IDs for the current run.
        current_checksums: Current SHA-256 checksums keyed by fixture ID.
        fresh: When True, deletes existing and returns None.

    Returns:
        Filtered ``BenchmarkResult``, or ``None``.
    """
    raw = _load_raw_result(path, fresh=fresh)
    if raw is None:
        return None
    return _apply_stale_fixture_filter(raw, selected_fixtures, current_checksums)


def _save_incremental(
    partial_runs: dict[str, list[RunResult]],
    output_path: Path,
    fixtures_used: list[str],
    runs_per_fixture: int,
    fixture_checksums: dict[str, str],
    experiment_fingerprint: str,
    full_existing: BenchmarkResult | None,
) -> None:
    """Persist the current partial run state to the output file.

    Merges with ``full_existing`` before saving so that historical data from
    previous configs is never discarded, even on mid-run cancellation.

    Args:
        partial_runs: Mapping of model to accumulated RunResult list.
        output_path: Destination file to write.
        fixtures_used: Fixture IDs for this benchmark session.
        runs_per_fixture: Configured runs per fixture.
        fixture_checksums: Content checksums for current fixtures.
        experiment_fingerprint: Immutable identity of the current experiment.
        full_existing: Full historical result to merge with, or None.
    """
    current = BenchmarkResult(
        fixtures_used=fixtures_used,
        runs_per_fixture=runs_per_fixture,
        experiment_fingerprint=experiment_fingerprint,
        fixture_checksums=fixture_checksums,
        models={
            m: ModelResult(
                model=m,
                runs=runs,
                total_cost_usd=sum(r.actual_cost_usd or 0.0 for r in runs),
            )
            for m, runs in partial_runs.items()
        },
    )
    result_to_save = full_existing.merge(current) if full_existing is not None else current
    result_to_save.save(output_path)


def _show_resume_info(scoped_existing: BenchmarkResult | None, total: int) -> None:
    """Display resume progress summary when a prior scoped result exists.

    Args:
        scoped_existing: Config-scoped existing result, or None if starting fresh.
        total: Total number of runs for the current configuration.
    """
    if scoped_existing is None:
        return
    completed = len(scoped_existing.completed_run_keys())
    if completed > 0:
        console.print(
            f"[bold]Resuming:[/bold] [green]{completed}[/green] runs already done, "
            f"[cyan]{total - completed}[/cyan] remaining."
        )
        display_benchmark_results(scoped_existing)


def _confirm_proceed(
    *,
    yes: bool,
    scoped_existing: BenchmarkResult | None,
    total: int,
    total_cost: float,
) -> bool:
    """Prompt for confirmation unless --yes was passed.

    Args:
        yes: When True, skip the prompt and return True immediately.
        scoped_existing: Config-scoped existing result for remaining run count.
        total: Total configured run count.
        total_cost: Estimated cost from the pricing display.

    Returns:
        True if the user confirmed or --yes was set.
    """
    if yes:
        return True
    completed_count = len(scoped_existing.completed_run_keys()) if scoped_existing else 0
    remaining = total - completed_count
    prompt = f"\nProceed with {remaining} remaining runs? (estimated cost: ${total_cost:.4f}) [y/N]: "
    if console.input(prompt).lower() not in ("y", "yes"):
        console.print("[yellow]Benchmark cancelled.[/yellow]")
        return False
    return True


async def _run_benchmark_async(
    config: BenchmarkConfig,
    output_path: Path,
    *,
    existing_result: BenchmarkResult | None = None,
    full_existing_result: BenchmarkResult | None = None,
    current_checksums: dict[str, str] | None = None,
) -> BenchmarkResult:
    """Execute benchmark with Rich progress display and incremental saving.

    Each completed run is immediately persisted to ``output_path`` so progress
    survives cancellation.

    Args:
        config: Benchmark configuration.
        output_path: Destination file for incremental and final results.
        existing_result: Config-scoped prior result used for skip decisions.
        full_existing_result: Complete unfiltered historical result merged into
            every incremental save to prevent data loss across config changes.
        current_checksums: SHA-256 checksums of current fixture content.

    Returns:
        Complete benchmark result scoped to the current configuration.
    """
    runner = BenchmarkRunner(config)
    completed_keys = (
        existing_result.completed_run_keys(experiment_fingerprint(config)[0]) if existing_result else frozenset()
    )
    total_runs = len(config.models) * len(config.fixture_ids) * config.runs_per_fixture
    remaining_runs = total_runs - len(completed_keys)
    checksums = current_checksums or {}

    partial_runs: dict[str, list[RunResult]] = {
        m: list(existing_result.models[m].runs) if existing_result and m in existing_result.models else []
        for m in treatment_ids(config)
    }

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
        suffix = f" ({len(completed_keys)} already done)" if completed_keys else ""
        overall_task = progress.add_task(
            f"[bold]Running {len(config.models)} models x "
            f"{len(config.fixture_ids)} fixtures x {config.runs_per_fixture} runs{suffix}",
            total=max(remaining_runs, 1),
        )
        runs_completed = 0

        def update_progress(model: str, fixture_id: str, run_number: int, *, run_result: RunResult) -> None:
            nonlocal runs_completed
            runs_completed += 1
            partial_runs[model].append(run_result)
            _save_incremental(
                partial_runs,
                output_path,
                config.fixture_ids,
                config.runs_per_fixture,
                checksums,
                experiment_fingerprint(config)[0],
                full_existing_result,
            )
            status = "[green]✓[/green]" if run_result.success else "[red]✗[/red]"
            progress.console.print(
                f"{status} [cyan]{model:40s}[/cyan] {fixture_id:30s} run {run_number}",
            )
            progress.update(overall_task, completed=runs_completed)

        final = await runner.run(progress_callback=update_progress, existing_result=existing_result)
        return final.model_copy(update={"fixture_checksums": checksums})


def _provider_needs_registry_key(model: str, base_url: str | None) -> bool:
    """Return True when a treatment must resolve its key from the secret registry.

    Local providers (llama.cpp, Ollama), providers whose key is optional
    (e.g. Google Vertex ADC), and OpenAI-compatible custom endpoints
    (``openai:`` with a base URL) never need the canonical secrets directory.
    """
    provider = model.split(":", 1)[0] if ":" in model else model
    if provider in KEYLESS_PROVIDERS or provider in API_KEY_OPTIONAL_PROVIDERS:
        return False
    return not (provider == "openai" and base_url is not None)


def _requires_secret_registry(
    model_names: list[str],
    llm_settings: Path | None,
    chain: str | None,
    *,
    base_url: str | None,
    api_key: str | None,
) -> bool:
    """Decide whether the canonical secret registry must be loaded up front.

    An explicit ``--api-key`` covers every treatment, and pure-local runs need
    no keys at all, so neither touches the secrets directory. A named-settings
    document is inspected for the *selected* chain's models -- mirroring
    ``resolve_chain`` (the named chain when present, else the default provider) --
    so a local default paired with a cloud chain still loads the registry while a
    pure-local selected chain stays secret-free. Provider prefixes are read
    straight from the payload, so no keys are needed to make this decision.
    Malformed JSON is treated as "required" so the authoritative error surfaces
    during resolution.
    """
    if api_key:
        return False
    if llm_settings is not None:
        try:
            payload = json.loads(llm_settings.read_text())
        except json.JSONDecodeError, OSError:
            return True
        if not isinstance(payload, dict):
            return True
        chains = payload.get("chains")
        if chain is not None and isinstance(chains, dict) and chain in chains:
            selected = chains[chain]
        else:
            selected = payload.get("provider")
        specs = _group_model_specs(selected)
    else:
        specs = [(name, base_url if name.split(":", 1)[0] == "openai" else None) for name in model_names]
    return any(_provider_needs_registry_key(model, url) for model, url in specs)


def _convenience_base_url(name: str, *, base_url: str | None, ollama_base_url: str | None) -> str | None:
    """Resolve the endpoint base URL for a bare ``--model`` treatment.

    Local providers require an explicit base URL at ``LLMModelConfig`` validation:
    Ollama models carry their dedicated configured URL and llama.cpp models carry
    ``--base-url``. OpenAI-compatible custom endpoints also keep ``--base-url``;
    other providers use their built-in default.
    """
    provider = name.split(":", 1)[0] if ":" in name else name
    if provider == "ollama":
        return ollama_base_url or DEFAULT_OLLAMA_BASE_URL
    if provider in {"llamacpp", "openai"}:
        return base_url
    return None


def _resolve_treatments(
    model_names: list[str],
    llm_settings: Path | None,
    chain: str | None,
    *,
    reasoning_effort: ReasoningEffort,
    base_url: str | None,
    ollama_base_url: str | None,
    api_key: str | None,
    api_keys: object,
) -> tuple[tuple[LLMModelConfig, ...], object | None]:
    """Resolve CLI convenience models or a standard named LLM chain."""
    if llm_settings is not None:
        if model_names:
            msg = "--llm-settings is mutually exclusive with --model"
            raise typer.BadParameter(msg)
        return _load_llm_treatments(llm_settings, chain, api_keys)
    if chain is not None:
        msg = "--chain requires --llm-settings"
        raise typer.BadParameter(msg)
    if not model_names:
        msg = "At least one --model or --llm-settings is required"
        raise typer.BadParameter(msg)
    return (
        tuple(
            LLMModelConfig(
                model=name,
                reasoning_effort=reasoning_effort,
                base_url=_convenience_base_url(name, base_url=base_url, ollama_base_url=ollama_base_url),
                api_key=SecretStr(api_key) if api_key else None,
                app_title="Nohiki LLM Benchmark",
            )
            for name in model_names
        ),
        None,
    )


def run(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Explicit experiment result JSON path"),
    ],
    models: Annotated[list[str] | None, typer.Option("--model", "-m", help="Model(s) to benchmark")] = None,
    llm_settings: Annotated[
        Path | None,
        typer.Option(
            "--llm-settings",
            exists=True,
            dir_okay=False,
            help="Standard LLMSettings JSON",
        ),
    ] = None,
    chain: Annotated[str | None, typer.Option("--chain", help="Named chain within --llm-settings")] = None,
    fixtures: Annotated[list[str] | None, typer.Option("--fixture", "-f", help="Fixture ID(s) to use")] = None,
    runs: Annotated[
        int, typer.Option("--runs", "-r", help="Runs per fixture per model", min=1)
    ] = DEFAULT_RUNS_PER_FIXTURE,
    concurrency: Annotated[
        int, typer.Option("--concurrency", "-c", help="Max parallel LLM calls", min=1)
    ] = DEFAULT_BENCHMARK_CONCURRENCY,
    ollama_base_url: Annotated[
        str | None,
        typer.Option("--ollama-base-url", help="Ollama API base URL (overrides default)"),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", "-b", help="Base URL override for openai: and llamacpp: models"),
    ] = None,
    ollama_timeout: Annotated[
        float | None,
        typer.Option(
            "--ollama-timeout",
            help="Per-call timeout for Ollama models in seconds",
            min=1.0,
        ),
    ] = None,
    max_tokens: Annotated[
        int | None,
        typer.Option("--max-tokens", help="Max output tokens per call (default: no limit)", min=1),
    ] = None,
    cost_cap: Annotated[
        float,
        typer.Option("--cost-cap", help="Owner-approved reserved cost cap in USD", min=0.01),
    ] = DEFAULT_COST_CAP_USD,
    unknown_price_max: Annotated[
        float | None,
        typer.Option(
            "--unknown-price-max",
            help="Explicit maximum USD per call for treatments without resolvable pricing",
            min=0.01,
        ),
    ] = None,
    max_retries: Annotated[
        int,
        typer.Option(
            "--max-retries",
            help="PydanticAI structured-output validation retries per call. Each retry sends the "
            "validation error back to the model as feedback for self-correction. Set to 0 to disable.",
            min=0,
        ),
    ] = DEFAULT_MAX_TOOL_RETRIES,
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            help="Per-model API key override for all models in this session. "
            "Overrides the ApiKeyRegistry for every LLM call, enabling custom "
            "OpenAI-compatible endpoints without modifying secrets files.",
        ),
    ] = None,
    reasoning_effort: Annotated[
        Literal["disabled", "low", "medium", "high"],
        typer.Option(
            "--reasoning-effort",
            "-R",
            help="Reasoning effort for all models in this run",
        ),
    ] = DEFAULT_REASONING_EFFORT,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
    estimate_only: Annotated[bool, typer.Option("--estimate-only", help="Show cost estimate only")] = False,
    fresh: Annotated[
        bool,
        typer.Option("--fresh", help="Ignore and delete existing results; start fresh"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-V",
            help="Print full model output, reasoning, and thinking after each run",
        ),
    ] = False,
) -> None:
    """Execute benchmark across models and fixtures in parallel.

    Automatically resumes from a previous run if the output file exists.
    Use --fresh to delete existing results and start over.
    Results are saved incrementally after each run completes.
    """
    selected_models = models or []
    selected_fixtures = fixtures or list(DEFAULT_FIXTURES)
    output_path = output
    api_keys = (
        load_api_keys()
        if _requires_secret_registry(selected_models, llm_settings, chain, base_url=base_url, api_key=api_key)
        else ApiKeyRegistry()
    )
    treatment_models, resolved_provider = _resolve_treatments(
        selected_models,
        llm_settings,
        chain,
        reasoning_effort=reasoning_effort,
        base_url=base_url,
        ollama_base_url=ollama_base_url,
        api_key=api_key,
        api_keys=api_keys,
    )
    if not api_key:
        for model in treatment_models:
            if (
                _provider_needs_registry_key(model.model, model.base_url)
                and model.api_key is None
                and model.provider_name not in api_keys
            ):
                msg = (
                    f"Treatment {model.model!r} needs an API key for provider {model.provider_name!r}; "
                    "add it to the secret registry or pass --api-key."
                )
                raise typer.BadParameter(msg, param_hint="--api-key")
    selected_model_names = [model.model for model in treatment_models]
    try:
        pricing_snapshots = tuple(resolve_pricing_snapshot(model) for model in treatment_models)
    except PricingRouteError as exc:
        raise typer.BadParameter(str(exc), param_hint="--llm-settings") from exc
    current_checksums = {fid: compute_fixture_checksum(fid) for fid in selected_fixtures}

    console.print(Panel.fit("[bold]LLM Model Benchmark[/bold]", subtitle="Nohiki"))

    raw_existing = _load_raw_result(output_path, fresh=fresh)
    total = len(selected_model_names) * len(selected_fixtures) * runs

    total_cost = display_cost_estimate(treatment_models, len(selected_fixtures), runs, snapshots=pricing_snapshots)

    if estimate_only:
        return

    provider_temperature = getattr(resolved_provider, "temperature", 0.0)
    provider_max_tokens = getattr(resolved_provider, "max_tokens", max_tokens)
    provider_retries = getattr(resolved_provider, "max_tool_retries", max_retries)
    provider_timeout = getattr(resolved_provider, "timeout_seconds", 120.0)
    config = BenchmarkConfig(
        models=treatment_models,
        fixture_ids=selected_fixtures,
        runs_per_fixture=runs,
        api_keys=api_keys,
        timeout_seconds=provider_timeout,
        temperature=provider_temperature,
        max_concurrency=concurrency,
        reasoning_effort=reasoning_effort,
        ollama_base_url=ollama_base_url or DEFAULT_OLLAMA_BASE_URL,
        ollama_timeout_seconds=(provider_timeout if resolved_provider is not None else ollama_timeout)
        or DEFAULT_OLLAMA_TIMEOUT_SECONDS,
        base_url=base_url,
        api_key=api_key,
        max_tokens=provider_max_tokens,
        max_retries=provider_retries,
        verbose=verbose,
        cost_cap_usd=cost_cap,
        unknown_price_max_usd=unknown_price_max,
        pricing_snapshots=pricing_snapshots,
    )
    expected_fingerprint = experiment_fingerprint(
        config, snapshots=pricing_snapshots, fixture_checksums=current_checksums
    )[0]
    full_existing = raw_existing
    scoped_existing = raw_existing
    if raw_existing is not None:
        # A pure fixture-content change (stale gold/prompt for some fixtures) must
        # resume and rerun only those cells, not reject. Recompute the identity the
        # stored result would carry if its stale fixtures still held their recorded
        # content: when that (or the current identity) matches, only fixture content
        # drifted and the stale filter handles it. Any treatment, fixture-set, or
        # run-count drift changes both identities and is rejected.
        compat_checksums = {
            fid: raw_existing.fixture_checksums.get(fid, current_checksums[fid]) for fid in selected_fixtures
        }
        compat_fingerprint = experiment_fingerprint(
            config, snapshots=pricing_snapshots, fixture_checksums=compat_checksums
        )[0]
        if raw_existing.experiment_fingerprint not in {
            expected_fingerprint,
            compat_fingerprint,
        }:
            msg = "Output belongs to an incompatible experiment; choose a fresh --output or pass --fresh"
            raise typer.BadParameter(msg, param_hint="--output")
        # Re-stamp the full history to the current fingerprint so completed_run_keys()
        # and merge() stay consistent, then strip stale selected-fixture runs. The
        # stripped result is used as BOTH the resume skip base AND the incremental
        # merge base: if the merge base still carried un-rerun stale cells, an
        # interrupted resume would persist them behind the current checksum and
        # fingerprint, and the next resume would skip them forever. Only unrelated
        # and non-stale history is preserved; stale cells are absent until rerun.
        restamped = raw_existing.model_copy(update={"experiment_fingerprint": expected_fingerprint})
        scoped_existing = _apply_stale_fixture_filter(restamped, selected_fixtures, current_checksums)
        full_existing = scoped_existing
    _show_resume_info(scoped_existing, total)
    if not _confirm_proceed(yes=yes, scoped_existing=scoped_existing, total=total, total_cost=total_cost):
        return

    session_result = asyncio.run(
        _run_benchmark_async(
            config,
            output_path,
            existing_result=scoped_existing,
            full_existing_result=full_existing,
            current_checksums=current_checksums,
        )
    )
    final_result = session_result
    final_result.save(output_path)
    snapshot_path = save_timestamped_snapshot(final_result, output_path)
    display_benchmark_results(session_result)
    console.print(f"\n[green]Results saved to:[/green] {output_path}")
    console.print(f"[dim]Snapshot: {snapshot_path}[/dim]")
