"""Parallel benchmark runner for comparing LLM models on extraction tasks.

Executes all models and runs concurrently using ``asyncio.TaskGroup``.
Per-model concurrency is delegated to ``nohiki-llm-client`` via
``ConcurrencyLimitedModel`` -- the runner spawns all tasks freely and
the model wrappers handle rate limiting transparently.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit, urlunsplit

from job_ingest_enrichment_service.extraction_contract import (
    DEFAULT_EXTRACTION_SPEC,
    ExtractionContext,
)
from nohiki.job.ingest.v1 import DiscoveredListing
from nohiki_llm_client import (
    LLMError,
    LLMModelConfig,
    LLMProviderSettings,
    LLMSettings,
    LLMValidationError,
    OllamaSettings,
    StructuredAgentConfig,
)
from nohiki_llm_client.config.constants import MAX_RETRY_ATTEMPTS
from nohiki_observability import get_logger
from pydantic import SecretStr

from llm_benchmark.config.constants import (
    BENCHMARK_POLICY_VERSION,
    BENCHMARK_SOURCE_VERSION,
)
from llm_benchmark.display.console import console
from llm_benchmark.engine.budget import BudgetExhaustedError, BudgetScheduler
from llm_benchmark.fixtures import compute_fixture_checksum, get_fixture, get_gold_case
from llm_benchmark.pricing import resolve_pricing_snapshot
from llm_benchmark.schemas.gold import score_extraction
from llm_benchmark.schemas.metrics import BenchmarkResult, ModelResult, RunResult

if TYPE_CHECKING:
    from typing import Any

    from nohiki_llm_client import LLMClient, LLMResult
    from pydantic import BaseModel
    from pydantic_ai import Agent

    from llm_benchmark.config.models import BenchmarkConfig
    from llm_benchmark.pricing import PricingSnapshot

logger = get_logger(__name__)


class RunProgressCallback(Protocol):
    """Type-safe callback protocol for benchmark run progress reporting."""

    def __call__(self, model: str, fixture_id: str, run_number: int, *, run_result: RunResult) -> None:
        """Report progress after a single benchmark run completes."""
        ...


def _create_client(settings: LLMSettings) -> LLMClient:
    """Create an LLM client from settings.

    Args:
        settings: LLM configuration settings.

    Returns:
        Configured LLM client instance.
    """
    from nohiki_llm_client import LLMClient as _LLMClient

    return _LLMClient(settings)


async def _close_client(client: LLMClient) -> None:
    """Close a real client while tolerating synchronous benchmark test doubles."""
    close_result = client.close()
    if inspect.isawaitable(close_result):
        await close_result


def _fingerprint(value: object) -> str:
    """Return a deterministic SHA-256 fingerprint for JSON-compatible data."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _base_url_identity(base_url: str | None) -> str | None:
    """Return endpoint identity without credentials, query values, or fragments."""
    if base_url is None:
        return None
    parsed = urlsplit(base_url)
    hostname = parsed.hostname or ""
    host = f"[{hostname}]" if ":" in hostname else hostname
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme.casefold(), host.casefold(), parsed.path.rstrip("/"), "", ""))


def _pricing_snapshots(
    config: BenchmarkConfig,
    snapshots: tuple[PricingSnapshot, ...] | None = None,
) -> tuple[PricingSnapshot, ...]:
    """Return per-treatment pricing snapshots, resolving once when not supplied.

    An explicit ``snapshots`` argument wins; otherwise pre-resolved
    ``config.pricing_snapshots`` are reused; otherwise each treatment is resolved
    now (one preflight network fetch per routed treatment).
    """
    if snapshots is not None:
        return snapshots
    if config.pricing_snapshots:
        return config.pricing_snapshots
    return tuple(resolve_pricing_snapshot(model) for model in config.models)


def _treatment_fingerprint(model: LLMModelConfig, config: BenchmarkConfig, snapshot: PricingSnapshot) -> str:
    """Fingerprint the exact non-secret model, provider, and pricing settings."""
    return _fingerprint(
        {
            "model": model.model,
            "reasoning_effort": model.reasoning_effort,
            "base_url": _base_url_identity(model.base_url),
            "provider_order": model.provider_order,
            "provider_allow_fallbacks": model.provider_allow_fallbacks,
            "provider_zdr": model.provider_zdr,
            "google_project": model.google_project,
            "google_location": model.google_location,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "max_retries": config.max_retries,
            "timeout_seconds": config.ollama_timeout_seconds
            if model.provider_name in {"llamacpp", "ollama"}
            else config.timeout_seconds,
            "cost_cap_usd": config.cost_cap_usd,
            "unknown_price_max_usd": config.unknown_price_max_usd,
            "pricing": snapshot.fingerprint_material(),
        }
    )


def experiment_fingerprint(
    config: BenchmarkConfig,
    *,
    snapshots: tuple[PricingSnapshot, ...] | None = None,
    fixture_checksums: dict[str, str] | None = None,
) -> tuple[str, tuple[str, ...]]:
    """Return immutable experiment identity and ordered treatment identities.

    Pricing snapshots are folded into every treatment identity so a resumed run
    whose route prices changed is rejected as an incompatible experiment.

    ``fixture_checksums`` lets a caller substitute explicit per-fixture content
    checksums instead of recomputing them from current fixture content. Resume
    logic uses this to ask "would this experiment's identity match if the stale
    fixtures still carried their previously-recorded content?" so a pure fixture
    content change is recognised as the same experiment (handled by the stale
    filter) while treatment, fixture-set, or run-count changes still reject.
    """
    resolved = _pricing_snapshots(config, snapshots)
    treatments = tuple(
        _treatment_fingerprint(model, config, snapshot) for model, snapshot in zip(config.models, resolved, strict=True)
    )
    checksums = (
        fixture_checksums
        if fixture_checksums is not None
        else {fixture_id: compute_fixture_checksum(fixture_id) for fixture_id in config.fixture_ids}
    )
    identity = _fingerprint(
        {
            "source_version": BENCHMARK_SOURCE_VERSION,
            "policy_version": BENCHMARK_POLICY_VERSION,
            "fixtures": checksums,
            "runs_per_fixture": config.runs_per_fixture,
            "treatments": treatments,
        }
    )
    return identity, treatments


def treatment_ids(
    config: BenchmarkConfig,
    *,
    snapshots: tuple[PricingSnapshot, ...] | None = None,
) -> tuple[str, ...]:
    """Return stable result keys for independently configured candidates."""
    _, fingerprints = experiment_fingerprint(config, snapshots=snapshots)
    return tuple(
        f"{model.model}@{fingerprint[:16]}" for model, fingerprint in zip(config.models, fingerprints, strict=True)
    )


class BenchmarkRunner:
    """Parallel benchmark runner across multiple models and fixtures.

    Uses ``asyncio.TaskGroup`` for structured concurrency. Per-model
    rate limiting is handled by ``nohiki-llm-client``'s
    ``ConcurrencyLimitedModel`` wrapper -- the runner spawns all tasks
    and the model layer throttles HTTP requests transparently.

    Attributes:
        config: Benchmark configuration.
    """

    def __init__(self, config: BenchmarkConfig) -> None:
        """Initialize benchmark runner.

        Args:
            config: Benchmark configuration.
        """
        self._config = config
        self._pricing_snapshots = _pricing_snapshots(config)
        self._experiment_fingerprint, self._treatment_fingerprints = experiment_fingerprint(
            config, snapshots=self._pricing_snapshots
        )

    def _print_verbose(
        self,
        *,
        model_name: str,
        fixture_id: str,
        run_number: int,
        result: LLMResult[Any],
        run_result: RunResult,
    ) -> None:
        """Print full run details to the console when verbose mode is enabled.

        Extracts ThinkingPart content from the message history so the caller
        can see exactly what the model reasoned through, and prints the full
        extracted JSON so validation failures are immediately visible.

        Args:
            model_name: Model identifier.
            fixture_id: Fixture identifier.
            run_number: 1-indexed run number.
            result: Raw LLM result with messages and usage.
            run_result: Serialized run result for token counts.
        """
        from pydantic_ai.messages import ModelResponse, ThinkingPart

        header = f"[bold cyan]{model_name}[/bold cyan] | [yellow]{fixture_id}[/yellow] | run {run_number}"
        console.rule(header)

        console.print(
            f"  Latency:   [green]{run_result.latency_ms:,.0f}ms[/green]"
            f"  Tokens: in=[white]{run_result.input_tokens:,}[/white]"
            f" out=[white]{run_result.output_tokens:,}[/white]"
            f" reasoning=[magenta]{run_result.reasoning_tokens:,}[/magenta]"
        )

        # Extract thinking content from the message history.
        thinking_parts = [
            part
            for msg in result.messages
            if isinstance(msg, ModelResponse)
            for part in msg.parts
            if isinstance(part, ThinkingPart)
        ]
        if thinking_parts:
            thinking_text = "\n---\n".join(p.content for p in thinking_parts)
            console.print(f"\n[bold magenta]Thinking ({len(thinking_text):,} chars):[/bold magenta]")
            console.print(f"[dim]{thinking_text[:2000]}[/dim]")
            if len(thinking_text) > 2000:
                console.print(f"[dim]  ... ({len(thinking_text) - 2000:,} more chars)[/dim]")
        else:
            console.print("[dim]  (no thinking content)[/dim]")

        if run_result.output_json is not None:
            console.print("\n[bold green]Output:[/bold green]")
            console.print(json.dumps(run_result.output_json, indent=2))

        console.rule()

    async def run(
        self,
        progress_callback: RunProgressCallback | None = None,
        *,
        existing_result: BenchmarkResult | None = None,
    ) -> BenchmarkResult:
        """Execute benchmark across all models and fixtures in parallel.

        All models run concurrently via ``ConcurrencyLimitedModel``. Each model's
        client and agent are created once and shared across all fixture+run
        tasks for that model. Results are collected immutably after all tasks
        complete, enabling safe use of ``cached_property`` in ``ModelResult``.

        When ``existing_result`` is provided, any already-attempted
        ``(model, fixture_id, run_number)`` triples are skipped, enabling
        incremental resume after a cancelled run.

        Args:
            progress_callback: Optional callback invoked after each run with the
                ``RunResult``, enabling live display and incremental persistence.
            existing_result: Previously saved partial result to resume from.
                Already-attempted runs are skipped; new runs are merged in.

        Returns:
            Complete benchmark result with extraction outputs.
        """
        fixture_map = {fid: get_fixture(fid) for fid in self._config.fixture_ids}
        completed_keys = (
            existing_result.completed_run_keys(self._experiment_fingerprint) if existing_result else frozenset()
        )
        initial_charged = existing_result.total_charged_cost if existing_result else 0.0
        initial_actual = existing_result.total_actual_cost if existing_result else 0.0
        scheduler = BudgetScheduler(
            cap_usd=self._config.cost_cap_usd,
            max_concurrency=self._config.max_concurrency,
            initial_charged_usd=initial_charged,
            initial_actual_usd=initial_actual,
        )
        if self._config.max_tokens is None and any(
            model.provider_name not in {"llamacpp", "ollama"} for model in self._config.models
        ):
            msg = "Paid benchmark treatments require a finite max_tokens reservation bound"
            raise ValueError(msg)
        retry_multiplier = (self._config.max_retries + 1) * MAX_RETRY_ATTEMPTS
        snapshots_by_treatment = dict(zip(self._treatment_fingerprints, self._pricing_snapshots, strict=True))
        maximum_costs = {
            (treatment_fingerprint, fixture_id): snapshot.maximum_call_cost(
                max_input_tokens=len(
                    (DEFAULT_EXTRACTION_SPEC.system_prompt + DEFAULT_EXTRACTION_SPEC.build_prompt(listing)).encode()
                )
                * retry_multiplier,
                max_output_tokens=(self._config.max_tokens or 0) * retry_multiplier,
                unknown_price_max_usd=self._config.unknown_price_max_usd,
            )
            for treatment_fingerprint, snapshot in snapshots_by_treatment.items()
            for fixture_id, listing in fixture_map.items()
        }

        task_list: list[asyncio.Task[tuple[str, RunResult | None]]] = []
        async with AsyncExitStack() as clients, asyncio.TaskGroup() as tg:
            for model_config, treatment_fingerprint, snapshot in zip(
                self._config.models,
                self._treatment_fingerprints,
                self._pricing_snapshots,
                strict=True,
            ):
                model_name = f"{model_config.model}@{treatment_fingerprint[:16]}"
                is_local = model_config.provider_name in {"llamacpp", "ollama"}
                effective_model = model_config.model_copy(
                    update={
                        "api_key": model_config.api_key
                        or (SecretStr(self._config.api_key) if self._config.api_key else None),
                        "base_url": model_config.base_url
                        or (self._config.ollama_base_url if model_config.provider_name == "ollama" else None),
                    }
                )
                settings = LLMSettings(
                    provider=LLMProviderSettings(
                        models=[effective_model],
                        api_keys=self._config.api_keys,
                        temperature=self._config.temperature,
                        max_tokens=self._config.max_tokens,
                        max_tool_retries=self._config.max_retries,
                        timeout_seconds=(
                            self._config.ollama_timeout_seconds if is_local else self._config.timeout_seconds
                        ),
                        concurrency_limit=1 if is_local else self._config.max_concurrency,
                        ollama=OllamaSettings(),
                    ),
                )
                client = _create_client(settings)
                clients.push_async_callback(_close_client, client)
                agent = client.create_agent(
                    StructuredAgentConfig(
                        deps_type=ExtractionContext,
                        output_type=DEFAULT_EXTRACTION_SPEC.output_type,
                        system_prompt=DEFAULT_EXTRACTION_SPEC.system_prompt,
                    )
                )
                task_list.extend(
                    tg.create_task(
                        self._execute_run(
                            client=client,
                            agent=agent,
                            listing=listing,
                            fixture_id=fixture_id,
                            run_number=run_num,
                            model_name=model_name,
                            treatment_fingerprint=treatment_fingerprint,
                            snapshot=snapshot,
                            progress_callback=progress_callback,
                            scheduler=scheduler,
                            maximum_cost_usd=maximum_costs[(treatment_fingerprint, fixture_id)],
                        )
                    )
                    for fixture_id, listing in fixture_map.items()
                    for run_num in range(1, self._config.runs_per_fixture + 1)
                    if (model_name, fixture_id, run_num) not in completed_keys
                )

        result_keys = tuple(
            f"{model.model}@{fingerprint[:16]}"
            for model, fingerprint in zip(self._config.models, self._treatment_fingerprints, strict=True)
        )
        new_runs_by_model: dict[str, list[RunResult]] = {m: [] for m in result_keys}
        for task in task_list:
            model_name, run_result = task.result()
            if run_result is not None:
                new_runs_by_model[model_name].append(run_result)

        model_results: dict[str, ModelResult] = {}
        for model_name, new_runs in new_runs_by_model.items():
            prior_runs = (
                list(existing_result.models[model_name].runs)
                if existing_result and model_name in existing_result.models
                else []
            )
            all_runs = prior_runs + new_runs
            total_cost = sum(r.actual_cost_usd or 0.0 for r in all_runs)
            model_results[model_name] = ModelResult(
                model=model_name,
                runs=all_runs,
                total_cost_usd=total_cost,
            )

        return BenchmarkResult(
            experiment_fingerprint=self._experiment_fingerprint,
            fixtures_used=self._config.fixture_ids,
            runs_per_fixture=self._config.runs_per_fixture,
            fixture_checksums={fid: compute_fixture_checksum(fid) for fid in self._config.fixture_ids},
            models=model_results,
        )

    async def _execute_run(
        self,
        *,
        client: LLMClient,
        agent: Agent[ExtractionContext, BaseModel],
        listing: DiscoveredListing,
        fixture_id: str,
        run_number: int,
        model_name: str,
        treatment_fingerprint: str,
        snapshot: PricingSnapshot,
        progress_callback: RunProgressCallback | None,
        scheduler: BudgetScheduler,
        maximum_cost_usd: float,
    ) -> tuple[str, RunResult | None]:
        """Execute a single extraction run.

        Concurrency is controlled by ``ConcurrencyLimitedModel`` at the
        model layer -- this method simply awaits the LLM call. Fires the
        progress callback in-task for live reporting.

        Args:
            client: Shared LLM client for this model.
            agent: Shared PydanticAI agent for extraction.
            treatment_fingerprint: Immutable identity for the candidate model settings.
            snapshot: Immutable pricing evidence resolved once for this treatment.
            listing: Raw listing to extract from.
            fixture_id: Fixture identifier.
            run_number: 1-indexed run number.
            model_name: Model identifier for progress reporting.
            progress_callback: Optional progress callback.
            scheduler: Global pre-dispatch budget and concurrency scheduler.
            maximum_cost_usd: Worst-case cost reserved for this call.

        Returns:
            Tuple of (model_name, run_result) for immutable collection.
        """
        cell_fingerprint = _fingerprint(
            {
                "experiment": self._experiment_fingerprint,
                "treatment": treatment_fingerprint,
                "fixture": fixture_id,
                "run_number": run_number,
            }
        )
        prompt = DEFAULT_EXTRACTION_SPEC.build_prompt(listing)
        ctx = DEFAULT_EXTRACTION_SPEC.build_context(listing)

        start_time = time.perf_counter()
        try:

            async def _dispatch() -> tuple[LLMResult[Any], float | None]:
                result = await client.run(agent, prompt, deps=ctx)
                return result, result.cost_usd

            result = await scheduler.run(maximum_cost_usd, _dispatch)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            if self._config.max_tokens is not None and result.usage.output_tokens >= self._config.max_tokens:
                truncation_result = RunResult(
                    fixture_id=fixture_id,
                    treatment_fingerprint=treatment_fingerprint,
                    cell_fingerprint=cell_fingerprint,
                    run_number=run_number,
                    success=False,
                    latency_ms=elapsed_ms,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    retry_count=result.retry_count,
                    actual_cost_usd=snapshot.recorded_cost(
                        client_cost=result.cost_usd,
                        input_tokens=result.usage.input_tokens,
                        output_tokens=result.usage.output_tokens,
                    ),
                    reserved_cost_usd=maximum_cost_usd,
                    maximum_possible_cost_usd=maximum_cost_usd,
                    error_message=(
                        f"Output truncated: {result.usage.output_tokens} tokens"
                        f" reached max_tokens={self._config.max_tokens}"
                    ),
                )
                if progress_callback:
                    progress_callback(model_name, fixture_id, run_number, run_result=truncation_result)
                return (model_name, truncation_result)
            output_json = result.output.model_dump(mode="json")
            gold_score = score_extraction(get_gold_case(fixture_id), output_json)
            run_result = RunResult(
                fixture_id=fixture_id,
                treatment_fingerprint=treatment_fingerprint,
                cell_fingerprint=cell_fingerprint,
                run_number=run_number,
                success=True,
                latency_ms=elapsed_ms,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cache_read_tokens=result.usage.cache_read_tokens,
                cache_write_tokens=result.usage.cache_write_tokens,
                reasoning_tokens=result.usage.details.get("reasoning_tokens", 0),
                api_requests=result.usage.requests,
                tool_calls_made=result.usage.tool_calls,
                retry_count=result.retry_count,
                usage_details=dict(result.usage.details),
                actual_cost_usd=snapshot.recorded_cost(
                    client_cost=result.cost_usd,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                ),
                reserved_cost_usd=maximum_cost_usd,
                maximum_possible_cost_usd=maximum_cost_usd,
                output_json=output_json,
                gold_score=gold_score,
            )
            if self._config.verbose:
                self._print_verbose(
                    model_name=model_name,
                    fixture_id=fixture_id,
                    run_number=run_number,
                    result=result,
                    run_result=run_result,
                )
        except (LLMError, RuntimeError, ValueError, TimeoutError) as e:
            if isinstance(e, BudgetExhaustedError):
                return (model_name, None)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "Run failed",
                model=model_name,
                fixture_id=fixture_id,
                run_number=run_number,
                error=str(e),
            )
            if isinstance(e, LLMValidationError) and e.__cause__ is not None:
                logger.warning(
                    "Validation error detail",
                    model=model_name,
                    fixture_id=fixture_id,
                    run_number=run_number,
                    cause=str(e.__cause__),
                )
            run_result = RunResult(
                fixture_id=fixture_id,
                treatment_fingerprint=treatment_fingerprint,
                cell_fingerprint=cell_fingerprint,
                run_number=run_number,
                success=False,
                latency_ms=elapsed_ms,
                retry_count=None,
                reserved_cost_usd=0.0 if isinstance(e, BudgetExhaustedError) else maximum_cost_usd,
                maximum_possible_cost_usd=maximum_cost_usd,
                error_message=str(e),
            )
            if self._config.verbose:
                fail_header = (
                    f"[bold red]FAILED[/bold red] [cyan]{model_name}[/cyan]"
                    f" | [yellow]{fixture_id}[/yellow] | run {run_number}"
                )
                console.rule(fail_header)
                console.print(f"[red]{e}[/red]")
                console.rule()

        if progress_callback:
            progress_callback(model_name, fixture_id, run_number, run_result=run_result)
        return (model_name, run_result)
