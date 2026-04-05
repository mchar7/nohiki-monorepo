"""Pydantic AI Evals integration for systematic LLM evaluation.

Provides evaluation capabilities for structured output agents with custom evaluators
designed for Nohiki's specific use cases (job extraction, skill clarification).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from nohiki_llm_client.client import StructuredAgentConfig

if TYPE_CHECKING:
    from nohiki_llm_client.client import LLMClient


@dataclass(slots=True)
class FieldMatchEvaluator[TOutput: BaseModel](Evaluator[TOutput, TOutput]):
    """Evaluator that checks if specific fields match between expected and actual output.

    Supports exact match for enums/strings and tolerance-based matching for numeric fields.

    Attributes:
        field_path: Dot-notation path to field (e.g., "location.country_code").
        tolerance: For numeric fields, acceptable difference ratio (0.0-1.0).
        case_sensitive: For string comparison.
    """

    field_path: str
    tolerance: float = 0.0
    case_sensitive: bool = True

    def evaluate(self, ctx: EvaluatorContext[TOutput, TOutput]) -> float:
        """Evaluate field match between expected and actual output.

        Returns:
            1.0 if fields match, 0.0 otherwise.
            For numeric fields with tolerance > 0, returns proportional score.
        """
        if ctx.expected_output is None:
            return 0.0

        expected = _get_field_value(ctx.expected_output, self.field_path)
        actual = _get_field_value(ctx.output, self.field_path)

        if expected is None and actual is None:
            return 1.0
        if expected is None or actual is None:
            return 0.0

        return self._compare_values(expected, actual)

    def _compare_values(self, expected: object, actual: object) -> float:
        """Compare two values with appropriate strategy based on type."""
        match (expected, actual):
            case (int() | float() as e, int() | float() as a):
                return self._compare_numeric(float(e), float(a))
            case (str() as e, str() as a):
                return self._compare_strings(e, a)
            case _ if hasattr(expected, "value") and hasattr(actual, "value"):
                return 1.0 if expected.value == actual.value else 0.0
            case _:
                return 1.0 if expected == actual else 0.0

    def _compare_numeric(self, expected: float, actual: float) -> float:
        """Compare numeric values with optional tolerance."""
        if self.tolerance <= 0:
            return 1.0 if expected == actual else 0.0
        if expected == 0:
            return 1.0 if actual == 0 else 0.0
        diff_ratio = abs(actual - expected) / abs(expected)
        if diff_ratio <= self.tolerance:
            return 1.0 - (diff_ratio / self.tolerance) * 0.5
        return 0.0

    def _compare_strings(self, expected: str, actual: str) -> float:
        """Compare strings with optional case insensitivity."""
        if not self.case_sensitive:
            expected = expected.lower()
            actual = actual.lower()
        return 1.0 if expected == actual else 0.0


@dataclass(slots=True)
class ListLengthEvaluator[TOutput: BaseModel](Evaluator[TOutput, TOutput]):
    """Evaluator for checking if list field lengths are within acceptable range.

    Useful for evaluating skill extraction (e.g., extracted 5-15 skills from posting).
    """

    field_path: str
    min_items: int | None = None
    max_items: int | None = None
    tolerance_ratio: float = 0.2

    def evaluate(self, ctx: EvaluatorContext[TOutput, TOutput]) -> float:
        """Evaluate list length match.

        Returns:
            1.0 if within tolerance, 0.0 if outside bounds.
        """
        if ctx.expected_output is None:
            return 0.0

        expected_list = _get_field_value(ctx.expected_output, self.field_path)
        actual_list = _get_field_value(ctx.output, self.field_path)

        if not isinstance(expected_list, list) or not isinstance(actual_list, list):
            return 0.0

        return self._score_lengths(len(expected_list), len(actual_list))

    def _score_lengths(self, expected_len: int, actual_len: int) -> float:
        """Score based on length comparison with bounds and tolerance."""
        if self.min_items is not None and actual_len < self.min_items:
            return 0.0
        if self.max_items is not None and actual_len > self.max_items:
            return 0.0
        if expected_len == 0:
            return 1.0 if actual_len == 0 else 0.0

        diff_ratio = abs(actual_len - expected_len) / expected_len
        if diff_ratio <= self.tolerance_ratio:
            return 1.0 - (diff_ratio / self.tolerance_ratio) * 0.5
        return 0.0


@dataclass(slots=True)
class EvaluationResult[TOutput]:
    """Result of running an evaluation.

    Contains the full PydanticAI EvaluationReport plus Nohiki-specific metadata.
    """

    dataset_name: str
    total_cases: int
    passed_cases: int
    average_scores: dict[str, float]
    report: object  # EvaluationReport from pydantic-evals

    @property
    def pass_rate(self) -> float:
        """Percentage of cases that passed all evaluators."""
        if self.total_cases == 0:
            return 0.0
        return self.passed_cases / self.total_cases


def _get_field_value(obj: BaseModel, path: str) -> object | None:
    """Get value from nested object using dot notation.

    Traverses a Pydantic model using dot-separated field paths.

    Args:
        obj: Pydantic model to traverse.
        path: Dot-notation path (e.g., "location.country_code").

    Returns:
        Field value if found, None otherwise.
    """
    parts = path.split(".")
    current: object = obj
    for part in parts:
        if current is None:
            return None
        if isinstance(current, BaseModel):
            current = getattr(current, part, None)
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


class LLMEvaluator[TInput, TOutput: BaseModel]:
    """Evaluation runner for LLM agents with structured output.

    Provides a clean interface for running PydanticAI Evals against agents
    created via LLMClient. Maintains DRY principle by reusing existing
    agent creation and configuration logic.

    Example::

        evaluator = LLMEvaluator(llm_client)

        dataset = Dataset[DiscoveredListing, JobExtractionSchema](
            cases=[
                Case(
                    name="senior_swe_sf",
                    inputs=discovered_listing,
                    expected_output=expected_extraction,
                ),
            ],
            evaluators=[
                FieldMatchEvaluator("seniority_level"),
                FieldMatchEvaluator("location.country_code"),
            ],
        )

        result = await evaluator.evaluate_structured(
            dataset,
            agent_config=StructuredAgentConfig(...),
        )

        print(f"Pass rate: {result.pass_rate:.1%}")
    """

    def __init__(self, llm_client: LLMClient) -> None:
        """Initialize evaluator with LLMClient instance.

        Args:
            llm_client: Configured LLMClient for agent creation.
        """
        self._client = llm_client

    async def evaluate_structured(
        self,
        dataset: Dataset[TInput, TOutput],
        *,
        agent_config: StructuredAgentConfig[TInput, TOutput],
        max_concurrency: int = 5,
    ) -> EvaluationResult[TOutput]:
        """Evaluate a structured agent against a dataset.

        Creates the agent using LLMClient, runs all cases, and returns
        aggregated results.
        """
        agent = self._client.create_agent(agent_config)

        async def run_task(inputs: TInput) -> TOutput:
            result = await self._client.run(agent, "Extract", deps=inputs)
            return result.output

        report = await dataset.evaluate(run_task, max_concurrency=max_concurrency)

        total_cases = len(report.cases)
        passed_cases = sum(1 for case in report.cases if not case.evaluator_failures)

        scores_by_evaluator: defaultdict[str, list[float]] = defaultdict(list)
        for case in report.cases:
            for name, score in case.scores.items():
                scores_by_evaluator[name].append(float(score.value))
        average_scores = {name: sum(vals) / len(vals) for name, vals in scores_by_evaluator.items() if vals}

        return EvaluationResult(
            dataset_name=getattr(dataset, "name", "unnamed"),
            total_cases=total_cases,
            passed_cases=passed_cases,
            average_scores=average_scores,
            report=report,
        )


def create_extraction_dataset[TInput, TOutput](
    name: str,
    cases: Sequence[Case[TInput, TOutput]],
    field_evaluators: list[tuple[str, float]] | None = None,
) -> Dataset[TInput, TOutput]:
    """Create a standardized dataset for extraction tasks.

    Convenience factory for creating datasets with common evaluators
    for structured extraction tasks.

    Args:
        name: Dataset identifier.
        cases: List of test cases.
        field_evaluators: List of (field_path, tolerance) tuples.
            If None, uses default extraction evaluators.

    Returns:
        Configured Dataset with appropriate evaluators.
    """
    evaluators: list[Evaluator] = []

    if field_evaluators:
        for field_path, tolerance in field_evaluators:
            evaluators.append(FieldMatchEvaluator(field_path, tolerance=tolerance))
    else:
        evaluators = [
            FieldMatchEvaluator("seniority_level"),
            FieldMatchEvaluator("location.country_code"),
            FieldMatchEvaluator("work_arrangement"),
            FieldMatchEvaluator("employment_term"),
            ListLengthEvaluator("skills", min_items=1, max_items=50, tolerance_ratio=0.3),
        ]

    return Dataset(cases=cases, evaluators=evaluators, name=name)
