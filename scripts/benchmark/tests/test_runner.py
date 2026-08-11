"""Tests for benchmark runner, fixture registry, and client factory."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import replace
from typing import TypedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_ingest_enrichment_service.extraction_contract import (
    DEFAULT_EXTRACTION_SPEC,
)
from job_ingest_enrichment_service.extraction_contract import (
    ExtractionContext as ProductionExtractionContext,
)
from nohiki_llm_client import (
    ApiKeyRegistry,
    LLMModelConfig,
    LLMProviderSettings,
    LLMSettings,
    ReasoningEffort,
)
from nohiki_llm_client.config.constants import DEFAULT_MAX_TOOL_RETRIES

from llm_benchmark.config.constants import (
    DEFAULT_BENCHMARK_CONCURRENCY,
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
)
from llm_benchmark.config.models import BenchmarkConfig as _BenchmarkConfig
from llm_benchmark.engine import runner as runner_module
from llm_benchmark.engine.runner import (
    BenchmarkRunner,
    _create_client,
    experiment_fingerprint,
)
from llm_benchmark.fixtures import get_fixture
from llm_benchmark.pricing import EndpointRate, PricingSnapshot
from llm_benchmark.schemas.metrics import BenchmarkResult, ModelResult, RunResult


class BenchmarkConfig(_BenchmarkConfig):
    def __init__(
        self,
        *,
        models: Sequence[str | LLMModelConfig],
        fixture_ids: list[str],
        runs_per_fixture: int,
        api_keys: ApiKeyRegistry | None = None,
        max_concurrency: int = DEFAULT_BENCHMARK_CONCURRENCY,
        ollama_timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS,
        temperature: float = 0.0,
        max_tokens: int | None = 2_048,
        max_retries: int = DEFAULT_MAX_TOOL_RETRIES,
        timeout_seconds: float = 120.0,
        cost_cap_usd: float = 10.0,
        unknown_price_max_usd: float | None = 0.1,
        pricing_snapshots: tuple[PricingSnapshot, ...] = (),
    ) -> None:
        resolved_models = tuple(
            model if isinstance(model, LLMModelConfig) else LLMModelConfig(model=model) for model in models
        )
        super().__init__(
            models=resolved_models,
            fixture_ids=fixture_ids,
            runs_per_fixture=runs_per_fixture,
            api_keys=api_keys if api_keys is not None else ApiKeyRegistry(),
            max_concurrency=max_concurrency,
            ollama_timeout_seconds=ollama_timeout_seconds,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
            cost_cap_usd=cost_cap_usd,
            unknown_price_max_usd=unknown_price_max_usd,
            pricing_snapshots=pricing_snapshots,
        )


build_extraction_prompt = DEFAULT_EXTRACTION_SPEC.build_prompt


class TestProductionExtractionContract:
    """Tests that benchmarks execute the production extraction contract."""

    def test_runner_exports_exact_production_contract_symbols(self) -> None:
        assert runner_module.DEFAULT_EXTRACTION_SPEC is DEFAULT_EXTRACTION_SPEC
        assert runner_module.ExtractionContext is ProductionExtractionContext


class _ModelOverrides(TypedDict, total=False):
    """Typed subset of LLMModelConfig fields mutated by fingerprint tests."""

    model: str
    base_url: str | None
    provider_order: tuple[str, ...]
    provider_allow_fallbacks: bool
    provider_zdr: bool
    reasoning_effort: ReasoningEffort


class _ConfigMutation(TypedDict, total=False):
    """Typed subset of BenchmarkConfig fields mutated by fingerprint tests."""

    model: _ModelOverrides
    temperature: float
    max_retries: int
    max_tokens: int
    timeout_seconds: float
    cost_cap_usd: float
    unknown_price_max_usd: float


_BASELINE_PRICING = PricingSnapshot(
    input_per_million_usd=1.0,
    output_per_million_usd=2.0,
    source="openrouter_endpoint",
    endpoints=(EndpointRate("route-a", 1.0, 2.0),),
)


class TestExperimentFingerprint:
    """Tests that every execution-semantic change invalidates resume identity."""

    @pytest.fixture(autouse=True)
    def _prohibit_pricing_network(self) -> Iterator[None]:
        """Fail loudly instead of performing pricing network I/O (offline identity)."""
        guard = AssertionError("fingerprint tests must not perform pricing network I/O")
        with patch("llm_benchmark.pricing.fetch_openrouter_endpoints", side_effect=guard):
            yield

    @staticmethod
    def _config(
        changes: _ConfigMutation | None = None,
        *,
        pricing: PricingSnapshot | None = None,
    ) -> BenchmarkConfig:
        changes = changes or {}
        model = LLMModelConfig(
            model="openrouter:synthetic/candidate",
            reasoning_effort="medium",
            base_url="https://gateway-a.example.test/v1",
            provider_order=("route-a",),
            provider_allow_fallbacks=False,
        )
        model_overrides = changes.get("model")
        if model_overrides is not None:
            model = model.model_copy(update=model_overrides)
        resolved_pricing = pricing if pricing is not None else _BASELINE_PRICING
        return BenchmarkConfig(
            models=(model,),
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            temperature=changes.get("temperature", 0.2),
            max_tokens=changes.get("max_tokens", 2_048),
            max_retries=changes.get("max_retries", 2),
            timeout_seconds=changes.get("timeout_seconds", 30.0),
            cost_cap_usd=changes.get("cost_cap_usd", 2.0),
            unknown_price_max_usd=changes.get("unknown_price_max_usd", 0.05),
            pricing_snapshots=(resolved_pricing,),
        )

    @pytest.mark.parametrize(
        "changed",
        [
            {"temperature": 0.3},
            {"model": {"model": "openrouter:synthetic/other"}},
            {"model": {"base_url": "https://gateway-b.example.test/v1"}},
            {"model": {"provider_order": ("route-b",)}},
            {"model": {"provider_allow_fallbacks": True}},
            {"model": {"reasoning_effort": "high"}},
            {"max_retries": 3},
            {"max_tokens": 4_096},
            {"timeout_seconds": 31.0},
            {"cost_cap_usd": 3.0},
            {"unknown_price_max_usd": 0.06},
        ],
    )
    def test_execution_setting_change_invalidates_identity(self, changed: _ConfigMutation) -> None:
        baseline_experiment, baseline_treatments = experiment_fingerprint(self._config())
        changed_experiment, changed_treatments = experiment_fingerprint(self._config(changed))

        assert changed_experiment != baseline_experiment
        assert changed_treatments != baseline_treatments

    def test_prompt_schema_or_gold_change_invalidates_identity(self) -> None:
        baseline = experiment_fingerprint(self._config())[0]
        with patch.object(runner_module, "BENCHMARK_SOURCE_VERSION", "changed-prompt-schema"):
            assert experiment_fingerprint(self._config())[0] != baseline
        with patch.object(runner_module, "BENCHMARK_POLICY_VERSION", "changed-execution-policy"):
            assert experiment_fingerprint(self._config())[0] != baseline
        with patch.object(runner_module, "compute_fixture_checksum", return_value="changed-gold"):
            assert experiment_fingerprint(self._config())[0] != baseline

    def test_pricing_snapshot_change_invalidates_identity(self) -> None:
        baseline_experiment, baseline_treatments = experiment_fingerprint(self._config())
        repriced = PricingSnapshot(
            input_per_million_usd=9.0,
            output_per_million_usd=18.0,
            source="openrouter_endpoint",
            endpoints=(EndpointRate("route-a", 9.0, 18.0),),
        )
        changed_experiment, changed_treatments = experiment_fingerprint(self._config(pricing=repriced))

        assert changed_experiment != baseline_experiment
        assert changed_treatments != baseline_treatments

    def test_provider_zdr_change_invalidates_identity(self) -> None:
        """Toggling Zero Data Retention re-fingerprints the treatment and experiment."""
        baseline_experiment, baseline_treatments = experiment_fingerprint(self._config())
        zdr_experiment, zdr_treatments = experiment_fingerprint(self._config({"model": {"provider_zdr": True}}))

        assert zdr_experiment != baseline_experiment
        assert zdr_treatments != baseline_treatments


class TestBuildExtractionPrompt:
    """Tests for build_extraction_prompt."""

    def test_prompt_contains_listing_data(self) -> None:
        listing = get_fixture("senior_python_remote")
        prompt = build_extraction_prompt(listing)
        assert "Job Posting to Extract" in prompt
        assert listing.title in prompt
        assert listing.company_name in prompt

    def test_prompt_contains_description(self) -> None:
        listing = get_fixture("senior_python_remote")
        prompt = build_extraction_prompt(listing)
        assert "Description" in prompt

    def test_prompt_contains_location(self) -> None:
        listing = get_fixture("senior_python_remote")
        prompt = build_extraction_prompt(listing)
        assert listing.location_raw in prompt

    def test_prompt_extraction_instruction(self) -> None:
        listing = get_fixture("senior_python_remote")
        prompt = build_extraction_prompt(listing)
        assert "JobExtractionSchema" in prompt

    def test_prompt_no_description_fallback(self) -> None:
        listing = get_fixture("senior_python_remote")
        empty_listing = replace(listing, description="")
        prompt = build_extraction_prompt(empty_listing)
        assert "No description provided" in prompt


class TestCreateClient:
    """Tests for _create_client factory."""

    def test_creates_client(self) -> None:
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="openrouter:google/gemini-3-flash-preview")],
                api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-api-key"}),
            ),
        )
        client = _create_client(settings)
        assert client is not None

    def test_creates_client_with_custom_params(self) -> None:
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="openrouter:deepseek/deepseek-v3.2")],
                api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
                timeout_seconds=60.0,
                temperature=0.5,
            ),
        )
        client = _create_client(settings)
        assert client is not None

    def test_creates_ollama_client(self) -> None:
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="ollama:qwen3:30b",
                        base_url="https://model.example.test/v1",
                    )
                ],
            ),
        )
        client = _create_client(settings)
        assert client is not None


class TestBuildExtractionPromptRawSkills:
    """Tests for build_extraction_prompt with raw_skills populated."""

    def test_includes_raw_skills_section(self) -> None:
        listing = get_fixture("senior_python_remote")
        listing_with_skills = replace(listing, raw_skills=["Python", "Docker", "Kubernetes"])
        prompt = build_extraction_prompt(listing_with_skills)
        assert "Raw Skills Mentioned" in prompt
        assert "Python" in prompt
        assert "Docker" in prompt

    def test_no_raw_skills_section_without_skills(self) -> None:
        listing = get_fixture("senior_python_remote")
        listing_no_skills = replace(listing, raw_skills=[])
        prompt = build_extraction_prompt(listing_no_skills)
        assert "Raw Skills Mentioned" not in prompt


class TestBenchmarkRunnerRun:
    """Tests for BenchmarkRunner.run with mocked LLM client."""

    def _make_mock_client(self) -> MagicMock:
        """Build a mock LLMClient whose run() returns a fake extraction result."""
        mock_output = MagicMock()
        mock_output.model_dump.return_value = {"cleaned_title": "Software Engineer"}
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_usage.cache_read_tokens = 0
        mock_usage.cache_write_tokens = 0
        mock_usage.requests = 1
        mock_usage.tool_calls = 0
        mock_usage.details = {"reasoning_tokens": 0}
        mock_run_result = MagicMock()
        mock_run_result.output = mock_output
        mock_run_result.usage = mock_usage
        mock_run_result.retry_count = 0
        mock_run_result.cost_usd = None

        mock_client = MagicMock()
        mock_client.run = AsyncMock(return_value=mock_run_result)
        mock_client.create_agent.return_value = MagicMock()
        return mock_client

    @pytest.mark.asyncio
    async def test_custom_base_url_applies_only_to_openai_models(self) -> None:
        config = BenchmarkConfig(
            models=[
                LLMModelConfig(
                    model="openai:synthetic-custom-model",
                    base_url="https://gateway.example.test/v1",
                ),
                LLMModelConfig(model="openrouter:synthetic/cloud-model"),
            ],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key", "openai": "test-key"}),
            max_concurrency=7,
        )
        settings_by_model: dict[str, LLMSettings] = {}

        def capture_settings(settings: LLMSettings) -> MagicMock:
            settings_by_model[settings.provider.models[0].model] = settings
            return self._make_mock_client()

        with patch("llm_benchmark.engine.runner._create_client", side_effect=capture_settings):
            await BenchmarkRunner(config).run()

        assert settings_by_model["openai:synthetic-custom-model"].provider.models[0].base_url == (
            "https://gateway.example.test/v1"
        )
        assert settings_by_model["openrouter:synthetic/cloud-model"].provider.models[0].base_url is None
        assert settings_by_model["openai:synthetic-custom-model"].provider.concurrency_limit == 7
        assert settings_by_model["openrouter:synthetic/cloud-model"].provider.concurrency_limit == 7

    @pytest.mark.asyncio
    async def test_llamacpp_uses_canonical_dispatch_and_serial_local_concurrency(
        self,
    ) -> None:
        config = BenchmarkConfig(
            models=[
                LLMModelConfig(
                    model="llamacpp:synthetic-local-candidate",
                    base_url="https://local-runtime.example.test/v1",
                )
            ],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            max_concurrency=9,
            ollama_timeout_seconds=47.0,
        )
        captured: list[LLMSettings] = []

        def capture_settings(settings: LLMSettings) -> MagicMock:
            captured.append(settings)
            return self._make_mock_client()

        with patch("llm_benchmark.engine.runner._create_client", side_effect=capture_settings):
            result = await BenchmarkRunner(config).run()

        provider = captured[0].provider
        assert provider.models[0].model == "llamacpp:synthetic-local-candidate"
        assert provider.models[0].base_url == "https://local-runtime.example.test/v1"
        assert provider.concurrency_limit == 1
        assert provider.timeout_seconds == pytest.approx(47.0)
        assert next(iter(result.models.values())).runs[0].success is True

    @pytest.mark.asyncio
    async def test_run_returns_benchmark_result(self) -> None:
        config = BenchmarkConfig(
            models=["openrouter:test/model"],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        mock_client = self._make_mock_client()
        with patch("llm_benchmark.engine.runner._create_client", return_value=mock_client):
            runner = BenchmarkRunner(config)
            result = await runner.run()
        model_result = next(iter(result.models.values()))
        assert model_result.model.startswith("openrouter:test/model@")
        assert len(model_result.runs) == 1
        assert model_result.runs[0].success is True
        agent_config = mock_client.create_agent.call_args.args[0]
        assert agent_config.system_prompt is DEFAULT_EXTRACTION_SPEC.system_prompt
        assert agent_config.deps_type is ProductionExtractionContext

        listing = get_fixture("senior_python_remote")
        run_call = mock_client.run.await_args
        assert run_call.args[1] == DEFAULT_EXTRACTION_SPEC.build_prompt(listing)
        assert run_call.kwargs["deps"] == DEFAULT_EXTRACTION_SPEC.build_context(listing)

    @pytest.mark.asyncio
    async def test_run_multiple_fixtures_and_runs(self) -> None:
        config = BenchmarkConfig(
            models=["openrouter:model-a"],
            fixture_ids=["senior_python_remote", "nurse_icu_onsite"],
            runs_per_fixture=2,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        mock_client = self._make_mock_client()
        with patch("llm_benchmark.engine.runner._create_client", return_value=mock_client):
            runner = BenchmarkRunner(config)
            result = await runner.run()
        runs = next(iter(result.models.values())).runs
        assert len(runs) == 4

    @pytest.mark.asyncio
    async def test_run_fires_progress_callback(self) -> None:
        config = BenchmarkConfig(
            models=["openrouter:test/model"],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        mock_client = self._make_mock_client()
        from llm_benchmark.schemas.metrics import RunResult as _RunResult

        calls: list[tuple[str, str, int, _RunResult]] = []

        def progress(model: str, fixture_id: str, run_number: int, *, run_result: _RunResult) -> None:
            calls.append((model, fixture_id, run_number, run_result))

        with patch("llm_benchmark.engine.runner._create_client", return_value=mock_client):
            runner = BenchmarkRunner(config)
            await runner.run(progress_callback=progress)
        assert len(calls) == 1
        assert calls[0][0].startswith("openrouter:test/model@")
        assert calls[0][3].success is True

    @pytest.mark.asyncio
    async def test_paid_treatment_requires_finite_token_reservation_bound(self) -> None:
        config = _BenchmarkConfig(
            models=(LLMModelConfig(model="openrouter:test/model"),),
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
            max_tokens=None,
            unknown_price_max_usd=0.1,
        )
        with pytest.raises(ValueError, match="finite max_tokens reservation bound"):
            await BenchmarkRunner(config).run()

    @pytest.mark.asyncio
    async def test_run_records_failed_run_on_error(self) -> None:
        config = BenchmarkConfig(
            models=["openrouter:test/model"],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        mock_client = MagicMock()
        mock_client.run = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        mock_client.create_agent.return_value = MagicMock()
        with patch("llm_benchmark.engine.runner._create_client", return_value=mock_client):
            runner = BenchmarkRunner(config)
            result = await runner.run()
        runs = next(iter(result.models.values())).runs
        assert len(runs) == 1
        assert runs[0].success is False
        assert runs[0].error_message is not None

    @pytest.mark.asyncio
    async def test_run_records_transient_error_retry_count_unknown(self) -> None:
        """Transient failure records an unknown retry_count (None), never a fabricated count."""
        from nohiki_llm_client import LLMTransientError

        config = BenchmarkConfig(
            models=["openrouter:test/model"],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        mock_client = MagicMock()
        mock_client.run = AsyncMock(side_effect=LLMTransientError("provider unavailable"))
        mock_client.create_agent.return_value = MagicMock()
        with patch("llm_benchmark.engine.runner._create_client", return_value=mock_client):
            runner = BenchmarkRunner(config)
            result = await runner.run()
        run = next(iter(result.models.values())).runs[0]
        assert run.success is False
        assert run.retry_count is None

    @pytest.mark.asyncio
    async def test_run_records_validation_error_retry_count_unknown(self) -> None:
        """Validation failure records an unknown retry_count (None): no measured count is exposed."""
        from nohiki_llm_client import LLMValidationError

        config = BenchmarkConfig(
            models=["openrouter:test/model"],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        mock_client = MagicMock()
        mock_client.run = AsyncMock(
            side_effect=LLMValidationError("Exceeded maximum retries (3) for output validation")
        )
        mock_client.create_agent.return_value = MagicMock()
        with patch("llm_benchmark.engine.runner._create_client", return_value=mock_client):
            runner = BenchmarkRunner(config)
            result = await runner.run()
        run = next(iter(result.models.values())).runs[0]
        assert run.success is False
        assert run.retry_count is None

    @pytest.mark.asyncio
    async def test_run_records_provider_response_error_retry_count_unknown(
        self,
    ) -> None:
        """Provider response failure records an unknown retry_count (None)."""
        from nohiki_llm_client import LLMProviderResponseError
        from nohiki_llm_client.config.constants import (
            OPENROUTER_INVALID_RESPONSE_PREFIX,
        )

        config = BenchmarkConfig(
            models=["openrouter:test/model"],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        mock_client = MagicMock()
        mock_client.run = AsyncMock(
            side_effect=LLMProviderResponseError(
                f"{OPENROUTER_INVALID_RESPONSE_PREFIX}: 5 validation errors for _OpenRouterChatCompletion"
            )
        )
        mock_client.create_agent.return_value = MagicMock()
        with patch("llm_benchmark.engine.runner._create_client", return_value=mock_client):
            runner = BenchmarkRunner(config)
            result = await runner.run()
        run = next(iter(result.models.values())).runs[0]
        assert run.success is False
        assert run.retry_count is None

    @pytest.mark.asyncio
    async def test_run_success_preserves_measured_retry_count(self) -> None:
        """Successful runs retain the measured LLMResult.retry_count verbatim, including nonzero."""
        config = BenchmarkConfig(
            models=["openrouter:test/model"],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        mock_client = self._make_mock_client()
        mock_client.run.return_value.retry_count = 3
        with patch("llm_benchmark.engine.runner._create_client", return_value=mock_client):
            result = await BenchmarkRunner(config).run()
        run = next(iter(result.models.values())).runs[0]
        assert run.success is True
        assert run.retry_count == 3

    @pytest.mark.asyncio
    async def test_run_truncation_preserves_measured_retry_count(self) -> None:
        """A truncation failure keeps the measured retry_count because dispatch succeeded."""
        config = BenchmarkConfig(
            models=["openrouter:test/model"],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            max_tokens=64,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        mock_client = self._make_mock_client()
        mock_client.run.return_value.usage.output_tokens = 64
        mock_client.run.return_value.retry_count = 2
        with patch("llm_benchmark.engine.runner._create_client", return_value=mock_client):
            result = await BenchmarkRunner(config).run()
        run = next(iter(result.models.values())).runs[0]
        assert run.success is False
        assert "truncated" in (run.error_message or "")
        assert run.retry_count == 2


class TestBenchmarkRunnerResumeCostGating:
    """Resume finalizes attempted cells and gates the cap by persisted charge."""

    def _make_mock_client(self) -> MagicMock:
        mock_output = MagicMock()
        mock_output.model_dump.return_value = {"cleaned_title": "Software Engineer"}
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_usage.cache_read_tokens = 0
        mock_usage.cache_write_tokens = 0
        mock_usage.requests = 1
        mock_usage.tool_calls = 0
        mock_usage.details = {"reasoning_tokens": 0}
        mock_run_result = MagicMock()
        mock_run_result.output = mock_output
        mock_run_result.usage = mock_usage
        mock_run_result.retry_count = 0
        mock_run_result.cost_usd = None
        mock_client = MagicMock()
        mock_client.run = AsyncMock(return_value=mock_run_result)
        mock_client.create_agent.return_value = MagicMock()
        return mock_client

    @staticmethod
    def _unknown_snapshot() -> PricingSnapshot:
        return PricingSnapshot(input_per_million_usd=None, output_per_million_usd=None, source="unknown")

    @staticmethod
    def _model_name(runner: BenchmarkRunner) -> str:
        config = runner._config
        fingerprint = runner._treatment_fingerprints[0]
        return f"{config.models[0].model}@{fingerprint[:16]}"

    def _prior_result(
        self,
        runner: BenchmarkRunner,
        *,
        fixture_id: str,
        reserved_cost_usd: float,
        total_cost_usd: float = 0.0,
    ) -> BenchmarkResult:
        model_name = self._model_name(runner)
        failed = RunResult(
            fixture_id=fixture_id,
            treatment_fingerprint="prior-treatment",
            cell_fingerprint="prior-cell",
            run_number=1,
            success=False,
            latency_ms=1.0,
            actual_cost_usd=None,
            reserved_cost_usd=reserved_cost_usd,
            error_message="prior dispatched failure",
            retry_count=0,
        )
        return BenchmarkResult(
            experiment_fingerprint=runner._experiment_fingerprint,
            fixtures_used=[fixture_id],
            runs_per_fixture=1,
            models={model_name: ModelResult(model=model_name, total_cost_usd=total_cost_usd, runs=[failed])},
        )

    @pytest.mark.asyncio
    async def test_persisted_failed_cell_is_not_re_dispatched_on_resume(self) -> None:
        config = BenchmarkConfig(
            models=["openrouter:test/model"],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
            pricing_snapshots=(self._unknown_snapshot(),),
        )
        runner = BenchmarkRunner(config)
        existing = self._prior_result(runner, fixture_id="senior_python_remote", reserved_cost_usd=0.05)
        mock_client = self._make_mock_client()
        with patch("llm_benchmark.engine.runner._create_client", return_value=mock_client):
            result = await runner.run(existing_result=existing)
        # The failed attempt is final: no provider call, and the failure survives.
        assert mock_client.run.await_count == 0
        runs = result.models[self._model_name(runner)].runs
        assert [(r.fixture_id, r.success) for r in runs] == [("senior_python_remote", False)]

    @pytest.mark.asyncio
    async def test_resume_seeds_scheduler_with_charged_and_actual_totals(self) -> None:
        config = BenchmarkConfig(
            models=["openrouter:test/model"],
            fixture_ids=["senior_python_remote", "nurse_icu_onsite"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
            pricing_snapshots=(self._unknown_snapshot(),),
        )
        runner = BenchmarkRunner(config)
        existing = self._prior_result(
            runner,
            fixture_id="senior_python_remote",
            reserved_cost_usd=0.05,
            total_cost_usd=0.01,
        )
        captured: dict[str, float] = {}
        real_scheduler = runner_module.BudgetScheduler

        def spy(
            *,
            cap_usd: float,
            max_concurrency: int,
            initial_charged_usd: float = 0.0,
            initial_actual_usd: float = 0.0,
        ) -> runner_module.BudgetScheduler:
            captured.update(
                initial_charged_usd=initial_charged_usd,
                initial_actual_usd=initial_actual_usd,
            )
            return real_scheduler(
                cap_usd=cap_usd,
                max_concurrency=max_concurrency,
                initial_charged_usd=initial_charged_usd,
                initial_actual_usd=initial_actual_usd,
            )

        with (
            patch(
                "llm_benchmark.engine.runner._create_client",
                return_value=self._make_mock_client(),
            ),
            patch("llm_benchmark.engine.runner.BudgetScheduler", side_effect=spy),
        ):
            await runner.run(existing_result=existing)
        # Charged total (failed reservation) gates the cap; actual total reports separately.
        assert captured["initial_charged_usd"] == pytest.approx(existing.total_charged_cost)
        assert captured["initial_actual_usd"] == pytest.approx(existing.total_actual_cost)
        assert captured["initial_charged_usd"] == pytest.approx(0.05)
        assert captured["initial_actual_usd"] == pytest.approx(0.01)

    @pytest.mark.asyncio
    async def test_resume_refuses_new_dispatch_when_persisted_charge_exhausts_cap(
        self,
    ) -> None:
        # Cap 0.15; per-call reservation 0.10 (unknown price). A fresh run would
        # dispatch the second fixture (0.10 <= 0.15), but a prior failed cell
        # already charged 0.10, leaving only 0.05 headroom -> the new cell is
        # refused. Old behavior seeded from actual cost (0.0 for a failure) and
        # would silently re-spend past the cap.
        config = BenchmarkConfig(
            models=["openrouter:test/model"],
            fixture_ids=["senior_python_remote", "nurse_icu_onsite"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
            cost_cap_usd=0.15,
            unknown_price_max_usd=0.10,
            pricing_snapshots=(self._unknown_snapshot(),),
        )
        runner = BenchmarkRunner(config)
        existing = self._prior_result(runner, fixture_id="senior_python_remote", reserved_cost_usd=0.10)
        mock_client = self._make_mock_client()
        with patch("llm_benchmark.engine.runner._create_client", return_value=mock_client):
            result = await runner.run(existing_result=existing)
        assert mock_client.run.await_count == 0
        runs = result.models[self._model_name(runner)].runs
        assert [(r.fixture_id, r.success) for r in runs] == [("senior_python_remote", False)]


class TestLocalProviderTokenExemption:
    """Local llama.cpp/Ollama treatments are zero-cost and need no max_tokens bound."""

    def _make_mock_client(self) -> MagicMock:
        mock_output = MagicMock()
        mock_output.model_dump.return_value = {"cleaned_title": "Software Engineer"}
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_usage.cache_read_tokens = 0
        mock_usage.cache_write_tokens = 0
        mock_usage.requests = 1
        mock_usage.tool_calls = 0
        mock_usage.details = {"reasoning_tokens": 0}
        mock_run_result = MagicMock()
        mock_run_result.output = mock_output
        mock_run_result.usage = mock_usage
        mock_run_result.retry_count = 0
        mock_run_result.cost_usd = None
        mock_client = MagicMock()
        mock_client.run = AsyncMock(return_value=mock_run_result)
        mock_client.create_agent.return_value = MagicMock()
        return mock_client

    @pytest.mark.asyncio
    async def test_llamacpp_only_run_omits_max_tokens_without_error(self) -> None:
        config = _BenchmarkConfig(
            models=(
                LLMModelConfig(
                    model="llamacpp:synthetic-local",
                    base_url="https://model.example.test/v1",
                ),
            ),
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            max_tokens=None,
        )
        with patch(
            "llm_benchmark.engine.runner._create_client",
            return_value=self._make_mock_client(),
        ):
            result = await BenchmarkRunner(config).run()
        assert len(result.models) == 1
        assert next(iter(result.models.values())).runs[0].success is True

    @pytest.mark.asyncio
    async def test_all_local_providers_run_without_max_tokens(self) -> None:
        config = _BenchmarkConfig(
            models=(
                LLMModelConfig(
                    model="llamacpp:synthetic-local",
                    base_url="https://model.example.test/v1",
                ),
                LLMModelConfig(
                    model="ollama:synthetic-local",
                    base_url="https://model.example.test/v1",
                ),
            ),
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            max_tokens=None,
        )
        with patch(
            "llm_benchmark.engine.runner._create_client",
            return_value=self._make_mock_client(),
        ):
            result = await BenchmarkRunner(config).run()
        assert len(result.models) == 2

    @pytest.mark.asyncio
    async def test_mixed_local_and_paid_still_requires_max_tokens(self) -> None:
        config = _BenchmarkConfig(
            models=(
                LLMModelConfig(
                    model="llamacpp:synthetic-local",
                    base_url="https://model.example.test/v1",
                ),
                LLMModelConfig(model="openrouter:test/model"),
            ),
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
            max_tokens=None,
            unknown_price_max_usd=0.1,
        )
        with pytest.raises(ValueError, match="finite max_tokens reservation bound"):
            await BenchmarkRunner(config).run()
