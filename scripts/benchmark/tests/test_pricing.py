"""Tests for pricing cost calculation using genai_prices."""

from __future__ import annotations

import pytest
from pydantic_ai.usage import RequestUsage

from llm_benchmark.pricing import (
    calc_cost,
    estimate_benchmark_cost,
    get_per_million_prices,
)


class TestCalcCost:
    """Tests for calc_cost function."""

    def test_ollama_model_returns_zero(self) -> None:
        usage = RequestUsage(input_tokens=1000, output_tokens=500)
        cost = calc_cost(usage, "ollama:qwen3:30b")
        assert cost == pytest.approx(0.0)

    def test_unknown_provider_returns_none(self) -> None:
        usage = RequestUsage(input_tokens=1000, output_tokens=500)
        cost = calc_cost(usage, "mycloud:some/model")
        assert cost is None

    def test_unknown_model_returns_none(self) -> None:
        usage = RequestUsage(input_tokens=1000, output_tokens=500)
        cost = calc_cost(usage, "openrouter:nonexistent/model-xyz-99999")
        assert cost is None

    def test_known_model_returns_float(self) -> None:
        usage = RequestUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = calc_cost(usage, "openrouter:google/gemini-2.5-flash")
        assert cost is None or isinstance(cost, float)

    def test_no_provider_prefix_raises(self) -> None:
        usage = RequestUsage(input_tokens=100, output_tokens=50)
        with pytest.raises(ValueError, match="provider:model_name"):
            calc_cost(usage, "bare-model-name")

    def test_zero_tokens_ollama_returns_zero(self) -> None:
        usage = RequestUsage(input_tokens=0, output_tokens=0)
        cost = calc_cost(usage, "ollama:llama3.2:3b")
        assert cost == pytest.approx(0.0)

    def test_cost_type_is_float_or_none(self) -> None:
        usage = RequestUsage(input_tokens=5000, output_tokens=1000)
        for model in ["openrouter:google/gemini-2.5-flash", "openrouter:nonexistent/xyz"]:
            cost = calc_cost(usage, model)
            assert cost is None or isinstance(cost, float)


class TestGetPerMillionPrices:
    """Tests for get_per_million_prices function."""

    def test_ollama_returns_zero_tuple(self) -> None:
        inp, out = get_per_million_prices("ollama:qwen3:30b")
        assert inp == pytest.approx(0.0)
        assert out == pytest.approx(0.0)

    def test_unknown_provider_returns_none_tuple(self) -> None:
        inp, out = get_per_million_prices("mycloud:some/model")
        assert inp is None
        assert out is None

    def test_unknown_model_returns_none_tuple(self) -> None:
        inp, out = get_per_million_prices("openrouter:nonexistent/model-xyz-99999")
        assert inp is None
        assert out is None

    def test_returns_tuple_of_two(self) -> None:
        result = get_per_million_prices("openrouter:google/gemini-2.5-flash")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_values_are_float_or_none(self) -> None:
        inp, out = get_per_million_prices("openrouter:google/gemini-2.5-flash")
        assert inp is None or isinstance(inp, float)
        assert out is None or isinstance(out, float)

    def test_no_provider_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="provider:model_name"):
            get_per_million_prices("bare-model-name")


class TestEstimateBenchmarkCost:
    """Tests for estimate_benchmark_cost function."""

    def test_returns_dict_keyed_by_model(self) -> None:
        models = ["ollama:qwen3:30b", "openrouter:nonexistent/xyz"]
        costs = estimate_benchmark_cost(models=models, fixtures_count=3, runs_per_fixture=2)
        assert set(costs.keys()) == set(models)

    def test_ollama_model_always_zero(self) -> None:
        costs = estimate_benchmark_cost(
            models=["ollama:qwen3:30b"],
            fixtures_count=5,
            runs_per_fixture=3,
        )
        assert costs["ollama:qwen3:30b"] == pytest.approx(0.0)

    def test_unknown_model_is_none(self) -> None:
        costs = estimate_benchmark_cost(
            models=["openrouter:nonexistent/model-xyz-99999"],
            fixtures_count=3,
            runs_per_fixture=1,
        )
        assert costs["openrouter:nonexistent/model-xyz-99999"] is None

    def test_multiple_models_independently_priced(self) -> None:
        costs = estimate_benchmark_cost(
            models=["ollama:qwen3:30b", "openrouter:nonexistent/xyz"],
            fixtures_count=2,
            runs_per_fixture=2,
        )
        assert costs["ollama:qwen3:30b"] == pytest.approx(0.0)
        assert costs["openrouter:nonexistent/xyz"] is None

    def test_values_are_float_or_none(self) -> None:
        models = ["ollama:llama3.2:3b", "openrouter:google/gemini-2.5-flash"]
        costs = estimate_benchmark_cost(models=models, fixtures_count=1, runs_per_fixture=1)
        for cost in costs.values():
            assert cost is None or isinstance(cost, float)


class TestLocalProviderZeroCost:
    """Both local transports (llama.cpp and Ollama) price at exactly zero."""

    @pytest.mark.parametrize("model", ["llamacpp:qwen3-30b", "ollama:qwen3:30b"])
    def test_calc_cost_is_zero(self, model: str) -> None:
        usage = RequestUsage(input_tokens=12_345, output_tokens=6_789)
        assert calc_cost(usage, model) == pytest.approx(0.0)

    @pytest.mark.parametrize("model", ["llamacpp:qwen3-30b", "ollama:qwen3:30b"])
    def test_calc_cost_zero_tokens_is_zero(self, model: str) -> None:
        assert calc_cost(RequestUsage(input_tokens=0, output_tokens=0), model) == pytest.approx(0.0)

    @pytest.mark.parametrize("model", ["llamacpp:qwen3-30b", "ollama:qwen3:30b"])
    def test_per_million_prices_are_zero(self, model: str) -> None:
        assert get_per_million_prices(model) == (pytest.approx(0.0), pytest.approx(0.0))
