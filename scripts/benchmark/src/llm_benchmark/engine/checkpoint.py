"""Evaluation checkpoint persistence for resume support.

Provides incremental persistence of LLM-as-judge evaluation results,
enabling resume after interruption without losing completed work.
Checkpoint data is stored alongside benchmark results and cleaned up
after successful completion.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from llm_benchmark.schemas.judge import PointwiseJudgment

_CHECKPOINT_SUFFIX: str = ".eval.checkpoint.json"


class JudgmentRecord(BaseModel):
    """Single attempt with task metadata for checkpoint persistence.

    A record is a genuine dispatched attempt: successes carry a ``judgment``
    and their actual cost; dispatched failures carry ``judgment=None`` with a
    fail-closed reservation charge and zero actual cost. Budget-rejected
    non-dispatches are never recorded.

    Attributes:
        model_name: Name of the model being evaluated.
        fixture_id: Test fixture identifier.
        run_number: Run number within the model/fixture combo.
        judgment: Structured pointwise judgment, or ``None`` for a failed attempt.
        cost_usd: Actual provider cost for this call (``0.0`` for failures).
        charged_cost_usd: Budget-charged cost (fail-closed reservation for
            failures). ``None`` in legacy checkpoints, where it defaults to
            ``cost_usd`` via :attr:`charged_cost`.
    """

    model_name: str
    fixture_id: str
    run_number: int
    judgment: PointwiseJudgment | None = None
    cost_usd: float = 0.0
    charged_cost_usd: float | None = None

    @property
    def charged_cost(self) -> float:
        """Budget-charged cost, defaulting to actual cost for legacy records."""
        return self.charged_cost_usd if self.charged_cost_usd is not None else self.cost_usd

    @property
    def task_key(self) -> str:
        """Composite key uniquely identifying this evaluation task."""
        return f"{self.model_name}::{self.fixture_id}::{self.run_number}"


class JudgeCheckpoint(BaseModel):
    """Checkpoint for a single judge's evaluation progress.

    Attributes:
        judge_model: Fully qualified judge model identifier.
        reasoning_effort: Reasoning effort level used for this judge.
        records: Completed judgment records with full task metadata.
        total_cost_usd: Accumulated actual provider cost for completed judgments.
    """

    judge_model: str
    reasoning_effort: str
    records: list[JudgmentRecord]
    total_cost_usd: float

    @property
    def completed_task_keys(self) -> frozenset[str]:
        """Set of task keys for all completed attempts (successes and failures)."""
        return frozenset(r.task_key for r in self.records)

    @property
    def total_charged_cost_usd(self) -> float:
        """Accumulated budget-charged cost across attempts (incl. failures)."""
        return sum(r.charged_cost for r in self.records)

    def to_judgments_by_model(self) -> dict[str, list[PointwiseJudgment]]:
        """Convert successful records to the judgments_by_model format.

        Returns:
            Mapping of model name to list of pointwise judgments. Failed
            attempts (``judgment is None``) are excluded.
        """
        result: dict[str, list[PointwiseJudgment]] = {}
        for record in self.records:
            if record.judgment is not None:
                result.setdefault(record.model_name, []).append(record.judgment)
        return result


class EvaluationCheckpoint(BaseModel):
    """Full evaluation checkpoint for incremental persistence and resume.

    Stores raw judgment data per judge with enough metadata to validate
    that the checkpoint matches the current evaluation configuration.

    Attributes:
        benchmark_file: Basename of the benchmark result file.
        config_fingerprint: Hash of evaluation config for invalidation.
        judges: Per-judge checkpoint data keyed by judge model identifier.
        started_at: ISO timestamp when evaluation began.
        last_updated_at: ISO timestamp of most recent checkpoint update.
    """

    benchmark_file: str
    config_fingerprint: str
    judges: dict[str, JudgeCheckpoint]
    started_at: str
    last_updated_at: str


def compute_eval_config_fingerprint(
    *,
    benchmark_timestamp: str,
    max_runs_per_fixture: int,
    min_pass_rate: float,
    fixtures: list[str],
    judge_models: list[str],
    cost_cap_usd: float | None = None,
    unknown_price_max_usd: float | None = None,
) -> str:
    """Compute a deterministic fingerprint of evaluation configuration.

    Used to detect when evaluation config has changed, invalidating
    any existing checkpoint from a previous configuration.

    Args:
        benchmark_timestamp: Timestamp from the benchmark result.
        max_runs_per_fixture: Cap on runs evaluated per model/fixture combo.
        min_pass_rate: Minimum benchmark pass rate threshold.
        fixtures: Selected fixture IDs.
        judge_models: Judge model identifiers.
        cost_cap_usd: Owner-approved evaluation cost cap.
        unknown_price_max_usd: Explicit per-call maximum for unknown pricing.

    Returns:
        Hex digest prefix uniquely identifying this configuration.
    """
    config_data = json.dumps(
        {
            "benchmark_timestamp": benchmark_timestamp,
            "max_runs_per_fixture": max_runs_per_fixture,
            "min_pass_rate": min_pass_rate,
            "fixtures": sorted(fixtures),
            "judge_models": sorted(judge_models),
            "cost_cap_usd": cost_cap_usd,
            "unknown_price_max_usd": unknown_price_max_usd,
        },
        sort_keys=True,
    )
    return hashlib.sha256(config_data.encode()).hexdigest()[:16]


class CheckpointManager:
    """Manages incremental evaluation checkpoint persistence.

    Handles loading, saving, and querying checkpoint data. Provides
    resume state information for the evaluation engine and persists
    new judgments as they complete.
    """

    def __init__(
        self,
        result_file: Path,
        config_fingerprint: str,
    ) -> None:
        """Initialize checkpoint manager.

        Loads an existing checkpoint if it matches the current config,
        or creates a fresh checkpoint state.

        Args:
            result_file: Path to the benchmark result file.
            config_fingerprint: Hash of current evaluation config.
        """
        self._path = result_file.with_suffix(_CHECKPOINT_SUFFIX)
        self._config_fingerprint = config_fingerprint
        self._benchmark_file = result_file.name
        self._checkpoint = self._load_or_create()
        self._record_indices_by_judge: dict[str, dict[str, int]] = {
            judge_model: {record.task_key: index for index, record in enumerate(checkpoint.records)}
            for judge_model, checkpoint in self._checkpoint.judges.items()
        }

    def _load_or_create(self) -> EvaluationCheckpoint:
        """Load existing checkpoint if valid, otherwise create fresh state."""
        if self._path.exists():
            try:
                checkpoint = EvaluationCheckpoint.model_validate_json(self._path.read_text())
            except ValueError, KeyError:
                checkpoint = None
            else:
                if (
                    checkpoint.config_fingerprint == self._config_fingerprint
                    and checkpoint.benchmark_file == self._benchmark_file
                ):
                    return checkpoint

        now = datetime.now(UTC).isoformat()
        return EvaluationCheckpoint(
            benchmark_file=self._benchmark_file,
            config_fingerprint=self._config_fingerprint,
            judges={},
            started_at=now,
            last_updated_at=now,
        )

    @property
    def has_progress(self) -> bool:
        """Whether any judgments have been completed."""
        return any(len(jc.records) > 0 for jc in self._checkpoint.judges.values())

    @property
    def total_completed(self) -> int:
        """Total number of completed judgments across all judges."""
        return sum(len(jc.records) for jc in self._checkpoint.judges.values())

    @property
    def path(self) -> Path:
        """Path to the checkpoint file."""
        return self._path

    def completed_keys_for_judge(self, judge_model: str) -> frozenset[str]:
        """Get completed task keys for a specific judge.

        Args:
            judge_model: Judge model identifier.

        Returns:
            Frozen set of completed task keys.
        """
        indices = self._record_indices_by_judge.get(judge_model)
        return frozenset(indices) if indices is not None else frozenset()

    def existing_judgments_for_judge(self, judge_model: str) -> dict[str, list[PointwiseJudgment]]:
        """Get existing judgments grouped by model for a specific judge.

        Args:
            judge_model: Judge model identifier.

        Returns:
            Judgments keyed by evaluated model name.
        """
        if jc := self._checkpoint.judges.get(judge_model):
            return jc.to_judgments_by_model()
        return {}

    def existing_records_for_judge(self, judge_model: str) -> tuple[JudgmentRecord, ...]:
        """Return immutable exact-unit records for a resumed judge."""
        if checkpoint := self._checkpoint.judges.get(judge_model):
            return tuple(checkpoint.records)
        return ()

    def existing_cost_for_judge(self, judge_model: str) -> float:
        """Get accumulated cost for a specific judge.

        Args:
            judge_model: Judge model identifier.

        Returns:
            Total cost in USD for completed judgments.
        """
        if jc := self._checkpoint.judges.get(judge_model):
            return jc.total_cost_usd
        return 0.0

    def existing_charged_for_judge(self, judge_model: str) -> float:
        """Get accumulated budget-charged cost (incl. failures) for a judge.

        Seeds the resumed scheduler's committed budget so repeated resume can
        never exceed the cap or double-charge a persisted attempt.
        """
        if jc := self._checkpoint.judges.get(judge_model):
            return jc.total_charged_cost_usd
        return 0.0

    def completed_count_for_judge(self, judge_model: str) -> int:
        """Get count of completed judgments for a specific judge.

        Args:
            judge_model: Judge model identifier.

        Returns:
            Number of completed judgment records.
        """
        if jc := self._checkpoint.judges.get(judge_model):
            return len(jc.records)
        return 0

    def record_judgment(
        self,
        judge_model: str,
        reasoning_effort: str,
        model_name: str,
        fixture_id: str,
        run_number: int,
        judgment: PointwiseJudgment,
        cost_usd: float,
        *,
        charged_cost_usd: float | None = None,
    ) -> None:
        """Record a successful judgment and persist checkpoint to disk.

        The budget charge defaults to the actual ``cost_usd`` but may be given
        explicitly: an unknown-price success bills the fail-closed reservation,
        not its (unknown) actual cost, so ``charged_cost_usd`` must be preserved
        distinctly to seed a resumed scheduler correctly.

        Args:
            judge_model: Judge model identifier.
            reasoning_effort: Reasoning effort level.
            model_name: Evaluated model name.
            fixture_id: Test fixture identifier.
            run_number: Run number.
            judgment: Structured judge output.
            cost_usd: Actual provider cost for this call.
            charged_cost_usd: Budget-charged cost; defaults to ``cost_usd``.
        """
        self._upsert(
            judge_model,
            reasoning_effort,
            model_name,
            fixture_id,
            run_number,
            judgment=judgment,
            cost_usd=cost_usd,
            charged_cost_usd=charged_cost_usd if charged_cost_usd is not None else cost_usd,
        )

    def record_failure(
        self,
        judge_model: str,
        reasoning_effort: str,
        model_name: str,
        fixture_id: str,
        run_number: int,
        *,
        charged_cost_usd: float,
    ) -> None:
        """Record a dispatched-but-failed attempt with its fail-closed charge.

        The attempt has no judgment and zero actual cost, but its worst-case
        reservation is committed durably so a resumed scheduler stays within
        the cap and does not auto-retry the failed cell.

        Args:
            judge_model: Judge model identifier.
            reasoning_effort: Reasoning effort level.
            model_name: Evaluated model name.
            fixture_id: Test fixture identifier.
            run_number: Run number.
            charged_cost_usd: Budget-charged worst-case reservation for the call.
        """
        self._upsert(
            judge_model,
            reasoning_effort,
            model_name,
            fixture_id,
            run_number,
            judgment=None,
            cost_usd=0.0,
            charged_cost_usd=charged_cost_usd,
        )

    def _upsert(
        self,
        judge_model: str,
        reasoning_effort: str,
        model_name: str,
        fixture_id: str,
        run_number: int,
        *,
        judgment: PointwiseJudgment | None,
        cost_usd: float,
        charged_cost_usd: float,
    ) -> None:
        """Insert or replace one attempt record and persist durably."""
        if judge_model not in self._checkpoint.judges:
            self._checkpoint.judges[judge_model] = JudgeCheckpoint(
                judge_model=judge_model,
                reasoning_effort=reasoning_effort,
                records=[],
                total_cost_usd=0.0,
            )
            self._record_indices_by_judge[judge_model] = {}
        jc = self._checkpoint.judges[judge_model]
        record = JudgmentRecord(
            model_name=model_name,
            fixture_id=fixture_id,
            run_number=run_number,
            judgment=judgment,
            cost_usd=cost_usd,
            charged_cost_usd=charged_cost_usd,
        )
        indices_by_key = self._record_indices_by_judge[judge_model]
        if (index := indices_by_key.get(record.task_key)) is not None:
            existing = jc.records[index]
            jc.records[index] = record
            jc.total_cost_usd += cost_usd - existing.cost_usd
        else:
            indices_by_key[record.task_key] = len(jc.records)
            jc.records.append(record)
            jc.total_cost_usd += cost_usd
        self._checkpoint.last_updated_at = datetime.now(UTC).isoformat()
        self._save()

    def _save(self) -> None:
        """Persist checkpoint to disk atomically and durably."""
        tmp = self._path.with_suffix(".tmp")
        try:
            with tmp.open("w") as checkpoint_file:
                checkpoint_file.write(self._checkpoint.model_dump_json(indent=2))
                checkpoint_file.flush()
                os.fsync(checkpoint_file.fileno())
            tmp.replace(self._path)
            directory_fd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def cleanup(self) -> None:
        """Remove the checkpoint file after successful completion."""
        if self._path.exists():
            self._path.unlink()

    def resume_summary(self) -> str:
        """Generate a human-readable summary of checkpoint progress.

        Returns:
            Formatted string describing checkpoint state per judge.
        """
        lines: list[str] = []
        for judge_model, jc in self._checkpoint.judges.items():
            short = judge_model.rsplit("/", maxsplit=1)[-1] if "/" in judge_model else judge_model
            lines.append(f"  {short}: {len(jc.records)} judgments, ${jc.total_cost_usd:.4f}")
        return "\n".join(lines) if lines else "  (no progress)"
