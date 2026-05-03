"""Pointwise LLM-as-judge evaluation engine.

Implements a PydanticAI-powered judge agent that scores each model's extraction
output independently against the original job listing across 8 quality
categories. Uses YAML pre-formatting for token efficiency and Anthropic prompt
caching for the static rubric.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml
from job_ingest_enrichment_service.extraction_contract import DEFAULT_EXTRACTION_SPEC
from nohiki_llm_client import (
    ApiKeyRegistry,
    CachePoint,
    LLMContextTooLongError,
    LLMModelConfig,
    LLMProviderResponseError,
    LLMProviderSettings,
    LLMSettings,
    LLMTransientError,
    LLMValidationError,
    ReasoningEffort,
    StructuredAgentConfig,
)
from nohiki_llm_client.config.constants import MAX_RETRY_ATTEMPTS
from nohiki_observability import get_logger
from pydantic import SecretStr

from llm_benchmark.config.constants import (
    JUDGE_APP_TITLE,
    JUDGE_MAX_RETRIES,
    JUDGE_MAX_TOKENS,
    JUDGE_TEMPERATURE,
    JUDGE_TIMEOUT_SECONDS,
    YAML_DUMP_WIDTH,
)
from llm_benchmark.config.models import EvaluationResumeState, JudgeConfig, model_family
from llm_benchmark.engine.budget import BudgetExhaustedError, BudgetScheduler
from llm_benchmark.fixtures import get_fixture
from llm_benchmark.schemas.aggregation import (
    EvaluationResult,
    JudgmentUnit,
    MultiJudgeEvaluationSummary,
    compute_multi_judge_summary,
)
from llm_benchmark.schemas.judge import PointwiseJudgment
from llm_benchmark.schemas.metrics import BenchmarkResult

if TYPE_CHECKING:
    from nohiki_llm_client import LLMClient, LLMResult
    from pydantic_ai import Agent

    from llm_benchmark.pricing import PricingSnapshot

logger = get_logger(__name__)

type EvalProgressCallback = Callable[[str, int, int, float], None]
type MultiJudgeProgressCallback = Callable[[str, str, int, int, float], None]
type OnTaskComplete = Callable[[str, str, int, PointwiseJudgment | None, float | None, float], None]
type AttemptPersistCallback = Callable[[str, str, int, PointwiseJudgment | None, float | None, float], None]
type MultiJudgeAttemptCallback = Callable[
    [str, str, str, str, int, PointwiseJudgment | None, float | None, float], None
]

JUDGE_SYSTEM_PROMPT = """\
You are evaluating only the residual, subjective quality of one structured job extraction.
The treatment identity is intentionally blinded. Do not guess the model or provider.

Deterministic gold evaluation separately covers exact field correctness, schema validity,
grounded critical failures, and other objectively verifiable properties. Do not rescore
those properties and do not disqualify an extraction.

Score these three residual dimensions from 0 to 100:

1. Inference Reasonableness: Are genuinely ambiguous or inferred values sensible and
appropriately cautious given the source posting?
2. Description Quality: Is the cleaned description readable, well structured, and useful
without needless boilerplate, while preserving the source's meaning?
3. Downstream Usefulness: Where multiple valid representations are possible, is the
chosen representation coherent and practically useful for job matching?

Give concise, source-grounded reasoning for every score. Judge only the supplied output;
never compare it with another treatment. Perfect scores should be rare."""

SCHEMA_DESCRIPTION = (
    "## JobExtractionSchema JSON Schema\n\n```json\n"
    f"{json.dumps(DEFAULT_EXTRACTION_SPEC.output_type.model_json_schema(), sort_keys=True, separators=(',', ':'))}\n"
    "```"
)

SCORE_CALIBRATION = """\
## Score Calibration Guide
- **90-100**: Exceptional subjective handling; no meaningful residual weakness.
- **75-89**: Good; minor presentation or judgment issues.
- **60-74**: Acceptable but noticeably less coherent or useful.
- **40-59**: Poor subjective handling that harms interpretation.
- **0-39**: Fundamentally unusable on a residual dimension."""

_FULL_SYSTEM_PROMPT: str = f"{JUDGE_SYSTEM_PROMPT}\n\n---\n\n{SCHEMA_DESCRIPTION}\n\n---\n\n{SCORE_CALIBRATION}"


@dataclass(frozen=True, slots=True)
class _PointwiseTask:
    """Single evaluation task: one model's output for one fixture+run.

    Attributes:
        model_name: Real model identifier.
        fixture_id: Test fixture identifier.
        run_number: 1-indexed run number.
        yaml_output: Pre-formatted YAML extraction output.
        static_context: Fixture-specific prompt + schema description.
    """

    model_name: str
    fixture_id: str
    run_number: int
    yaml_output: str
    static_context: str

    @property
    def task_key(self) -> str:
        """Composite key uniquely identifying this evaluation task."""
        return f"{self.model_name}::{self.fixture_id}::{self.run_number}"


def _format_output_as_yaml(output_json: dict[str, object]) -> str:
    """Convert extraction output JSON to compact YAML for token efficiency.

    Args:
        output_json: Raw extraction output dict.

    Returns:
        YAML-formatted string representation.
    """
    return yaml.dump(
        output_json,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=YAML_DUMP_WIDTH,
    )


def _build_fixture_context(fixture_id: str) -> str:
    """Build the fixture-specific context string (original extraction prompt).

    This string is identical for all models evaluated against the same fixture.
    The schema description and scoring rubric live in the system prompt (cached
    automatically by Anthropic), so only the fixture-varying original prompt is
    placed here in the user message.

    Args:
        fixture_id: Test fixture identifier.

    Returns:
        Formatted original extraction prompt section.
    """
    listing = get_fixture(fixture_id)
    original_prompt = DEFAULT_EXTRACTION_SPEC.build_prompt(listing)
    return f"## Original Extraction Prompt\n\n{original_prompt}"


def _gather_pointwise_tasks(
    benchmark: BenchmarkResult,
    skip_task_keys: frozenset[str] = frozenset(),
) -> list[_PointwiseTask]:
    """Build the list of pointwise evaluation tasks from benchmark results.

    Creates one task per successful model output per fixture per run. Pre-computes
    fixture context strings (shared across models) and YAML-formatted outputs.
    Tasks whose composite key appears in ``skip_task_keys`` are omitted,
    enabling checkpoint-based resume.

    Args:
        benchmark: Benchmark result containing extraction outputs.
        skip_task_keys: Task keys to skip (already completed in a prior run).

    Returns:
        List of pointwise tasks ready for concurrent evaluation.
    """
    fixture_contexts: dict[str, str] = {fid: _build_fixture_context(fid) for fid in benchmark.fixtures_used}

    tasks: list[_PointwiseTask] = []
    for model_name, model_result in benchmark.models.items():
        for run in model_result.runs:
            if not run.success or run.output_json is None:
                continue
            if run.fixture_id not in fixture_contexts:
                continue
            task_key = f"{model_name}::{run.fixture_id}::{run.run_number}"
            if task_key in skip_task_keys:
                continue

            tasks.append(
                _PointwiseTask(
                    model_name=model_name,
                    fixture_id=run.fixture_id,
                    run_number=run.run_number,
                    yaml_output=_format_output_as_yaml(run.output_json),
                    static_context=fixture_contexts[run.fixture_id],
                )
            )

    tasks.sort(key=lambda t: t.fixture_id)
    return tasks


def _select_independent_tasks(
    tasks: list[_PointwiseTask],
    judge_model: str,
) -> list[_PointwiseTask]:
    """Exclude treatments from the judge model family, preserving task order."""
    judge_family = model_family(judge_model)
    independent_tasks = [task for task in tasks if model_family(task.model_name) != judge_family]
    excluded = sorted({task.model_name for task in tasks if model_family(task.model_name) == judge_family})
    if excluded:
        logger.warning(
            "Excluded same-family judge/treatment combinations",
            judge=judge_model,
            family=judge_family,
            treatments=excluded,
        )
    return independent_tasks


def _build_pointwise_prompt(task: _PointwiseTask) -> list[str | CachePoint]:
    """Build the user prompt for a single pointwise evaluation.

    Returns a list with a ``CachePoint`` marker separating fixture context
    (cacheable across models) from per-model output (variable).  The
    ``LLMClient`` automatically strips ``CachePoint`` markers for models
    that do not support them, so callers need not handle provider differences.

    Args:
        task: Pointwise evaluation task with pre-formatted data.

    Returns:
        Prompt list with ``CachePoint`` for provider-side caching.
    """
    variable = (
        "---\n\n"
        "## Extraction Output to Evaluate\n\n"
        f"```yaml\n{task.yaml_output}```\n\n"
        "---\n\n"
        "Score only the three residual dimensions. Be thorough and specific."
    )
    return [task.static_context, CachePoint(), variable]


async def _execute_pointwise_task(
    client: LLMClient,
    agent: Agent[None, PointwiseJudgment],
    task: _PointwiseTask,
    semaphore: asyncio.Semaphore,
    on_complete: OnTaskComplete,
    cancel_event: asyncio.Event | None = None,
    budget_scheduler: BudgetScheduler | None = None,
    pricing_snapshot: PricingSnapshot | None = None,
    unknown_price_max_usd: float | None = None,
    max_retries: int = JUDGE_MAX_RETRIES,
) -> tuple[str, str, int, PointwiseJudgment | None]:
    """Execute a single pointwise judge evaluation under a concurrency semaphore.

    Calls ``on_complete`` immediately when the evaluation finishes (success or
    dispatched failure), enabling real-time progress reporting and durable
    attempt accounting from within the TaskGroup. If ``cancel_event`` is set
    (e.g. cost cap exceeded) or the pre-dispatch budget rejects the call, the
    task exits immediately without firing ``on_complete`` so budget-rejected
    non-dispatches are never persisted.

    Pricing is route-aware: the reservation and recorded cost both come from the
    treatment's immutable ``pricing_snapshot`` (local -> zero, routed OpenRouter
    -> conservative endpoint rate). A dispatched failure charges the worst-case
    reservation fail-closed; a success charges its recorded cost (or the
    reservation when the price is unknown), mirroring generation semantics.

    Args:
        client: Shared LLM client for this judge model.
        agent: Shared PydanticAI agent for structured judgment output.
        task: Pointwise evaluation task.
        semaphore: Concurrency semaphore for throttling.
        on_complete: Callback fired after each attempt with ``(model_name,
            fixture_id, run_number, judgment_or_none, actual_cost_or_none,
            charged_cost)``.
        cancel_event: Shared event signalling graceful cancellation.
        budget_scheduler: Shared pre-dispatch budget scheduler.
        pricing_snapshot: Immutable route-aware pricing evidence for this judge.
        unknown_price_max_usd: Explicit call maximum when pricing is unavailable.
        max_retries: Structured-output validation retries for worst-case sizing.

    Returns:
        Tuple of (model_name, fixture_id, run_number, judgment or None on failure/cancel).
    """
    _cancelled = (task.model_name, task.fixture_id, task.run_number, None)
    if cancel_event and cancel_event.is_set():
        return _cancelled

    judgment: PointwiseJudgment | None = None
    actual_cost: float | None = None
    charged_cost = 0.0
    async with semaphore:
        if cancel_event and cancel_event.is_set():
            return _cancelled

        prompt = _build_pointwise_prompt(task)
        maximum_cost = 0.0
        if budget_scheduler is not None and pricing_snapshot is not None:
            maximum_cost = pricing_snapshot.maximum_call_cost(
                max_input_tokens=sum(len(str(part).encode("utf-8")) for part in prompt)
                * (max_retries + 1)
                * MAX_RETRY_ATTEMPTS,
                max_output_tokens=JUDGE_MAX_TOKENS * (max_retries + 1) * MAX_RETRY_ATTEMPTS,
                unknown_price_max_usd=unknown_price_max_usd,
            )

        async def _dispatch() -> tuple[LLMResult[Any], float | None]:
            call_result = await client.run(agent, prompt, deps=None)
            return call_result, call_result.cost_usd

        try:
            if budget_scheduler is not None and pricing_snapshot is not None:
                result = await budget_scheduler.run(maximum_cost, _dispatch)
            else:
                result = await client.run(agent, prompt, deps=None)
        except BudgetExhaustedError:
            if cancel_event:
                cancel_event.set()
            return _cancelled
        except (
            LLMProviderResponseError,
            LLMValidationError,
            LLMContextTooLongError,
        ) as e:
            logger.warning(
                "Pointwise judge evaluation failed (non-retryable)",
                model=task.model_name,
                fixture_id=task.fixture_id,
                run_number=task.run_number,
                error_type=type(e).__name__,
                error=str(e),
            )
            charged_cost = maximum_cost
        except LLMTransientError as e:
            logger.warning(
                "Pointwise judge evaluation failed (retries exhausted)",
                model=task.model_name,
                fixture_id=task.fixture_id,
                run_number=task.run_number,
                error_type=type(e).__name__,
                error=str(e),
            )
            charged_cost = maximum_cost
        else:
            judgment = result.output
            actual_cost = (
                pricing_snapshot.recorded_cost(
                    client_cost=result.cost_usd,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                )
                if pricing_snapshot is not None
                else result.cost_usd
            )
            charged_cost = actual_cost if actual_cost is not None else maximum_cost

    on_complete(
        task.model_name,
        task.fixture_id,
        task.run_number,
        judgment,
        actual_cost,
        charged_cost,
    )
    return (task.model_name, task.fixture_id, task.run_number, judgment)


async def _close_client(client: LLMClient) -> None:
    """Close a real client while tolerating synchronous benchmark test doubles."""
    close_result = client.close()
    if inspect.isawaitable(close_result):
        await close_result


def _create_judge_client(
    judge_model: str,
    api_keys: ApiKeyRegistry,
    reasoning_effort: ReasoningEffort,
    provider_order: tuple[str, ...] = (),
    *,
    provider_allow_fallbacks: bool = True,
    provider_zdr: bool = False,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> LLMClient:
    """Create an LLM client configured for judge evaluation.

    Args:
        judge_model: Fully qualified judge model string.
        api_keys: Provider API key registry.
        reasoning_effort: Reasoning token effort level.
        provider_order: OpenRouter provider routing preference.
        provider_allow_fallbacks: Whether OpenRouter may route outside
            ``provider_order``; carried through so routing never silently widens.
        provider_zdr: Require OpenRouter Zero Data Retention routing.
        base_url: Optional custom API endpoint override.
        api_key: Optional per-model API key override.
        timeout_seconds: Per-request timeout. ``None`` uses ``JUDGE_TIMEOUT_SECONDS``.
        max_retries: Structured-output validation retries. ``None`` uses ``JUDGE_MAX_RETRIES``.

    Returns:
        Configured LLM client for judge evaluation.
    """
    from nohiki_llm_client import LLMClient as _LLMClient

    settings = LLMSettings(
        provider=LLMProviderSettings(
            models=[
                LLMModelConfig(
                    model=judge_model,
                    reasoning_effort=reasoning_effort,
                    app_title=JUDGE_APP_TITLE,
                    provider_order=provider_order,
                    provider_allow_fallbacks=provider_allow_fallbacks,
                    provider_zdr=provider_zdr,
                    base_url=base_url,
                    api_key=SecretStr(api_key) if api_key else None,
                )
            ],
            api_keys=api_keys,
            temperature=JUDGE_TEMPERATURE,
            timeout_seconds=timeout_seconds if timeout_seconds is not None else JUDGE_TIMEOUT_SECONDS,
            max_tool_retries=max_retries if max_retries is not None else JUDGE_MAX_RETRIES,
            max_tokens=JUDGE_MAX_TOKENS,
        ),
    )
    return _LLMClient(settings)


async def evaluate_benchmark(
    benchmark: BenchmarkResult,
    api_keys: ApiKeyRegistry,
    *,
    judge_model: str,
    reasoning_effort: ReasoningEffort = "high",
    max_concurrency: int | None = None,
    progress_callback: EvalProgressCallback | None = None,
    on_attempt: AttemptPersistCallback | None = None,
    resume_state: EvaluationResumeState | None = None,
    cancel_event: asyncio.Event | None = None,
    provider_order: tuple[str, ...] = (),
    provider_allow_fallbacks: bool = True,
    provider_zdr: bool = False,
    base_url: str | None = None,
    api_key: str | None = None,
    budget_scheduler: BudgetScheduler | None = None,
    pricing_snapshot: PricingSnapshot | None = None,
    unknown_price_max_usd: float | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> EvaluationResult:
    """Run pointwise LLM-as-judge evaluation on stored benchmark results.

    Each treatment's extraction output is scored independently across three
    residual subjective dimensions, without exposing treatment identity.
    ``CachePoint`` markers are included in every prompt; the ``LLMClient``
    automatically strips them for non-Anthropic models.

    Progress updates fire in real-time as each evaluation completes, not
    after all tasks finish. Supports checkpoint-based resume via
    ``resume_state`` and graceful cancellation via ``cancel_event``.

    Args:
        benchmark: Benchmark result containing extraction outputs.
        api_keys: Provider API key registry for cloud provider authentication.
        judge_model: Fully qualified model string (e.g., ``openrouter:openai/gpt-5.2``).
        reasoning_effort: Reasoning token effort level.
        max_concurrency: Max simultaneous judge calls. ``None`` uses the
            provider-appropriate default from ``JudgeConfig.effective_concurrency``.
        progress_callback: Optional ``callback(fixture_id, completed, total,
            cost_usd)`` called after each evaluation completes, where
            ``cost_usd`` is the cost of the individual call (not accumulated).
        on_attempt: Optional callback fired for every completed attempt
            (success or dispatched failure), with ``(model_name, fixture_id,
            run_number, judgment_or_none, actual_cost_or_none, charged_cost)``.
            Failures are persisted so resume skips them and their fail-closed
            charge is not lost.
        resume_state: Pre-populated state from a prior checkpoint for resume.
        cancel_event: Shared event signalling graceful cancellation
            (cost cap exceeded or timeout reached).
        provider_order: OpenRouter provider routing preference.
        provider_allow_fallbacks: Whether OpenRouter may route outside
            ``provider_order``; carried through to dispatch and pricing.
        provider_zdr: Require OpenRouter Zero Data Retention routing.
        base_url: Optional custom API endpoint override.
        api_key: Optional per-model API key override.
        budget_scheduler: Shared pre-dispatch budget and concurrency scheduler.
        pricing_snapshot: Immutable route-aware pricing evidence for this judge.
        unknown_price_max_usd: Explicit per-call maximum for unknown pricing.
        timeout_seconds: Per-request timeout for this judge. ``None`` uses the default.
        max_retries: Structured-output validation retries. ``None`` uses the default.

    Returns:
        ``EvaluationResult`` containing per-model pointwise judgments.
    """
    from llm_benchmark.config.constants import DEFAULT_EVAL_CONCURRENCY

    state = resume_state or EvaluationResumeState()
    effective_concurrency = max_concurrency if max_concurrency is not None else DEFAULT_EVAL_CONCURRENCY

    client = _create_judge_client(
        judge_model,
        api_keys,
        reasoning_effort,
        provider_order,
        provider_allow_fallbacks=provider_allow_fallbacks,
        provider_zdr=provider_zdr,
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    try:
        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=type(None),
                output_type=PointwiseJudgment,
                system_prompt=_FULL_SYSTEM_PROMPT,
            )
        )
    except BaseException:
        await _close_client(client)
        raise

    tasks = _select_independent_tasks(
        _gather_pointwise_tasks(benchmark, skip_task_keys=state.skip_task_keys),
        judge_model,
    )
    remaining_evals = len(tasks)
    total_evals = remaining_evals + state.existing_completed_count

    if total_evals == 0:
        logger.warning("No independent successful extraction outputs found for evaluation")
        await _close_client(client)
        return EvaluationResult(judgments_by_model={}, expected_units=0)

    if state.existing_completed_count > 0:
        logger.info(
            "Resuming pointwise evaluation",
            remaining=remaining_evals,
            already_completed=state.existing_completed_count,
            total=total_evals,
            judge_model=judge_model,
        )
    else:
        logger.info(
            "Starting pointwise evaluation",
            total_evaluations=total_evals,
            judge_model=judge_model,
            models=list(benchmark.models.keys()),
        )

    if remaining_evals == 0:
        logger.info("All tasks already completed from checkpoint")
        await _close_client(client)
        return EvaluationResult(
            judgments_by_model=dict(state.existing_judgments),
            units=state.existing_units,
            expected_units=total_evals,
            failed_units=sum(unit.judgment is None for unit in state.existing_units),
            total_cost_usd=state.existing_cost_usd,
        )

    semaphore = asyncio.Semaphore(effective_concurrency)
    results: dict[str, list[PointwiseJudgment]] = {k: list(v) for k, v in state.existing_judgments.items()}
    completed_count = state.existing_completed_count
    accumulated_cost = state.existing_cost_usd
    units: list[JudgmentUnit] = list(state.existing_units)
    failed_units = sum(unit.judgment is None for unit in state.existing_units)

    def _on_task_complete(
        model_name: str,
        fixture_id: str,
        run_number: int,
        judgment: PointwiseJudgment | None,
        actual_cost_usd: float | None,
        charged_cost_usd: float,
    ) -> None:
        nonlocal completed_count, accumulated_cost, failed_units
        completed_count += 1
        call_cost = actual_cost_usd or 0.0
        accumulated_cost += call_cost
        units.append(
            JudgmentUnit(
                fixture_id=fixture_id,
                treatment=model_name,
                run_number=run_number,
                judge=judge_model,
                judgment=judgment,
            )
        )
        if judgment is None:
            failed_units += 1
        else:
            results.setdefault(model_name, []).append(judgment)
        # Persist every attempt (success and dispatched failure) so resume
        # skips it and its charged cost seeds the resumed budget.
        if on_attempt:
            on_attempt(
                model_name,
                fixture_id,
                run_number,
                judgment,
                actual_cost_usd,
                charged_cost_usd,
            )
        if progress_callback:
            progress_callback(fixture_id, completed_count, total_evals, call_cost)

    try:
        async with asyncio.TaskGroup() as tg:
            for ptask in tasks:
                tg.create_task(
                    _execute_pointwise_task(
                        client,
                        agent,
                        ptask,
                        semaphore,
                        _on_task_complete,
                        cancel_event,
                        budget_scheduler,
                        pricing_snapshot,
                        unknown_price_max_usd,
                        max_retries if max_retries is not None else JUDGE_MAX_RETRIES,
                    ),
                )

        return EvaluationResult(
            judgments_by_model=results,
            units=tuple(units),
            expected_units=total_evals,
            failed_units=failed_units,
            total_cost_usd=accumulated_cost,
        )
    finally:
        await _close_client(client)


async def evaluate_multi_judge(
    benchmark: BenchmarkResult,
    api_keys: ApiKeyRegistry,
    judges: list[JudgeConfig],
    *,
    progress_callback: MultiJudgeProgressCallback | None = None,
    on_attempt: MultiJudgeAttemptCallback | None = None,
    resume_states: dict[str, EvaluationResumeState] | None = None,
    cancel_event: asyncio.Event | None = None,
    budget_scheduler: BudgetScheduler | None = None,
    pricing_snapshots: dict[str, PricingSnapshot] | None = None,
    unknown_price_max_usd: float | None = None,
) -> MultiJudgeEvaluationSummary:
    """Run judge models in parallel and return a consolidated summary.

    Each judge independently evaluates the full benchmark using
    ``evaluate_benchmark()``. All judges run concurrently. Per-judge
    concurrency is controlled by ``JudgeConfig.effective_concurrency``,
    which auto-detects appropriate limits for local vs cloud providers.

    Args:
        benchmark: Benchmark result containing extraction outputs.
        api_keys: Provider API key registry for cloud provider authentication.
        judges: List of judge configurations.
        progress_callback: Optional ``callback(judge_model, fixture_id, completed,
            total, cost_usd)`` where ``cost_usd`` is the per-call cost.
        on_attempt: Optional callback fired for every completed attempt
            (success or dispatched failure), with ``(judge_model,
            reasoning_effort, model_name, fixture_id, run_number,
            judgment_or_none, actual_cost_or_none, charged_cost)``.
        resume_states: Per-judge resume states from a prior checkpoint.
        cancel_event: Shared event signalling graceful cancellation
            (cost cap exceeded or timeout reached).
        budget_scheduler: Shared pre-dispatch budget and concurrency scheduler.
        pricing_snapshots: Per-judge immutable route-aware pricing evidence,
            keyed by ``judge.model``.
        unknown_price_max_usd: Explicit per-call maximum for unknown judge pricing.

    Returns:
        ``MultiJudgeEvaluationSummary`` with per-judge and consensus results.
    """
    if len(judges) == 1:
        logger.info("Starting judge evaluation", judge=judges[0].model)
    else:
        logger.info(
            "Starting multi-judge evaluation",
            judge_count=len(judges),
            judges=[j.model for j in judges],
        )

    judge_results: dict[str, EvaluationResult] = {}

    async def _run_single_judge(judge: JudgeConfig) -> None:
        def _wrapped_callback(
            fixture_id: str,
            completed: int,
            total: int,
            cost_usd: float,
        ) -> None:
            if progress_callback:
                progress_callback(judge.model, fixture_id, completed, total, cost_usd)

        def _wrapped_attempt(
            model_name: str,
            fixture_id: str,
            run_number: int,
            judgment: PointwiseJudgment | None,
            actual_cost_usd: float | None,
            charged_cost_usd: float,
        ) -> None:
            if on_attempt:
                on_attempt(
                    judge.model,
                    judge.reasoning_effort,
                    model_name,
                    fixture_id,
                    run_number,
                    judgment,
                    actual_cost_usd,
                    charged_cost_usd,
                )

        state = (resume_states or {}).get(judge.model)
        snapshot = (pricing_snapshots or {}).get(judge.model)

        judge_results[judge.model] = await evaluate_benchmark(
            benchmark,
            api_keys,
            judge_model=judge.model,
            reasoning_effort=judge.reasoning_effort,
            max_concurrency=judge.effective_concurrency,
            progress_callback=_wrapped_callback,
            on_attempt=_wrapped_attempt,
            resume_state=state,
            cancel_event=cancel_event,
            provider_order=judge.provider_order,
            provider_allow_fallbacks=judge.provider_allow_fallbacks,
            provider_zdr=judge.provider_zdr,
            base_url=judge.base_url,
            api_key=judge.api_key,
            budget_scheduler=budget_scheduler,
            pricing_snapshot=snapshot,
            unknown_price_max_usd=unknown_price_max_usd,
            timeout_seconds=judge.effective_timeout_seconds,
            max_retries=judge.effective_max_retries,
        )

    async with asyncio.TaskGroup() as tg:
        for judge in judges:
            tg.create_task(_run_single_judge(judge))

    return compute_multi_judge_summary(
        judge_results,
        {judge.model: judge.weight for judge in judges},
    )
