"""Focused tests for the ``evaluate`` command's persistence, key-loading, and resume wiring.

Covers release blockers that live in ``evaluate.py`` itself rather than the engine:
- the evaluation artifact is derived so it never overwrites the source result;
- the shared secret registry is loaded only when a judge genuinely needs it
  (pure-local / explicit-key / local-proxy judges reach dispatch without it);
- a resumed run seeds its cumulative budget from the *charged* total (including
  fail-closed failure reservations), never re-charging or re-dispatching them.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from nohiki_llm_client import ApiKeyRegistry
from typer.testing import CliRunner

from llm_benchmark.cli import app
from llm_benchmark.cli.commands.evaluate import (
    _build_resume_states,
    _derive_eval_output,
    _evaluate_async_with_progress,
    _resolve_judges,
    _save_evaluation_results,
)
from llm_benchmark.config.constants import DEFAULT_EVAL_CONCURRENCY
from llm_benchmark.config.models import JudgeConfig
from llm_benchmark.engine.budget import BudgetScheduler as _RealBudgetScheduler
from llm_benchmark.engine.checkpoint import (
    CheckpointManager,
    compute_eval_config_fingerprint,
)
from llm_benchmark.schemas.aggregation import (
    EvaluationResult,
    MultiJudgeEvaluationSummary,
    compute_multi_judge_summary,
)
from llm_benchmark.schemas.judge import CategoryScore, PointwiseJudgment
from llm_benchmark.schemas.metrics import BenchmarkResult as _BenchmarkResult
from llm_benchmark.schemas.metrics import ModelResult
from llm_benchmark.schemas.metrics import RunResult as _RunResult

_JUDGE = "openrouter:test-judge"


class RunResult(_RunResult):
    """Run result with synthetic fingerprints so fixtures stay terse."""

    retry_count: int | None = 0

    treatment_fingerprint: str = "test-treatment"
    cell_fingerprint: str = "test-cell"


class BenchmarkResult(_BenchmarkResult):
    """Benchmark result with a synthetic experiment fingerprint."""

    experiment_fingerprint: str = "test-experiment"


def _make_judgment(score: int = 80) -> PointwiseJudgment:
    cat = CategoryScore(score=score, reasoning="Solid extraction quality across all fields")
    return PointwiseJudgment(
        inference_reasonableness=cat,
        description_quality=cat,
        downstream_usefulness=cat,
        summary="Good residual quality with minor issues in edge cases",
    )


def _summary() -> MultiJudgeEvaluationSummary:
    return compute_multi_judge_summary({_JUDGE: EvaluationResult(judgments_by_model={})})


def _saved_benchmark(tmp_path: Path) -> Path:
    """Persist a minimal benchmark with one successful, judge-eligible run."""
    benchmark = BenchmarkResult(
        fixtures_used=["senior_python_remote"],
        runs_per_fixture=1,
        models={
            "openrouter:test/model": ModelResult(
                model="openrouter:test/model",
                total_cost_usd=0.01,
                runs=[
                    RunResult(
                        fixture_id="senior_python_remote",
                        run_number=1,
                        success=True,
                        latency_ms=100.0,
                        input_tokens=100,
                        output_tokens=50,
                        output_json={"cleaned_title": "Test Job"},
                    ),
                ],
            ),
        },
    )
    out = tmp_path / "benchmark_test.json"
    benchmark.save(out)
    return out


class TestDeriveEvalOutput:
    """The evaluation artifact is a distinct sibling; it never overwrites the source."""

    def test_derives_sibling_eval_json(self, tmp_path: Path) -> None:
        result_file = tmp_path / "run.json"
        assert _derive_eval_output(result_file) == tmp_path / "run.eval.json"

    def test_symlinked_collision_is_refused(self, tmp_path: Path) -> None:
        # A crafted layout where the derived path resolves back onto the source
        # must be refused rather than silently clobbering the benchmark result.
        source = tmp_path / "a.json"
        source.write_text("{}")
        (tmp_path / "a.eval.json").symlink_to(source)
        with pytest.raises(typer.Exit) as exc:
            _derive_eval_output(source)
        assert exc.value.exit_code == 1

    def test_save_leaves_source_untouched_and_writes_distinct_file(self, tmp_path: Path) -> None:
        result_file = _saved_benchmark(tmp_path)
        original_bytes = result_file.read_bytes()

        _save_evaluation_results(_summary(), result_file)

        eval_output = tmp_path / "benchmark_test.eval.json"
        assert eval_output.exists()
        assert eval_output != result_file
        assert result_file.read_bytes() == original_bytes


class TestConditionalKeyLoading:
    """Mandatory registry loading happens only when a judge genuinely needs a key.

    Keyless-capable judges (local proxy, pure-local) never trigger the mandatory
    loader; they consult the optional probe, which stays keyless when no canonical
    registry is available.
    """

    def test_local_proxy_judge_skips_mandatory_registry(self) -> None:
        load_spy = MagicMock(side_effect=AssertionError("mandatory registry must not be loaded"))
        with (
            patch("llm_benchmark.cli.commands.evaluate.load_api_keys", load_spy),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys_optional",
                return_value=ApiKeyRegistry(),
            ),
        ):
            judges, api_keys = _resolve_judges(
                ["openai:gpt-5.2"],
                None,
                None,
                None,
                base_url="https://openai.example.com/v1",
                api_key=None,
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )
        load_spy.assert_not_called()
        assert [j.model for j in judges] == ["openai:gpt-5.2"]
        assert not api_keys.model_extra

    def test_pure_local_judge_skips_mandatory_registry(self) -> None:
        load_spy = MagicMock(side_effect=AssertionError("mandatory registry must not be loaded"))
        with (
            patch("llm_benchmark.cli.commands.evaluate.load_api_keys", load_spy),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys_optional",
                return_value=ApiKeyRegistry(),
            ),
        ):
            _judges, api_keys = _resolve_judges(
                ["ollama:qwen3:30b"],
                None,
                None,
                None,
                base_url=None,
                api_key=None,
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )
        load_spy.assert_not_called()
        assert not api_keys.model_extra

    def test_canonical_cloud_judge_requires_registry(self) -> None:
        registry = ApiKeyRegistry.model_validate({"openai": "credential-value"})
        load_spy = MagicMock(return_value=registry)
        with patch("llm_benchmark.cli.commands.evaluate.load_api_keys", load_spy):
            _judges, api_keys = _resolve_judges(
                ["openai:gpt-5.2"],
                None,
                None,
                None,
                base_url=None,
                api_key=None,
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )
        load_spy.assert_called_once()
        assert api_keys is registry

    def test_local_proxy_judge_reaches_dispatch_without_registry(self, tmp_path: Path) -> None:
        benchmark = _saved_benchmark(tmp_path)
        mock_eval = AsyncMock(return_value=(_summary(), False))
        load_spy = MagicMock(side_effect=AssertionError("secret registry must not be loaded"))
        with (
            patch(
                "llm_benchmark.cli.commands.evaluate._evaluate_async_with_progress",
                mock_eval,
            ),
            patch("llm_benchmark.cli.commands.evaluate.load_api_keys", load_spy),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys_optional",
                return_value=ApiKeyRegistry(),
            ),
        ):
            result = CliRunner().invoke(
                app,
                [
                    "evaluate",
                    str(benchmark),
                    "--judge-model",
                    "openai:gpt-5.2",
                    "--base-url",
                    "https://openai.example.com/v1",
                    "--unknown-price-max",
                    "0.01",
                ],
            )
        assert result.exit_code == 0, result.output
        load_spy.assert_not_called()
        assert mock_eval.await_args is not None

    def test_canonical_cloud_judge_loads_registry_end_to_end(self, tmp_path: Path) -> None:
        benchmark = _saved_benchmark(tmp_path)
        registry = ApiKeyRegistry.model_validate({"openai": "credential-value"})
        mock_eval = AsyncMock(return_value=(_summary(), False))
        load_spy = MagicMock(return_value=registry)
        with (
            patch(
                "llm_benchmark.cli.commands.evaluate._evaluate_async_with_progress",
                mock_eval,
            ),
            patch("llm_benchmark.cli.commands.evaluate.load_api_keys", load_spy),
        ):
            result = CliRunner().invoke(
                app,
                [
                    "evaluate",
                    str(benchmark),
                    "--judge-model",
                    "openai:gpt-5.2",
                    "--unknown-price-max",
                    "0.01",
                ],
            )
        assert result.exit_code == 0, result.output
        load_spy.assert_called_once()


class TestResumeChargedSeed:
    """A resumed run carries the charged total (incl. failures) into its cumulative budget."""

    def _seed_checkpoint(self, tmp_path: Path) -> tuple[Path, CheckpointManager]:
        result_file = tmp_path / "benchmark.json"
        result_file.write_text("{}")
        manager = CheckpointManager(result_file, "resume-fp")
        manager.record_judgment(_JUDGE, "high", "cand", "f1", 1, _make_judgment(), 0.01)
        manager.record_failure(_JUDGE, "high", "cand", "f2", 1, charged_cost_usd=0.04)
        return result_file, manager

    def test_build_resume_states_reports_charged_and_skips_failure(self, tmp_path: Path) -> None:
        _result_file, manager = self._seed_checkpoint(tmp_path)
        judge = JudgeConfig(model=_JUDGE)

        states, completed, cost, charged = _build_resume_states([judge], manager)

        assert completed == 2
        assert cost == pytest.approx(0.01)
        assert charged == pytest.approx(0.05)
        assert states is not None
        state = states[_JUDGE]
        assert state.existing_charged_usd == pytest.approx(0.05)
        # The failed attempt is treated as completed, so resume never re-dispatches it.
        assert {"cand::f1::1", "cand::f2::1"} <= set(state.skip_task_keys)

    @pytest.mark.asyncio
    async def test_scheduler_seeded_from_charged_total_including_failures(self, tmp_path: Path) -> None:
        _result_file, manager = self._seed_checkpoint(tmp_path)
        judge = JudgeConfig(model=_JUDGE)
        benchmark = BenchmarkResult(fixtures_used=["f1"], runs_per_fixture=1, models={})

        captured: dict[str, float] = {}

        def _spy(
            *,
            cap_usd: float,
            max_concurrency: int,
            initial_charged_usd: float = 0.0,
            initial_actual_usd: float = 0.0,
        ) -> _RealBudgetScheduler:
            captured.update(
                initial_charged_usd=initial_charged_usd,
                initial_actual_usd=initial_actual_usd,
            )
            return _RealBudgetScheduler(
                cap_usd=cap_usd,
                max_concurrency=max_concurrency,
                initial_charged_usd=initial_charged_usd,
                initial_actual_usd=initial_actual_usd,
            )

        with (
            patch("llm_benchmark.cli.commands.evaluate.BudgetScheduler", side_effect=_spy),
            patch(
                "llm_benchmark.cli.commands.evaluate.evaluate_multi_judge",
                new_callable=AsyncMock,
                return_value=_summary(),
            ),
        ):
            await _evaluate_async_with_progress(
                benchmark,
                ApiKeyRegistry(),
                [judge],
                checkpoint_manager=manager,
                cost_cap_usd=1.0,
                max_concurrency=1,
            )

        # Cumulative cap seeds from the CHARGED total (0.01 actual + 0.04 fail-closed),
        # while realized actual spend (0.01) seeds only the reported total.
        assert captured["initial_charged_usd"] == pytest.approx(0.05)
        assert captured["initial_actual_usd"] == pytest.approx(0.01)


class TestCustomOpenAiEndpointKeyLoading:
    """Test optional key loading for a custom ``openai:`` endpoint.

    An explicit ``--base-url`` adopts a present canonical registry key without
    mandating one, so a genuinely keyless local proxy still dispatches when no
    registry is available.
    """

    _PROXY = "https://provider.example.test/v1"

    def test_present_optional_registry_populates_custom_openai_judge(self) -> None:
        # An available canonical registry supplies the OpenAI key for a custom
        # base_url judge; the mandatory loader must never run for this case.
        optional = ApiKeyRegistry.model_validate({"openai": "credential-value"})
        mandatory = MagicMock(side_effect=AssertionError("mandatory registry load must not run"))
        with (
            patch("llm_benchmark.cli.commands.evaluate.load_api_keys", mandatory),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys_optional",
                return_value=optional,
            ) as opt,
        ):
            judges, api_keys = _resolve_judges(
                ["openai:gpt-5.2"],
                None,
                None,
                None,
                base_url=self._PROXY,
                api_key=None,
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )
        mandatory.assert_not_called()
        opt.assert_called_once()
        # Pre-fix behavior returned an empty registry here; the canonical key now flows through.
        assert api_keys is optional
        key = api_keys.get("openai")
        assert key is not None
        assert key.get_secret_value() == "credential-value"
        # The judge itself stays keyless-by-config: no explicit key, base_url override intact.
        assert judges[0].api_key is None
        assert judges[0].base_url == self._PROXY
        assert judges[0].requires_registry_key is False

    def test_absent_optional_registry_stays_keyless(self) -> None:
        # No canonical registry: dispatch continues keyless without error.
        empty = ApiKeyRegistry()
        mandatory = MagicMock(side_effect=AssertionError("mandatory registry load must not run"))
        with (
            patch("llm_benchmark.cli.commands.evaluate.load_api_keys", mandatory),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys_optional",
                return_value=empty,
            ),
        ):
            judges, api_keys = _resolve_judges(
                ["openai:gpt-5.2"],
                None,
                None,
                None,
                base_url="https://openai.example.com/v1",
                api_key=None,
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )
        mandatory.assert_not_called()
        assert not api_keys.model_extra
        assert [j.model for j in judges] == ["openai:gpt-5.2"]

    def test_absent_registry_directory_does_not_error(self, tmp_path: Path) -> None:
        # Exercise the real optional loader against a missing secret directory
        # (path mocked, no real files): a keyless-capable judge must not raise.
        missing = tmp_path / "no-such-secrets"
        with patch("llm_benchmark.cli._helpers.get_api_keys_dir", return_value=missing):
            judges, api_keys = _resolve_judges(
                ["openai:gpt-5.2"],
                None,
                None,
                None,
                base_url="https://openai.example.com/v1",
                api_key=None,
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )
        assert not api_keys.model_extra
        assert judges[0].base_url == "https://openai.example.com/v1"

    def test_explicit_api_key_takes_precedence_over_registry(self) -> None:
        # An explicit per-call key is carried on the judge and overrides the
        # registry at dispatch (LLMModelConfig.api_key wins over the lookup).
        optional = ApiKeyRegistry.model_validate({"openai": "credential-value"})
        mandatory = MagicMock(side_effect=AssertionError("mandatory registry load must not run"))
        with (
            patch("llm_benchmark.cli.commands.evaluate.load_api_keys", mandatory),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys_optional",
                return_value=optional,
            ),
        ):
            judges, _api_keys = _resolve_judges(
                ["openai:gpt-5.2"],
                None,
                None,
                None,
                base_url=self._PROXY,
                api_key="credential-value",
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )
        mandatory.assert_not_called()
        assert judges[0].api_key == "credential-value"
        model_config = judges[0].to_model_config()
        assert model_config.api_key is not None
        assert model_config.api_key.get_secret_value() == "credential-value"

    def test_canonical_cloud_judge_errors_when_registry_absent(self, tmp_path: Path) -> None:
        # A canonical cloud judge (no base_url, no explicit key) still requires a
        # registry and fails before dispatch when none is available.
        missing = tmp_path / "no-such-secrets"
        with (  # noqa: SIM117
            patch("llm_benchmark.cli._helpers.get_api_keys_dir", return_value=missing),
        ):
            with pytest.raises(typer.Exit) as exc_info:
                _resolve_judges(
                    ["openai:gpt-5.2"],
                    None,
                    None,
                    None,
                    base_url=None,
                    api_key=None,
                    concurrency=DEFAULT_EVAL_CONCURRENCY,
                )
        assert exc_info.value.exit_code == 1

    def test_registry_secret_absent_from_identity_and_serialization(self) -> None:
        # The adopted registry key never leaks into dispatch identity, the config
        # fingerprint, or the registry's own string/repr forms.
        optional = ApiKeyRegistry.model_validate({"openai": "credential-value"})
        with (
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys",
                MagicMock(side_effect=AssertionError),
            ),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys_optional",
                return_value=optional,
            ),
        ):
            judges, api_keys = _resolve_judges(
                ["openai:gpt-5.2"],
                None,
                None,
                None,
                base_url=self._PROXY,
                api_key=None,
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )
        assert "credential-value" not in judges[0].identity_key
        assert "credential-value" not in repr(api_keys)
        assert "credential-value" not in str(api_keys)
        fingerprint = compute_eval_config_fingerprint(
            benchmark_timestamp="2026-07-12T00:00:00Z",
            max_runs_per_fixture=1,
            min_pass_rate=0.0,
            fixtures=["fixture-a"],
            judge_models=[j.model for j in judges],
        )
        # Fingerprint is derived from judge config identity only, never the registry.
        assert "credential-value" not in fingerprint
