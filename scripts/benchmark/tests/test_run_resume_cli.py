"""Focused generation ``run`` CLI + resume regression tests.

These defend the launch-blocking generation contract:

* stale-fixture checksum rerun with full historical preservation (the
  ``_resolve_existing_result`` / ``_apply_stale_fixture_filter`` /
  ``full_existing_result`` helpers must actually be wired into ``run()`` --
  not defined-but-dead);
* exact attempted-cell resume (non-stale prior cells stay in the skip set
  while stale cells are re-executed);
* incompatible-experiment rejection;
* no silent loss when merging historical runs on incremental save;
* pure-local and explicit-``--api-key`` runs never require the canonical
  secret files (no eager key load), while a cloud model with no key still
  fails preflight;
* ``--model ollama:*`` resolves its ``base_url`` from ``--ollama-base-url``
  (today the convenience branch leaves it ``None`` and ``LLMModelConfig``
  rejects) and that value flows into the experiment identity;
* ``find_latest_result`` follows its documented most-recently-modified
  ordering rather than lexicographic filename order.

Every test either fails on the current dead-helper / eager-key / dead-ollama
behaviour and passes after the fix, or is an explicit protective guard noted
as such.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_llm_client import ApiKeyRegistry
from typer.testing import CliRunner

from llm_benchmark.cli import app
from llm_benchmark.cli._helpers import find_latest_result
from llm_benchmark.cli.commands.run import _save_incremental
from llm_benchmark.config.constants import DEFAULT_OLLAMA_BASE_URL
from llm_benchmark.config.models import BenchmarkConfig
from llm_benchmark.engine.runner import RunProgressCallback, experiment_fingerprint, treatment_ids
from llm_benchmark.fixtures import compute_fixture_checksum
from llm_benchmark.schemas.metrics import BenchmarkResult, ModelResult, RunResult

_STALE_FP = "fixture-content-invariant-identity"
_A_KEY_DIR = "llm_benchmark.cli._helpers.get_api_keys_dir"
_CLOUD_MODEL = "openrouter:google/gemini-3-flash-preview"
_RESULTS_DIR = "llm_benchmark.cli._helpers.get_results_dir"
_ASYNC = "llm_benchmark.cli.commands.run._run_benchmark_async"
_LOAD_KEYS = "llm_benchmark.cli.commands.run.load_api_keys"
_FINGERPRINT = "llm_benchmark.cli.commands.run.experiment_fingerprint"


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def _run_result(fixture_id: str, run_number: int = 1, *, cost: float = 0.01) -> RunResult:
    return RunResult(
        fixture_id=fixture_id,
        treatment_fingerprint="t",
        cell_fingerprint=f"{fixture_id}::{run_number}",
        run_number=run_number,
        success=True,
        latency_ms=1.0,
        output_json={"cleaned_title": "Job"},
        actual_cost_usd=cost,
        retry_count=0,
    )


def _result(
    *,
    experiment_fingerprint: str,
    fixtures: list[str],
    checksums: dict[str, str],
    runs_by_model: dict[str, list[RunResult]],
    runs_per_fixture: int = 1,
) -> BenchmarkResult:
    return BenchmarkResult(
        experiment_fingerprint=experiment_fingerprint,
        fixtures_used=fixtures,
        runs_per_fixture=runs_per_fixture,
        fixture_checksums=checksums,
        models={
            name: ModelResult(model=name, runs=runs, total_cost_usd=sum(r.actual_cost_usd or 0.0 for r in runs))
            for name, runs in runs_by_model.items()
        },
    )


def _session_stub() -> BenchmarkResult:
    """A minimal valid result for the mocked async runner to return."""
    return _result(
        experiment_fingerprint="session",
        fixtures=["senior_python_remote"],
        checksums={},
        runs_by_model={"m": [_run_result("senior_python_remote")]},
    )


class TestStaleResumeWiring:
    """`run()` must execute the stale-filter + historical-preservation path.

    Fails on the dead-helper behaviour: today ``run()`` uses ``_load_raw_result``
    directly as ``scoped_existing`` (no stale strip) and passes
    ``full_existing_result=None``, so ``_apply_stale_fixture_filter`` /
    ``_resolve_existing_result`` are defined-but-unused and history is discarded.
    """

    def _invoke(self, cli_runner: CliRunner, output: Path) -> tuple[BenchmarkResult, BenchmarkResult]:
        stale_checksum = "stale-content-checksum-does-not-match-current"
        nurse_checksum = compute_fixture_checksum("nurse_icu_onsite")
        existing = _result(
            experiment_fingerprint=_STALE_FP,
            fixtures=["senior_python_remote", "nurse_icu_onsite", "archived_history"],
            checksums={"senior_python_remote": stale_checksum, "nurse_icu_onsite": nurse_checksum},
            runs_by_model={
                _CLOUD_MODEL: [
                    _run_result("senior_python_remote"),
                    _run_result("nurse_icu_onsite"),
                    _run_result("archived_history"),
                ]
            },
        )
        existing.save(output)

        async_mock = AsyncMock(return_value=_session_stub())
        with (
            patch(_FINGERPRINT, return_value=(_STALE_FP, ("t",))),
            patch(_LOAD_KEYS, return_value=ApiKeyRegistry.model_validate({"openrouter": "k"})),
            patch(_ASYNC, async_mock),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "--yes",
                    "--output",
                    str(output),
                    "--model",
                    _CLOUD_MODEL,
                    "--fixture",
                    "senior_python_remote",
                    "--fixture",
                    "nurse_icu_onsite",
                ],
            )
        assert result.exit_code == 0, result.output
        call = async_mock.call_args
        scoped = call.kwargs["existing_result"]
        full = call.kwargs["full_existing_result"]
        assert scoped is not None
        return scoped, full

    def test_stale_fixture_runs_are_stripped_from_skip_set(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        scoped, _full = self._invoke(cli_runner, tmp_path / "out.json")
        scoped_fixtures = {r.fixture_id for mr in scoped.models.values() for r in mr.runs}
        # The stale fixture must be re-executed -> absent from the resume skip set.
        assert "senior_python_remote" not in scoped_fixtures

    def test_non_stale_prior_cell_is_preserved_for_exact_resume(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        scoped, _full = self._invoke(cli_runner, tmp_path / "out.json")
        scoped_fixtures = {r.fixture_id for mr in scoped.models.values() for r in mr.runs}
        # The unchanged fixture's attempted cell stays skipped (no needless rerun).
        assert "nurse_icu_onsite" in scoped_fixtures

    def test_full_history_excludes_stale_but_keeps_nonstale_and_unrelated(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        _scoped, full = self._invoke(cli_runner, tmp_path / "out.json")
        assert full is not None
        full_fixtures = {r.fixture_id for mr in full.models.values() for r in mr.runs}
        # Merge base preserves the non-stale prior cell and the unrelated historical
        # fixture, but must NOT carry the un-rerun stale cell (else an interrupt
        # would persist it behind the current checksum and the next resume skips it).
        assert "nurse_icu_onsite" in full_fixtures
        assert "archived_history" in full_fixtures
        assert "senior_python_remote" not in full_fixtures


class TestIncompatibleExperimentRejection:
    """Guard: a stored result from a different experiment identity is rejected."""

    def test_mismatched_fingerprint_rejected_before_dispatch(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        output = tmp_path / "out.json"
        existing = _result(
            experiment_fingerprint="a-different-experiment-identity",
            fixtures=["senior_python_remote"],
            checksums={"senior_python_remote": compute_fixture_checksum("senior_python_remote")},
            runs_by_model={_CLOUD_MODEL: [_run_result("senior_python_remote")]},
        )
        existing.save(output)
        async_mock = AsyncMock(return_value=_session_stub())
        with (
            patch(_FINGERPRINT, return_value=("expected-identity", ("t",))),
            patch(_LOAD_KEYS, return_value=ApiKeyRegistry.model_validate({"openrouter": "k"})),
            patch(_ASYNC, async_mock),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "--yes",
                    "--output",
                    str(output),
                    "--model",
                    _CLOUD_MODEL,
                    "--fixture",
                    "senior_python_remote",
                ],
            )
        assert result.exit_code != 0
        assert "incompatible experiment" in result.output.lower()
        async_mock.assert_not_called()


class TestNoDuplicateLoss:
    """Incremental save must merge full history without dropping or duplicating cells."""

    def test_incremental_save_preserves_history_and_dedups_newest(self, tmp_path: Path) -> None:
        output = tmp_path / "out.json"
        fp = "same-experiment"
        # Historical file: an unrelated cell plus an older copy of a cell we re-run.
        full_existing = _result(
            experiment_fingerprint=fp,
            fixtures=["senior_python_remote", "nurse_icu_onsite"],
            checksums={},
            runs_by_model={
                _CLOUD_MODEL: [
                    _run_result("nurse_icu_onsite", 1, cost=0.02),
                    _run_result("senior_python_remote", 1, cost=0.99),
                ]
            },
        )
        # New partial re-ran the senior cell with fresh (lower) cost.
        partial = {_CLOUD_MODEL: [_run_result("senior_python_remote", 1, cost=0.01)]}
        _save_incremental(
            partial,
            output,
            ["senior_python_remote"],
            1,
            {"senior_python_remote": "cur"},
            fp,
            full_existing,
        )
        saved = BenchmarkResult.load(output)
        runs = saved.models[_CLOUD_MODEL].runs
        keys = sorted((r.fixture_id, r.run_number) for r in runs)
        # Unrelated historical cell survives; colliding cell is deduped to exactly one.
        assert keys == [("nurse_icu_onsite", 1), ("senior_python_remote", 1)]
        senior = next(r for r in runs if r.fixture_id == "senior_python_remote")
        assert senior.actual_cost_usd == pytest.approx(0.01), "newest run must win, not the historical copy"


class TestSecretFileRequirements:
    """Pure-local and explicit-key runs must not require canonical secret files."""

    def test_pure_local_run_needs_no_secret_files(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Fails today: `run()` eagerly loads keys and exits before local dispatch."""
        missing_keys = tmp_path / "no_secrets"
        async_mock = AsyncMock(return_value=_session_stub())
        with (
            patch(_A_KEY_DIR, return_value=missing_keys),
            patch(_ASYNC, async_mock),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "--yes",
                    "--output",
                    str(tmp_path / "out.json"),
                    "--model",
                    "llamacpp:synthetic-local",
                    "--base-url",
                    "https://provider.example.test/v1",
                    "--fixture",
                    "senior_python_remote",
                ],
            )
        assert result.exit_code == 0, result.output
        async_mock.assert_called_once()

    def test_explicit_api_key_needs_no_secret_files(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Fails today: `--api-key` still cannot bypass the eager secret-file load."""
        missing_keys = tmp_path / "no_secrets"
        async_mock = AsyncMock(return_value=_session_stub())
        with (
            patch(_A_KEY_DIR, return_value=missing_keys),
            patch(_ASYNC, async_mock),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "--yes",
                    "--output",
                    str(tmp_path / "out.json"),
                    "--model",
                    _CLOUD_MODEL,
                    "--api-key",
                    "credential-value",
                    "--fixture",
                    "senior_python_remote",
                ],
            )
        assert result.exit_code == 0, result.output
        async_mock.assert_called_once()

    def test_cloud_without_key_fails_preflight(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Guard: relaxing key loading must not let a cloud model run keyless."""
        missing_keys = tmp_path / "no_secrets"
        async_mock = AsyncMock(return_value=_session_stub())
        with (
            patch(_A_KEY_DIR, return_value=missing_keys),
            patch(_ASYNC, async_mock),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "--yes",
                    "--output",
                    str(tmp_path / "out.json"),
                    "--model",
                    _CLOUD_MODEL,
                    "--fixture",
                    "senior_python_remote",
                ],
            )
        assert result.exit_code != 0
        async_mock.assert_not_called()


class TestOllamaBaseUrlResolution:
    """`--model ollama:*` must resolve base_url from `--ollama-base-url`.

    Today the convenience branch sets ``base_url`` only for ``openai:`` models,
    so an ollama treatment gets ``base_url=None`` and ``LLMModelConfig``'s
    validator raises ``"Ollama provider requires base_url"`` -- the run cannot
    even construct.
    """

    def _capture_config(self, cli_runner: CliRunner, output: Path, ollama_url: str | None) -> BenchmarkConfig:
        async_mock = AsyncMock(return_value=_session_stub())
        args = [
            "run",
            "--yes",
            "--output",
            str(output),
            "--model",
            "ollama:synthetic-local",
            "--fixture",
            "senior_python_remote",
        ]
        if ollama_url is not None:
            args += ["--ollama-base-url", ollama_url]
        with (
            patch(_LOAD_KEYS, return_value=ApiKeyRegistry()),
            patch(_ASYNC, async_mock),
        ):
            result = cli_runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        async_mock.assert_called_once()
        config = async_mock.call_args.args[0]
        assert isinstance(config, BenchmarkConfig)
        return config

    def test_flag_reaches_treatment_and_config(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        url = "https://model.example.test/v1"
        config = self._capture_config(cli_runner, tmp_path / "out.json", url)
        assert config.models[0].base_url == url
        assert config.ollama_base_url == url

    def test_omitted_flag_falls_back_to_default(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        config = self._capture_config(cli_runner, tmp_path / "out.json", None)
        assert config.models[0].base_url == DEFAULT_OLLAMA_BASE_URL

    def test_flag_changes_experiment_identity(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        cfg_a = self._capture_config(cli_runner, tmp_path / "a.json", "http://host-a:11434/v1")
        cfg_b = self._capture_config(cli_runner, tmp_path / "b.json", "http://host-b:11434/v1")
        assert experiment_fingerprint(cfg_a)[0] != experiment_fingerprint(cfg_b)[0]


class TestFindLatestResultOrdering:
    """`find_latest_result` must honour its documented most-recently-modified order.

    Fails today: it sorts ``benchmark_*.json`` lexicographically and returns the
    last name, which diverges from modification time under clock skew, sequence
    suffixes, or out-of-order writes.
    """

    def test_returns_most_recently_modified_not_lexicographic_last(self, tmp_path: Path) -> None:
        lex_last_but_older = tmp_path / "benchmark_20260301_000000.json"
        lex_first_but_newer = tmp_path / "benchmark_20260101_000000.json"
        lex_last_but_older.write_text("{}")
        lex_first_but_newer.write_text("{}")
        os.utime(lex_last_but_older, (1_000_000, 1_000_000))
        os.utime(lex_first_but_newer, (2_000_000, 2_000_000))
        with patch(_RESULTS_DIR, return_value=tmp_path):
            latest = find_latest_result()
        assert latest == lex_first_but_newer


class TestNamedChainSecretRequirements:
    """Secret loading for `--llm-settings`/`--chain` keys off the SELECTED chain.

    The decision must inspect the resolved/selected chain's treatments, not the
    document's default provider: a local default with a cloud chain still needs
    the canonical registry, and a cloud default with a pure-local chain must not.
    """

    def _write_settings(self, path: Path, payload: dict[str, object]) -> None:
        path.write_text(json.dumps(payload))

    def _capture_config(self, cli_runner: CliRunner, settings: Path, chain: str, output: Path) -> BenchmarkConfig:
        async_mock = AsyncMock(return_value=_session_stub())
        with patch(_ASYNC, async_mock):
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "--yes",
                    "--output",
                    str(output),
                    "--llm-settings",
                    str(settings),
                    "--chain",
                    chain,
                    "--fixture",
                    "senior_python_remote",
                ],
            )
        assert result.exit_code == 0, result.output
        async_mock.assert_called_once()
        config = async_mock.call_args.args[0]
        assert isinstance(config, BenchmarkConfig)
        return config

    def test_local_default_cloud_chain_loads_canonical_registry(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Guard: a cloud-model chain must load keys even when the default is local."""
        keys_dir = tmp_path / "secrets"
        keys_dir.mkdir()
        (keys_dir / "openrouter").write_text("credential-value")
        settings = tmp_path / "llm.json"
        self._write_settings(
            settings,
            {
                "provider": {
                    "models": [{"model": "llamacpp:local-default", "base_url": "https://provider.example.test/v1"}]
                },
                "chains": {"cloud": {"models": [{"model": "openrouter:synthetic/cloud-a"}]}},
            },
        )
        with patch(_A_KEY_DIR, return_value=keys_dir):
            config = self._capture_config(cli_runner, settings, "cloud", tmp_path / "out.json")
        key = config.api_keys.get("openrouter")
        assert key is not None
        assert key.get_secret_value() == "credential-value"

    def test_cloud_default_local_chain_needs_no_secrets(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Fails today: eager load (and default-provider key validation) blocks a local chain."""
        missing_keys = tmp_path / "no_secrets"
        settings = tmp_path / "llm.json"
        self._write_settings(
            settings,
            {
                "provider": {"models": [{"model": "openrouter:synthetic/cloud-default"}]},
                "chains": {
                    "local": {"models": [{"model": "llamacpp:local-a", "base_url": "https://provider.example.test/v1"}]}
                },
            },
        )
        with patch(_A_KEY_DIR, return_value=missing_keys):
            config = self._capture_config(cli_runner, settings, "local", tmp_path / "out.json")
        assert config.api_keys.get("openrouter") is None


class TestInterruptedStaleResumeDurability:
    """Interrupting a resume mid-way must never launder un-rerun stale cells.

    Scenario (Main's contract): two stale selected cells plus an unrelated
    historical fixture. The run re-executes and persists only ONE stale cell,
    then is interrupted. The on-disk result must NOT contain the un-rerun stale
    cell (which would otherwise sit behind the current fixture checksum and be
    skipped forever), while the unrelated historical fixture survives -- so the
    next resume schedules the remaining stale cell.

    Fails on the unstripped-merge-base behaviour: with full_existing == raw, the
    incremental save merges the un-rerun stale cell straight back to disk.
    """

    def _stale_run(self, fixture_id: str, marker: str) -> RunResult:
        return RunResult(
            fixture_id=fixture_id,
            treatment_fingerprint="prior",
            cell_fingerprint=f"{fixture_id}::1",
            run_number=1,
            success=True,
            latency_ms=1.0,
            output_json={"marker": marker},
            actual_cost_usd=0.5,
            retry_count=0,
        )

    def test_interrupt_after_one_replacement_does_not_persist_unrerun_stale_cell(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        output = tmp_path / "out.json"
        existing = _result(
            experiment_fingerprint=_STALE_FP,
            fixtures=["senior_python_remote", "nurse_icu_onsite", "archived_history"],
            checksums={
                "senior_python_remote": "stale-senior-checksum",
                "nurse_icu_onsite": "stale-nurse-checksum",
            },
            runs_by_model={
                "openrouter:google/gemini-3-flash-preview@staleseed00000": [
                    self._stale_run("senior_python_remote", "old"),
                    self._stale_run("nurse_icu_onsite", "old"),
                    self._stale_run("archived_history", "historical"),
                ]
            },
        )
        existing.save(output)

        captured: dict[str, BenchmarkConfig] = {}

        def make_runner(config: BenchmarkConfig) -> MagicMock:
            captured["config"] = config
            runner = MagicMock()

            async def fake_run(
                progress_callback: RunProgressCallback | None = None,
                *,
                existing_result: BenchmarkResult | None = None,
            ) -> BenchmarkResult:
                _ = existing_result
                # Re-execute and persist exactly ONE stale cell, then interrupt.
                key = treatment_ids(captured["config"])[0]
                fresh = RunResult(
                    fixture_id="senior_python_remote",
                    treatment_fingerprint="fresh",
                    cell_fingerprint="senior_python_remote::1",
                    run_number=1,
                    success=True,
                    latency_ms=1.0,
                    output_json={"marker": "fresh"},
                    actual_cost_usd=0.01,
                    retry_count=0,
                )
                assert progress_callback is not None
                progress_callback(key, "senior_python_remote", 1, run_result=fresh)
                msg = "interrupted mid-run"
                raise RuntimeError(msg)

            runner.run = fake_run
            return runner

        with (
            patch(_FINGERPRINT, return_value=(_STALE_FP, ("t",))),
            patch(_LOAD_KEYS, return_value=ApiKeyRegistry.model_validate({"openrouter": "k"})),
            patch("llm_benchmark.cli.commands.run.BenchmarkRunner", side_effect=make_runner),
        ):
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "--yes",
                    "--output",
                    str(output),
                    "--model",
                    _CLOUD_MODEL,
                    "--fixture",
                    "senior_python_remote",
                    "--fixture",
                    "nurse_icu_onsite",
                ],
            )
        # The run aborted, but the incremental save already committed to disk.
        assert result.exit_code != 0
        saved = BenchmarkResult.load(output)
        runs = [r for mr in saved.models.values() for r in mr.runs]
        by_fixture = {r.fixture_id for r in runs}

        # The un-rerun stale cell must be absent under the current checksum.
        assert "nurse_icu_onsite" not in by_fixture
        # The re-executed cell is persisted, with its fresh content.
        senior = [r for r in runs if r.fixture_id == "senior_python_remote"]
        assert senior
        assert all(r.output_json == {"marker": "fresh"} for r in senior)
        # The unrelated historical fixture survives.
        assert "archived_history" in by_fixture
        # The persisted checksum is the current one -> a lingering nurse cell would
        # have been laundered as valid; its absence is what forces the rerun.
        assert saved.fixture_checksums.get("nurse_icu_onsite") == compute_fixture_checksum("nurse_icu_onsite")

        # Next resume: the remaining stale cell is scheduled (absent from the skip
        # set) while the unrelated historical fixture remains in the record.
        completed_fixtures = {fid for _model, fid, _run in saved.completed_run_keys()}
        assert "nurse_icu_onsite" not in completed_fixtures
        assert "archived_history" in completed_fixtures
