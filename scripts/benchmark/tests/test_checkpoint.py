"""Tests for evaluation checkpoint persistence and resume support."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from unittest.mock import patch

import pytest

from llm_benchmark.engine.checkpoint import (
    CheckpointManager,
    EvaluationCheckpoint,
    JudgeCheckpoint,
    JudgmentRecord,
    compute_eval_config_fingerprint,
)
from llm_benchmark.schemas.judge import CategoryScore, PointwiseJudgment


def _make_judgment(*, score: int = 80) -> PointwiseJudgment:
    """Build a minimal valid PointwiseJudgment for testing.

    Args:
        score: Score applied uniformly across all categories.

    Returns:
        A valid PointwiseJudgment instance.
    """
    cat = CategoryScore(score=score, reasoning="Solid extraction quality across all fields")
    return PointwiseJudgment(
        inference_reasonableness=cat,
        description_quality=cat,
        downstream_usefulness=cat,
        summary="Good residual quality with minor issues in edge cases",
    )


def _judgment_score(record: JudgmentRecord) -> int:
    """Return the score from a record expected to contain a successful judgment."""
    judgment = record.judgment
    assert judgment is not None
    return judgment.inference_reasonableness.score


class TestJudgmentRecord:
    """Tests for JudgmentRecord model."""

    def test_task_key_format(self) -> None:
        record = JudgmentRecord(
            model_name="openrouter:test/model",
            fixture_id="senior_python_remote",
            run_number=2,
            judgment=_make_judgment(),
            cost_usd=0.001,
            charged_cost_usd=0.001,
        )
        assert record.task_key == "openrouter:test/model::senior_python_remote::2"

    def test_serialization_roundtrip(self) -> None:
        record = JudgmentRecord(
            model_name="model-a",
            fixture_id="f1",
            run_number=1,
            judgment=_make_judgment(score=90),
            cost_usd=0.0025,
            charged_cost_usd=0.0025,
        )
        json_str = record.model_dump_json()
        restored = JudgmentRecord.model_validate_json(json_str)
        assert restored.task_key == record.task_key
        assert restored.cost_usd == pytest.approx(0.0025)
        assert _judgment_score(restored) == 90


class TestJudgeCheckpoint:
    """Tests for JudgeCheckpoint model."""

    def test_completed_task_keys_empty(self) -> None:
        jc = JudgeCheckpoint(
            judge_model="test-judge",
            reasoning_effort="high",
            records=[],
            total_cost_usd=0.0,
        )
        assert jc.completed_task_keys == frozenset()

    def test_completed_task_keys_populated(self) -> None:
        records = [
            JudgmentRecord(
                model_name="m1",
                fixture_id="f1",
                run_number=1,
                judgment=_make_judgment(),
                cost_usd=0.001,
                charged_cost_usd=0.001,
            ),
            JudgmentRecord(
                model_name="m2",
                fixture_id="f1",
                run_number=1,
                judgment=_make_judgment(),
                cost_usd=0.002,
                charged_cost_usd=0.002,
            ),
        ]
        jc = JudgeCheckpoint(
            judge_model="test-judge",
            reasoning_effort="high",
            records=records,
            total_cost_usd=0.003,
        )
        expected = frozenset({"m1::f1::1", "m2::f1::1"})
        assert jc.completed_task_keys == expected

    def test_to_judgments_by_model(self) -> None:
        j1 = _make_judgment(score=80)
        j2 = _make_judgment(score=90)
        records = [
            JudgmentRecord(
                model_name="m1",
                fixture_id="f1",
                run_number=1,
                judgment=j1,
                cost_usd=0.001,
                charged_cost_usd=0.001,
            ),
            JudgmentRecord(
                model_name="m1",
                fixture_id="f2",
                run_number=1,
                judgment=j2,
                cost_usd=0.002,
                charged_cost_usd=0.002,
            ),
            JudgmentRecord(
                model_name="m2",
                fixture_id="f1",
                run_number=1,
                judgment=j1,
                cost_usd=0.001,
                charged_cost_usd=0.001,
            ),
        ]
        jc = JudgeCheckpoint(
            judge_model="test-judge",
            reasoning_effort="high",
            records=records,
            total_cost_usd=0.004,
        )
        result = jc.to_judgments_by_model()
        assert len(result) == 2
        assert len(result["m1"]) == 2
        assert len(result["m2"]) == 1


class TestComputeEvalConfigFingerprint:
    """Tests for compute_eval_config_fingerprint function."""

    def test_deterministic(self) -> None:
        fp1 = compute_eval_config_fingerprint(
            benchmark_timestamp="2026-03-09T12:00:00",
            max_runs_per_fixture=3,
            min_pass_rate=0.5,
            fixtures=["f1", "f2"],
            judge_models=["judge-a"],
        )
        fp2 = compute_eval_config_fingerprint(
            benchmark_timestamp="2026-03-09T12:00:00",
            max_runs_per_fixture=3,
            min_pass_rate=0.5,
            fixtures=["f1", "f2"],
            judge_models=["judge-a"],
        )
        assert fp1 == fp2

    def test_different_max_runs_changes_fingerprint(self) -> None:
        fp1 = compute_eval_config_fingerprint(
            benchmark_timestamp="2026-03-09T12:00:00",
            max_runs_per_fixture=3,
            min_pass_rate=0.5,
            fixtures=["f1"],
            judge_models=["judge-a"],
        )
        fp2 = compute_eval_config_fingerprint(
            benchmark_timestamp="2026-03-09T12:00:00",
            max_runs_per_fixture=5,
            min_pass_rate=0.5,
            fixtures=["f1"],
            judge_models=["judge-a"],
        )
        assert fp1 != fp2

    def test_different_fixtures_changes_fingerprint(self) -> None:
        fp1 = compute_eval_config_fingerprint(
            benchmark_timestamp="2026-03-09T12:00:00",
            max_runs_per_fixture=3,
            min_pass_rate=0.5,
            fixtures=["f1"],
            judge_models=["judge-a"],
        )
        fp2 = compute_eval_config_fingerprint(
            benchmark_timestamp="2026-03-09T12:00:00",
            max_runs_per_fixture=3,
            min_pass_rate=0.5,
            fixtures=["f1", "f2"],
            judge_models=["judge-a"],
        )
        assert fp1 != fp2

    def test_fixture_order_does_not_matter(self) -> None:
        fp1 = compute_eval_config_fingerprint(
            benchmark_timestamp="2026-03-09T12:00:00",
            max_runs_per_fixture=3,
            min_pass_rate=0.5,
            fixtures=["f1", "f2"],
            judge_models=["judge-a"],
        )
        fp2 = compute_eval_config_fingerprint(
            benchmark_timestamp="2026-03-09T12:00:00",
            max_runs_per_fixture=3,
            min_pass_rate=0.5,
            fixtures=["f2", "f1"],
            judge_models=["judge-a"],
        )
        assert fp1 == fp2

    def test_returns_hex_string(self) -> None:
        fp = compute_eval_config_fingerprint(
            benchmark_timestamp="ts",
            max_runs_per_fixture=3,
            min_pass_rate=0.5,
            fixtures=["f1"],
            judge_models=["j1"],
        )
        assert len(fp) == 16
        int(fp, 16)


class TestCheckpointManager:
    """Tests for CheckpointManager lifecycle and operations."""

    def _make_manager(self, tmp_path: Path, *, fingerprint: str = "abc123") -> CheckpointManager:
        result_file = tmp_path / "benchmark_test.json"
        result_file.write_text("{}")
        return CheckpointManager(result_file, fingerprint)

    def test_fresh_init_no_progress(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        assert not mgr.has_progress
        assert mgr.total_completed == 0

    def test_record_judgment_persists_to_disk(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        mgr.record_judgment(
            judge_model="judge-a",
            reasoning_effort="high",
            model_name="model-1",
            fixture_id="f1",
            run_number=1,
            judgment=_make_judgment(),
            cost_usd=0.001,
        )
        assert mgr.has_progress
        assert mgr.total_completed == 1
        assert mgr.path.exists()

        loaded = EvaluationCheckpoint.model_validate_json(mgr.path.read_text())
        assert "judge-a" in loaded.judges
        assert len(loaded.judges["judge-a"].records) == 1

    def test_completed_keys_for_judge(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        mgr.record_judgment(
            "judge-a",
            "high",
            "m1",
            "f1",
            1,
            _make_judgment(),
            0.001,
        )
        mgr.record_judgment(
            "judge-a",
            "high",
            "m2",
            "f1",
            1,
            _make_judgment(),
            0.002,
        )
        keys = mgr.completed_keys_for_judge("judge-a")
        assert keys == frozenset({"m1::f1::1", "m2::f1::1"})

    def test_completed_keys_for_unknown_judge(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        assert mgr.completed_keys_for_judge("nonexistent") == frozenset()

    def test_existing_judgments_for_judge(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        j1 = _make_judgment(score=80)
        j2 = _make_judgment(score=90)
        mgr.record_judgment("judge-a", "high", "m1", "f1", 1, j1, 0.001)
        mgr.record_judgment("judge-a", "high", "m1", "f2", 1, j2, 0.002)

        judgments = mgr.existing_judgments_for_judge("judge-a")
        assert "m1" in judgments
        assert len(judgments["m1"]) == 2

    def test_existing_cost_for_judge(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        mgr.record_judgment("judge-a", "high", "m1", "f1", 1, _make_judgment(), 0.001)
        mgr.record_judgment("judge-a", "high", "m2", "f1", 1, _make_judgment(), 0.003)
        assert mgr.existing_cost_for_judge("judge-a") == pytest.approx(0.004)

    def test_existing_judgments_for_unknown_judge(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        assert mgr.existing_judgments_for_judge("nonexistent") == {}

    def test_completed_count_for_unknown_judge(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        assert mgr.completed_count_for_judge("nonexistent") == 0

    def test_existing_cost_for_unknown_judge(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        assert mgr.existing_cost_for_judge("nonexistent") == pytest.approx(0.0)

    def test_completed_count_for_judge(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        mgr.record_judgment("judge-a", "high", "m1", "f1", 1, _make_judgment(), 0.001)
        mgr.record_judgment("judge-a", "high", "m1", "f2", 1, _make_judgment(), 0.002)
        mgr.record_judgment("judge-b", "medium", "m1", "f1", 1, _make_judgment(), 0.003)
        assert mgr.completed_count_for_judge("judge-a") == 2
        assert mgr.completed_count_for_judge("judge-b") == 1

    def test_total_completed_across_judges(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        mgr.record_judgment("judge-a", "high", "m1", "f1", 1, _make_judgment(), 0.001)
        mgr.record_judgment("judge-b", "high", "m1", "f1", 1, _make_judgment(), 0.002)
        assert mgr.total_completed == 2

    def test_cleanup_removes_checkpoint_file(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        mgr.record_judgment("judge-a", "high", "m1", "f1", 1, _make_judgment(), 0.001)
        assert mgr.path.exists()
        mgr.cleanup()
        assert not mgr.path.exists()

    def test_cleanup_no_error_when_no_file(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        mgr.cleanup()

    def test_resume_loads_existing_checkpoint(self, tmp_path: Path) -> None:
        result_file = tmp_path / "benchmark_test.json"
        result_file.write_text("{}")
        fingerprint = "fp123"

        mgr1 = CheckpointManager(result_file, fingerprint)
        mgr1.record_judgment("judge-a", "high", "m1", "f1", 1, _make_judgment(), 0.005)
        mgr1.record_judgment("judge-a", "high", "m2", "f1", 1, _make_judgment(), 0.003)

        mgr2 = CheckpointManager(result_file, fingerprint)
        assert mgr2.has_progress
        assert mgr2.total_completed == 2
        assert mgr2.existing_cost_for_judge("judge-a") == pytest.approx(0.008)

    def test_rejects_checkpoint_with_wrong_fingerprint(self, tmp_path: Path) -> None:
        result_file = tmp_path / "benchmark_test.json"
        result_file.write_text("{}")

        mgr1 = CheckpointManager(result_file, "fingerprint-v1")
        mgr1.record_judgment("judge-a", "high", "m1", "f1", 1, _make_judgment(), 0.001)

        mgr2 = CheckpointManager(result_file, "fingerprint-v2")
        assert not mgr2.has_progress
        assert mgr2.total_completed == 0

    def test_rejects_corrupt_checkpoint(self, tmp_path: Path) -> None:
        result_file = tmp_path / "benchmark_test.json"
        result_file.write_text("{}")
        checkpoint_path = result_file.with_suffix(".eval.checkpoint.json")
        checkpoint_path.write_text("NOT VALID JSON {{{")

        mgr = CheckpointManager(result_file, "fp")
        assert not mgr.has_progress
        assert mgr.total_completed == 0

    def test_resume_summary_format(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        mgr.record_judgment(
            "openrouter:google/gemini-3-flash",
            "high",
            "m1",
            "f1",
            1,
            _make_judgment(),
            0.001,
        )
        summary = mgr.resume_summary()
        assert "gemini-3-flash" in summary
        assert "1 judgments" in summary
        assert "$0.0010" in summary

    def test_duplicate_identity_replaces_in_constant_size_before_and_after_reload(self, tmp_path: Path) -> None:
        result_file = tmp_path / "benchmark_test.json"
        result_file.write_text("{}")
        manager = CheckpointManager(result_file, "identity-v1")
        manager.record_judgment("judge-a", "high", "treatment-a", "fixture-a", 1, _make_judgment(score=60), 0.01)
        manager.record_judgment("judge-a", "high", "treatment-a", "fixture-a", 1, _make_judgment(score=70), 0.02)

        assert manager.completed_count_for_judge("judge-a") == 1
        assert manager.existing_cost_for_judge("judge-a") == pytest.approx(0.02)
        assert _judgment_score(manager.existing_records_for_judge("judge-a")[0]) == 70

        recovered = CheckpointManager(result_file, "identity-v1")
        recovered.record_judgment("judge-a", "high", "treatment-a", "fixture-a", 1, _make_judgment(score=90), 0.03)

        assert recovered.completed_keys_for_judge("judge-a") == frozenset({"treatment-a::fixture-a::1"})
        assert recovered.completed_count_for_judge("judge-a") == 1
        assert recovered.existing_cost_for_judge("judge-a") == pytest.approx(0.03)
        assert _judgment_score(recovered.existing_records_for_judge("judge-a")[0]) == 90

    def test_resume_summary_no_progress(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        assert "(no progress)" in mgr.resume_summary()

    def test_path_derived_from_result_file(self, tmp_path: Path) -> None:
        result_file = tmp_path / "benchmark_test.json"
        result_file.write_text("{}")
        mgr = CheckpointManager(result_file, "fp")
        assert mgr.path == tmp_path / "benchmark_test.eval.checkpoint.json"


@dataclass(frozen=True)
class _FingerprintConfig:
    """Typed evaluation-config inputs for compute_eval_config_fingerprint."""

    benchmark_timestamp: str = "2026-03-09T12:00:00"
    max_runs_per_fixture: int = 3
    min_pass_rate: float = 0.5
    fixtures: list[str] = field(default_factory=lambda: ["f1", "f2"])
    judge_models: list[str] = field(default_factory=lambda: ["judge-a"])
    cost_cap_usd: float | None = 2.0
    unknown_price_max_usd: float | None = 0.125

    def fingerprint(self) -> str:
        return compute_eval_config_fingerprint(
            benchmark_timestamp=self.benchmark_timestamp,
            max_runs_per_fixture=self.max_runs_per_fixture,
            min_pass_rate=self.min_pass_rate,
            fixtures=self.fixtures,
            judge_models=self.judge_models,
            cost_cap_usd=self.cost_cap_usd,
            unknown_price_max_usd=self.unknown_price_max_usd,
        )


_RESUME_DIMENSION_MUTATIONS: dict[str, Callable[[_FingerprintConfig], _FingerprintConfig]] = {
    "benchmark_timestamp": lambda c: replace(c, benchmark_timestamp="2026-03-10T12:00:00"),
    "max_runs_per_fixture": lambda c: replace(c, max_runs_per_fixture=4),
    "min_pass_rate": lambda c: replace(c, min_pass_rate=0.75),
    "fixtures": lambda c: replace(c, fixtures=["f1", "f3"]),
    "judge_models": lambda c: replace(c, judge_models=["judge-b"]),
    "cost_cap_usd": lambda c: replace(c, cost_cap_usd=3.0),
    "unknown_price_max_usd": lambda c: replace(c, unknown_price_max_usd=0.25),
}


@pytest.mark.parametrize(
    "mutate",
    _RESUME_DIMENSION_MUTATIONS.values(),
    ids=_RESUME_DIMENSION_MUTATIONS.keys(),
)
def test_evaluation_fingerprint_covers_every_resume_semantic(
    mutate: Callable[[_FingerprintConfig], _FingerprintConfig],
) -> None:
    baseline = _FingerprintConfig()

    assert baseline.fingerprint() != mutate(baseline).fingerprint()


def test_evaluation_fingerprint_ignores_only_set_order() -> None:
    ordered = _FingerprintConfig(
        fixtures=["f1", "f2"],
        judge_models=["judge-a", "judge-b"],
    )
    reordered = _FingerprintConfig(
        fixtures=["f2", "f1"],
        judge_models=["judge-b", "judge-a"],
    )

    assert ordered.fingerprint() == reordered.fingerprint()


def test_checkpoint_resume_preserves_exact_judgment_units(tmp_path: Path) -> None:
    result_file = tmp_path / "benchmark.json"
    result_file.write_text("{}")
    manager = CheckpointManager(result_file, "exact-units")
    manager.record_judgment("judge-a", "high", "candidate-a", "fixture-1", 2, _make_judgment(score=61), 0.011)
    manager.record_judgment("judge-a", "high", "candidate-a", "fixture-2", 1, _make_judgment(score=93), 0.017)

    records = CheckpointManager(result_file, "exact-units").existing_records_for_judge("judge-a")

    assert [
        (
            record.model_name,
            record.fixture_id,
            record.run_number,
            _judgment_score(record),
            record.cost_usd,
        )
        for record in records
    ] == [
        ("candidate-a", "fixture-1", 2, 61, 0.011),
        ("candidate-a", "fixture-2", 1, 93, 0.017),
    ]


def test_failed_atomic_replace_recovers_last_durable_checkpoint(tmp_path: Path) -> None:
    result_file = tmp_path / "benchmark.json"
    result_file.write_text("{}")
    manager = CheckpointManager(result_file, "durable")
    manager.record_judgment("judge-a", "high", "candidate-a", "fixture-1", 1, _make_judgment(score=70), 0.01)

    with (
        patch.object(Path, "replace", side_effect=OSError("synthetic interrupted replace")),
        pytest.raises(OSError, match="interrupted replace"),
    ):
        manager.record_judgment("judge-a", "high", "candidate-a", "fixture-2", 1, _make_judgment(score=90), 0.02)

    recovered = CheckpointManager(result_file, "durable")
    assert recovered.completed_keys_for_judge("judge-a") == frozenset({"candidate-a::fixture-1::1"})
    assert recovered.existing_cost_for_judge("judge-a") == pytest.approx(0.01)
    assert not manager.path.with_suffix(".tmp").exists()


def test_failed_file_fsync_recovers_last_durable_checkpoint(tmp_path: Path) -> None:
    result_file = tmp_path / "benchmark.json"
    result_file.write_text("{}")
    manager = CheckpointManager(result_file, "fsync-durable")
    manager.record_judgment("judge-a", "high", "candidate-a", "fixture-1", 1, _make_judgment(score=70), 0.01)

    with (
        patch("llm_benchmark.engine.checkpoint.os.fsync", side_effect=OSError("synthetic fsync failure")),
        pytest.raises(OSError, match="fsync failure"),
    ):
        manager.record_judgment("judge-a", "high", "candidate-a", "fixture-2", 1, _make_judgment(score=90), 0.02)

    recovered = CheckpointManager(result_file, "fsync-durable")
    assert recovered.completed_keys_for_judge("judge-a") == frozenset({"candidate-a::fixture-1::1"})
    assert not manager.path.with_suffix(".tmp").exists()


def test_corrupt_checkpoint_is_replaced_by_next_valid_record(tmp_path: Path) -> None:
    result_file = tmp_path / "benchmark.json"
    result_file.write_text("{}")
    checkpoint_path = result_file.with_suffix(".eval.checkpoint.json")
    checkpoint_path.write_text('{"judges":')

    manager = CheckpointManager(result_file, "recovery")
    manager.record_judgment("judge-a", "high", "candidate-a", "fixture-1", 1, _make_judgment(score=84), 0.012)
    recovered = CheckpointManager(result_file, "recovery")

    assert recovered.completed_keys_for_judge("judge-a") == frozenset({"candidate-a::fixture-1::1"})
    assert _judgment_score(recovered.existing_records_for_judge("judge-a")[0]) == 84


def test_duplicate_identity_lookup_does_not_scan_persisted_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_file = tmp_path / "benchmark.json"
    result_file.write_text("{}")
    manager = CheckpointManager(result_file, "indexed")
    for run_number in range(1, 5):
        manager.record_judgment(
            "judge-a", "high", "candidate-a", "fixture-1", run_number, _make_judgment(score=60), 0.01
        )

    original_task_key = JudgmentRecord.task_key.fget
    assert original_task_key is not None
    task_key_reads = 0

    def counted_task_key(record: JudgmentRecord) -> str:
        nonlocal task_key_reads
        task_key_reads += 1
        return original_task_key(record)

    monkeypatch.setattr(JudgmentRecord, "task_key", property(counted_task_key))
    manager.record_judgment("judge-a", "high", "candidate-a", "fixture-1", 3, _make_judgment(score=99), 0.025)

    assert task_key_reads == 1
    assert manager.completed_count_for_judge("judge-a") == 4
    assert manager.existing_cost_for_judge("judge-a") == pytest.approx(0.055)


def test_record_failure_persists_dispatched_attempt_with_charge(tmp_path: Path) -> None:
    result_file = tmp_path / "benchmark.json"
    result_file.write_text("{}")
    manager = CheckpointManager(result_file, "failures")
    manager.record_failure("judge-a", "high", "cand-a", "fix-1", 1, charged_cost_usd=0.02)

    assert manager.completed_keys_for_judge("judge-a") == frozenset({"cand-a::fix-1::1"})
    assert manager.existing_charged_for_judge("judge-a") == pytest.approx(0.02)
    assert manager.existing_cost_for_judge("judge-a") == pytest.approx(0.0)
    record = manager.existing_records_for_judge("judge-a")[0]
    assert record.judgment is None
    assert record.cost_usd == pytest.approx(0.0)
    assert record.charged_cost_usd == pytest.approx(0.02)


def test_failure_excluded_from_judgments_but_counts_as_completed(tmp_path: Path) -> None:
    result_file = tmp_path / "benchmark.json"
    result_file.write_text("{}")
    manager = CheckpointManager(result_file, "mixed")
    manager.record_judgment("judge-a", "high", "cand-a", "fix-1", 1, _make_judgment(score=80), 0.01)
    manager.record_failure("judge-a", "high", "cand-a", "fix-2", 1, charged_cost_usd=0.03)

    assert manager.completed_count_for_judge("judge-a") == 2
    judgments = manager.existing_judgments_for_judge("judge-a")
    assert sum(len(v) for v in judgments.values()) == 1


def test_charged_and_actual_costs_tracked_separately(tmp_path: Path) -> None:
    result_file = tmp_path / "benchmark.json"
    result_file.write_text("{}")
    manager = CheckpointManager(result_file, "split")
    manager.record_judgment("judge-a", "high", "cand-a", "fix-1", 1, _make_judgment(), 0.01)
    manager.record_failure("judge-a", "high", "cand-a", "fix-2", 1, charged_cost_usd=0.04)

    assert manager.existing_cost_for_judge("judge-a") == pytest.approx(0.01)
    assert manager.existing_charged_for_judge("judge-a") == pytest.approx(0.05)


def test_resume_skips_failed_task_and_carries_charge_across_reload(tmp_path: Path) -> None:
    result_file = tmp_path / "benchmark.json"
    result_file.write_text("{}")
    CheckpointManager(result_file, "resume").record_failure(
        "judge-a", "high", "cand-a", "fix-1", 1, charged_cost_usd=0.02
    )

    reloaded = CheckpointManager(result_file, "resume")
    # A dispatched failure counts as completed so resume skips it -- no auto-retry.
    assert "cand-a::fix-1::1" in reloaded.completed_keys_for_judge("judge-a")
    assert reloaded.existing_charged_for_judge("judge-a") == pytest.approx(0.02)
    assert reloaded.existing_cost_for_judge("judge-a") == pytest.approx(0.0)


def test_failed_attempt_durably_persisted_and_reloaded(tmp_path: Path) -> None:
    result_file = tmp_path / "benchmark.json"
    result_file.write_text("{}")
    CheckpointManager(result_file, "durable-fail").record_failure(
        "judge-a", "high", "cand-a", "fix-1", 1, charged_cost_usd=0.09
    )

    loaded = EvaluationCheckpoint.model_validate_json((result_file.with_suffix(".eval.checkpoint.json")).read_text())
    record = loaded.judges["judge-a"].records[0]
    assert record.judgment is None
    assert record.charged_cost_usd == pytest.approx(0.09)


def test_success_charged_can_exceed_actual_for_unknown_price(tmp_path: Path) -> None:
    # An unknown-price success bills actual=0 but seeds the budget from the reservation.
    result_file = tmp_path / "benchmark.json"
    result_file.write_text("{}")
    manager = CheckpointManager(result_file, "unknown-price")
    manager.record_judgment("judge-a", "high", "cand-a", "fix-1", 1, _make_judgment(), 0.0, charged_cost_usd=0.5)

    assert manager.existing_cost_for_judge("judge-a") == pytest.approx(0.0)
    assert manager.existing_charged_for_judge("judge-a") == pytest.approx(0.5)
