"""Tests for benchmark metrics and result models."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from llm_benchmark.schemas.metrics import BenchmarkResult as _BenchmarkResult
from llm_benchmark.schemas.metrics import ModelResult
from llm_benchmark.schemas.metrics import RunResult as _RunResult


class RunResult(_RunResult):
    treatment_fingerprint: str = "test-treatment"
    cell_fingerprint: str = "test-cell"


class BenchmarkResult(_BenchmarkResult):
    experiment_fingerprint: str = "test-experiment"


class TestRunResult:
    """Tests for RunResult model."""

    def test_successful_run(self) -> None:
        run = RunResult(
            fixture_id="test_fixture",
            run_number=1,
            success=True,
            latency_ms=1500.0,
            input_tokens=1000,
            output_tokens=200,
        )
        assert run.total_tokens == 1200
        assert run.success is True
        assert run.error_message is None
        assert run.output_json is None

    def test_failed_run(self) -> None:
        run = RunResult(
            fixture_id="test_fixture",
            run_number=2,
            success=False,
            latency_ms=500.0,
            error_message="Timeout exceeded",
        )
        assert run.total_tokens == 0
        assert run.success is False
        assert run.error_message == "Timeout exceeded"

    def test_failed_run_allows_unknown_retry_count(self) -> None:
        run = RunResult(
            fixture_id="test_fixture",
            run_number=2,
            success=False,
            latency_ms=500.0,
            retry_count=None,
            error_message="boom",
        )
        assert run.retry_count is None

    def test_run_with_output_json(self) -> None:
        output = {"cleaned_title": "Software Engineer", "cleaned_company": "Acme"}
        run = RunResult(
            fixture_id="fix1",
            run_number=1,
            success=True,
            latency_ms=2000.0,
            input_tokens=500,
            output_tokens=100,
            output_json=output,
        )
        assert run.output_json == output

    def test_run_with_cache_tokens(self) -> None:
        run = RunResult(
            fixture_id="fix1",
            run_number=1,
            success=True,
            latency_ms=800.0,
            input_tokens=1000,
            output_tokens=200,
            cache_read_tokens=500,
            cache_write_tokens=300,
        )
        assert run.cache_read_tokens == 500
        assert run.cache_write_tokens == 300


class TestModelResult:
    """Tests for ModelResult model."""

    @pytest.fixture
    def model_with_runs(self) -> ModelResult:
        return ModelResult(
            model="test/model-a",
            runs=[
                RunResult(
                    fixture_id="f1",
                    run_number=1,
                    success=True,
                    latency_ms=1000.0,
                    input_tokens=100,
                    output_tokens=50,
                ),
                RunResult(
                    fixture_id="f1",
                    run_number=2,
                    success=True,
                    latency_ms=2000.0,
                    input_tokens=120,
                    output_tokens=60,
                ),
                RunResult(
                    fixture_id="f2",
                    run_number=1,
                    success=False,
                    latency_ms=500.0,
                    error_message="fail",
                ),
            ],
        )

    def test_total_runs(self, model_with_runs: ModelResult) -> None:
        assert model_with_runs.total_runs == 3

    def test_successful_runs(self, model_with_runs: ModelResult) -> None:
        assert model_with_runs.successful_runs == 2

    def test_pass_rate(self, model_with_runs: ModelResult) -> None:
        assert model_with_runs.pass_rate == pytest.approx(2 / 3)

    def test_pass_rate_empty(self) -> None:
        model = ModelResult(model="test/empty")
        assert model.pass_rate == pytest.approx(0.0)

    def test_avg_latency(self, model_with_runs: ModelResult) -> None:
        assert model_with_runs.avg_latency_ms == pytest.approx(1500.0)

    def test_latency_stdev(self, model_with_runs: ModelResult) -> None:
        assert model_with_runs.latency_stdev_ms > 0

    def test_latency_stdev_single_success(self) -> None:
        model = ModelResult(
            model="test/single",
            runs=[
                RunResult(fixture_id="f1", run_number=1, success=True, latency_ms=1000.0),
            ],
        )
        assert model.latency_stdev_ms == pytest.approx(0.0)

    def test_avg_tokens(self, model_with_runs: ModelResult) -> None:
        assert model_with_runs.avg_input_tokens == pytest.approx(110.0)
        assert model_with_runs.avg_output_tokens == pytest.approx(55.0)

    def test_total_tokens(self, model_with_runs: ModelResult) -> None:
        assert model_with_runs.total_input_tokens == 220
        assert model_with_runs.total_output_tokens == 110

    def test_avg_retry_count_zero_when_no_retries(self, model_with_runs: ModelResult) -> None:
        assert model_with_runs.avg_retry_count == pytest.approx(0.0)

    def test_avg_retry_count_with_retries(self) -> None:
        model = ModelResult(
            model="test/m",
            runs=[
                RunResult(
                    fixture_id="f1",
                    run_number=1,
                    success=True,
                    latency_ms=100.0,
                    retry_count=0,
                ),
                RunResult(
                    fixture_id="f1",
                    run_number=2,
                    success=True,
                    latency_ms=200.0,
                    retry_count=2,
                ),
                RunResult(
                    fixture_id="f2",
                    run_number=1,
                    success=False,
                    latency_ms=50.0,
                    retry_count=1,
                ),
            ],
        )
        assert model.avg_retry_count == pytest.approx(1.0)

    def test_retry_count_stdev(self) -> None:
        model = ModelResult(
            model="test/m",
            runs=[
                RunResult(
                    fixture_id="f1",
                    run_number=1,
                    success=True,
                    latency_ms=100.0,
                    retry_count=0,
                ),
                RunResult(
                    fixture_id="f1",
                    run_number=2,
                    success=True,
                    latency_ms=200.0,
                    retry_count=2,
                ),
            ],
        )
        assert model.retry_count_stdev > 0

    def test_retry_count_stdev_single_run(self) -> None:
        model = ModelResult(
            model="test/m",
            runs=[
                RunResult(
                    fixture_id="f1",
                    run_number=1,
                    success=True,
                    latency_ms=100.0,
                    retry_count=3,
                )
            ],
        )
        assert model.retry_count_stdev == pytest.approx(0.0)

    def test_avg_retry_count_none_when_no_measured_samples(self) -> None:
        model = ModelResult(
            model="test/m",
            runs=[
                RunResult(
                    fixture_id="f1",
                    run_number=1,
                    success=False,
                    latency_ms=5.0,
                    retry_count=None,
                ),
                RunResult(
                    fixture_id="f1",
                    run_number=2,
                    success=False,
                    latency_ms=6.0,
                    retry_count=None,
                ),
            ],
        )
        assert model.avg_retry_count is None

    def test_avg_retry_count_genuine_zero_distinct_from_unknown(self) -> None:
        measured = ModelResult(
            model="test/m",
            runs=[
                RunResult(
                    fixture_id="f1",
                    run_number=1,
                    success=True,
                    latency_ms=5.0,
                    retry_count=0,
                ),
                RunResult(
                    fixture_id="f1",
                    run_number=2,
                    success=True,
                    latency_ms=6.0,
                    retry_count=0,
                ),
            ],
        )
        # A measured, genuine zero is 0.0 and must not be conflated with "no data" (None).
        assert measured.avg_retry_count == pytest.approx(0.0)
        assert measured.avg_retry_count is not None

    def test_avg_retry_count_skips_unknown_failures(self) -> None:
        model = ModelResult(
            model="test/m",
            runs=[
                RunResult(
                    fixture_id="f1",
                    run_number=1,
                    success=True,
                    latency_ms=5.0,
                    retry_count=0,
                ),
                RunResult(
                    fixture_id="f1",
                    run_number=2,
                    success=True,
                    latency_ms=6.0,
                    retry_count=2,
                ),
                RunResult(
                    fixture_id="f2",
                    run_number=1,
                    success=False,
                    latency_ms=7.0,
                    retry_count=None,
                ),
            ],
        )
        # Mean over measured samples only: (0 + 2) / 2; the unknown failure is excluded, not counted as 0.
        assert model.avg_retry_count == pytest.approx(1.0)

    def test_retry_count_stdev_none_when_no_measured_samples(self) -> None:
        model = ModelResult(
            model="test/m",
            runs=[
                RunResult(
                    fixture_id="f1",
                    run_number=1,
                    success=False,
                    latency_ms=5.0,
                    retry_count=None,
                )
            ],
        )
        assert model.retry_count_stdev is None

    def test_retry_count_stdev_zero_with_single_measured_sample(self) -> None:
        model = ModelResult(
            model="test/m",
            runs=[
                RunResult(
                    fixture_id="f1",
                    run_number=1,
                    success=True,
                    latency_ms=5.0,
                    retry_count=4,
                ),
                RunResult(
                    fixture_id="f2",
                    run_number=1,
                    success=False,
                    latency_ms=6.0,
                    retry_count=None,
                ),
            ],
        )
        # One measured sample -> 0.0, distinct from None (no measured samples).
        assert model.retry_count_stdev == pytest.approx(0.0)

    def test_retry_count_stdev_measured_only(self) -> None:
        model = ModelResult(
            model="test/m",
            runs=[
                RunResult(
                    fixture_id="f1",
                    run_number=1,
                    success=True,
                    latency_ms=5.0,
                    retry_count=0,
                ),
                RunResult(
                    fixture_id="f1",
                    run_number=2,
                    success=True,
                    latency_ms=6.0,
                    retry_count=2,
                ),
                RunResult(
                    fixture_id="f2",
                    run_number=1,
                    success=False,
                    latency_ms=7.0,
                    retry_count=None,
                ),
            ],
        )
        # Standard deviation of measured {0, 2} only; unknown failure excluded.
        assert model.retry_count_stdev == pytest.approx(2**0.5)


class TestBenchmarkResult:
    """Tests for BenchmarkResult model."""

    @pytest.fixture
    def benchmark(self) -> BenchmarkResult:
        return BenchmarkResult(
            fixtures_used=["f1", "f2"],
            runs_per_fixture=2,
            models={
                "fast/cheap": ModelResult(
                    model="fast/cheap",
                    total_cost_usd=0.01,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=500.0,
                        ),
                        RunResult(
                            fixture_id="f1",
                            run_number=2,
                            success=True,
                            latency_ms=600.0,
                        ),
                    ],
                ),
                "slow/expensive": ModelResult(
                    model="slow/expensive",
                    total_cost_usd=0.10,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=3000.0,
                        ),
                        RunResult(
                            fixture_id="f1",
                            run_number=2,
                            success=True,
                            latency_ms=3500.0,
                        ),
                    ],
                ),
                "unreliable/model": ModelResult(
                    model="unreliable/model",
                    total_cost_usd=0.05,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=1000.0,
                        ),
                        RunResult(
                            fixture_id="f1",
                            run_number=2,
                            success=False,
                            latency_ms=200.0,
                        ),
                        RunResult(
                            fixture_id="f2",
                            run_number=1,
                            success=False,
                            latency_ms=100.0,
                        ),
                        RunResult(
                            fixture_id="f2",
                            run_number=2,
                            success=False,
                            latency_ms=100.0,
                        ),
                    ],
                ),
            },
        )

    def test_total_actual_cost(self, benchmark: BenchmarkResult) -> None:
        assert benchmark.total_actual_cost == pytest.approx(0.16)

    def test_get_fastest_model(self, benchmark: BenchmarkResult) -> None:
        assert benchmark.get_fastest_model() == "fast/cheap"

    def test_get_cheapest_model(self, benchmark: BenchmarkResult) -> None:
        assert benchmark.get_cheapest_model() == "fast/cheap"

    def test_get_most_consistent_model(self, benchmark: BenchmarkResult) -> None:
        assert benchmark.get_most_consistent_model() == "fast/cheap"

    def test_fastest_model_none_when_all_fail(self) -> None:
        result = BenchmarkResult(
            models={
                "bad": ModelResult(
                    model="bad",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=False,
                            latency_ms=100.0,
                        )
                    ],
                ),
            },
        )
        assert result.get_fastest_model() is None

    def test_cheapest_model_none_when_all_fail(self) -> None:
        result = BenchmarkResult(
            models={
                "bad": ModelResult(
                    model="bad",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=False,
                            latency_ms=100.0,
                        )
                    ],
                ),
            },
        )
        assert result.get_cheapest_model() is None

    def test_most_consistent_model_empty(self) -> None:
        result = BenchmarkResult()
        assert result.get_most_consistent_model() is None

    def test_merge_adds_missing_models(self, benchmark: BenchmarkResult) -> None:
        other = BenchmarkResult(
            fixtures_used=["f3"],
            models={"new/model": ModelResult(model="new/model")},
        )
        merged = benchmark.merge(other)
        assert "new/model" in merged.models
        assert "fast/cheap" in merged.models
        assert set(merged.fixtures_used) == {"f1", "f2", "f3"}

    def test_merge_combines_runs_per_model(self) -> None:
        base_run = RunResult(
            fixture_id="f1",
            run_number=1,
            success=True,
            latency_ms=100.0,
            actual_cost_usd=0.01,
        )
        new_run = RunResult(
            fixture_id="f1",
            run_number=2,
            success=True,
            latency_ms=200.0,
            actual_cost_usd=0.02,
        )
        self_result = BenchmarkResult(
            fixtures_used=["f1"],
            models={"m1": ModelResult(model="m1", runs=[base_run])},
        )
        other_result = BenchmarkResult(
            fixtures_used=["f1"],
            models={"m1": ModelResult(model="m1", runs=[new_run])},
        )
        merged = self_result.merge(other_result)
        assert len(merged.models["m1"].runs) == 2
        assert merged.models["m1"].total_cost_usd == pytest.approx(0.03)

    def test_merge_other_wins_on_duplicate_key(self) -> None:
        old_run = RunResult(fixture_id="f1", run_number=1, success=False, latency_ms=999.0)
        new_run = RunResult(fixture_id="f1", run_number=1, success=True, latency_ms=100.0)
        self_result = BenchmarkResult(models={"m1": ModelResult(model="m1", runs=[old_run])})
        other_result = BenchmarkResult(models={"m1": ModelResult(model="m1", runs=[new_run])})
        merged = self_result.merge(other_result)
        assert len(merged.models["m1"].runs) == 1
        assert merged.models["m1"].runs[0].success is True
        assert merged.models["m1"].runs[0].latency_ms == pytest.approx(100.0)

    def test_merge_uses_other_runs_per_fixture(self) -> None:
        self_result = BenchmarkResult(runs_per_fixture=9, fixtures_used=["f1"])
        other_result = BenchmarkResult(runs_per_fixture=3, fixtures_used=["f1"])
        merged = self_result.merge(other_result)
        assert merged.runs_per_fixture == 3

    def test_merge_merges_fixture_checksums(self) -> None:
        self_result = BenchmarkResult(fixture_checksums={"f1": "aaa"})
        other_result = BenchmarkResult(fixture_checksums={"f2": "bbb"})
        merged = self_result.merge(other_result)
        assert merged.fixture_checksums == {"f1": "aaa", "f2": "bbb"}

    def test_filter_to_config_scopes_models(self, benchmark: BenchmarkResult) -> None:
        filtered = benchmark.filter_to_config(["fast/cheap"], ["f1"], 2)
        assert "fast/cheap" in filtered.models
        assert "slow/expensive" not in filtered.models
        assert "unreliable/model" not in filtered.models

    def test_filter_to_config_scopes_fixtures(self, benchmark: BenchmarkResult) -> None:
        filtered = benchmark.filter_to_config(["fast/cheap", "unreliable/model"], ["f1"], 2)
        for runs in [m.runs for m in filtered.models.values()]:
            assert all(r.fixture_id == "f1" for r in runs)

    def test_filter_to_config_scopes_run_numbers(self, benchmark: BenchmarkResult) -> None:
        filtered = benchmark.filter_to_config(["unreliable/model"], ["f1", "f2"], 1)
        for run in filtered.models["unreliable/model"].runs:
            assert run.run_number <= 1

    def test_filter_to_config_preserves_timestamp(self, benchmark: BenchmarkResult) -> None:
        filtered = benchmark.filter_to_config(["fast/cheap"], ["f1"], 2)
        assert filtered.timestamp == benchmark.timestamp

    def test_filter_to_config_updates_fixtures_used(self, benchmark: BenchmarkResult) -> None:
        filtered = benchmark.filter_to_config(["fast/cheap"], ["f1"], 2)
        assert filtered.fixtures_used == ["f1"]

    def test_filter_to_config_excludes_model_with_no_matching_runs(self, benchmark: BenchmarkResult) -> None:
        filtered = benchmark.filter_to_config(["fast/cheap", "slow/expensive"], ["f2"], 2)
        assert "fast/cheap" not in filtered.models

    def test_filter_to_config_empty_when_no_overlap(self, benchmark: BenchmarkResult) -> None:
        filtered = benchmark.filter_to_config(["nonexistent/model"], ["f99"], 1)
        assert filtered.models == {}

    def test_save_and_load(self, benchmark: BenchmarkResult, tmp_path: Path) -> None:
        path = tmp_path / "test_result.json"
        benchmark.save(path)
        assert path.exists()

        loaded = BenchmarkResult.load(path)
        assert len(loaded.models) == len(benchmark.models)
        assert loaded.fixtures_used == benchmark.fixtures_used

    def test_load_validates_schema(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"invalid": "data"}))
        loaded = BenchmarkResult.load(path)
        assert len(loaded.models) == 0

    def test_load_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            BenchmarkResult.load(tmp_path / "nonexistent.json")

    def test_save_no_tmp_file_after_success(self, benchmark: BenchmarkResult, tmp_path: Path) -> None:
        path = tmp_path / "result.json"
        benchmark.save(path)
        assert path.exists()
        assert not path.with_suffix(".tmp").exists()

    def test_save_creates_parent_dirs(self, benchmark: BenchmarkResult, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dir" / "result.json"
        benchmark.save(path)
        assert path.exists()

    def test_save_cleans_tmp_on_failure(self, benchmark: BenchmarkResult, tmp_path: Path) -> None:
        path = tmp_path / "result.json"
        tmp = path.with_suffix(".tmp")
        with (
            patch.object(Path, "replace", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            benchmark.save(path)
        assert not tmp.exists()

    def test_save_atomic_does_not_corrupt_existing(self, benchmark: BenchmarkResult, tmp_path: Path) -> None:
        path = tmp_path / "result.json"
        benchmark.save(path)
        original_content = path.read_text()
        with (
            patch("os.fsync", side_effect=OSError("no space")),
            pytest.raises(OSError, match="no space"),
        ):
            benchmark.save(path)
        assert path.read_text() == original_content

    def test_completed_run_keys_empty(self) -> None:
        result = BenchmarkResult()
        assert result.completed_run_keys() == frozenset()

    def test_completed_run_keys_includes_failed_attempts(self) -> None:
        """Every persisted attempt is final for resume, including failures.

        Old behavior filtered to ``run.success`` so a failed provider/schema
        cell was silently re-run on resume (failure replay bias) and its
        fail-closed budget charge was forgotten. The repaired contract skips
        every attempted cell.
        """
        result = BenchmarkResult(
            models={
                "m1": ModelResult(
                    model="m1",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=100.0,
                        ),
                        RunResult(
                            fixture_id="f1",
                            run_number=2,
                            success=False,
                            latency_ms=50.0,
                        ),
                        RunResult(
                            fixture_id="f2",
                            run_number=1,
                            success=True,
                            latency_ms=200.0,
                        ),
                    ],
                ),
            },
        )
        keys = result.completed_run_keys()
        assert ("m1", "f1", 1) in keys
        assert ("m1", "f1", 2) in keys
        assert ("m1", "f2", 1) in keys
        assert len(keys) == 3

    def test_completed_run_keys_rejects_different_experiment_identity(self) -> None:
        result = BenchmarkResult(
            experiment_fingerprint="experiment-a",
            models={
                "candidate": ModelResult(
                    model="candidate",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=100.0,
                        )
                    ],
                )
            },
        )

        with pytest.raises(ValueError, match="different benchmark experiment"):
            result.completed_run_keys("experiment-b")

    def test_merge_rejects_results_from_different_experiments(self) -> None:
        first = BenchmarkResult(experiment_fingerprint="experiment-a")
        second = BenchmarkResult(experiment_fingerprint="experiment-b")

        with pytest.raises(ValueError, match="different experiments"):
            first.merge(second)

    def test_completed_run_keys_multiple_models(self) -> None:
        result = BenchmarkResult(
            models={
                "m1": ModelResult(
                    model="m1",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=100.0,
                        )
                    ],
                ),
                "m2": ModelResult(
                    model="m2",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=100.0,
                        )
                    ],
                ),
            },
        )
        keys = result.completed_run_keys()
        assert ("m1", "f1", 1) in keys
        assert ("m2", "f1", 1) in keys


class TestChargedCostRules:
    """Per-run budget-charged cost, mirroring the scheduler's fail-closed settlement."""

    def test_known_price_success_charges_actual_cost(self) -> None:
        run = RunResult(
            fixture_id="f1",
            run_number=1,
            success=True,
            latency_ms=10.0,
            actual_cost_usd=0.004,
            reserved_cost_usd=0.05,
        )
        assert run.charged_cost_usd == pytest.approx(0.004)

    def test_unknown_price_success_charges_persisted_reservation(self) -> None:
        # Successful run whose provider cost is unavailable: charge the
        # worst-case reservation, never zero.
        run = RunResult(
            fixture_id="f1",
            run_number=1,
            success=True,
            latency_ms=10.0,
            actual_cost_usd=None,
            reserved_cost_usd=0.05,
        )
        assert run.charged_cost_usd == pytest.approx(0.05)

    def test_dispatched_failure_charges_persisted_reservation(self) -> None:
        run = RunResult(
            fixture_id="f1",
            run_number=1,
            success=False,
            latency_ms=10.0,
            actual_cost_usd=None,
            reserved_cost_usd=0.05,
        )
        assert run.charged_cost_usd == pytest.approx(0.05)

    def test_truncation_failure_with_known_actual_charges_actual(self) -> None:
        # A dispatched truncation records an actual cost even though success=False;
        # it must charge the actual, not the reservation.
        run = RunResult(
            fixture_id="f1",
            run_number=1,
            success=False,
            latency_ms=10.0,
            actual_cost_usd=0.002,
            reserved_cost_usd=0.05,
        )
        assert run.charged_cost_usd == pytest.approx(0.002)

    def test_total_charged_cost_stays_separate_from_total_actual_cost(self) -> None:
        # One known-price success (actual 0.01) and one dispatched failure
        # (reservation 0.10, no actual). Actual reporting must exclude the
        # failure's reservation; charged accounting must include it.
        result = BenchmarkResult(
            models={
                "m1": ModelResult(
                    model="m1",
                    total_cost_usd=0.01,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=True,
                            latency_ms=1.0,
                            actual_cost_usd=0.01,
                            reserved_cost_usd=0.10,
                        ),
                        RunResult(
                            fixture_id="f1",
                            run_number=2,
                            success=False,
                            latency_ms=1.0,
                            actual_cost_usd=None,
                            reserved_cost_usd=0.10,
                        ),
                    ],
                ),
            },
        )
        assert result.total_actual_cost == pytest.approx(0.01)
        assert result.total_charged_cost == pytest.approx(0.11)


class TestBackwardArtifactLoading:
    """Existing artifacts without a persisted charged cost load conservatively."""

    def test_legacy_run_without_charged_field_recomputes_from_reservation(self, tmp_path: Path) -> None:
        # Simulate an artifact written before charged_cost_usd existed: a failed
        # run with only a reservation and no actual cost, and no charged field.
        legacy = {
            "experiment_fingerprint": "legacy-exp",
            "fixtures_used": ["f1"],
            "runs_per_fixture": 1,
            "fixture_checksums": {},
            "models": {
                "m1": {
                    "model": "m1",
                    "total_cost_usd": 0.0,
                    "runs": [
                        {
                            "fixture_id": "f1",
                            "treatment_fingerprint": "t1",
                            "cell_fingerprint": "c1",
                            "run_number": 1,
                            "success": False,
                            "latency_ms": 5.0,
                            "actual_cost_usd": None,
                            "reserved_cost_usd": 0.07,
                        }
                    ],
                }
            },
        }
        path = tmp_path / "legacy.json"
        path.write_text(json.dumps(legacy))
        loaded = _BenchmarkResult.load(path)
        run = loaded.models["m1"].runs[0]
        assert run.charged_cost_usd == pytest.approx(0.07)
        assert loaded.total_charged_cost == pytest.approx(0.07)
        assert loaded.total_actual_cost == pytest.approx(0.0)

    def test_charged_cost_round_trips_through_save_load(self, tmp_path: Path) -> None:
        result = BenchmarkResult(
            models={
                "m1": ModelResult(
                    model="m1",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=False,
                            latency_ms=5.0,
                            actual_cost_usd=None,
                            reserved_cost_usd=0.09,
                        )
                    ],
                )
            },
        )
        path = tmp_path / "result.json"
        result.save(path)
        assert "charged_cost_usd" in json.loads(path.read_text())["models"]["m1"]["runs"][0]
        reloaded = BenchmarkResult.load(path)
        assert reloaded.total_charged_cost == pytest.approx(0.09)

    def test_legacy_artifact_with_integer_retry_counts_loads_and_aggregates(self, tmp_path: Path) -> None:
        # Pre-nullable artifacts stored retry_count as a plain int on every run, failures included.
        legacy = {
            "experiment_fingerprint": "legacy-exp",
            "fixtures_used": ["f1"],
            "runs_per_fixture": 1,
            "fixture_checksums": {},
            "models": {
                "m1": {
                    "model": "m1",
                    "total_cost_usd": 0.0,
                    "runs": [
                        {
                            "fixture_id": "f1",
                            "treatment_fingerprint": "t1",
                            "cell_fingerprint": "c1",
                            "run_number": 1,
                            "success": True,
                            "latency_ms": 5.0,
                            "retry_count": 0,
                        },
                        {
                            "fixture_id": "f1",
                            "treatment_fingerprint": "t1",
                            "cell_fingerprint": "c2",
                            "run_number": 2,
                            "success": True,
                            "latency_ms": 6.0,
                            "retry_count": 2,
                        },
                        {
                            "fixture_id": "f1",
                            "treatment_fingerprint": "t1",
                            "cell_fingerprint": "c3",
                            "run_number": 3,
                            "success": False,
                            "latency_ms": 7.0,
                            "retry_count": 1,
                        },
                    ],
                }
            },
        }
        path = tmp_path / "legacy.json"
        path.write_text(json.dumps(legacy))
        loaded = _BenchmarkResult.load(path)
        model = loaded.models["m1"]
        assert [r.retry_count for r in model.runs] == [0, 2, 1]
        assert model.avg_retry_count == pytest.approx(1.0)

    def test_legacy_failure_without_retry_field_defaults_to_zero(self, tmp_path: Path) -> None:
        # An old failure run that omits retry_count loads as the int default 0, not None.
        legacy = {
            "experiment_fingerprint": "legacy-exp",
            "fixtures_used": ["f1"],
            "runs_per_fixture": 1,
            "fixture_checksums": {},
            "models": {
                "m1": {
                    "model": "m1",
                    "total_cost_usd": 0.0,
                    "runs": [
                        {
                            "fixture_id": "f1",
                            "treatment_fingerprint": "t1",
                            "cell_fingerprint": "c1",
                            "run_number": 1,
                            "success": False,
                            "latency_ms": 5.0,
                        }
                    ],
                }
            },
        }
        path = tmp_path / "legacy.json"
        path.write_text(json.dumps(legacy))
        loaded = _BenchmarkResult.load(path)
        assert loaded.models["m1"].runs[0].retry_count == 0

    def test_nullable_unknown_retry_round_trips_through_save_load(self, tmp_path: Path) -> None:
        result = BenchmarkResult(
            models={
                "m1": ModelResult(
                    model="m1",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=False,
                            latency_ms=5.0,
                            retry_count=None,
                        )
                    ],
                )
            },
        )
        path = tmp_path / "result.json"
        result.save(path)
        dumped = json.loads(path.read_text())["models"]["m1"]["runs"][0]
        assert dumped["retry_count"] is None
        reloaded = BenchmarkResult.load(path)
        assert reloaded.models["m1"].runs[0].retry_count is None


class TestResumeAccountingPreservation:
    """merge and config scoping must preserve failed attempts and their charges."""

    def test_merge_preserves_failed_reservation_in_charged_total(self) -> None:
        failed = RunResult(
            fixture_id="f1",
            run_number=1,
            success=False,
            latency_ms=5.0,
            actual_cost_usd=None,
            reserved_cost_usd=0.08,
        )
        succeeded = RunResult(
            fixture_id="f2",
            run_number=1,
            success=True,
            latency_ms=5.0,
            actual_cost_usd=0.01,
            reserved_cost_usd=0.08,
        )
        base = BenchmarkResult(models={"m1": ModelResult(model="m1", runs=[failed])})
        other = BenchmarkResult(models={"m1": ModelResult(model="m1", runs=[succeeded])})
        merged = base.merge(other)
        # Both attempts survive the merge and both charges are accounted for.
        assert merged.completed_run_keys() == frozenset({("m1", "f1", 1), ("m1", "f2", 1)})
        assert merged.total_charged_cost == pytest.approx(0.09)

    def test_filter_to_config_retains_failed_attempts_and_charge(self) -> None:
        result = BenchmarkResult(
            models={
                "m1": ModelResult(
                    model="m1",
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            run_number=1,
                            success=False,
                            latency_ms=5.0,
                            actual_cost_usd=None,
                            reserved_cost_usd=0.06,
                        ),
                        RunResult(
                            fixture_id="f1",
                            run_number=2,
                            success=True,
                            latency_ms=5.0,
                            actual_cost_usd=0.02,
                            reserved_cost_usd=0.06,
                        ),
                    ],
                )
            },
        )
        scoped = result.filter_to_config(["m1"], ["f1"], 2)
        # The failed attempt is retained so resume still skips it and its charge survives.
        assert scoped.completed_run_keys() == frozenset({("m1", "f1", 1), ("m1", "f1", 2)})
        assert scoped.total_charged_cost == pytest.approx(0.08)


class TestSaveDurability:
    """save() must be checkpoint-durable: fsync the file, atomic replace, then fsync the parent dir."""

    @staticmethod
    def _result() -> BenchmarkResult:
        return BenchmarkResult(
            models={
                "m1": ModelResult(
                    model="m1",
                    runs=[RunResult(fixture_id="f1", run_number=1, success=True, latency_ms=5.0)],
                )
            },
        )

    def _instrumented_save(self, result: BenchmarkResult, path: Path) -> list[str]:
        """Run save() while recording fsync/replace ordering; returns the ordered event list."""
        events: list[str] = []
        real_replace = os.replace

        def record_replace(src: object, dst: object) -> None:
            events.append("replace")
            real_replace(src, dst)  # type: ignore[arg-type]

        def record_fsync(_fd: object) -> None:
            events.append("fsync")

        with (
            patch("os.fsync", side_effect=record_fsync),
            patch("os.replace", side_effect=record_replace),
        ):
            result.save(path)
        return events

    def test_save_fsyncs_file_then_replaces_then_fsyncs_parent_dir(self, tmp_path: Path) -> None:
        path = tmp_path / "result.json"
        events = self._instrumented_save(self._result(), path)
        assert "replace" in events
        replace_idx = events.index("replace")
        assert "fsync" in events[:replace_idx], "file must be fsynced before the atomic replace"
        assert "fsync" in events[replace_idx + 1 :], "parent directory must be fsynced after the replace"
        # Data landed atomically at the final path.
        assert BenchmarkResult.load(path).models["m1"].model == "m1"

    def test_save_leaves_no_temp_file(self, tmp_path: Path) -> None:
        path = tmp_path / "result.json"
        self._instrumented_save(self._result(), path)
        assert path.exists()
        assert not path.with_suffix(".tmp").exists()

    def test_save_cleans_temp_when_fsync_fails(self, tmp_path: Path) -> None:
        path = tmp_path / "result.json"
        with (
            patch("os.fsync", side_effect=OSError("disk gone")),
            pytest.raises(OSError, match="disk gone"),
        ):
            self._result().save(path)
        assert not path.with_suffix(".tmp").exists()
        assert not path.exists()

    def test_save_cleans_temp_when_replace_fails(self, tmp_path: Path) -> None:
        path = tmp_path / "result.json"
        with (
            patch("os.replace", side_effect=OSError("rename failed")),
            pytest.raises(OSError, match="rename failed"),
        ):
            self._result().save(path)
        assert not path.with_suffix(".tmp").exists()
        assert not path.exists()

    def test_save_preserves_existing_target_on_crash(self, tmp_path: Path) -> None:
        path = tmp_path / "result.json"
        self._result().save(path)
        original = path.read_text()
        newer = BenchmarkResult(models={"m2": ModelResult(model="m2", runs=[])})
        with (
            patch("os.replace", side_effect=KeyboardInterrupt),
            pytest.raises(KeyboardInterrupt),
        ):
            newer.save(path)
        assert path.read_text() == original
        assert not path.with_suffix(".tmp").exists()
