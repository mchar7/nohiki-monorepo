"""Tests for Pydantic AI Evals integration."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from nohiki_llm_client import (
    EvaluationResult,
    FieldMatchEvaluator,
    ListLengthEvaluator,
    LLMClient,
    LLMEvaluator,
    LLMSettings,
    StructuredAgentConfig,
    create_extraction_dataset,
)
from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EvaluatorContext
from pydantic_evals.otel import SpanTree


def _make_eval_context[TInput, TOutput](
    inputs: TInput,
    output: TOutput,
    expected_output: TOutput,
    name: str = "test",
) -> EvaluatorContext[TInput, TOutput, None]:
    """Create an EvaluatorContext for testing with required fields populated."""
    return EvaluatorContext(
        name=name,
        inputs=inputs,
        metadata=None,
        expected_output=expected_output,
        output=output,
        duration=0.0,
        _span_tree=SpanTree(),
        attributes={},
        metrics={},
    )


@dataclass
class SampleContext:
    """Sample context for testing."""

    data: str


class SampleOutput(BaseModel):
    """Sample output model for testing."""

    result: str
    count: int = 0


class TestFieldMatchEvaluator:
    """Tests for FieldMatchEvaluator."""

    def test_none_expected_output_returns_zero(self) -> None:
        """None expected_output returns 0.0."""
        evaluator = FieldMatchEvaluator("result")

        actual = SampleOutput(result="hello")
        ctx = EvaluatorContext(
            name="test",
            inputs=SampleContext(data="test"),
            metadata=None,
            expected_output=None,
            output=actual,
            duration=0.0,
            _span_tree=SpanTree(),
            attributes={},
            metrics={},
        )

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(0.0)

    def test_both_fields_none_returns_one(self) -> None:
        """Both expected and actual field being None returns 1.0."""

        class ModelWithOptional(BaseModel):
            value: str | None = None

        evaluator = FieldMatchEvaluator("value")

        expected = ModelWithOptional(value=None)
        actual = ModelWithOptional(value=None)
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(1.0)

    def test_one_field_none_returns_zero(self) -> None:
        """One field None and other not returns 0.0."""

        class ModelWithOptional(BaseModel):
            value: str | None = None

        evaluator = FieldMatchEvaluator("value")

        expected = ModelWithOptional(value="hello")
        actual = ModelWithOptional(value=None)
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(0.0)

    def test_exact_string_match(self) -> None:
        """Exact string match returns 1.0."""
        evaluator = FieldMatchEvaluator("result")

        expected = SampleOutput(result="hello")
        actual = SampleOutput(result="hello")
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(1.0)

    def test_string_mismatch(self) -> None:
        """String mismatch returns 0.0."""
        evaluator = FieldMatchEvaluator("result")

        expected = SampleOutput(result="hello")
        actual = SampleOutput(result="world")
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(0.0)

    def test_numeric_exact_match(self) -> None:
        """Exact numeric match returns 1.0."""
        evaluator = FieldMatchEvaluator("count")

        expected = SampleOutput(result="test", count=42)
        actual = SampleOutput(result="test", count=42)
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(1.0)

    def test_numeric_with_tolerance(self) -> None:
        """Numeric within tolerance returns proportional score."""
        evaluator = FieldMatchEvaluator("count", tolerance=0.2)

        expected = SampleOutput(result="test", count=100)
        actual = SampleOutput(result="test", count=110)  # 10% diff
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        # 10% diff with 20% tolerance should give score between 0.5 and 1.0
        assert 0.5 < score <= 1.0

    def test_nested_field_access(self) -> None:
        """Nested field access via dot notation."""

        class NestedModel(BaseModel):
            inner: SampleOutput

        evaluator = FieldMatchEvaluator("inner.result")

        expected = NestedModel(inner=SampleOutput(result="hello"))
        actual = NestedModel(inner=SampleOutput(result="hello"))
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(1.0)

    def test_case_insensitive_string_match(self) -> None:
        """Case insensitive comparison matches different cases."""
        evaluator = FieldMatchEvaluator("result", case_sensitive=False)

        expected = SampleOutput(result="HELLO")
        actual = SampleOutput(result="hello")
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(1.0)

    def test_enum_comparison(self) -> None:
        """Enum values are compared by their value attribute."""
        from enum import Enum

        class Status(Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        class ModelWithEnum(BaseModel):
            status: Status

        evaluator = FieldMatchEvaluator("status")

        expected = ModelWithEnum(status=Status.ACTIVE)
        actual = ModelWithEnum(status=Status.ACTIVE)
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(1.0)

    def test_compare_values_default_case_equal(self) -> None:
        """Two arbitrary equal objects (not numeric/string/enum) return 1.0."""
        evaluator = FieldMatchEvaluator("result")
        score = evaluator._compare_values([1, 2, 3], [1, 2, 3])
        assert score == pytest.approx(1.0)

    def test_compare_values_default_case_unequal(self) -> None:
        """Two arbitrary unequal objects (not numeric/string/enum) return 0.0."""
        evaluator = FieldMatchEvaluator("result")
        score = evaluator._compare_values([1, 2], [1, 2, 3])
        assert score == pytest.approx(0.0)

    def test_enum_mismatch(self) -> None:
        """Different enum values return 0.0."""
        from enum import Enum

        class Status(Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        class ModelWithEnum(BaseModel):
            status: Status

        evaluator = FieldMatchEvaluator("status")

        expected = ModelWithEnum(status=Status.ACTIVE)
        actual = ModelWithEnum(status=Status.INACTIVE)
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(0.0)

    def test_numeric_zero_expected_with_tolerance(self) -> None:
        """When expected is zero with tolerance, only zero actual matches."""
        evaluator = FieldMatchEvaluator("count", tolerance=0.2)

        expected = SampleOutput(result="test", count=0)
        actual = SampleOutput(result="test", count=0)
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(1.0)

    def test_numeric_zero_expected_nonzero_actual(self) -> None:
        """When expected is zero but actual is not, returns 0.0."""
        evaluator = FieldMatchEvaluator("count", tolerance=0.2)

        expected = SampleOutput(result="test", count=0)
        actual = SampleOutput(result="test", count=5)
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(0.0)

    def test_numeric_outside_tolerance(self) -> None:
        """Numeric difference outside tolerance returns 0.0."""
        evaluator = FieldMatchEvaluator("count", tolerance=0.1)

        expected = SampleOutput(result="test", count=100)
        actual = SampleOutput(result="test", count=120)  # 20% diff > 10% tolerance
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(0.0)


class TestListLengthEvaluator:
    """Tests for ListLengthEvaluator."""

    def test_length_exact_match(self) -> None:
        """Exact length match returns 1.0."""

        class WithList(BaseModel):
            items: list[str]

        evaluator = ListLengthEvaluator("items", tolerance_ratio=0.2)

        expected = WithList(items=["a", "b", "c"])
        actual = WithList(items=["x", "y", "z"])
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(1.0)

    def test_length_within_tolerance(self) -> None:
        """Length within tolerance returns proportional score."""

        class WithList(BaseModel):
            items: list[str]

        evaluator = ListLengthEvaluator("items", tolerance_ratio=0.2)

        expected = WithList(items=["a", "b", "c", "d", "e"])  # 5 items
        actual = WithList(items=["x", "y", "z", "w"])  # 4 items (20% diff)
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert 0.5 <= score <= 1.0

    def test_length_outside_tolerance(self) -> None:
        """Length outside tolerance returns 0.0."""

        class WithList(BaseModel):
            items: list[str]

        evaluator = ListLengthEvaluator("items", tolerance_ratio=0.2)

        expected = WithList(items=["a", "b", "c", "d", "e"])  # 5 items
        actual = WithList(items=["x"])  # 1 item (80% diff)
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(0.0)

    def test_min_items_bound(self) -> None:
        """Below min_items returns 0.0."""

        class WithList(BaseModel):
            items: list[str]

        evaluator = ListLengthEvaluator("items", min_items=2)

        expected = WithList(items=["a", "b", "c"])
        actual = WithList(items=["x"])  # Only 1 item
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(0.0)

    def test_max_items_bound(self) -> None:
        """Above max_items returns 0.0."""

        class WithList(BaseModel):
            items: list[str]

        evaluator = ListLengthEvaluator("items", max_items=3)

        expected = WithList(items=["a", "b"])
        actual = WithList(items=["w", "x", "y", "z"])  # 4 items > 3 max
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(0.0)

    def test_empty_lists_match(self) -> None:
        """Both empty lists return 1.0."""

        class WithList(BaseModel):
            items: list[str]

        evaluator = ListLengthEvaluator("items")

        expected = WithList(items=[])
        actual = WithList(items=[])
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(1.0)

    def test_empty_expected_nonempty_actual(self) -> None:
        """Empty expected with non-empty actual returns 0.0."""

        class WithList(BaseModel):
            items: list[str]

        evaluator = ListLengthEvaluator("items")

        expected = WithList(items=[])
        actual = WithList(items=["x"])
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(0.0)

    def test_none_expected_output_returns_zero(self) -> None:
        """None expected_output returns 0.0."""

        class WithList(BaseModel):
            items: list[str]

        evaluator = ListLengthEvaluator("items")

        actual = WithList(items=["x", "y"])
        ctx = EvaluatorContext(
            name="test",
            inputs=SampleContext(data="test"),
            metadata=None,
            expected_output=None,
            output=actual,
            duration=0.0,
            _span_tree=SpanTree(),
            attributes={},
            metrics={},
        )

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(0.0)

    def test_non_list_field_returns_zero(self) -> None:
        """Non-list field returns 0.0."""
        evaluator = ListLengthEvaluator("result")

        expected = SampleOutput(result="hello")
        actual = SampleOutput(result="world")
        ctx = _make_eval_context(SampleContext(data="test"), actual, expected)

        score = evaluator.evaluate(ctx)
        assert score == pytest.approx(0.0)


class TestGetFieldValue:
    """Tests for _get_field_value helper function."""

    def test_dict_field_traversal(self) -> None:
        """Can traverse dict fields within models."""
        from nohiki_llm_client.evals import _get_field_value

        class ModelWithDict(BaseModel):
            data: dict[str, str]

        obj = ModelWithDict(data={"key": "value"})
        result = _get_field_value(obj, "data.key")
        assert result == "value"

    def test_missing_field_returns_none(self) -> None:
        """Missing field path returns None."""
        from nohiki_llm_client.evals import _get_field_value

        obj = SampleOutput(result="hello")
        result = _get_field_value(obj, "nonexistent")
        assert result is None

    def test_non_model_intermediate_returns_none(self) -> None:
        """Non-model/dict intermediate in path returns None."""
        from nohiki_llm_client.evals import _get_field_value

        obj = SampleOutput(result="hello")
        result = _get_field_value(obj, "result.nested")
        assert result is None

    def test_none_intermediate_in_path_returns_none(self) -> None:
        """None value encountered mid-traversal short-circuits and returns None."""
        from nohiki_llm_client.evals import _get_field_value

        class Outer(BaseModel):
            inner: SampleOutput | None = None

        obj = Outer(inner=None)
        result = _get_field_value(obj, "inner.result")
        assert result is None


class TestCreateExtractionDataset:
    """Tests for create_extraction_dataset factory."""

    def test_creates_dataset_with_default_evaluators(self) -> None:
        """Dataset created with default evaluators for extraction."""
        case = Case(
            name="test",
            inputs=SampleContext(data="test"),
            expected_output=SampleOutput(result="hello"),
        )

        dataset = create_extraction_dataset("test_dataset", [case])

        assert dataset.name == "test_dataset"
        assert len(dataset.cases) == 1
        # Should have default evaluators
        assert len(dataset.evaluators) > 0

    def test_creates_dataset_with_custom_evaluators(self) -> None:
        """Dataset created with custom field evaluators."""
        case = Case(
            name="test",
            inputs=SampleContext(data="test"),
            expected_output=SampleOutput(result="hello", count=42),
        )

        field_evaluators = [("result", 0.0), ("count", 0.1)]
        dataset = create_extraction_dataset("test_dataset", [case], field_evaluators)

        assert dataset.name == "test_dataset"
        assert len(dataset.evaluators) == 2  # One per field


class TestLLMEvaluator:
    """Tests for LLMEvaluator class."""

    @pytest.mark.asyncio
    async def test_evaluate_structured_collects_scores(
        self,
        llm_settings: LLMSettings,
    ) -> None:
        """evaluate_structured aggregates per-evaluator scores from cases that have scores."""
        from unittest.mock import AsyncMock, MagicMock, patch

        client = LLMClient(llm_settings)
        evaluator = LLMEvaluator(client)

        field_evaluator = FieldMatchEvaluator("result")
        case = Case(
            name="scored_case",
            inputs=SampleContext(data="test"),
            expected_output=SampleOutput(result="hello"),
        )
        dataset = Dataset(cases=[case], evaluators=[field_evaluator], name="scored_dataset")

        config = StructuredAgentConfig(
            deps_type=SampleContext,
            output_type=SampleOutput,
        )

        mock_result = MagicMock()
        mock_result.output = SampleOutput(result="hello")

        with (
            patch.object(LLMClient, "create_agent") as mock_create_agent,
            patch.object(LLMClient, "run", new_callable=AsyncMock, return_value=mock_result),
        ):
            mock_create_agent.return_value = MagicMock()
            result = await evaluator.evaluate_structured(
                dataset,
                agent_config=config,
            )

        assert result.average_scores, "Expected non-empty average_scores when evaluators produce scores"

    @pytest.mark.asyncio
    async def test_evaluate_structured_runs_agent(
        self,
        llm_settings: LLMSettings,
    ) -> None:
        """Evaluation runs agent against all dataset cases."""
        from unittest.mock import AsyncMock, MagicMock, patch

        client = LLMClient(llm_settings)
        evaluator = LLMEvaluator(client)

        # Create a simple dataset
        case = Case(
            name="test_case",
            inputs=SampleContext(data="test"),
            expected_output=SampleOutput(result="expected"),
        )
        dataset = Dataset(cases=[case], evaluators=[], name="test_dataset")

        config = StructuredAgentConfig(
            deps_type=SampleContext,
            output_type=SampleOutput,
        )

        # Patch at class level since LLMClient uses __slots__
        with (
            patch.object(LLMClient, "create_agent") as mock_create_agent,
            patch.object(LLMClient, "run", new_callable=AsyncMock) as mock_run,
        ):
            mock_agent = MagicMock()
            mock_create_agent.return_value = mock_agent

            # Mock the run method to return expected output
            mock_result = MagicMock()
            mock_result.output = SampleOutput(result="expected")
            mock_run.return_value = mock_result

            result = await evaluator.evaluate_structured(
                dataset,
                agent_config=config,
            )

            assert isinstance(result, EvaluationResult)
            assert result.dataset_name == "test_dataset"
            assert result.total_cases == 1

    def test_evaluation_result_pass_rate(self) -> None:
        """EvaluationResult calculates pass rate correctly."""
        # All pass
        result = EvaluationResult(
            dataset_name="test",
            total_cases=10,
            passed_cases=10,
            average_scores={},
            report=None,
        )
        assert result.pass_rate == pytest.approx(1.0)

        # Half pass
        result = EvaluationResult(
            dataset_name="test",
            total_cases=10,
            passed_cases=5,
            average_scores={},
            report=None,
        )
        assert result.pass_rate == pytest.approx(0.5)

        # None pass
        result = EvaluationResult(
            dataset_name="test",
            total_cases=10,
            passed_cases=0,
            average_scores={},
            report=None,
        )
        assert result.pass_rate == pytest.approx(0.0)

        # Empty dataset
        result = EvaluationResult(
            dataset_name="test",
            total_cases=0,
            passed_cases=0,
            average_scores={},
            report=None,
        )
        assert result.pass_rate == pytest.approx(0.0)
