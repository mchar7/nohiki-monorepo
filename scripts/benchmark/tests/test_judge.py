"""Tests for pointwise LLM-as-judge evaluation engine."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_ingest_enrichment_service.schemas import JobExtractionSchema
from nohiki_llm_client import (
    ApiKeyRegistry,
    CachePoint,
    LLMAuthenticationError,
    LLMProviderResponseError,
    LLMTransientError,
    LLMValidationError,
)

from llm_benchmark.config.models import EvaluationResumeState, JudgeConfig, model_family
from llm_benchmark.engine.budget import BudgetScheduler
from llm_benchmark.engine.judge import (
    JUDGE_SYSTEM_PROMPT,
    SCHEMA_DESCRIPTION,
    _build_pointwise_prompt,
    _create_judge_client,
    _execute_pointwise_task,
    _format_output_as_yaml,
    _gather_pointwise_tasks,
    _PointwiseTask,
    evaluate_benchmark,
    evaluate_multi_judge,
)
from llm_benchmark.pricing import PricingSnapshot
from llm_benchmark.schemas.aggregation import (
    EvaluationResult,
    JudgmentUnit,
    MultiJudgeEvaluationSummary,
)
from llm_benchmark.schemas.judge import CategoryScore, PointwiseJudgment
from llm_benchmark.schemas.metrics import BenchmarkResult as _BenchmarkResult
from llm_benchmark.schemas.metrics import ModelResult
from llm_benchmark.schemas.metrics import RunResult as _RunResult


class RunResult(_RunResult):
    treatment_fingerprint: str = "test-treatment"
    cell_fingerprint: str = "test-cell"


class BenchmarkResult(_BenchmarkResult):
    experiment_fingerprint: str = "test-experiment"


def _valid_judgment(score: int = 80) -> PointwiseJudgment:
    category = CategoryScore(score=score, reasoning="Residual quality is coherent and source grounded")
    return PointwiseJudgment(
        inference_reasonableness=category,
        description_quality=category,
        downstream_usefulness=category,
        summary="Residual subjective quality is coherent and useful.",
    )


def _make_benchmark(
    *,
    models: dict[str, list[tuple[str, int, bool, dict[str, object] | None]]],
) -> BenchmarkResult:
    """Build a BenchmarkResult from simplified run specs.

    Args:
        models: Mapping of model_name to list of (fixture_id, run_number, success, output_json).

    Returns:
        BenchmarkResult with the specified runs.
    """
    model_results: dict[str, ModelResult] = {}
    all_fixtures: set[str] = set()

    for model_name, runs in models.items():
        run_results = []
        for fixture_id, run_number, success, output_json in runs:
            all_fixtures.add(fixture_id)
            run_results.append(
                RunResult(
                    fixture_id=fixture_id,
                    run_number=run_number,
                    success=success,
                    latency_ms=1000.0,
                    input_tokens=100,
                    output_tokens=50,
                    output_json=output_json,
                ),
            )
        model_results[model_name] = ModelResult(model=model_name, runs=run_results)

    return BenchmarkResult(
        fixtures_used=sorted(all_fixtures),
        runs_per_fixture=1,
        models=model_results,
    )


OUTPUT_A: dict[str, object] = {
    "cleaned_title": "Senior Software Engineer",
    "cleaned_company": "Acme",
}
OUTPUT_B: dict[str, object] = {
    "cleaned_title": "Sr. SWE",
    "cleaned_company": "ACME Corp.",
}


class TestSchemaDescription:
    """Tests for the production output contract supplied to judges."""

    def test_uses_production_schema_with_major_unit_semantics(self) -> None:
        serialized_schema = json.dumps(
            JobExtractionSchema.model_json_schema(),
            sort_keys=True,
            separators=(",", ":"),
        )
        normalized_description = SCHEMA_DESCRIPTION.casefold()

        assert serialized_schema in SCHEMA_DESCRIPTION
        assert "major units" in normalized_description
        assert "whole currency units" in normalized_description
        assert all(stale_term not in normalized_description for stale_term in ("minor_units", "minor units", "cents"))


class TestFormatOutputAsYaml:
    """Tests for _format_output_as_yaml function."""

    def test_converts_dict_to_yaml(self) -> None:
        result = _format_output_as_yaml(OUTPUT_A)
        assert "cleaned_title" in result
        assert "Senior Software Engineer" in result
        assert "cleaned_company" in result
        assert "Acme" in result

    def test_no_json_braces(self) -> None:
        result = _format_output_as_yaml(OUTPUT_A)
        assert "{" not in result
        assert "}" not in result

    def test_preserves_key_order(self) -> None:
        result = _format_output_as_yaml(OUTPUT_A)
        title_pos = result.index("cleaned_title")
        company_pos = result.index("cleaned_company")
        assert title_pos < company_pos


class TestBuildPointwisePrompt:
    """Tests for _build_pointwise_prompt function."""

    def test_always_returns_list_with_cache_point(self) -> None:
        task = _PointwiseTask(
            model_name="model-a",
            fixture_id="f1",
            run_number=1,
            yaml_output="cleaned_title: Test\n",
            static_context="## Original Extraction Prompt\n\nExtract the data.",
        )
        prompt = _build_pointwise_prompt(task)
        assert isinstance(prompt, list)
        assert len(prompt) == 3
        assert isinstance(prompt[1], CachePoint)

    def test_static_context_before_cache_point(self) -> None:
        task = _PointwiseTask(
            model_name="model-a",
            fixture_id="f1",
            run_number=1,
            yaml_output="cleaned_title: Test\n",
            static_context="## Original Extraction Prompt\n\nExtract the data.",
        )
        prompt = _build_pointwise_prompt(task)
        context = prompt[0]
        assert isinstance(context, str)
        assert "Original Extraction Prompt" in context
        assert "Extract the data" in context

    def test_variable_output_after_cache_point(self) -> None:
        task = _PointwiseTask(
            model_name="model-a",
            fixture_id="f1",
            run_number=1,
            yaml_output="cleaned_title: Test\n",
            static_context="context",
        )
        prompt = _build_pointwise_prompt(task)
        variable_part = prompt[2]
        assert isinstance(variable_part, str)
        assert "cleaned_title: Test" in variable_part
        assert "```yaml" in variable_part
        assert "Score only the three residual dimensions" in variable_part

    def test_prompt_blinds_treatment_identity_and_limits_scope_to_residual_quality(
        self,
    ) -> None:
        task = _PointwiseTask(
            model_name="openrouter:synthetic/secret-treatment",
            fixture_id="f1",
            run_number=1,
            yaml_output="cleaned_title: Test\n",
            static_context="source context",
        )
        rendered = "\n".join(part for part in _build_pointwise_prompt(task) if isinstance(part, str))

        assert task.model_name not in rendered
        assert "residual" in JUDGE_SYSTEM_PROMPT.casefold()
        assert "do not guess the model or provider" in JUDGE_SYSTEM_PROMPT.casefold()
        assert "do not rescore" in JUDGE_SYSTEM_PROMPT.casefold()


class TestModelFamily:
    @pytest.mark.parametrize(
        ("model", "expected_family"),
        [
            ("openrouter:openai/gpt-5.2", "openai"),
            ("openai:gpt-5.2", "openai"),
            ("openrouter:anthropic/claude-sonnet-4", "anthropic"),
            ("anthropic:claude-sonnet-4", "anthropic"),
            ("openai:qwen3-coder", "qwen"),
        ],
    )
    def test_infers_underlying_family_independent_of_proxy_transport(self, model: str, expected_family: str) -> None:
        assert model_family(model) == expected_family


class TestPointwiseTask:
    """Tests for _PointwiseTask dataclass."""

    def test_task_key_format(self) -> None:
        task = _PointwiseTask(
            model_name="openrouter:test/model",
            fixture_id="senior_python_remote",
            run_number=3,
            yaml_output="yaml",
            static_context="ctx",
        )
        assert task.task_key == "openrouter:test/model::senior_python_remote::3"

    def test_task_key_uniqueness(self) -> None:
        t1 = _PointwiseTask(
            model_name="m",
            fixture_id="f",
            run_number=1,
            yaml_output="y",
            static_context="c",
        )
        t2 = _PointwiseTask(
            model_name="m",
            fixture_id="f",
            run_number=2,
            yaml_output="y",
            static_context="c",
        )
        assert t1.task_key != t2.task_key


class TestEvaluationResumeState:
    """Tests for EvaluationResumeState dataclass."""

    def test_defaults(self) -> None:
        state = EvaluationResumeState()
        assert state.skip_task_keys == frozenset()
        assert state.existing_judgments == {}
        assert state.existing_cost_usd == 0.0
        assert state.existing_completed_count == 0

    def test_frozen(self) -> None:
        assert EvaluationResumeState.__dataclass_params__.frozen


class TestGatherPointwiseTasks:
    """Tests for _gather_pointwise_tasks function."""

    @patch("llm_benchmark.engine.judge.get_fixture")
    @patch("llm_benchmark.engine.judge._build_fixture_context")
    def test_creates_one_task_per_successful_output(
        self,
        mock_prompt: MagicMock,
        mock_fixture: MagicMock,
    ) -> None:
        mock_fixture.return_value = MagicMock()
        mock_prompt.return_value = "prompt"

        benchmark = _make_benchmark(
            models={
                "model-a": [("f1", 1, True, OUTPUT_A)],
                "model-b": [("f1", 1, True, OUTPUT_B)],
            },
        )
        tasks = _gather_pointwise_tasks(benchmark)
        assert len(tasks) == 2

    @patch("llm_benchmark.engine.judge.get_fixture")
    @patch("llm_benchmark.engine.judge._build_fixture_context")
    def test_skips_failed_runs(
        self,
        mock_prompt: MagicMock,
        mock_fixture: MagicMock,
    ) -> None:
        mock_fixture.return_value = MagicMock()
        mock_prompt.return_value = "prompt"

        benchmark = _make_benchmark(
            models={
                "model-a": [("f1", 1, True, OUTPUT_A)],
                "model-b": [("f1", 1, False, None)],
            },
        )
        tasks = _gather_pointwise_tasks(benchmark)
        assert len(tasks) == 1
        assert tasks[0].model_name == "model-a"

    @patch("llm_benchmark.engine.judge.get_fixture")
    @patch("llm_benchmark.engine.judge._build_fixture_context")
    def test_skips_null_output_json(
        self,
        mock_prompt: MagicMock,
        mock_fixture: MagicMock,
    ) -> None:
        mock_fixture.return_value = MagicMock()
        mock_prompt.return_value = "prompt"

        benchmark = _make_benchmark(
            models={
                "model-a": [("f1", 1, True, OUTPUT_A)],
                "model-b": [("f1", 1, True, None)],
            },
        )
        tasks = _gather_pointwise_tasks(benchmark)
        assert len(tasks) == 1

    @patch("llm_benchmark.engine.judge.get_fixture")
    @patch("llm_benchmark.engine.judge._build_fixture_context")
    def test_task_yaml_output_is_not_json(
        self,
        mock_prompt: MagicMock,
        mock_fixture: MagicMock,
    ) -> None:
        mock_fixture.return_value = MagicMock()
        mock_prompt.return_value = "prompt"

        benchmark = _make_benchmark(
            models={"model-a": [("f1", 1, True, OUTPUT_A)]},
        )
        tasks = _gather_pointwise_tasks(benchmark)
        assert len(tasks) == 1
        assert "{" not in tasks[0].yaml_output

    @patch("llm_benchmark.engine.judge.get_fixture")
    @patch("llm_benchmark.engine.judge._build_fixture_context")
    def test_tasks_sorted_by_fixture_id(
        self,
        mock_prompt: MagicMock,
        mock_fixture: MagicMock,
    ) -> None:
        mock_fixture.return_value = MagicMock()
        mock_prompt.return_value = "prompt"

        benchmark = _make_benchmark(
            models={
                "model-a": [
                    ("z_fixture", 1, True, OUTPUT_A),
                    ("a_fixture", 1, True, OUTPUT_A),
                ],
            },
        )
        tasks = _gather_pointwise_tasks(benchmark)
        assert len(tasks) == 2
        assert tasks[0].fixture_id == "a_fixture"
        assert tasks[1].fixture_id == "z_fixture"

    @patch("llm_benchmark.engine.judge.get_fixture")
    @patch("llm_benchmark.engine.judge._build_fixture_context")
    def test_skips_tasks_in_skip_set(
        self,
        mock_prompt: MagicMock,
        mock_fixture: MagicMock,
    ) -> None:
        mock_fixture.return_value = MagicMock()
        mock_prompt.return_value = "prompt"

        benchmark = _make_benchmark(
            models={
                "model-a": [("f1", 1, True, OUTPUT_A), ("f1", 2, True, OUTPUT_A)],
                "model-b": [("f1", 1, True, OUTPUT_B)],
            },
        )
        skip = frozenset({"model-a::f1::1", "model-b::f1::1"})
        tasks = _gather_pointwise_tasks(benchmark, skip_task_keys=skip)
        assert len(tasks) == 1
        assert tasks[0].model_name == "model-a"
        assert tasks[0].run_number == 2

    @patch("llm_benchmark.engine.judge.get_fixture")
    @patch("llm_benchmark.engine.judge._build_fixture_context")
    def test_empty_skip_set_returns_all(
        self,
        mock_prompt: MagicMock,
        mock_fixture: MagicMock,
    ) -> None:
        mock_fixture.return_value = MagicMock()
        mock_prompt.return_value = "prompt"

        benchmark = _make_benchmark(
            models={"model-a": [("f1", 1, True, OUTPUT_A)]},
        )
        tasks = _gather_pointwise_tasks(benchmark, skip_task_keys=frozenset())
        assert len(tasks) == 1


class TestJudgeConfig:
    """Tests for JudgeConfig and JudgeConfig.from_string factory."""

    def test_from_string_model_only(self) -> None:
        cfg = JudgeConfig.from_string("openrouter:openai/gpt-5.2")
        assert cfg.model == "openrouter:openai/gpt-5.2"
        assert cfg.reasoning_effort == "high"

    def test_from_string_with_effort_high(self) -> None:
        cfg = JudgeConfig.from_string("openrouter:openai/gpt-5.2:high")
        assert cfg.model == "openrouter:openai/gpt-5.2"
        assert cfg.reasoning_effort == "high"

    def test_from_string_with_effort_medium(self) -> None:
        cfg = JudgeConfig.from_string("openrouter:anthropic/claude-opus-4.6:medium")
        assert cfg.model == "openrouter:anthropic/claude-opus-4.6"
        assert cfg.reasoning_effort == "medium"

    def test_from_string_with_effort_low(self) -> None:
        cfg = JudgeConfig.from_string("openrouter:openai/gpt-5.2:low")
        assert cfg.reasoning_effort == "low"

    def test_from_string_ollama_no_effort(self) -> None:
        cfg = JudgeConfig.from_string("ollama:qwen3:30b")
        assert cfg.model == "ollama:qwen3:30b"
        assert cfg.reasoning_effort == "high"

    def test_default_weight(self) -> None:
        cfg = JudgeConfig(model="openrouter:x")
        assert cfg.weight == pytest.approx(1.0)

    def test_default_provider_order(self) -> None:
        cfg = JudgeConfig(model="openrouter:x")
        assert cfg.provider_order == ()

    def test_from_string_with_provider_order(self) -> None:
        cfg = JudgeConfig.from_string("openrouter:qwen/qwen3.5-35b-a3b@atlas-cloud/fp8")
        assert cfg.model == "openrouter:qwen/qwen3.5-35b-a3b"
        assert cfg.reasoning_effort == "high"
        assert cfg.provider_order == ("atlas-cloud/fp8",)

    def test_from_string_effort_and_provider(self) -> None:
        cfg = JudgeConfig.from_string("openrouter:qwen/qwen3.5-35b-a3b:medium@atlas-cloud/fp8")
        assert cfg.model == "openrouter:qwen/qwen3.5-35b-a3b"
        assert cfg.reasoning_effort == "medium"
        assert cfg.provider_order == ("atlas-cloud/fp8",)

    def test_from_string_multiple_providers(self) -> None:
        cfg = JudgeConfig.from_string("openrouter:test/model@provider-a,provider-b/fp16")
        assert cfg.provider_order == ("provider-a", "provider-b/fp16")

    def test_from_string_empty_provider(self) -> None:
        cfg = JudgeConfig.from_string("openrouter:test/model@")
        assert cfg.provider_order == ()


class TestEvaluationResult:
    """Tests for EvaluationResult dataclass."""

    def test_attributes(self) -> None:
        result = EvaluationResult(judgments_by_model={"model-a": []})
        assert "model-a" in result.judgments_by_model


class TestExecutePointwiseTask:
    """Tests for _execute_pointwise_task with mocked LLM client."""

    def _make_mock_client(
        self,
        return_judgment: object | None = None,
        cost_usd: float | None = 0.001,
    ) -> MagicMock:
        """Build a mock LLMClient returning a PointwiseJudgment."""
        mock_result = MagicMock()
        mock_result.output = return_judgment
        mock_result.cost_usd = cost_usd
        mock_client = MagicMock()
        mock_client.run = AsyncMock(return_value=mock_result)
        return mock_client

    def _make_task(self) -> _PointwiseTask:
        return _PointwiseTask(
            model_name="model-a",
            fixture_id="test_fixture",
            run_number=1,
            yaml_output="cleaned_title: Test\n",
            static_context="context",
        )

    @staticmethod
    def _noop_callback(
        _model: str,
        _fixture: str,
        _run: int,
        _judgment: object,
        _cost: float | None,
        _charged: float,
    ) -> None:
        pass

    @pytest.mark.asyncio
    async def test_returns_judgment_on_success(self) -> None:
        judgment = MagicMock()
        mock_client = self._make_mock_client(return_judgment=judgment)
        semaphore = asyncio.Semaphore(1)
        model_name, fixture_id, run_num, result = await _execute_pointwise_task(
            mock_client,
            MagicMock(),
            self._make_task(),
            semaphore,
            self._noop_callback,
        )
        assert model_name == "model-a"
        assert fixture_id == "test_fixture"
        assert run_num == 1
        assert result is judgment

    @pytest.mark.asyncio
    async def test_fires_on_complete_with_cost(self) -> None:
        judgment = MagicMock()
        mock_client = self._make_mock_client(return_judgment=judgment, cost_usd=0.0025)
        semaphore = asyncio.Semaphore(1)
        calls: list[tuple[str, str, int, object, float | None]] = []

        def capture(
            model: str,
            fixture: str,
            run: int,
            j: object,
            cost: float | None,
            charged: float,
        ) -> None:
            calls.append((model, fixture, run, j, cost, charged))

        await _execute_pointwise_task(
            mock_client,
            MagicMock(),
            self._make_task(),
            semaphore,
            capture,
        )
        assert len(calls) == 1
        assert calls[0][0] == "model-a"
        assert calls[0][4] == pytest.approx(0.0025)

    @pytest.mark.asyncio
    async def test_returns_none_on_provider_response_error(self) -> None:
        mock_client = MagicMock()
        mock_client.run = AsyncMock(side_effect=LLMProviderResponseError("500 Internal Server Error"))
        semaphore = asyncio.Semaphore(1)
        _, _, _, result = await _execute_pointwise_task(
            mock_client,
            MagicMock(),
            self._make_task(),
            semaphore,
            self._noop_callback,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_validation_error(self) -> None:
        mock_client = MagicMock()
        mock_client.run = AsyncMock(side_effect=LLMValidationError("Exceeded maximum retries"))
        semaphore = asyncio.Semaphore(1)
        _, _, _, result = await _execute_pointwise_task(
            mock_client,
            MagicMock(),
            self._make_task(),
            semaphore,
            self._noop_callback,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_transient_error(self) -> None:
        mock_client = MagicMock()
        mock_client.run = AsyncMock(side_effect=LLMTransientError("Connection reset"))
        semaphore = asyncio.Semaphore(1)
        _, _, _, result = await _execute_pointwise_task(
            mock_client,
            MagicMock(),
            self._make_task(),
            semaphore,
            self._noop_callback,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_cancel_event_skips_before_semaphore(self) -> None:
        mock_client = self._make_mock_client(return_judgment=MagicMock())
        semaphore = asyncio.Semaphore(1)
        cancel = asyncio.Event()
        cancel.set()

        calls: list[tuple[str, str, int, object, float | None]] = []

        def capture(
            model: str,
            fixture: str,
            run: int,
            j: object,
            cost: float | None,
            charged: float,
        ) -> None:
            calls.append((model, fixture, run, j, cost, charged))

        _, _, _, result = await _execute_pointwise_task(
            mock_client,
            MagicMock(),
            self._make_task(),
            semaphore,
            capture,
            cancel_event=cancel,
        )
        assert result is None
        assert len(calls) == 0
        mock_client.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_event_skips_after_semaphore(self) -> None:
        mock_client = self._make_mock_client(return_judgment=MagicMock())
        semaphore = asyncio.Semaphore(1)
        cancel = asyncio.Event()

        async def set_cancel_and_release() -> None:
            cancel.set()
            semaphore.release()

        await semaphore.acquire()
        asyncio.get_event_loop().call_soon(lambda: asyncio.ensure_future(set_cancel_and_release()))

        calls: list[tuple[str, str, int, object, float | None]] = []

        def capture(
            model: str,
            fixture: str,
            run: int,
            j: object,
            cost: float | None,
            charged: float,
        ) -> None:
            calls.append((model, fixture, run, j, cost, charged))

        _, _, _, result = await _execute_pointwise_task(
            mock_client,
            MagicMock(),
            self._make_task(),
            semaphore,
            capture,
            cancel_event=cancel,
        )
        assert result is None
        assert len(calls) == 0
        mock_client.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_fires_on_complete_even_on_error(self) -> None:
        mock_client = MagicMock()
        mock_client.run = AsyncMock(side_effect=LLMProviderResponseError("500"))
        semaphore = asyncio.Semaphore(1)
        calls: list[tuple[str, str, int, object, float | None]] = []

        def capture(
            model: str,
            fixture: str,
            run: int,
            j: object,
            cost: float | None,
            charged: float,
        ) -> None:
            calls.append((model, fixture, run, j, cost, charged))

        await _execute_pointwise_task(
            mock_client,
            MagicMock(),
            self._make_task(),
            semaphore,
            capture,
        )
        assert len(calls) == 1
        assert calls[0][3] is None
        assert calls[0][4] is None

    @pytest.mark.asyncio
    async def test_propagates_authentication_error(self) -> None:
        mock_client = MagicMock()
        mock_client.run = AsyncMock(side_effect=LLMAuthenticationError("Invalid API key"))
        semaphore = asyncio.Semaphore(1)
        with pytest.raises(LLMAuthenticationError):
            await _execute_pointwise_task(
                mock_client,
                MagicMock(),
                self._make_task(),
                semaphore,
                self._noop_callback,
            )


class TestEvaluateBenchmark:
    """Tests for evaluate_benchmark with mocked LLM client."""

    def _make_benchmark_with_outputs(
        self,
        fixture_ids: list[str] | None = None,
    ) -> BenchmarkResult:
        fids = fixture_ids or ["f1"]
        return BenchmarkResult(
            fixtures_used=fids,
            runs_per_fixture=1,
            models={
                "synthetic:model-a": ModelResult(
                    model="synthetic:model-a",
                    runs=[
                        RunResult(
                            fixture_id=fid,
                            run_number=1,
                            success=True,
                            latency_ms=100.0,
                            input_tokens=100,
                            output_tokens=50,
                            output_json=OUTPUT_A,
                        )
                        for fid in fids
                    ],
                ),
                "synthetic:model-b": ModelResult(
                    model="synthetic:model-b",
                    runs=[
                        RunResult(
                            fixture_id=fid,
                            run_number=1,
                            success=True,
                            latency_ms=100.0,
                            input_tokens=100,
                            output_tokens=50,
                            output_json=OUTPUT_B,
                        )
                        for fid in fids
                    ],
                ),
            },
        )

    @pytest.mark.asyncio
    @patch("llm_benchmark.engine.judge.get_fixture")
    @patch("llm_benchmark.engine.judge._build_fixture_context")
    async def test_returns_evaluation_result(
        self,
        mock_prompt: MagicMock,
        mock_fixture: MagicMock,
    ) -> None:
        mock_fixture.return_value = MagicMock()
        mock_prompt.return_value = "test prompt"

        mock_judgment = _valid_judgment()
        mock_run_result = MagicMock()
        mock_run_result.output = mock_judgment
        mock_run_result.cost_usd = 0.0
        mock_client = MagicMock()
        mock_client.run = AsyncMock(return_value=mock_run_result)
        mock_client.create_agent.return_value = MagicMock()

        benchmark = self._make_benchmark_with_outputs()
        with patch("llm_benchmark.engine.judge._create_judge_client", return_value=mock_client):
            result = await evaluate_benchmark(
                benchmark,
                ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
                judge_model="openrouter:synthetic/judge",
            )

        assert isinstance(result, EvaluationResult)
        assert len(result.judgments_by_model) == 2

    @pytest.mark.asyncio
    @patch("llm_benchmark.engine.judge.get_fixture")
    @patch("llm_benchmark.engine.judge._build_fixture_context")
    async def test_with_progress_callback(
        self,
        mock_prompt: MagicMock,
        mock_fixture: MagicMock,
    ) -> None:
        mock_fixture.return_value = MagicMock()
        mock_prompt.return_value = "test prompt"

        mock_judgment = _valid_judgment()
        mock_run_result = MagicMock()
        mock_run_result.output = mock_judgment
        mock_run_result.cost_usd = 0.0
        mock_client = MagicMock()
        mock_client.run = AsyncMock(return_value=mock_run_result)
        mock_client.create_agent.return_value = MagicMock()

        calls: list[tuple[str, int, int, float]] = []

        def on_progress(fixture_id: str, completed: int, total: int, cost_usd: float) -> None:
            calls.append((fixture_id, completed, total, cost_usd))

        benchmark = self._make_benchmark_with_outputs()
        with patch("llm_benchmark.engine.judge._create_judge_client", return_value=mock_client):
            result = await evaluate_benchmark(
                benchmark,
                ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
                judge_model="openrouter:synthetic/judge",
                progress_callback=on_progress,
            )

        assert isinstance(result, EvaluationResult)
        assert len(calls) >= 1
        assert all(total > 0 for _, _, total, _ in calls)

    @pytest.mark.asyncio
    async def test_returns_empty_result_when_no_valid_outputs(
        self,
    ) -> None:
        empty_benchmark = BenchmarkResult(
            fixtures_used=["senior_python_remote"],
            runs_per_fixture=1,
            models={
                "model-a": ModelResult(
                    model="model-a",
                    runs=[
                        RunResult(
                            fixture_id="senior_python_remote",
                            run_number=1,
                            success=False,
                            latency_ms=100.0,
                            error_message="timeout",
                        )
                    ],
                ),
            },
        )
        result = await evaluate_benchmark(
            empty_benchmark,
            ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
            judge_model="openrouter:synthetic/judge",
        )
        assert isinstance(result, EvaluationResult)
        assert result.judgments_by_model == {}

    @pytest.mark.asyncio
    @patch("llm_benchmark.engine.judge.get_fixture")
    @patch("llm_benchmark.engine.judge._build_fixture_context")
    async def test_excludes_same_family_across_proxy_transports(
        self, mock_prompt: MagicMock, mock_fixture: MagicMock
    ) -> None:
        mock_fixture.return_value = MagicMock()
        mock_prompt.return_value = "source"
        benchmark = _make_benchmark(
            models={
                "openrouter:openai/synthetic-candidate": [("f1", 1, True, OUTPUT_A)],
                "openrouter:qwen/synthetic-candidate": [("f1", 1, True, OUTPUT_B)],
            }
        )
        run_result = MagicMock(output=_valid_judgment(), cost_usd=0.0)
        client = MagicMock()
        client.run = AsyncMock(return_value=run_result)
        client.create_agent.return_value = MagicMock()

        with patch("llm_benchmark.engine.judge._create_judge_client", return_value=client):
            result = await evaluate_benchmark(
                benchmark,
                ApiKeyRegistry.model_validate({"openrouter": "synthetic-key"}),
                judge_model="openai:gpt-synthetic-judge",
            )

        assert client.run.await_count == 1
        assert set(result.judgments_by_model) == {"openrouter:qwen/synthetic-candidate"}

    @pytest.mark.asyncio
    @patch("llm_benchmark.engine.judge.get_fixture")
    @patch("llm_benchmark.engine.judge._build_fixture_context")
    async def test_same_family_only_benchmark_has_no_judgment_units(
        self,
        mock_prompt: MagicMock,
        mock_fixture: MagicMock,
    ) -> None:
        mock_fixture.return_value = MagicMock()
        mock_prompt.return_value = "source"
        benchmark = _make_benchmark(
            models={"openrouter:openai/synthetic-candidate": [("synthetic-fixture", 1, True, OUTPUT_A)]},
        )
        client = MagicMock()
        client.run = AsyncMock(return_value=MagicMock(output=_valid_judgment(), cost_usd=0.0))
        client.create_agent.return_value = MagicMock()

        with patch("llm_benchmark.engine.judge._create_judge_client", return_value=client):
            result = await evaluate_benchmark(
                benchmark,
                ApiKeyRegistry.model_validate({"openrouter": "synthetic-key"}),
                judge_model="openai:gpt-synthetic-judge",
            )

        client.run.assert_not_awaited()
        assert result.judgments_by_model == {}
        assert result.units == ()
        assert result.expected_units == 0

    @pytest.mark.asyncio
    @patch("llm_benchmark.engine.judge.get_fixture")
    @patch("llm_benchmark.engine.judge._build_fixture_context")
    async def test_completed_resume_preserves_exact_judgment_units(
        self, mock_prompt: MagicMock, mock_fixture: MagicMock
    ) -> None:
        mock_fixture.return_value = MagicMock()
        mock_prompt.return_value = "source"
        benchmark = _make_benchmark(models={"openrouter:qwen/synthetic-candidate": [("f1", 1, True, OUTPUT_A)]})
        judgment = PointwiseJudgment.model_construct(disqualifications=[])
        unit = JudgmentUnit(
            fixture_id="f1",
            treatment="openrouter:qwen/synthetic-candidate",
            run_number=1,
            judge="openrouter:openai/synthetic-judge",
            judgment=judgment,
        )
        state = EvaluationResumeState(
            skip_task_keys=frozenset({"openrouter:qwen/synthetic-candidate::f1::1"}),
            existing_judgments={"openrouter:qwen/synthetic-candidate": [judgment]},
            existing_units=(unit,),
            existing_cost_usd=0.25,
            existing_completed_count=1,
        )
        client = MagicMock()
        client.create_agent.return_value = MagicMock()

        with patch("llm_benchmark.engine.judge._create_judge_client", return_value=client):
            result = await evaluate_benchmark(
                benchmark,
                ApiKeyRegistry.model_validate({"openrouter": "synthetic-key"}),
                judge_model="openrouter:openai/synthetic-judge",
                resume_state=state,
            )

        assert result.units == (unit,)
        assert result.total_cost_usd == pytest.approx(0.25)


class TestEvaluateMultiJudge:
    """Tests for evaluate_multi_judge with mocked evaluate_benchmark."""

    def _make_mock_eval_result(self) -> EvaluationResult:
        return EvaluationResult(judgments_by_model={})

    @pytest.mark.asyncio
    async def test_returns_multi_judge_summary(
        self,
    ) -> None:
        benchmark = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=1,
            models={
                "model-a": ModelResult(
                    model="model-a",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=100.0,
                            input_tokens=100,
                            output_tokens=50,
                            output_json=OUTPUT_A,
                        )
                    ],
                ),
            },
        )
        judges = [
            JudgeConfig(model="openrouter:test-judge-1"),
            JudgeConfig(model="openrouter:test-judge-2"),
        ]
        mock_result = self._make_mock_eval_result()
        with patch(
            "llm_benchmark.engine.judge.evaluate_benchmark",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            summary = await evaluate_multi_judge(
                benchmark,
                ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
                judges,
            )
        assert isinstance(summary, MultiJudgeEvaluationSummary)
        assert set(summary.per_judge.keys()) == {
            "openrouter:test-judge-1",
            "openrouter:test-judge-2",
        }

    @pytest.mark.asyncio
    async def test_fires_progress_callback(
        self,
    ) -> None:
        benchmark = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=1,
            models={},
        )
        judges = [JudgeConfig(model="openrouter:test-judge")]
        mock_result = self._make_mock_eval_result()
        calls: list[tuple[str, str, int, int, float]] = []

        def on_progress(
            judge_model: str,
            fixture_id: str,
            completed: int,
            total: int,
            cost_usd: float,
        ) -> None:
            calls.append((judge_model, fixture_id, completed, total, cost_usd))

        def fake_eval(
            _benchmark: object,
            _api_keys: object,
            *,
            progress_callback: Callable[[str, int, int, float], None] | None = None,
            **_unused: object,
        ) -> EvaluationResult:
            if progress_callback is not None:
                progress_callback("f1", 1, 1, 0.001)
            return mock_result

        with patch(
            "llm_benchmark.engine.judge.evaluate_benchmark",
            new_callable=AsyncMock,
            side_effect=fake_eval,
        ):
            await evaluate_multi_judge(
                benchmark,
                ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
                judges,
                progress_callback=on_progress,
            )
        assert ("openrouter:test-judge", "f1", 1, 1, 0.001) in calls


class TestCreateJudgeClientRouting:
    """Route/fallback/ZDR settings must survive into the dispatched client config."""

    def _model_config(self, **kwargs: object) -> object:
        registry = ApiKeyRegistry.model_validate({"openrouter": "k"})
        with patch("nohiki_llm_client.LLMClient") as mock_client:
            _create_judge_client(
                "openrouter:qwen/qwen3.5-35b-a3b",
                registry,
                "high",
                ("atlas-cloud/fp8",),
                **kwargs,
            )
        settings = mock_client.call_args.args[0]
        return settings.provider.models[0]

    def test_propagates_provider_order(self) -> None:
        assert self._model_config().provider_order == ("atlas-cloud/fp8",)

    def test_propagates_zdr_and_disabled_fallbacks(self) -> None:
        model = self._model_config(provider_allow_fallbacks=False, provider_zdr=True)
        assert model.provider_allow_fallbacks is False
        assert model.provider_zdr is True

    def test_defaults_preserve_fallbacks_and_no_zdr(self) -> None:
        model = self._model_config()
        assert model.provider_allow_fallbacks is True
        assert model.provider_zdr is False


class TestJudgeIdentityKey:
    """identity_key captures every dispatch-affecting knob but never the weight."""

    def test_weight_is_not_part_of_identity(self) -> None:
        light = JudgeConfig(model="openrouter:x", weight=1.0)
        heavy = JudgeConfig(model="openrouter:x", weight=4.0)
        assert light.identity_key == heavy.identity_key

    def test_zdr_distinguishes_identity(self) -> None:
        plain = JudgeConfig(model="openrouter:x")
        zdr = JudgeConfig(model="openrouter:x", provider_zdr=True)
        assert plain.identity_key != zdr.identity_key

    def test_allow_fallbacks_distinguishes_identity(self) -> None:
        allowed = JudgeConfig(model="openrouter:x", provider_allow_fallbacks=True)
        pinned = JudgeConfig(model="openrouter:x", provider_allow_fallbacks=False)
        assert allowed.identity_key != pinned.identity_key

    def test_route_effort_base_url_distinguish_identity(self) -> None:
        base = JudgeConfig(model="openrouter:x")
        assert base.identity_key != JudgeConfig(model="openrouter:x", provider_order=("p",)).identity_key
        assert base.identity_key != JudgeConfig(model="openrouter:x", reasoning_effort="low").identity_key
        assert base.identity_key != JudgeConfig(model="openrouter:x", base_url="http://host").identity_key


class TestMultiJudgeRoutingPropagation:
    """evaluate_multi_judge threads each judge's routing knobs into evaluate_benchmark."""

    @pytest.mark.asyncio
    async def test_threads_route_fallbacks_and_zdr_per_judge(self) -> None:
        benchmark = BenchmarkResult(fixtures_used=["f1"], runs_per_fixture=1, models={})
        judge = JudgeConfig(
            model="openrouter:test-judge",
            provider_order=("prov-a",),
            provider_allow_fallbacks=False,
            provider_zdr=True,
        )
        with patch(
            "llm_benchmark.engine.judge.evaluate_benchmark",
            new_callable=AsyncMock,
            return_value=EvaluationResult(judgments_by_model={}),
        ) as mock_eval:
            await evaluate_multi_judge(benchmark, ApiKeyRegistry.model_validate({"openrouter": "k"}), [judge])
        kwargs = mock_eval.call_args.kwargs
        assert kwargs["provider_order"] == ("prov-a",)
        assert kwargs["provider_allow_fallbacks"] is False
        assert kwargs["provider_zdr"] is True


class TestExecutePointwiseTaskAccounting:
    """Dispatched failures charge fail-closed; budget-rejected non-dispatches vanish."""

    def _task(self) -> _PointwiseTask:
        return _PointwiseTask(
            model_name="model-a",
            fixture_id="f1",
            run_number=1,
            yaml_output="cleaned_title: Test\n",
            static_context="context",
        )

    def _snapshot(self) -> PricingSnapshot:
        return PricingSnapshot(1.0, 1.0, "genai_prices")

    @pytest.mark.asyncio
    async def test_dispatched_failure_charges_fail_closed_reservation(self) -> None:
        client = MagicMock()
        client.run = AsyncMock(side_effect=LLMValidationError("Exceeded maximum retries"))
        scheduler = BudgetScheduler(cap_usd=1_000_000.0, max_concurrency=1)
        calls: list[tuple[str, str, int, object, float | None, float]] = []

        def capture(m: str, f: str, r: int, j: object, actual: float | None, charged: float) -> None:
            calls.append((m, f, r, j, actual, charged))

        _, _, _, result = await _execute_pointwise_task(
            client,
            MagicMock(),
            self._task(),
            asyncio.Semaphore(1),
            capture,
            budget_scheduler=scheduler,
            pricing_snapshot=self._snapshot(),
        )
        assert result is None
        assert len(calls) == 1
        _, _, _, judgment, actual, charged = calls[0]
        assert judgment is None
        assert actual is None
        assert charged > 0.0
        # The fail-closed charge equals the worst-case reservation the budget held.
        assert scheduler.snapshot.charged_usd == pytest.approx(charged)

    @pytest.mark.asyncio
    async def test_budget_rejected_non_dispatch_is_never_reported(self) -> None:
        client = MagicMock()
        client.run = AsyncMock()
        scheduler = BudgetScheduler(cap_usd=1e-9, max_concurrency=1)
        cancel = asyncio.Event()
        calls: list[tuple[object, ...]] = []

        _, _, _, result = await _execute_pointwise_task(
            client,
            MagicMock(),
            self._task(),
            asyncio.Semaphore(1),
            lambda *a: calls.append(a),
            cancel_event=cancel,
            budget_scheduler=scheduler,
            pricing_snapshot=self._snapshot(),
        )
        assert result is None
        assert calls == []
        client.run.assert_not_called()
        assert cancel.is_set()
        assert scheduler.snapshot.charged_usd == pytest.approx(0.0)


class TestRequiresRegistryKey:
    """requires_registry_key mirrors the library's key-resolution rule."""

    def test_openrouter_requires_registry(self) -> None:
        assert JudgeConfig(model="openrouter:x").requires_registry_key is True

    def test_canonical_openai_requires_registry(self) -> None:
        assert JudgeConfig(model="openai:gpt-5.2").requires_registry_key is True

    def test_openai_with_base_url_is_exempt(self) -> None:
        judge = JudgeConfig(model="openai:gpt-5.2", base_url="https://openai.example.com/v1")
        assert judge.requires_registry_key is False

    def test_anthropic_with_base_url_still_requires_registry(self) -> None:
        judge = JudgeConfig(
            model="anthropic:claude-sonnet-4-6",
            base_url="https://model.example.test/v1",
        )
        assert judge.requires_registry_key is True

    @pytest.mark.parametrize("model", ["llamacpp:qwen3-30b", "ollama:qwen3:30b"])
    def test_local_providers_are_exempt(self, model: str) -> None:
        assert JudgeConfig(model=model).requires_registry_key is False

    def test_explicit_api_key_exempts_any_provider(self) -> None:
        assert JudgeConfig(model="openai:gpt-5.2", api_key="x").requires_registry_key is False
        assert JudgeConfig(model="anthropic:claude-sonnet-4-6", api_key="x").requires_registry_key is False
