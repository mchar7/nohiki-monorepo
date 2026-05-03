"""Benchmark metrics and result models for structured collection and persistence.

Stores extraction outputs as JSON for downstream comparative evaluation by the
LLM-as-judge. All models use Pydantic for validation and JSON round-tripping.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from statistics import mean, stdev

from pydantic import BaseModel, ConfigDict, Field, computed_field

from llm_benchmark.schemas.gold import GoldScore


class RunResult(BaseModel):
    """Result of a single extraction run, including the raw output for judge evaluation.

    Token fields map directly to PydanticAI's ``RunUsage``.
    ``usage_details`` carries the raw provider-specific ``RunUsage.details``
    dict (e.g., reasoning token count for thinking models).

    Attributes:
        fixture_id: Identifier of the test fixture used.
        run_number: 1-indexed run number within this fixture.
        success: Whether the extraction completed without error.
        latency_ms: Wall-clock time in milliseconds.
        input_tokens: Prompt tokens consumed (``RunUsage.input_tokens``).
        output_tokens: Completion tokens generated (``RunUsage.output_tokens``).
        cache_read_tokens: Tokens served from provider cache.
        cache_write_tokens: Tokens written to provider cache.
        reasoning_tokens: Reasoning/thinking tokens (``usage_details["reasoning_tokens"]``).
        api_requests: Number of API round-trips (``RunUsage.requests``).
        tool_calls_made: Number of tool calls executed (``RunUsage.tool_calls``).
        usage_details: Raw ``RunUsage.details`` dict with provider-specific extras.
        actual_cost_usd: Actual provider cost via genai_prices, ``None`` if unknown.
            Reported separately from the budget-charged cost.
        reserved_cost_usd: Worst-case cost reserved before dispatch (fail-closed bound).
        maximum_possible_cost_usd: Absolute worst-case cost for this cell.
        charged_cost_usd: Budget-charged cost that seeds a resumed scheduler
            (known success=actual, unknown success/dispatched failure=reservation).
        error_message: Error description if extraction failed.
        output_json: Full extraction output as JSON dict (``None`` on failure).
    """

    fixture_id: str
    treatment_fingerprint: str
    cell_fingerprint: str
    run_number: int
    success: bool
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    api_requests: int = 0
    tool_calls_made: int = 0
    retry_count: int | None = 0
    usage_details: dict[str, int] = Field(default_factory=dict)
    actual_cost_usd: float | None = None
    reserved_cost_usd: float = 0.0
    maximum_possible_cost_usd: float = 0.0
    error_message: str | None = None
    output_json: dict[str, object] | None = None
    gold_score: GoldScore | None = None

    @property
    def total_tokens(self) -> int:
        """Total tokens used in this run."""
        return self.input_tokens + self.output_tokens

    @computed_field
    @property
    def charged_cost_usd(self) -> float:
        """Budget-charged cost mirroring the fail-closed scheduler settlement.

        Known-price success charges the actual provider cost; unknown-price
        success and any dispatched failure charge the worst-case reservation.
        This is the amount that seeds a resumed ``BudgetScheduler`` so repeated
        resume can never exceed the cap or forget a failure's fail-closed charge.
        Serialized for round-tripping; recomputed for legacy artifacts.
        """
        if self.actual_cost_usd is not None:
            return self.actual_cost_usd
        return self.reserved_cost_usd


class ModelResult(BaseModel):
    """Aggregated results for a single model across all fixtures and runs.

    Attributes:
        model: Fully qualified model identifier (e.g., ``openrouter:google/gemini-3-flash-preview``).
        runs: Individual run results with extraction outputs.
        total_cost_usd: Total actual cost from provider billing data.
    """

    model_config = ConfigDict(ignored_types=(cached_property,))

    model: str
    runs: list[RunResult] = Field(default_factory=list)
    total_cost_usd: float = 0.0

    @cached_property
    def _successful_runs(self) -> list[RunResult]:
        """Successful runs, computed once and cached."""
        return [r for r in self.runs if r.success]

    @property
    def total_runs(self) -> int:
        """Total number of runs attempted."""
        return len(self.runs)

    @property
    def successful_runs(self) -> int:
        """Number of runs that completed without error."""
        return len(self._successful_runs)

    @property
    def pass_rate(self) -> float:
        """Proportion of successful runs (0.0 to 1.0)."""
        if not self.runs:
            return 0.0
        return self.successful_runs / self.total_runs

    @computed_field
    @property
    def avg_gold_score(self) -> float:
        """Mean deterministic gold score across successfully scored runs."""
        scores = [run.gold_score.deterministic_score for run in self._successful_runs if run.gold_score is not None]
        return mean(scores) if scores else 0.0

    @property
    def avg_latency_ms(self) -> float:
        """Mean latency across successful runs."""
        data = self._successful_runs
        return mean(r.latency_ms for r in data) if data else 0.0

    @property
    def latency_stdev_ms(self) -> float:
        """Standard deviation of latency across successful runs."""
        latencies = [r.latency_ms for r in self._successful_runs]
        return stdev(latencies) if len(latencies) > 1 else 0.0

    @property
    def avg_retry_count(self) -> float | None:
        """Mean retry count across runs with a measured count.

        Returns ``None`` when no run has a measured retry count (all failures
        with unknown telemetry), distinguishing "unavailable" from "zero
        retries". Successful runs always contribute a measured count.
        """
        counts = [r.retry_count for r in self.runs if r.retry_count is not None]
        return mean(counts) if counts else None

    @property
    def retry_count_stdev(self) -> float | None:
        """Standard deviation of measured retry counts across runs.

        Returns ``None`` when no run has a measured retry count, and ``0.0``
        when only one measured sample exists.
        """
        counts = [r.retry_count for r in self.runs if r.retry_count is not None]
        if not counts:
            return None
        return stdev(counts) if len(counts) > 1 else 0.0

    @property
    def avg_input_tokens(self) -> float:
        """Mean input tokens across successful runs."""
        data = self._successful_runs
        return mean(r.input_tokens for r in data) if data else 0.0

    @property
    def avg_output_tokens(self) -> float:
        """Mean output tokens across successful runs."""
        data = self._successful_runs
        return mean(r.output_tokens for r in data) if data else 0.0

    @property
    def total_input_tokens(self) -> int:
        """Sum of input tokens across all runs."""
        return sum(r.input_tokens for r in self.runs)

    @property
    def total_output_tokens(self) -> int:
        """Sum of output tokens across all runs."""
        return sum(r.output_tokens for r in self.runs)

    @property
    def total_reasoning_tokens(self) -> int:
        """Sum of reasoning tokens across all runs."""
        return sum(r.reasoning_tokens for r in self.runs)

    def model_post_init(self, _context: object, /) -> None:
        """Clear cached_property after Pydantic validation to keep cache coherent."""
        self.__dict__.pop("_successful_runs", None)


class BenchmarkResult(BaseModel):
    """Complete benchmark result across all models with persistence.

    Attributes:
        timestamp: ISO 8601 timestamp of benchmark execution.
        fixtures_used: List of fixture IDs included in this benchmark.
        runs_per_fixture: Number of runs per fixture per model.
        fixture_checksums: SHA-256 checksums of fixture content at benchmark time.
            Used to detect stale runs when resuming a previous session.
        models: Mapping of model identifier to aggregated results.
    """

    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    experiment_fingerprint: str

    fixtures_used: list[str] = Field(default_factory=list)
    runs_per_fixture: int = 3
    fixture_checksums: dict[str, str] = Field(default_factory=dict)
    models: dict[str, ModelResult] = Field(default_factory=dict)

    def get_best_gold_model(self) -> str | None:
        """Return the treatment with the strongest deterministic gold evidence."""
        if not self.models:
            return None
        return max(self.models.items(), key=lambda item: item[1].avg_gold_score)[0]

    @property
    def total_actual_cost(self) -> float:
        """Total actual cost across all models."""
        return sum(m.total_cost_usd for m in self.models.values())

    @property
    def total_charged_cost(self) -> float:
        """Total budget-charged cost across all attempted runs.

        Seeds a resumed scheduler's committed budget so repeated resume cannot
        exceed the cap. Distinct from ``total_actual_cost``, which reports only
        realized provider spend.
        """
        return sum(run.charged_cost_usd for m in self.models.values() for run in m.runs)

    def get_fastest_model(self) -> str | None:
        """Return model with lowest average latency (min 50% pass rate)."""
        candidates = [(n, m.avg_latency_ms) for n, m in self.models.items() if m.pass_rate >= 0.5]
        if not candidates:
            return None
        return min(candidates, key=lambda x: x[1])[0]

    def get_cheapest_model(self) -> str | None:
        """Return model with lowest actual cost (min 50% pass rate)."""
        candidates = [(n, m.total_cost_usd) for n, m in self.models.items() if m.pass_rate >= 0.5]
        if not candidates:
            return None
        return min(candidates, key=lambda x: x[1])[0]

    def get_most_consistent_model(self) -> str | None:
        """Return model with highest pass rate, breaking ties by lowest latency stdev."""
        if not self.models:
            return None
        candidates = [(n, m.pass_rate, m.latency_stdev_ms) for n, m in self.models.items()]
        best = max(candidates, key=lambda x: (x[1], -x[2]))
        return best[0]

    def filter_for_evaluation(
        self,
        selected_fixtures: list[str],
        min_pass_rate: float,
        max_runs_per_fixture: int | None = None,
    ) -> tuple[BenchmarkResult, dict[str, float]]:
        """Filter models by pass rate, fixture subset, and run cap for evaluation.

        Retains only models whose benchmark pass rate meets the threshold,
        only runs matching the selected fixtures with successful outputs,
        and at most ``max_runs_per_fixture`` runs per model/fixture combo
        (selected by lowest run_number for reproducibility).

        Args:
            selected_fixtures: Fixture IDs to include.
            min_pass_rate: Minimum pass rate threshold (0.0-1.0).
            max_runs_per_fixture: Cap on runs evaluated per model/fixture combo.

        Returns:
            Tuple of (filtered benchmark, skipped model names mapped to their pass rates).
        """
        skipped_models: dict[str, float] = {}
        kept_models: dict[str, ModelResult] = {}
        for model_name, model_result in self.models.items():
            if model_result.pass_rate < min_pass_rate:
                skipped_models[model_name] = model_result.pass_rate
            else:
                kept_models[model_name] = model_result

        fixture_set = set(selected_fixtures)
        filtered_models: dict[str, ModelResult] = {}
        for model_name, model_result in kept_models.items():
            eligible_runs = [
                r for r in model_result.runs if r.fixture_id in fixture_set and r.success and r.output_json is not None
            ]
            if max_runs_per_fixture is not None:
                runs_by_fixture: dict[str, list[RunResult]] = {}
                for run_item in eligible_runs:
                    runs_by_fixture.setdefault(run_item.fixture_id, []).append(run_item)
                capped: list[RunResult] = []
                for fixture_runs in runs_by_fixture.values():
                    fixture_runs.sort(key=lambda r: r.run_number)
                    capped.extend(fixture_runs[:max_runs_per_fixture])
                eligible_runs = capped

            if eligible_runs:
                filtered_models[model_name] = ModelResult(
                    model=model_name,
                    runs=eligible_runs,
                    total_cost_usd=model_result.total_cost_usd,
                )

        filtered_benchmark = BenchmarkResult(
            timestamp=self.timestamp,
            experiment_fingerprint=self.experiment_fingerprint,
            fixtures_used=list(selected_fixtures),
            runs_per_fixture=self.runs_per_fixture,
            fixture_checksums=self.fixture_checksums,
            models=filtered_models,
        )
        return filtered_benchmark, skipped_models

    def strip_stale_fixture_runs(
        self,
        selected_fixtures: list[str],
        current_checksums: dict[str, str],
    ) -> tuple[BenchmarkResult, frozenset[str]]:
        """Return a copy with runs for stale fixtures stripped.

        Compares stored fixture checksums against current checksums to detect
        fixtures whose content has changed. Runs for stale fixtures are removed
        so they will be re-executed.

        Args:
            selected_fixtures: Fixture IDs for the current run.
            current_checksums: Current SHA-256 checksums keyed by fixture ID.

        Returns:
            Tuple of (filtered result, frozenset of stale fixture IDs).
            When no fixtures are stale, returns ``(self, frozenset())``.
        """
        stale_fixtures = frozenset(
            fid
            for fid in selected_fixtures
            if fid in self.fixture_checksums and self.fixture_checksums[fid] != current_checksums[fid]
        )

        if not stale_fixtures:
            return self, frozenset()

        cleaned_models: dict[str, ModelResult] = {}
        for model_name, model_result in self.models.items():
            valid_runs = [r for r in model_result.runs if r.fixture_id not in stale_fixtures]
            cleaned_models[model_name] = ModelResult(
                model=model_name,
                runs=valid_runs,
                total_cost_usd=sum(r.actual_cost_usd or 0.0 for r in valid_runs),
            )
        cleaned = BenchmarkResult(
            experiment_fingerprint=self.experiment_fingerprint,
            fixtures_used=self.fixtures_used,
            runs_per_fixture=self.runs_per_fixture,
            fixture_checksums=self.fixture_checksums,
            models=cleaned_models,
        )
        return cleaned, stale_fixtures

    def completed_run_keys(self, experiment_fingerprint: str | None = None) -> frozenset[tuple[str, str, int]]:
        """Return every attempted cell key, rejecting a mismatched experiment identity.

        Includes both successes and failures: each persisted ``RunResult`` is a
        genuine attempt whose fail-closed budget charge is already committed.
        Budget-exhausted non-dispatches are never persisted, so they are absent
        here and remain eligible for a later run. Automatic resume skips every
        key returned, so it can never silently re-run a failed provider/schema
        cell or double-charge its reservation.
        """
        if experiment_fingerprint is not None and experiment_fingerprint != self.experiment_fingerprint:
            msg = "Result root belongs to a different benchmark experiment"
            raise ValueError(msg)
        return frozenset(
            (model_name, run.fixture_id, run.run_number)
            for model_name, model_result in self.models.items()
            for run in model_result.runs
        )

    def filter_to_config(
        self,
        models: list[str],
        fixture_ids: list[str],
        runs_per_fixture: int,
    ) -> BenchmarkResult:
        """Return a copy scoped to the given configuration parameters.

        Retains only runs for models and fixtures in the given sets, and only
        run numbers within ``[1, runs_per_fixture]``. Historical data outside
        the current config is preserved in the saved file but excluded from
        resume decisions and display.

        Args:
            models: Model identifiers to include.
            fixture_ids: Fixture IDs to include.
            runs_per_fixture: Maximum run number to retain (inclusive).

        Returns:
            New ``BenchmarkResult`` scoped to the given configuration.
        """
        model_set = set(models)
        fixture_set = set(fixture_ids)
        scoped_models: dict[str, ModelResult] = {}
        for model_name, model_result in self.models.items():
            if model_name not in model_set:
                continue
            scoped_runs = [
                r for r in model_result.runs if r.fixture_id in fixture_set and r.run_number <= runs_per_fixture
            ]
            if scoped_runs:
                scoped_models[model_name] = ModelResult(
                    model=model_name,
                    runs=scoped_runs,
                    total_cost_usd=sum(r.actual_cost_usd or 0.0 for r in scoped_runs),
                )
        return BenchmarkResult(
            timestamp=self.timestamp,
            experiment_fingerprint=self.experiment_fingerprint,
            fixtures_used=list(fixture_ids),
            runs_per_fixture=runs_per_fixture,
            fixture_checksums={fid: cs for fid, cs in self.fixture_checksums.items() if fid in fixture_set},
            models=scoped_models,
        )

    def merge(self, other: BenchmarkResult) -> BenchmarkResult:
        """Merge another result, combining all runs per model.

        Runs are deduplicated by ``(fixture_id, run_number)``; ``other``'s
        runs take precedence when the same key exists in both, so the newest
        data always wins.

        Args:
            other: Benchmark result to merge in.

        Returns:
            New ``BenchmarkResult`` with all runs from both results combined.
        """
        if self.experiment_fingerprint != other.experiment_fingerprint:
            msg = "Cannot merge benchmark results from different experiments"
            raise ValueError(msg)
        all_model_names = set(self.models) | set(other.models)
        merged_models: dict[str, ModelResult] = {}
        for model_name in sorted(all_model_names):
            base: dict[tuple[str, int], RunResult] = {
                (r.fixture_id, r.run_number): r
                for r in (self.models[model_name].runs if model_name in self.models else [])
            }
            for run_item in other.models[model_name].runs if model_name in other.models else []:
                base[(run_item.fixture_id, run_item.run_number)] = run_item
            all_runs = sorted(base.values(), key=lambda r: (r.fixture_id, r.run_number))
            merged_models[model_name] = ModelResult(
                model=model_name,
                runs=all_runs,
                total_cost_usd=sum(r.actual_cost_usd or 0.0 for r in all_runs),
            )
        merged_checksums = dict(self.fixture_checksums) | dict(other.fixture_checksums)
        all_fixtures = list(dict.fromkeys([*self.fixtures_used, *other.fixtures_used]))
        return BenchmarkResult(
            timestamp=datetime.now(UTC).isoformat(),
            experiment_fingerprint=self.experiment_fingerprint,
            fixtures_used=all_fixtures,
            runs_per_fixture=other.runs_per_fixture,
            fixture_checksums=merged_checksums,
            models=merged_models,
        )

    def save(self, path: Path) -> None:
        """Persist the result to JSON with checkpoint-grade durability.

        Writes to a sibling ``.tmp`` file, flushes and ``fsync``s its contents
        to disk, atomically replaces ``path``, then ``fsync``s the parent
        directory so the rename itself survives a crash. A ``KeyboardInterrupt``
        or crash mid-write therefore cannot leave a truncated file or an
        acknowledged result whose rename was never durably recorded. The temp
        file is removed on any ``BaseException``.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(self.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            tmp.replace(path)
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    @classmethod
    def load(cls, path: Path) -> BenchmarkResult:
        """Load benchmark result from JSON file.

        Args:
            path: Path to JSON results file.

        Returns:
            Deserialized ``BenchmarkResult``.

        Raises:
            FileNotFoundError: If path does not exist.
            ValidationError: If JSON does not match schema.
        """
        data = json.loads(path.read_text())
        return cls.model_validate(data)
