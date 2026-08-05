"""Focused tests for named judge-chain loading in the ``evaluate`` command.

Residual evaluation can load its judges from a standard ``LLMSettings`` document
via ``--llm-settings`` / ``--chain``, matching the reusable configuration path
used by benchmark generation. These tests defend that contract end to end:

* one judge per chain model, in chain order;
* each model's endpoint, reasoning effort, provider routing, timeout, retry, and
  concurrency resolved independently;
* equal default weights, or explicit weights mapped positionally by chain order;
* recursive rejection of inline credentials anywhere in the settings JSON;
* provider defaults for an omitted (``None``) chain, a rejected unknown chain, and
  user-facing ``BadParameter`` for a malformed or structurally invalid document;
* mutual exclusion between ``--llm-settings`` and the direct judge overrides;
* fingerprints that retain every resolved judge setting, so semantically equal
  explicit and chain configurations share a fingerprint while any resolved
  difference splits it.

All models are synthetic identifiers and all settings live in ``tmp_path``; no
real model calls are made.
"""

import json
from pathlib import Path
from typing import NotRequired, TypedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from nohiki_llm_client import ApiKeyRegistry
from typer.testing import CliRunner

from llm_benchmark.cli import app
from llm_benchmark.cli.commands.evaluate import (
    _load_chain_judges,
    _reject_colliding_judges,
    _resolve_judge_weights,
    _resolve_judges,
)
from llm_benchmark.config.constants import (
    DEFAULT_EVAL_CONCURRENCY,
    JUDGE_MAX_RETRIES,
    JUDGE_TIMEOUT_SECONDS,
)
from llm_benchmark.config.models import JudgeConfig
from llm_benchmark.engine.checkpoint import compute_eval_config_fingerprint
from llm_benchmark.schemas.aggregation import (
    EvaluationResult,
    MultiJudgeEvaluationSummary,
    compute_multi_judge_summary,
)
from llm_benchmark.schemas.metrics import BenchmarkResult as _BenchmarkResult
from llm_benchmark.schemas.metrics import ModelResult
from llm_benchmark.schemas.metrics import RunResult as _RunResult

_CHAIN = "benchmark_residual_judges"
_REGISTRY = ApiKeyRegistry.model_validate({"openrouter": "synthetic-or-key", "openai": "synthetic-oa-key"})


class _ProviderModelPayload(TypedDict):
    model: str
    base_url: NotRequired[str]


class RunResult(_RunResult):
    """Run result with synthetic fingerprints so fixtures stay terse."""

    retry_count: int | None = 0

    treatment_fingerprint: str = "test-treatment"
    cell_fingerprint: str = "test-cell"


class BenchmarkResult(_BenchmarkResult):
    """Benchmark result with a synthetic experiment fingerprint."""

    experiment_fingerprint: str = "test-experiment"


def _write_settings(
    path: Path,
    chains: dict[str, object],
    *,
    provider_models: list[_ProviderModelPayload] | None = None,
) -> Path:
    """Write an LLMSettings JSON document with the given chains and return its path.

    The provider chain defaults to a single credential-free OpenRouter model; the
    injected registry supplies the key, mirroring the generation path.
    """
    payload = {
        "provider": {"models": provider_models or [{"model": "openrouter:synthetic/default"}]},
        "chains": chains,
    }
    path.write_text(json.dumps(payload))
    return path


@pytest.fixture
def cli_runner() -> CliRunner:
    """Return a Typer test CliRunner."""
    return CliRunner()


@pytest.fixture
def saved_benchmark(tmp_path: Path) -> Path:
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


@pytest.fixture
def multi_judge_summary() -> MultiJudgeEvaluationSummary:
    """Return a minimal multi-judge summary for mocked evaluation runs."""
    return compute_multi_judge_summary({"test-judge": EvaluationResult(judgments_by_model={})})


class TestLoadChainJudges:
    """``_load_chain_judges`` maps chain models to independent judge configs."""

    @pytest.fixture(autouse=True)
    def _hermetic_registry(self) -> object:
        # Cloud chains lazily load the shared secret registry; keep tests hermetic.
        with patch("llm_benchmark.cli.commands.evaluate.load_api_keys", return_value=_REGISTRY):
            yield

    def test_loads_one_judge_per_chain_model_in_order(self, tmp_path: Path) -> None:
        settings = _write_settings(
            tmp_path / "s.json",
            {
                _CHAIN: {
                    "models": [
                        {"model": "openrouter:synthetic/a"},
                        {"model": "openrouter:synthetic/b"},
                    ]
                },
            },
        )

        judges, _ = _load_chain_judges(settings, _CHAIN, None)

        assert [j.model for j in judges] == [
            "openrouter:synthetic/a",
            "openrouter:synthetic/b",
        ]
        assert all(isinstance(j, JudgeConfig) for j in judges)

    def test_per_model_endpoint_reasoning_and_routing(self, tmp_path: Path) -> None:
        settings = _write_settings(
            tmp_path / "s.json",
            {
                _CHAIN: {
                    "models": [
                        {
                            "model": "openrouter:synthetic/a",
                            "reasoning_effort": "low",
                            "provider_order": ["route-a"],
                            "provider_allow_fallbacks": False,
                        },
                        {
                            "model": "openai:synthetic-b",
                            "base_url": "https://gateway-b.example.test/v1",
                        },
                    ]
                },
            },
        )

        (first, second), _ = _load_chain_judges(settings, _CHAIN, None)

        assert first.model == "openrouter:synthetic/a"
        assert first.reasoning_effort == "low"
        assert first.provider_order == ("route-a",)
        assert first.provider_allow_fallbacks is False
        assert first.base_url is None
        assert second.model == "openai:synthetic-b"
        assert second.reasoning_effort == "high"
        assert second.provider_order == ()
        assert second.base_url == "https://gateway-b.example.test/v1"

    def test_provider_timeout_retries_concurrency_applied_per_judge(self, tmp_path: Path) -> None:
        settings = _write_settings(
            tmp_path / "s.json",
            {
                _CHAIN: {
                    "timeout_seconds": 45.0,
                    "max_tool_retries": 2,
                    "concurrency_limit": 7,
                    "models": [
                        {"model": "openrouter:synthetic/a"},
                        {"model": "openrouter:synthetic/b"},
                    ],
                },
            },
        )

        judges, _ = _load_chain_judges(settings, _CHAIN, None)

        assert [j.timeout_seconds for j in judges] == [45.0, 45.0]
        assert [j.max_retries for j in judges] == [2, 2]
        assert [j.concurrency for j in judges] == [7, 7]
        assert [j.effective_timeout_seconds for j in judges] == [45.0, 45.0]
        assert [j.effective_max_retries for j in judges] == [2, 2]
        assert [j.effective_concurrency for j in judges] == [7, 7]

    def test_provider_defaults_flow_through_when_unset(self, tmp_path: Path) -> None:
        settings = _write_settings(
            tmp_path / "s.json",
            {_CHAIN: {"models": [{"model": "openrouter:synthetic/a"}]}},
        )

        (judge,), _ = _load_chain_judges(settings, _CHAIN, None)

        # LLMProviderSettings defaults: 120s timeout, 3 tool retries, no concurrency cap.
        assert judge.timeout_seconds == 120.0
        assert judge.max_retries == 3
        assert judge.concurrency is None
        assert judge.effective_timeout_seconds == 120.0
        assert judge.effective_max_retries == 3
        assert judge.effective_concurrency == DEFAULT_EVAL_CONCURRENCY

    def test_equal_default_weights_when_no_weight_flags(self, tmp_path: Path) -> None:
        settings = _write_settings(
            tmp_path / "s.json",
            {
                _CHAIN: {
                    "models": [
                        {"model": "openrouter:synthetic/a"},
                        {"model": "openrouter:synthetic/b"},
                    ]
                },
            },
        )

        judges, _ = _load_chain_judges(settings, _CHAIN, None)

        assert [j.weight for j in judges] == [1.0, 1.0]

    def test_explicit_weights_map_positionally_in_chain_order(self, tmp_path: Path) -> None:
        settings = _write_settings(
            tmp_path / "s.json",
            {
                _CHAIN: {
                    "models": [
                        {"model": "openrouter:synthetic/a"},
                        {"model": "openrouter:synthetic/b"},
                    ]
                },
            },
        )

        judges, _ = _load_chain_judges(settings, _CHAIN, [3.0, 1.0])

        assert judges[0].model == "openrouter:synthetic/a"
        assert judges[0].weight == 3.0
        assert judges[1].model == "openrouter:synthetic/b"
        assert judges[1].weight == 1.0

    @pytest.mark.parametrize(
        "credential_payload",
        [
            {"models": [{"model": "openrouter:synthetic/a", "api_key": "embedded-secret"}]},
            {
                "api_keys": {"openrouter": "embedded-secret"},
                "models": [{"model": "openrouter:synthetic/a"}],
            },
        ],
        ids=["model-level-key", "chain-level-registry"],
    )
    def test_rejects_credentials_embedded_in_chain(
        self,
        tmp_path: Path,
        credential_payload: dict[str, object],
    ) -> None:
        settings = _write_settings(tmp_path / "s.json", {_CHAIN: credential_payload})

        with pytest.raises(typer.BadParameter, match="must not contain API keys"):
            _load_chain_judges(settings, _CHAIN, None)

    def test_rejects_credentials_embedded_in_provider(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        path.write_text(
            json.dumps(
                {
                    "provider": {
                        "api_keys": {"openrouter": "embedded-secret"},
                        "models": [{"model": "openrouter:synthetic/default"}],
                    },
                    "chains": {_CHAIN: {"models": [{"model": "openrouter:synthetic/a"}]}},
                }
            )
        )

        with pytest.raises(typer.BadParameter, match="must not contain API keys"):
            _load_chain_judges(path, _CHAIN, None)

    def test_unknown_chain_is_rejected(self, tmp_path: Path) -> None:
        settings = _write_settings(
            tmp_path / "s.json",
            {_CHAIN: {"models": [{"model": "openrouter:synthetic/a"}]}},
            provider_models=[{"model": "openrouter:synthetic/default"}],
        )

        with pytest.raises(typer.BadParameter) as exc:
            _load_chain_judges(settings, "nonexistent_chain", None)
        message = str(exc.value)
        assert "Unknown chain 'nonexistent_chain'" in message
        assert "available chains: benchmark_residual_judges" in message

    def test_none_chain_uses_default_provider(self, tmp_path: Path) -> None:
        settings = _write_settings(
            tmp_path / "s.json",
            {_CHAIN: {"models": [{"model": "openrouter:synthetic/a"}]}},
            provider_models=[{"model": "openrouter:synthetic/default"}],
        )

        judges, _ = _load_chain_judges(settings, None, None)

        assert [j.model for j in judges] == ["openrouter:synthetic/default"]

    def test_empty_chain_models_raises_bad_parameter(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        path.write_text(
            json.dumps(
                {
                    "provider": {"models": [{"model": "openrouter:synthetic/default"}]},
                    "chains": {_CHAIN: {"models": []}},
                }
            )
        )

        with pytest.raises(typer.BadParameter, match="Invalid LLMSettings configuration:") as exc:
            _load_chain_judges(path, _CHAIN, None)
        assert "At least one model is required" in str(exc.value)

    def test_invalid_chain_field_raises_bad_parameter(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        path.write_text(
            json.dumps(
                {
                    "provider": {"models": [{"model": "openrouter:synthetic/default"}]},
                    "chains": {
                        _CHAIN: {
                            "models": [
                                {
                                    "model": "openrouter:synthetic/a",
                                    "reasoning_effort": "ludicrous",
                                }
                            ]
                        }
                    },
                }
            )
        )

        with pytest.raises(typer.BadParameter, match="Invalid LLMSettings configuration:"):
            _load_chain_judges(path, _CHAIN, None)

    def test_invalid_json_raises_bad_parameter(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        path.write_text("{not valid json")

        with pytest.raises(typer.BadParameter, match="Invalid LLMSettings JSON:"):
            _load_chain_judges(path, _CHAIN, None)

    def test_non_object_top_level_raises_bad_parameter(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        path.write_text(json.dumps(["not", "an", "object"]))

        with pytest.raises(typer.BadParameter, match="must define a top-level object"):
            _load_chain_judges(path, _CHAIN, None)


class TestResolveJudgeWeights:
    """``_resolve_judge_weights`` shares weight handling across both judge paths."""

    _COUNT_ERROR = "--judge-weight must be repeated once per judge in the same order."

    def test_equal_weights_when_none(self) -> None:
        assert _resolve_judge_weights(3, None, count_error=self._COUNT_ERROR) == [
            1.0,
            1.0,
            1.0,
        ]

    def test_returns_given_weights_when_count_matches(self) -> None:
        assert _resolve_judge_weights(2, [3.0, 1.0], count_error=self._COUNT_ERROR) == [
            3.0,
            1.0,
        ]

    def test_count_mismatch_exits(self) -> None:
        with pytest.raises(typer.Exit) as exc:
            _resolve_judge_weights(2, [1.0], count_error=self._COUNT_ERROR)
        assert exc.value.exit_code == 1

    def test_non_positive_weight_exits(self) -> None:
        with pytest.raises(typer.Exit) as exc:
            _resolve_judge_weights(2, [1.0, 0.0], count_error=self._COUNT_ERROR)
        assert exc.value.exit_code == 1


class TestResolveJudgesDispatch:
    """``_resolve_judges`` enforces mutual exclusion and dispatches to the chain loader."""

    def _settings(self, tmp_path: Path) -> Path:
        return _write_settings(
            tmp_path / "s.json",
            {_CHAIN: {"models": [{"model": "openrouter:synthetic/a"}]}},
        )

    def test_llm_settings_with_judge_model_is_mutually_exclusive(self, tmp_path: Path) -> None:
        settings = self._settings(tmp_path)
        with pytest.raises(
            typer.BadParameter,
            match="--llm-settings is mutually exclusive with --judge-model",
        ):
            _resolve_judges(
                ["openrouter:synthetic/judge"],
                None,
                settings,
                _CHAIN,
                base_url=None,
                api_key=None,
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )

    def test_llm_settings_with_base_url_is_mutually_exclusive(self, tmp_path: Path) -> None:
        settings = self._settings(tmp_path)
        with pytest.raises(typer.BadParameter, match="--base-url"):
            _resolve_judges(
                None,
                None,
                settings,
                _CHAIN,
                base_url="https://x.example.test/v1",
                api_key=None,
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )

    def test_llm_settings_with_api_key_is_mutually_exclusive(self, tmp_path: Path) -> None:
        settings = self._settings(tmp_path)
        with pytest.raises(typer.BadParameter, match="--api-key"):
            _resolve_judges(
                None,
                None,
                settings,
                _CHAIN,
                base_url=None,
                api_key="synthetic-key",
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )

    def test_mutual_exclusion_lists_every_conflicting_flag(self, tmp_path: Path) -> None:
        settings = self._settings(tmp_path)
        with pytest.raises(typer.BadParameter) as exc:
            _resolve_judges(
                ["openrouter:synthetic/judge"],
                None,
                settings,
                None,
                base_url="https://x.example.test/v1",
                api_key=None,
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )
        message = str(exc.value)
        assert "--judge-model" in message
        assert "--base-url" in message

    def test_chain_without_llm_settings_is_rejected(self) -> None:
        with pytest.raises(typer.BadParameter, match="--chain requires --llm-settings"):
            _resolve_judges(
                None,
                None,
                None,
                _CHAIN,
                base_url=None,
                api_key=None,
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )

    def test_llm_settings_path_resolves_chain_judges(self, tmp_path: Path) -> None:
        settings = self._settings(tmp_path)
        with patch("llm_benchmark.cli.commands.evaluate.load_api_keys", return_value=_REGISTRY):
            judges, api_keys = _resolve_judges(
                None,
                None,
                settings,
                _CHAIN,
                base_url=None,
                api_key=None,
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )
        assert [j.model for j in judges] == ["openrouter:synthetic/a"]
        # A cloud chain lazily loads the shared registry and threads it to dispatch.
        assert api_keys is _REGISTRY


class TestRejectCollidingJudges:
    """Two judges keyed by the same ``.model`` would silently collapse; reject them."""

    def test_exact_duplicate_identity_is_rejected(self) -> None:
        judge = JudgeConfig(model="openrouter:x", provider_order=("a",))
        with pytest.raises(typer.BadParameter, match="declared more than once"):
            _reject_colliding_judges([judge, judge])

    def test_same_model_different_string_but_same_identity_is_rejected(self) -> None:
        # Distinct CLI strings that collapse to one dispatch identity (effort default high).
        first = JudgeConfig.from_string("openrouter:x@a")
        second = JudgeConfig.from_string("openrouter:x:high@a")
        assert first.identity_key == second.identity_key
        with pytest.raises(typer.BadParameter, match="declared more than once"):
            _reject_colliding_judges([first, second])

    def test_same_model_colliding_route_is_rejected(self) -> None:
        first = JudgeConfig(model="openrouter:x", provider_order=("a",))
        second = JudgeConfig(model="openrouter:x", provider_order=("b",))
        assert first.identity_key != second.identity_key
        with pytest.raises(typer.BadParameter, match="Colliding judge identities"):
            _reject_colliding_judges([first, second])

    def test_distinct_models_are_allowed(self) -> None:
        judges = [JudgeConfig(model="openrouter:x"), JudgeConfig(model="openrouter:y")]
        _reject_colliding_judges(judges)  # no raise

    def test_collision_rejected_end_to_end_through_resolve(self) -> None:
        with (
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys",
                return_value=_REGISTRY,
            ),
            pytest.raises(typer.BadParameter, match="Colliding judge identities"),
        ):
            _resolve_judges(
                ["openrouter:x@a", "openrouter:x@b"],
                None,
                None,
                None,
                base_url=None,
                api_key=None,
                concurrency=DEFAULT_EVAL_CONCURRENCY,
            )


class TestEvaluateChainCli:
    """End-to-end wiring of ``evaluate --llm-settings --chain`` through the CLI."""

    def test_chain_judges_reach_engine_with_resolved_settings(
        self,
        cli_runner: CliRunner,
        saved_benchmark: Path,
        tmp_path: Path,
        multi_judge_summary: MultiJudgeEvaluationSummary,
    ) -> None:
        settings = _write_settings(
            tmp_path / "s.json",
            {
                _CHAIN: {
                    "timeout_seconds": 30.0,
                    "max_tool_retries": 2,
                    "models": [
                        {
                            "model": "openrouter:synthetic/a",
                            "reasoning_effort": "low",
                            "provider_order": ["route-a"],
                        },
                        {"model": "openrouter:synthetic/b"},
                    ],
                },
            },
        )
        mock_eval = AsyncMock(return_value=(multi_judge_summary, False))
        with (
            patch(
                "llm_benchmark.cli.commands.evaluate._evaluate_async_with_progress",
                mock_eval,
            ),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys",
                return_value=_REGISTRY,
            ),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "evaluate",
                    str(saved_benchmark),
                    "--llm-settings",
                    str(settings),
                    "--chain",
                    _CHAIN,
                    "--judge-weight",
                    "3",
                    "--judge-weight",
                    "1",
                    "--unknown-price-max",
                    "0.01",
                ],
            )

        assert result.exit_code == 0, result.output
        await_call = mock_eval.await_args
        assert await_call is not None
        judges = await_call.args[2]
        assert [j.model for j in judges] == [
            "openrouter:synthetic/a",
            "openrouter:synthetic/b",
        ]
        assert judges[0].reasoning_effort == "low"
        assert judges[0].provider_order == ("route-a",)
        assert [j.weight for j in judges] == [3.0, 1.0]
        assert [j.effective_timeout_seconds for j in judges] == [30.0, 30.0]
        assert [j.effective_max_retries for j in judges] == [2, 2]
        assert saved_benchmark.with_suffix(".eval.json").exists()

    def test_weight_count_mismatch_reports_error(
        self,
        cli_runner: CliRunner,
        saved_benchmark: Path,
        tmp_path: Path,
    ) -> None:
        settings = _write_settings(
            tmp_path / "s.json",
            {
                _CHAIN: {
                    "models": [
                        {"model": "openrouter:synthetic/a"},
                        {"model": "openrouter:synthetic/b"},
                    ]
                },
            },
        )
        with patch("llm_benchmark.cli.commands.evaluate.load_api_keys", return_value=_REGISTRY):
            result = cli_runner.invoke(
                app,
                [
                    "evaluate",
                    str(saved_benchmark),
                    "--llm-settings",
                    str(settings),
                    "--chain",
                    _CHAIN,
                    "--judge-weight",
                    "1",
                    "--unknown-price-max",
                    "0.01",
                ],
            )

        assert result.exit_code == 1
        assert "repeated once per judge in the same order" in result.output

    def test_non_positive_weight_reports_error(
        self,
        cli_runner: CliRunner,
        saved_benchmark: Path,
        tmp_path: Path,
    ) -> None:
        settings = _write_settings(
            tmp_path / "s.json",
            {
                _CHAIN: {
                    "models": [
                        {"model": "openrouter:synthetic/a"},
                        {"model": "openrouter:synthetic/b"},
                    ]
                },
            },
        )
        with patch("llm_benchmark.cli.commands.evaluate.load_api_keys", return_value=_REGISTRY):
            result = cli_runner.invoke(
                app,
                [
                    "evaluate",
                    str(saved_benchmark),
                    "--llm-settings",
                    str(settings),
                    "--chain",
                    _CHAIN,
                    "--judge-weight",
                    "1",
                    "--judge-weight",
                    "0",
                    "--unknown-price-max",
                    "0.01",
                ],
            )

        assert result.exit_code == 1
        assert "Judge weights must be greater than zero" in result.output


class TestChainFingerprint:
    """The evaluation fingerprint retains every resolved judge setting."""

    def _capture_judge_fingerprint(
        self,
        cli_runner: CliRunner,
        saved_benchmark: Path,
        extra_args: list[str],
        summary: MultiJudgeEvaluationSummary,
    ) -> list[str]:
        fingerprint_spy = MagicMock(side_effect=compute_eval_config_fingerprint)
        mock_eval = AsyncMock(return_value=(summary, False))
        with (
            patch(
                "llm_benchmark.cli.commands.evaluate.compute_eval_config_fingerprint",
                fingerprint_spy,
            ),
            patch(
                "llm_benchmark.cli.commands.evaluate._evaluate_async_with_progress",
                mock_eval,
            ),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys",
                return_value=_REGISTRY,
            ),
        ):
            result = cli_runner.invoke(app, ["evaluate", str(saved_benchmark), *extra_args])

        assert result.exit_code == 0, result.output
        return fingerprint_spy.call_args.kwargs["judge_models"]

    def test_fingerprint_includes_resolved_timeout_retries_concurrency(
        self,
        cli_runner: CliRunner,
        saved_benchmark: Path,
        tmp_path: Path,
        multi_judge_summary: MultiJudgeEvaluationSummary,
    ) -> None:
        settings = _write_settings(
            tmp_path / "s.json",
            {
                _CHAIN: {
                    "timeout_seconds": 30.0,
                    "max_tool_retries": 2,
                    "concurrency_limit": 5,
                    "models": [{"model": "openrouter:synthetic/a"}],
                },
            },
        )

        judge_models = self._capture_judge_fingerprint(
            cli_runner,
            saved_benchmark,
            [
                "--llm-settings",
                str(settings),
                "--chain",
                _CHAIN,
                "--unknown-price-max",
                "0.01",
            ],
            multi_judge_summary,
        )

        assert len(judge_models) == 1
        entry = judge_models[0]
        assert "timeout=30" in entry
        assert "retries=2" in entry
        assert "concurrency=5" in entry

    def test_fingerprint_changes_when_resolved_timeout_changes(
        self,
        cli_runner: CliRunner,
        saved_benchmark: Path,
        tmp_path: Path,
        multi_judge_summary: MultiJudgeEvaluationSummary,
    ) -> None:
        fast = _write_settings(
            tmp_path / "fast.json",
            {
                _CHAIN: {
                    "timeout_seconds": 30.0,
                    "models": [{"model": "openrouter:synthetic/a"}],
                }
            },
        )
        slow = _write_settings(
            tmp_path / "slow.json",
            {
                _CHAIN: {
                    "timeout_seconds": 90.0,
                    "models": [{"model": "openrouter:synthetic/a"}],
                }
            },
        )

        fast_models = self._capture_judge_fingerprint(
            cli_runner,
            saved_benchmark,
            [
                "--llm-settings",
                str(fast),
                "--chain",
                _CHAIN,
                "--unknown-price-max",
                "0.01",
            ],
            multi_judge_summary,
        )
        slow_models = self._capture_judge_fingerprint(
            cli_runner,
            saved_benchmark,
            [
                "--llm-settings",
                str(slow),
                "--chain",
                _CHAIN,
                "--unknown-price-max",
                "0.01",
            ],
            multi_judge_summary,
        )

        assert fast_models != slow_models

    def test_fingerprint_matches_for_semantically_equal_explicit_and_chain(
        self,
        cli_runner: CliRunner,
        saved_benchmark: Path,
        tmp_path: Path,
        multi_judge_summary: MultiJudgeEvaluationSummary,
    ) -> None:
        # Chain settings tuned so the resolved judge matches the explicit judge's
        # effective settings: same model/effort/weight/routing, timeout 120,
        # retries 5, default concurrency.
        settings = _write_settings(
            tmp_path / "s.json",
            {
                _CHAIN: {
                    "timeout_seconds": JUDGE_TIMEOUT_SECONDS,
                    "max_tool_retries": JUDGE_MAX_RETRIES,
                    "models": [{"model": "openrouter:synthetic/judge"}],
                },
            },
        )

        explicit_models = self._capture_judge_fingerprint(
            cli_runner,
            saved_benchmark,
            [
                "--judge-model",
                "openrouter:synthetic/judge",
                "--unknown-price-max",
                "0.01",
            ],
            multi_judge_summary,
        )
        chain_models = self._capture_judge_fingerprint(
            cli_runner,
            saved_benchmark,
            [
                "--llm-settings",
                str(settings),
                "--chain",
                _CHAIN,
                "--unknown-price-max",
                "0.01",
            ],
            multi_judge_summary,
        )

        assert explicit_models == chain_models


class TestChainOptionalRegistry:
    """Test optional registry loading for a keyless-capable named chain.

    An OpenAI-compatible endpoint with an explicit ``base_url`` adopts a present
    canonical registry key without mandating one; a cloud chain still requires
    the mandatory registry before dispatch.
    """

    _PROXY = "https://provider.example.test/v1"

    def _proxy_settings(self, tmp_path: Path) -> Path:
        model: _ProviderModelPayload = {"model": "openai:custom-model", "base_url": self._PROXY}
        return _write_settings(
            tmp_path / "s.json",
            {_CHAIN: {"models": [model]}},
            provider_models=[model],
        )

    def test_present_optional_registry_populates_chain_openai_endpoint(self, tmp_path: Path) -> None:
        settings = self._proxy_settings(tmp_path)
        optional = ApiKeyRegistry.model_validate({"openai": "credential-value"})
        mandatory = MagicMock(side_effect=AssertionError("mandatory registry load must not run"))
        with (
            patch("llm_benchmark.cli.commands.evaluate.load_api_keys", mandatory),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys_optional",
                return_value=optional,
            ) as opt,
        ):
            judges, api_keys = _load_chain_judges(settings, _CHAIN, None)
        mandatory.assert_not_called()
        opt.assert_called_once()
        # Pre-fix behavior left the registry empty here; the canonical key now flows through.
        assert api_keys is optional
        model_extra = api_keys.model_extra
        assert model_extra is not None
        assert model_extra["openai"].get_secret_value() == "credential-value"
        assert [j.model for j in judges] == ["openai:custom-model"]
        assert judges[0].base_url == self._PROXY
        assert judges[0].api_key is None

    def test_absent_optional_registry_keeps_chain_keyless(self, tmp_path: Path) -> None:
        settings = self._proxy_settings(tmp_path)
        empty = ApiKeyRegistry()
        mandatory = MagicMock(side_effect=AssertionError("mandatory registry load must not run"))
        with (
            patch("llm_benchmark.cli.commands.evaluate.load_api_keys", mandatory),
            patch(
                "llm_benchmark.cli.commands.evaluate.load_api_keys_optional",
                return_value=empty,
            ),
        ):
            judges, api_keys = _load_chain_judges(settings, _CHAIN, None)
        mandatory.assert_not_called()
        assert not api_keys.model_extra
        assert judges[0].base_url == self._PROXY

    def test_cloud_chain_requires_mandatory_registry(self, tmp_path: Path) -> None:
        # An OpenRouter chain needs a resolvable key: the mandatory loader runs and
        # the optional probe is never consulted.
        settings = _write_settings(
            tmp_path / "s.json",
            {_CHAIN: {"models": [{"model": "openrouter:synthetic/a"}]}},
        )
        mandatory = MagicMock(return_value=_REGISTRY)
        optional = MagicMock(side_effect=AssertionError("optional probe must not run for a cloud chain"))
        with (
            patch("llm_benchmark.cli.commands.evaluate.load_api_keys", mandatory),
            patch("llm_benchmark.cli.commands.evaluate.load_api_keys_optional", optional),
        ):
            _judges, api_keys = _load_chain_judges(settings, _CHAIN, None)
        mandatory.assert_called_once()
        optional.assert_not_called()
        assert api_keys is _REGISTRY

    def test_registry_secret_absent_from_chain_identity_and_serialization(self, tmp_path: Path) -> None:
        settings = self._proxy_settings(tmp_path)
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
            judges, api_keys = _load_chain_judges(settings, _CHAIN, None)
        assert all("credential-value" not in j.identity_key for j in judges)
        assert "credential-value" not in repr(api_keys)
        assert "credential-value" not in str(api_keys)
        fingerprint = compute_eval_config_fingerprint(
            benchmark_timestamp="2026-07-12T00:00:00Z",
            max_runs_per_fixture=1,
            min_pass_rate=0.0,
            fixtures=["fixture-a"],
            judge_models=[j.model for j in judges],
        )
        assert "credential-value" not in fingerprint
