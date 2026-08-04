"""Tests for the CLI commands using Typer's CliRunner."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import typer
from nohiki_llm_client import ApiKeyRegistry, LLMModelConfig, LLMProviderSettings
from typer.testing import CliRunner

from llm_benchmark import fixtures as benchmark_fixtures
from llm_benchmark.cli import app, main
from llm_benchmark.cli._helpers import load_api_keys, save_timestamped_snapshot
from llm_benchmark.cli.commands.evaluate import (
    _evaluate_async_with_progress,
    _save_evaluation_results,
)
from llm_benchmark.cli.commands.run import (
    _apply_stale_fixture_filter,
    _load_llm_treatments,
    _load_raw_result,
    _resolve_existing_result,
    _run_benchmark_async,
)
from llm_benchmark.config.models import BenchmarkConfig as _BenchmarkConfig
from llm_benchmark.config.models import JudgeConfig
from llm_benchmark.engine.runner import treatment_ids
from llm_benchmark.fixtures import compute_fixture_checksum
from llm_benchmark.schemas.aggregation import (
    EvaluationResult,
    MultiJudgeEvaluationSummary,
    compute_multi_judge_summary,
)
from llm_benchmark.schemas.metrics import BenchmarkResult as _BenchmarkResult
from llm_benchmark.schemas.metrics import ModelResult
from llm_benchmark.schemas.metrics import RunResult as _RunResult


class BenchmarkConfig(_BenchmarkConfig):
    def __init__(
        self,
        *,
        models: Sequence[str | LLMModelConfig],
        fixture_ids: list[str],
        runs_per_fixture: int,
        api_keys: ApiKeyRegistry,
    ) -> None:
        resolved_models = tuple(
            model if isinstance(model, LLMModelConfig) else LLMModelConfig(model=model) for model in models
        )
        super().__init__(
            models=resolved_models,
            fixture_ids=fixture_ids,
            runs_per_fixture=runs_per_fixture,
            api_keys=api_keys,
            max_tokens=2_048,
            unknown_price_max_usd=0.1,
        )


class RunResult(_RunResult):
    retry_count: int | None = 0
    treatment_fingerprint: str = "test-treatment"
    cell_fingerprint: str = "test-cell"


class BenchmarkResult(_BenchmarkResult):
    experiment_fingerprint: str = "test-experiment"


@pytest.fixture
def cli_runner() -> CliRunner:
    """Return a Typer test CliRunner."""
    return CliRunner()


@pytest.fixture
def _canonical_cloud_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep cloud CLI tests independent of workstation secret files."""
    registry = ApiKeyRegistry.model_validate({"openrouter": "synthetic-key"})
    monkeypatch.setattr("llm_benchmark.cli.commands.run.load_api_keys", lambda: registry)


@pytest.fixture
def minimal_benchmark() -> BenchmarkResult:
    """Return a minimal BenchmarkResult with one successful run."""
    return BenchmarkResult(
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


@pytest.fixture
def saved_benchmark(tmp_path: Path, minimal_benchmark: BenchmarkResult) -> Path:
    """Save a minimal benchmark to a temp file and return its path."""
    out = tmp_path / "benchmark_test.json"
    minimal_benchmark.save(out)
    return out


@pytest.fixture
def multi_judge_summary() -> MultiJudgeEvaluationSummary:
    """Return a minimal MultiJudgeEvaluationSummary."""
    result = EvaluationResult(judgments_by_model={})
    return compute_multi_judge_summary({"test-judge": result})


class TestLoadApiKeys:
    """Tests for _load_api_keys helper."""

    def test_loads_keys_from_dir(self, tmp_path: Path) -> None:
        (tmp_path / "openrouter").write_text("credential-value")
        with patch("llm_benchmark.cli._helpers.get_api_keys_dir", return_value=tmp_path):
            registry = load_api_keys()
        key = registry.get("openrouter")
        assert key is not None
        assert key.get_secret_value() == "credential-value"

    def test_strips_whitespace_from_keys(self, tmp_path: Path) -> None:
        (tmp_path / "openrouter").write_text("  credential-value  \n")
        with patch("llm_benchmark.cli._helpers.get_api_keys_dir", return_value=tmp_path):
            registry = load_api_keys()
        key = registry.get("openrouter")
        assert key is not None
        assert key.get_secret_value() == "credential-value"

    def test_loads_multiple_providers(self, tmp_path: Path) -> None:
        (tmp_path / "openrouter").write_text("or-key")
        (tmp_path / "openai").write_text("oa-key")
        with patch("llm_benchmark.cli._helpers.get_api_keys_dir", return_value=tmp_path):
            registry = load_api_keys()
        assert registry.get("openrouter") is not None
        assert registry.get("openai") is not None

    def test_missing_directory_exits(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        missing_dir = tmp_path / "no_keys_here"
        with patch("llm_benchmark.cli._helpers.get_api_keys_dir", return_value=missing_dir):
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "--output",
                    str(tmp_path / "benchmark.json"),
                    "--model",
                    "openrouter:synthetic/candidate",
                    "--yes",
                    "--fixture",
                    "senior_python_remote",
                ],
            )
        assert result.exit_code == 1

    def test_empty_directory_exits(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty_keys"
        empty_dir.mkdir()
        with patch("llm_benchmark.cli._helpers.get_api_keys_dir", return_value=empty_dir):
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "--output",
                    str(tmp_path / "benchmark.json"),
                    "--model",
                    "openrouter:synthetic/candidate",
                    "--yes",
                    "--fixture",
                    "senior_python_remote",
                ],
            )
        assert result.exit_code == 1


class TestStandardLLMSettingsTreatments:
    """Tests loading independent treatments from a standard named chain."""

    def test_named_chain_preserves_per_model_endpoint_and_routing(self, tmp_path: Path) -> None:
        path = tmp_path / "llm-settings.json"
        path.write_text(
            json.dumps(
                {
                    "provider": {"models": [{"model": "openrouter:synthetic/default"}]},
                    "chains": {
                        "benchmark": {
                            "models": [
                                {
                                    "model": "openrouter:synthetic/a",
                                    "provider_order": ["route-a"],
                                    "provider_allow_fallbacks": False,
                                },
                                {
                                    "model": "openai:synthetic-b",
                                    "base_url": "https://gateway-b.example.test/v1",
                                },
                            ]
                        }
                    },
                }
            )
        )
        registry = ApiKeyRegistry.model_validate({"openrouter": "synthetic-or-key", "openai": "synthetic-oa-key"})

        treatments, chain = _load_llm_treatments(path, "benchmark", registry)

        assert isinstance(chain, LLMProviderSettings)
        assert treatments == tuple(chain.models)
        assert treatments[0].provider_order == ("route-a",)
        assert treatments[0].provider_allow_fallbacks is False
        assert treatments[0].base_url is None
        assert treatments[1].base_url == "https://gateway-b.example.test/v1"
        assert treatments[1].provider_order == ()

    @pytest.mark.parametrize(
        "credential_payload",
        [
            {"api_keys": {"openrouter": "embedded-secret"}},
            {"models": [{"model": "openrouter:synthetic/a", "api_key": "embedded-secret"}]},
        ],
    )
    def test_rejects_credentials_embedded_anywhere(self, tmp_path: Path, credential_payload: dict[str, object]) -> None:
        path = tmp_path / "llm-settings.json"
        path.write_text(
            json.dumps(
                {
                    "provider": {"models": [{"model": "openrouter:synthetic/default"}]},
                    "chains": {"benchmark": credential_payload},
                }
            )
        )

        with pytest.raises(typer.BadParameter, match="must not contain API keys"):
            _load_llm_treatments(
                path,
                "benchmark",
                ApiKeyRegistry.model_validate({"openrouter": "registry-key"}),
            )


class TestExplicitArtifactRequirements:
    def test_run_requires_explicit_output_path(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(app, ["run", "--model", "openrouter:synthetic/candidate", "--estimate-only"])
        assert result.exit_code != 0
        assert "output" in result.output.casefold()

    def test_evaluate_requires_explicit_result_file(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(app, ["evaluate", "--judge-model", "openrouter:synthetic/judge"])
        assert result.exit_code != 0
        assert "result_file" in result.output.casefold() or "result file" in result.output.casefold()


class TestFixturesCommand:
    """Tests for the 'fixtures' CLI command."""

    def test_lists_fixture_ids(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(app, ["fixtures"])
        assert result.exit_code == 0
        assert "senior_python_remote" in result.output
        assert "nurse_icu_onsite" in result.output


@pytest.mark.usefixtures("_canonical_cloud_registry")
class TestRunCommandEstimateOnly:
    """Tests for the 'run --estimate-only' path (no actual LLM calls)."""

    def test_exits_zero_with_estimate_only(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--output",
                str(tmp_path / "benchmark.json"),
                "--estimate-only",
                "--fixture",
                "senior_python_remote",
                "--model",
                "openrouter:google/gemini-3-flash-preview",
            ],
        )
        assert result.exit_code == 0
        assert "Cost Estimate" in result.output

    def test_requires_explicit_model_selection(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        with patch("llm_benchmark.cli.commands.run._run_benchmark_async") as mock_run:
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "--output",
                    str(tmp_path / "benchmark.json"),
                    "--estimate-only",
                    "--fixture",
                    "senior_python_remote",
                ],
            )

        assert result.exit_code == 2
        assert "At least one --model" in result.output
        assert b"\x1b" not in result.output_bytes
        mock_run.assert_not_called()

    def test_run_cancelled_when_user_says_no(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--output",
                str(tmp_path / "benchmark.json"),
                "--fixture",
                "senior_python_remote",
                "--model",
                "openrouter:google/gemini-3-flash-preview",
            ],
            input="n\n",
        )
        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()


class TestSaveTimestampedSnapshot:
    """Tests for _save_timestamped_snapshot helper."""

    def test_creates_timestamped_file(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        output_path = tmp_path / "benchmark.json"
        snapshot = save_timestamped_snapshot(minimal_benchmark, output_path)
        assert snapshot.exists()
        assert snapshot.name.startswith("benchmark_")
        assert snapshot.suffix == ".json"

    def test_snapshot_name_format(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        output_path = tmp_path / "benchmark.json"
        snapshot = save_timestamped_snapshot(minimal_benchmark, output_path)
        stem = snapshot.stem  # e.g. benchmark_20260220_161200
        parts = stem.split("_")
        assert len(parts) == 3  # benchmark, YYYYMMDD, HHMMSS
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 6  # HHMMSS

    def test_snapshot_content_matches_result(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        output_path = tmp_path / "benchmark.json"
        snapshot = save_timestamped_snapshot(minimal_benchmark, output_path)
        loaded = BenchmarkResult.load(snapshot)
        assert set(loaded.models) == set(minimal_benchmark.models)

    def test_does_not_affect_canonical_output_path(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        output_path = tmp_path / "benchmark.json"
        assert not output_path.exists()
        save_timestamped_snapshot(minimal_benchmark, output_path)
        assert not output_path.exists()

    def test_prunes_oldest_when_over_keep_last(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        output_path = tmp_path / "benchmark.json"
        for i in range(5):
            ts = f"2026010{i + 1}_120000"
            (tmp_path / f"benchmark_{ts}.json").write_text("{}")
        save_timestamped_snapshot(minimal_benchmark, output_path, keep_last=3)
        remaining = sorted(tmp_path.glob("benchmark_*.json"))
        assert len(remaining) == 3

    def test_keep_last_one_retains_only_newest(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        output_path = tmp_path / "benchmark.json"
        save_timestamped_snapshot(minimal_benchmark, output_path, keep_last=1)
        snapshots = list(tmp_path.glob("benchmark_*.json"))
        assert len(snapshots) == 1

    def test_fallback_timestamp_when_invalid(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        bad_ts_result = minimal_benchmark.model_copy(update={"timestamp": "not-a-timestamp"})
        output_path = tmp_path / "benchmark.json"
        snapshot = save_timestamped_snapshot(bad_ts_result, output_path)
        assert snapshot.exists()

    def test_custom_stem_preserved(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        output_path = tmp_path / "my_run.json"
        snapshot = save_timestamped_snapshot(minimal_benchmark, output_path)
        assert snapshot.name.startswith("my_run_")


class TestRunCommandFull:
    """Tests for the full 'run' command path with mocked runner."""

    def test_run_saves_result_file(
        self,
        cli_runner: CliRunner,
        minimal_benchmark: BenchmarkResult,
        tmp_path: Path,
    ) -> None:
        output_path = tmp_path / "out.json"
        with (
            patch(
                "llm_benchmark.cli.commands.run._run_benchmark_async",
                new_callable=AsyncMock,
                return_value=minimal_benchmark,
            ),
            patch(
                "llm_benchmark.cli.commands.run.load_api_keys",
                return_value=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
            ),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "--yes",
                    "--fixture",
                    "senior_python_remote",
                    "--model",
                    "openrouter:google/gemini-3-flash-preview",
                    "--output",
                    str(output_path),
                ],
            )
        assert result.exit_code == 0
        assert output_path.exists()

    def test_run_saves_timestamped_snapshot(
        self,
        cli_runner: CliRunner,
        minimal_benchmark: BenchmarkResult,
        tmp_path: Path,
    ) -> None:
        output_path = tmp_path / "out.json"
        with (
            patch(
                "llm_benchmark.cli.commands.run._run_benchmark_async",
                new_callable=AsyncMock,
                return_value=minimal_benchmark,
            ),
            patch(
                "llm_benchmark.cli.commands.run.load_api_keys",
                return_value=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
            ),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "--yes",
                    "--fixture",
                    "senior_python_remote",
                    "--model",
                    "openrouter:google/gemini-3-flash-preview",
                    "--output",
                    str(output_path),
                ],
            )
        assert result.exit_code == 0
        snapshots = list(tmp_path.glob("out_*.json"))
        assert len(snapshots) == 1, "Expected exactly one timestamped snapshot"
        assert "Snapshot:" in result.output


class TestResultsCommand:
    """Tests for the 'results' display command."""

    def test_displays_benchmark_from_file(
        self,
        cli_runner: CliRunner,
        saved_benchmark: Path,
    ) -> None:
        result = cli_runner.invoke(app, ["results", str(saved_benchmark)])
        assert result.exit_code == 0
        assert "Benchmark Execution Summary" in result.output

    def test_exits_when_file_not_found(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        missing = tmp_path / "missing.json"
        result = cli_runner.invoke(app, ["results", str(missing)])
        assert result.exit_code == 1


class TestEvaluateCommand:
    """Tests for the 'evaluate' command."""

    def test_exits_when_result_file_missing(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        missing = tmp_path / "missing.json"
        result = cli_runner.invoke(app, ["evaluate", str(missing)])
        assert result.exit_code == 1

    def test_exits_when_no_successful_outputs(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        empty_result = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=1,
            models={
                "openrouter:test/model": ModelResult(
                    model="openrouter:test/model",
                    total_cost_usd=0.0,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=False,
                            latency_ms=100.0,
                            error_message="timed out",
                        ),
                    ],
                ),
            },
        )
        out_path = tmp_path / "empty.json"
        empty_result.save(out_path)
        result = cli_runner.invoke(app, ["evaluate", str(out_path)])
        assert result.exit_code == 1
        assert "No successful extraction outputs" in result.output

    def test_requires_explicit_judge_selection(
        self,
        cli_runner: CliRunner,
        saved_benchmark: Path,
    ) -> None:
        result = cli_runner.invoke(app, ["evaluate", str(saved_benchmark)])

        assert result.exit_code == 1
        assert "At least one --judge-model is required" in result.output

    def test_evaluate_saves_eval_json(
        self,
        cli_runner: CliRunner,
        saved_benchmark: Path,
        multi_judge_summary: MultiJudgeEvaluationSummary,
    ) -> None:
        with (
            patch(
                "llm_benchmark.cli.commands.evaluate.evaluate_multi_judge",
                new_callable=AsyncMock,
                return_value=multi_judge_summary,
            ),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys",
                return_value=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
            ),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "evaluate",
                    str(saved_benchmark),
                    "--judge-model",
                    "openrouter:synthetic/judge",
                    "--unknown-price-max",
                    "0.01",
                ],
            )
        assert result.exit_code == 0
        eval_file = saved_benchmark.with_suffix(".eval.json")
        assert eval_file.exists()
        loaded = json.loads(eval_file.read_text())
        assert "per_judge" in loaded
        assert "consensus" in loaded


class TestRunBenchmarkAsync:
    """Tests for the _run_benchmark_async helper covering Progress display."""

    @pytest.mark.asyncio
    async def test_calls_runner_and_returns_result(self, minimal_benchmark: BenchmarkResult, tmp_path: Path) -> None:
        config = BenchmarkConfig(
            models=["openrouter:google/gemini-3-flash-preview"],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        out = tmp_path / "benchmark.json"
        with patch("llm_benchmark.cli.commands.run.BenchmarkRunner") as mock_runner_cls:
            mock_runner_cls.return_value.run = AsyncMock(return_value=minimal_benchmark)
            result = await _run_benchmark_async(config, out)
        assert result.models == minimal_benchmark.models
        assert result.fixtures_used == minimal_benchmark.fixtures_used

    @pytest.mark.asyncio
    async def test_progress_callback_updates_count(self, minimal_benchmark: BenchmarkResult, tmp_path: Path) -> None:
        config = BenchmarkConfig(
            models=["openrouter:google/gemini-3-flash-preview"],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        out = tmp_path / "benchmark.json"
        dummy_run = RunResult(
            fixture_id="senior_python_remote",
            treatment_fingerprint="test-treatment",
            cell_fingerprint="test-cell",
            run_number=1,
            success=True,
            latency_ms=100.0,
        )

        def run_with_callback(
            progress_callback: Callable[..., None] | None = None,
            **_kwargs: object,
        ) -> BenchmarkResult:
            if progress_callback is not None:
                progress_callback(
                    treatment_ids(config)[0],
                    "senior_python_remote",
                    1,
                    run_result=dummy_run,
                )
            return minimal_benchmark

        with patch("llm_benchmark.cli.commands.run.BenchmarkRunner") as mock_runner_cls:
            mock_runner_cls.return_value.run = AsyncMock(side_effect=run_with_callback)
            result = await _run_benchmark_async(config, out)
        assert result.models == minimal_benchmark.models
        assert result.fixtures_used == minimal_benchmark.fixtures_used

    @pytest.mark.asyncio
    async def test_returns_result_with_current_checksums(
        self, minimal_benchmark: BenchmarkResult, tmp_path: Path
    ) -> None:
        config = BenchmarkConfig(
            models=["openrouter:google/gemini-3-flash-preview"],
            fixture_ids=["senior_python_remote"],
            runs_per_fixture=1,
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        out = tmp_path / "benchmark.json"
        checksum = compute_fixture_checksum("senior_python_remote")
        with patch("llm_benchmark.cli.commands.run.BenchmarkRunner") as mock_runner_cls:
            mock_runner_cls.return_value.run = AsyncMock(return_value=minimal_benchmark)
            result = await _run_benchmark_async(
                config,
                out,
                current_checksums={"senior_python_remote": checksum},
            )
        assert result.fixture_checksums == {"senior_python_remote": checksum}


class TestEvaluateAsyncWithProgress:
    """Tests for _evaluate_async_with_progress covering the progress callback."""

    @pytest.mark.asyncio
    async def test_fires_progress_callback(
        self,
        minimal_benchmark: BenchmarkResult,
        multi_judge_summary: MultiJudgeEvaluationSummary,
    ) -> None:
        judges = [JudgeConfig(model="openrouter:test-judge")]

        def call_with_callback(
            *_args: object,
            progress_callback: Callable[..., None] | None = None,
            **_kwargs: object,
        ) -> object:
            if progress_callback is not None:
                progress_callback("openrouter:test-judge", "senior_python_remote", 1, 1, 0.001)
            return multi_judge_summary

        with patch(
            "llm_benchmark.cli.commands.evaluate.evaluate_multi_judge",
            new_callable=AsyncMock,
            side_effect=call_with_callback,
        ):
            result = await _evaluate_async_with_progress(
                minimal_benchmark,
                ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
                judges,
                cost_cap_usd=1.0,
            )
        summary, cost_cap_hit = result
        assert summary == multi_judge_summary
        assert cost_cap_hit is False


class TestComputeFixtureChecksum:
    """Tests for _compute_fixture_checksum helper."""

    def test_returns_hex_sha256(self) -> None:
        checksum = compute_fixture_checksum("senior_python_remote")
        assert len(checksum) == 64
        assert all(c in "0123456789abcdef" for c in checksum)

    def test_same_fixture_same_checksum(self) -> None:
        assert compute_fixture_checksum("senior_python_remote") == compute_fixture_checksum("senior_python_remote")

    def test_different_fixtures_different_checksums(self) -> None:
        assert compute_fixture_checksum("senior_python_remote") != compute_fixture_checksum("nurse_icu_onsite")

    def test_changes_when_production_system_prompt_changes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original = compute_fixture_checksum("senior_python_remote")

        changed = replace(
            benchmark_fixtures.DEFAULT_EXTRACTION_SPEC,
            system_prompt="changed production system prompt",
        )
        monkeypatch.setattr(benchmark_fixtures, "DEFAULT_EXTRACTION_SPEC", changed)

        assert compute_fixture_checksum("senior_python_remote") != original

    def test_changes_when_built_user_prompt_changes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original = compute_fixture_checksum("senior_python_remote")
        changed = replace(
            benchmark_fixtures.DEFAULT_EXTRACTION_SPEC,
            limits=replace(benchmark_fixtures.DEFAULT_EXTRACTION_SPEC.limits, description_chars=32),
        )
        monkeypatch.setattr(benchmark_fixtures, "DEFAULT_EXTRACTION_SPEC", changed)

        assert compute_fixture_checksum("senior_python_remote") != original

    def test_changes_when_output_schema_changes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original = compute_fixture_checksum("senior_python_remote")

        class ChangedSchema:
            @staticmethod
            def model_json_schema() -> dict[str, str]:
                return {"title": "ChangedJobExtractionSchema"}

        changed = replace(benchmark_fixtures.DEFAULT_EXTRACTION_SPEC, output_type=ChangedSchema)
        monkeypatch.setattr(benchmark_fixtures, "DEFAULT_EXTRACTION_SPEC", changed)

        assert compute_fixture_checksum("senior_python_remote") != original


class TestResolveExistingResult:
    """Tests for _resolve_existing_result helper."""

    def test_returns_none_when_fresh_no_file(self, tmp_path: Path) -> None:
        path = tmp_path / "benchmark.json"
        result = _resolve_existing_result(path, ["f1"], {"f1": "abc"}, fresh=True)
        assert result is None

    def test_fresh_deletes_existing_file(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        path = tmp_path / "benchmark.json"
        minimal_benchmark.save(path)
        _resolve_existing_result(path, ["senior_python_remote"], {"senior_python_remote": "abc"}, fresh=True)
        assert not path.exists()

    def test_returns_none_when_file_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "benchmark.json"
        result = _resolve_existing_result(path, ["f1"], {"f1": "abc"}, fresh=False)
        assert result is None

    def test_returns_loaded_when_checksums_match(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        checksum = compute_fixture_checksum("senior_python_remote")
        bench = BenchmarkResult(
            fixtures_used=["senior_python_remote"],
            runs_per_fixture=1,
            fixture_checksums={"senior_python_remote": checksum},
            models=minimal_benchmark.models,
        )
        path = tmp_path / "benchmark.json"
        bench.save(path)
        result = _resolve_existing_result(
            path,
            ["senior_python_remote"],
            {"senior_python_remote": checksum},
            fresh=False,
        )
        assert result is not None
        assert "openrouter:test/model" in result.models

    def test_new_fixture_not_treated_as_stale(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        """A fixture that has never been run before must not trigger stale stripping."""
        checksum = compute_fixture_checksum("senior_python_remote")
        bench = BenchmarkResult(
            fixtures_used=["senior_python_remote"],
            runs_per_fixture=1,
            fixture_checksums={"senior_python_remote": checksum},
            models=minimal_benchmark.models,
        )
        path = tmp_path / "benchmark.json"
        bench.save(path)
        new_checksum = compute_fixture_checksum("nurse_icu_onsite")
        result = _resolve_existing_result(
            path,
            ["senior_python_remote", "nurse_icu_onsite"],
            {"senior_python_remote": checksum, "nurse_icu_onsite": new_checksum},
            fresh=False,
        )
        assert result is not None
        assert result.models["openrouter:test/model"].runs

    def test_strips_stale_fixture_runs(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        bench = BenchmarkResult(
            fixtures_used=["senior_python_remote"],
            runs_per_fixture=1,
            fixture_checksums={"senior_python_remote": "old_checksum"},
            models=minimal_benchmark.models,
        )
        path = tmp_path / "benchmark.json"
        bench.save(path)
        result = _resolve_existing_result(
            path,
            ["senior_python_remote"],
            {"senior_python_remote": "new_checksum"},
            fresh=False,
        )
        assert result is not None
        assert result.models["openrouter:test/model"].runs == []

    def test_rejects_corrupt_json(self, tmp_path: Path) -> None:
        path = tmp_path / "benchmark.json"
        path.write_text("{this is not valid json{{")
        with pytest.raises(typer.BadParameter, match="Cannot resume invalid benchmark result"):
            _resolve_existing_result(
                path,
                ["senior_python_remote"],
                {"senior_python_remote": "abc"},
                fresh=False,
            )

    def test_rejects_truncated_json(self, tmp_path: Path) -> None:
        path = tmp_path / "benchmark.json"
        path.write_text('{"timestamp": "2025-01-01T00:00:00+00:00", "fixtures_used": ["f1"')
        with pytest.raises(typer.BadParameter, match="Cannot resume invalid benchmark result"):
            _resolve_existing_result(path, ["f1"], {"f1": "abc"}, fresh=False)

    def test_rejects_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "benchmark.json"
        path.write_text("")
        with pytest.raises(typer.BadParameter, match="Cannot resume invalid benchmark result"):
            _resolve_existing_result(path, ["f1"], {"f1": "abc"}, fresh=False)


class TestLoadRawResult:
    """Tests for _load_raw_result helper."""

    def test_returns_none_when_fresh_no_file(self, tmp_path: Path) -> None:
        path = tmp_path / "benchmark.json"
        assert _load_raw_result(path, fresh=True) is None

    def test_fresh_deletes_existing_file(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        path = tmp_path / "benchmark.json"
        minimal_benchmark.save(path)
        _load_raw_result(path, fresh=True)
        assert not path.exists()

    def test_fresh_deletes_delete_on_fresh_not_load_path(
        self, tmp_path: Path, minimal_benchmark: BenchmarkResult
    ) -> None:
        """When loading from a snapshot, --fresh deletes the canonical file, not the snapshot."""
        snapshot = tmp_path / "benchmark_20260101_000000.json"
        canonical = tmp_path / "benchmark.json"
        minimal_benchmark.save(snapshot)
        canonical.write_text("{}")
        _load_raw_result(snapshot, fresh=True, delete_on_fresh=canonical)
        assert not canonical.exists()
        assert snapshot.exists()

    def test_returns_none_when_file_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "benchmark.json"
        assert _load_raw_result(path, fresh=False) is None

    def test_returns_loaded_result(self, tmp_path: Path, minimal_benchmark: BenchmarkResult) -> None:
        path = tmp_path / "benchmark.json"
        minimal_benchmark.save(path)
        result = _load_raw_result(path, fresh=False)
        assert result is not None
        assert result.model_dump() == minimal_benchmark.model_dump()

    def test_rejects_corrupt_json(self, tmp_path: Path) -> None:
        path = tmp_path / "benchmark.json"
        path.write_text("{invalid")
        with pytest.raises(typer.BadParameter, match="Cannot resume invalid benchmark result"):
            _load_raw_result(path, fresh=False)

    def test_rejects_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "benchmark.json"
        path.write_text("")
        with pytest.raises(typer.BadParameter, match="Cannot resume invalid benchmark result"):
            _load_raw_result(path, fresh=False)


class TestApplyStaleFixtureFilter:
    """Tests for _apply_stale_fixture_filter helper."""

    def test_returns_raw_unchanged_when_no_stale_fixtures(self, minimal_benchmark: BenchmarkResult) -> None:
        checksum = compute_fixture_checksum("senior_python_remote")
        bench = BenchmarkResult(
            fixtures_used=["senior_python_remote"],
            fixture_checksums={"senior_python_remote": checksum},
            models=minimal_benchmark.models,
        )
        result = _apply_stale_fixture_filter(bench, ["senior_python_remote"], {"senior_python_remote": checksum})
        assert result is bench

    def test_strips_runs_for_stale_fixture(self, minimal_benchmark: BenchmarkResult) -> None:
        bench = BenchmarkResult(
            fixtures_used=["senior_python_remote"],
            fixture_checksums={"senior_python_remote": "old_checksum"},
            models=minimal_benchmark.models,
        )
        result = _apply_stale_fixture_filter(bench, ["senior_python_remote"], {"senior_python_remote": "new_checksum"})
        for model_result in result.models.values():
            assert all(r.fixture_id != "senior_python_remote" for r in model_result.runs)

    def test_preserves_runs_for_non_stale_fixture(self, minimal_benchmark: BenchmarkResult) -> None:
        """Runs for fixtures not in selected_fixtures are untouched."""
        bench = BenchmarkResult(
            fixtures_used=["senior_python_remote"],
            fixture_checksums={"senior_python_remote": "old"},
            models=minimal_benchmark.models,
        )
        result = _apply_stale_fixture_filter(bench, ["nurse_icu_onsite"], {"nurse_icu_onsite": "abc"})
        assert result is bench

    def test_new_fixture_not_treated_as_stale(self, minimal_benchmark: BenchmarkResult) -> None:
        """A fixture with no prior checksum entry is not treated as stale."""
        checksum = compute_fixture_checksum("senior_python_remote")
        bench = BenchmarkResult(
            fixtures_used=["senior_python_remote"],
            fixture_checksums={"senior_python_remote": checksum},
            models=minimal_benchmark.models,
        )
        new_checksum = compute_fixture_checksum("nurse_icu_onsite")
        result = _apply_stale_fixture_filter(
            bench,
            ["senior_python_remote", "nurse_icu_onsite"],
            {"senior_python_remote": checksum, "nurse_icu_onsite": new_checksum},
        )
        assert result is bench

    def test_raw_result_is_not_mutated(self, minimal_benchmark: BenchmarkResult) -> None:
        """Stripping stale runs returns a new object; the original raw is unchanged."""
        original_runs = list(minimal_benchmark.models["openrouter:test/model"].runs)
        bench = BenchmarkResult(
            fixtures_used=["senior_python_remote"],
            fixture_checksums={"senior_python_remote": "old"},
            models=minimal_benchmark.models,
        )
        _apply_stale_fixture_filter(bench, ["senior_python_remote"], {"senior_python_remote": "new"})
        assert list(minimal_benchmark.models["openrouter:test/model"].runs) == original_runs


@pytest.mark.usefixtures("_canonical_cloud_registry")
class TestRunCommandFresh:
    """Tests for the --fresh flag in the run command."""

    def test_fresh_flag_accepted(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--output",
                str(tmp_path / "benchmark.json"),
                "--fresh",
                "--estimate-only",
                "--fixture",
                "senior_python_remote",
                "--model",
                "openrouter:synthetic/benchmark-model",
            ],
        )
        assert result.exit_code == 0

    def test_run_with_max_tokens_flag(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--output",
                str(tmp_path / "benchmark.json"),
                "--estimate-only",
                "--fixture",
                "senior_python_remote",
                "--model",
                "openrouter:synthetic/benchmark-model",
                "--max-tokens",
                "8192",
            ],
        )
        assert result.exit_code == 0


class TestMainEntrypoint:
    """Tests for the main() CLI entry point."""

    def test_main_calls_app(self) -> None:
        with patch("llm_benchmark.cli.app") as mock_app:
            main()
        mock_app.assert_called_once()


class TestFilterBenchmarkModels:
    """Tests for BenchmarkResult.filter_for_evaluation method."""

    def test_keeps_models_above_pass_rate(self, minimal_benchmark: BenchmarkResult) -> None:
        filtered, skipped = minimal_benchmark.filter_for_evaluation(
            minimal_benchmark.fixtures_used,
            min_pass_rate=0.5,
        )
        assert len(filtered.models) == 1
        assert skipped == {}

    def test_skips_models_below_pass_rate(self) -> None:
        benchmark = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=2,
            models={
                "openrouter:test/good": ModelResult(
                    model="openrouter:test/good",
                    total_cost_usd=0.01,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=50.0,
                            output_json={"a": 1},
                        ),
                        RunResult(
                            fixture_id="f1",
                            run_number=2,
                            success=True,
                            latency_ms=50.0,
                            output_json={"a": 1},
                        ),
                    ],
                ),
                "openrouter:test/bad": ModelResult(
                    model="openrouter:test/bad",
                    total_cost_usd=0.01,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=False,
                            latency_ms=50.0,
                            error_message="err",
                        ),
                        RunResult(
                            fixture_id="f1",
                            run_number=2,
                            success=False,
                            latency_ms=50.0,
                            error_message="err",
                        ),
                    ],
                ),
            },
        )
        filtered, skipped = benchmark.filter_for_evaluation(["f1"], min_pass_rate=0.5)
        assert "openrouter:test/good" in filtered.models
        assert "openrouter:test/bad" not in filtered.models
        assert "openrouter:test/bad" in skipped
        assert skipped["openrouter:test/bad"] == 0.0

    def test_filters_to_selected_fixtures(self) -> None:
        benchmark = BenchmarkResult(
            fixtures_used=["f1", "f2"],
            runs_per_fixture=1,
            models={
                "openrouter:test/model": ModelResult(
                    model="openrouter:test/model",
                    total_cost_usd=0.02,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=50.0,
                            output_json={"a": 1},
                        ),
                        RunResult(
                            fixture_id="f2",
                            run_number=1,
                            success=True,
                            latency_ms=50.0,
                            output_json={"b": 2},
                        ),
                    ],
                ),
            },
        )
        filtered, _ = benchmark.filter_for_evaluation(["f1"], min_pass_rate=0.0)
        runs = filtered.models["openrouter:test/model"].runs
        assert len(runs) == 1
        assert runs[0].fixture_id == "f1"

    def test_excludes_failed_runs_and_missing_output(self) -> None:
        benchmark = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=3,
            models={
                "openrouter:test/model": ModelResult(
                    model="openrouter:test/model",
                    total_cost_usd=0.01,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=50.0,
                            output_json={"ok": True},
                        ),
                        RunResult(
                            fixture_id="f1",
                            run_number=2,
                            success=False,
                            latency_ms=50.0,
                            error_message="err",
                        ),
                        RunResult(
                            fixture_id="f1",
                            run_number=3,
                            success=True,
                            latency_ms=50.0,
                            output_json=None,
                        ),
                    ],
                ),
            },
        )
        filtered, _ = benchmark.filter_for_evaluation(["f1"], min_pass_rate=0.0)
        runs = filtered.models["openrouter:test/model"].runs
        assert len(runs) == 1
        assert runs[0].run_number == 1

    def test_returns_empty_when_all_skipped(self) -> None:
        benchmark = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=1,
            models={
                "openrouter:test/bad": ModelResult(
                    model="openrouter:test/bad",
                    total_cost_usd=0.0,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=False,
                            latency_ms=50.0,
                            error_message="err",
                        ),
                    ],
                ),
            },
        )
        filtered, skipped = benchmark.filter_for_evaluation(["f1"], min_pass_rate=0.5)
        assert len(filtered.models) == 0
        assert "openrouter:test/bad" in skipped

    def test_preserves_benchmark_metadata(self, minimal_benchmark: BenchmarkResult) -> None:
        filtered, _ = minimal_benchmark.filter_for_evaluation(
            ["senior_python_remote"],
            min_pass_rate=0.0,
        )
        assert filtered.timestamp == minimal_benchmark.timestamp
        assert filtered.runs_per_fixture == minimal_benchmark.runs_per_fixture
        assert filtered.fixture_checksums == minimal_benchmark.fixture_checksums

    def test_max_runs_caps_per_fixture(self) -> None:
        benchmark = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=5,
            models={
                "openrouter:test/model": ModelResult(
                    model="openrouter:test/model",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=i,
                            success=True,
                            latency_ms=50.0,
                            output_json={"v": i},
                        )
                        for i in range(1, 6)
                    ],
                ),
            },
        )
        filtered, _ = benchmark.filter_for_evaluation(
            ["f1"],
            min_pass_rate=0.0,
            max_runs_per_fixture=3,
        )
        runs = filtered.models["openrouter:test/model"].runs
        assert len(runs) == 3

    def test_max_runs_selects_lowest_run_numbers(self) -> None:
        benchmark = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=5,
            models={
                "openrouter:test/model": ModelResult(
                    model="openrouter:test/model",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=i,
                            success=True,
                            latency_ms=50.0,
                            output_json={"v": i},
                        )
                        for i in range(1, 6)
                    ],
                ),
            },
        )
        filtered, _ = benchmark.filter_for_evaluation(
            ["f1"],
            min_pass_rate=0.0,
            max_runs_per_fixture=2,
        )
        runs = filtered.models["openrouter:test/model"].runs
        run_numbers = {r.run_number for r in runs}
        assert run_numbers == {1, 2}

    def test_max_runs_none_no_capping(self) -> None:
        benchmark = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=5,
            models={
                "openrouter:test/model": ModelResult(
                    model="openrouter:test/model",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=i,
                            success=True,
                            latency_ms=50.0,
                            output_json={"v": i},
                        )
                        for i in range(1, 6)
                    ],
                ),
            },
        )
        filtered, _ = benchmark.filter_for_evaluation(
            ["f1"],
            min_pass_rate=0.0,
            max_runs_per_fixture=None,
        )
        runs = filtered.models["openrouter:test/model"].runs
        assert len(runs) == 5

    def test_max_runs_fewer_available_than_cap(self) -> None:
        benchmark = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=2,
            models={
                "openrouter:test/model": ModelResult(
                    model="openrouter:test/model",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=50.0,
                            output_json={"v": 1},
                        ),
                        RunResult(
                            fixture_id="f1",
                            run_number=2,
                            success=True,
                            latency_ms=50.0,
                            output_json={"v": 2},
                        ),
                    ],
                ),
            },
        )
        filtered, _ = benchmark.filter_for_evaluation(
            ["f1"],
            min_pass_rate=0.0,
            max_runs_per_fixture=10,
        )
        runs = filtered.models["openrouter:test/model"].runs
        assert len(runs) == 2

    def test_max_runs_applies_per_fixture(self) -> None:
        benchmark = BenchmarkResult(
            fixtures_used=["f1", "f2"],
            runs_per_fixture=3,
            models={
                "openrouter:test/model": ModelResult(
                    model="openrouter:test/model",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=i,
                            success=True,
                            latency_ms=50.0,
                            output_json={"v": i},
                        )
                        for i in range(1, 4)
                    ]
                    + [
                        RunResult(
                            fixture_id="f2",
                            run_number=i,
                            success=True,
                            latency_ms=50.0,
                            output_json={"v": i},
                        )
                        for i in range(1, 4)
                    ],
                ),
            },
        )
        filtered, _ = benchmark.filter_for_evaluation(
            ["f1", "f2"],
            min_pass_rate=0.0,
            max_runs_per_fixture=2,
        )
        runs = filtered.models["openrouter:test/model"].runs
        assert len(runs) == 4
        f1_runs = [r for r in runs if r.fixture_id == "f1"]
        f2_runs = [r for r in runs if r.fixture_id == "f2"]
        assert len(f1_runs) == 2
        assert len(f2_runs) == 2


class TestEvaluateCommandFixtureFilter:
    """Tests for the --fixture filter in the evaluate command."""

    def test_exits_on_unknown_fixture(
        self,
        cli_runner: CliRunner,
        saved_benchmark: Path,
    ) -> None:
        result = cli_runner.invoke(
            app,
            ["evaluate", str(saved_benchmark), "--fixture", "nonexistent_fixture"],
        )
        assert result.exit_code == 1
        assert "Unknown fixtures" in result.output

    def test_fixture_filter_limits_evaluation(
        self,
        cli_runner: CliRunner,
        saved_benchmark: Path,
        multi_judge_summary: MultiJudgeEvaluationSummary,
    ) -> None:
        with (
            patch(
                "llm_benchmark.cli.commands.evaluate.evaluate_multi_judge",
                new_callable=AsyncMock,
                return_value=multi_judge_summary,
            ),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys",
                return_value=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
            ),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "evaluate",
                    str(saved_benchmark),
                    "--fixture",
                    "senior_python_remote",
                    "--judge-model",
                    "openrouter:synthetic/judge",
                    "--unknown-price-max",
                    "0.01",
                ],
            )
        assert result.exit_code == 0


class TestEvaluateCommandMinPassRate:
    """Tests for the --min-pass-rate option in the evaluate command."""

    def test_skips_low_pass_rate_model(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        benchmark = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=1,
            models={
                "openrouter:test/good": ModelResult(
                    model="openrouter:test/good",
                    total_cost_usd=0.01,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=50.0,
                            output_json={"a": 1},
                        ),
                    ],
                ),
                "openrouter:test/bad": ModelResult(
                    model="openrouter:test/bad",
                    total_cost_usd=0.0,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=False,
                            latency_ms=50.0,
                            error_message="err",
                        ),
                    ],
                ),
            },
        )
        out = tmp_path / "bench.json"
        benchmark.save(out)
        with (
            patch(
                "llm_benchmark.cli.commands.evaluate.evaluate_multi_judge",
                new_callable=AsyncMock,
                return_value=compute_multi_judge_summary({"judge": EvaluationResult(judgments_by_model={})}),
            ),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys",
                return_value=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
            ),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "evaluate",
                    str(out),
                    "--min-pass-rate",
                    "0.5",
                    "--judge-model",
                    "openrouter:synthetic/judge",
                    "--unknown-price-max",
                    "0.01",
                ],
            )
        assert result.exit_code == 0
        assert "Skipped" in result.output
        assert "test/bad" in result.output

    def test_all_models_below_threshold_exits(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        benchmark = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=1,
            models={
                "openrouter:test/bad": ModelResult(
                    model="openrouter:test/bad",
                    total_cost_usd=0.0,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=False,
                            latency_ms=50.0,
                            error_message="err",
                        ),
                    ],
                ),
            },
        )
        out = tmp_path / "bench.json"
        benchmark.save(out)
        result = cli_runner.invoke(app, ["evaluate", str(out), "--min-pass-rate", "0.5"])
        assert result.exit_code == 1
        assert "No successful extraction outputs" in result.output


class TestSaveEvaluationResults:
    """Tests for _save_evaluation_results helper."""

    def test_writes_eval_json(self, tmp_path: Path, multi_judge_summary: MultiJudgeEvaluationSummary) -> None:
        base = tmp_path / "benchmark_test.json"
        base.touch()
        _save_evaluation_results(multi_judge_summary, base)
        eval_out = base.with_suffix(".eval.json")
        assert eval_out.exists()
        data = json.loads(eval_out.read_text())
        assert "per_judge" in data
        assert "consensus" in data
