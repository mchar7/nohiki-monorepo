"""Tests for the LLM pricing calculation module."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from nohiki_llm_client.pricing import calc_llm_cost


class TestCalcLlmCost:
    """Tests for calc_llm_cost."""

    def test_returns_cost_for_known_model(self) -> None:
        mock_result = MagicMock()
        mock_result.total_price = Decimal("0.00123")
        usage = MagicMock()
        with patch("nohiki_llm_client.pricing.calc_price", return_value=mock_result) as mock_calc:
            cost = calc_llm_cost(usage, "gpt-4o", provider_api_url="https://api.openai.com/v1")
            assert cost == pytest.approx(0.00123)
            mock_calc.assert_called_once_with(usage, "gpt-4o", provider_api_url="https://api.openai.com/v1")

    def test_returns_none_for_lookup_error(self) -> None:
        usage = MagicMock()
        with patch("nohiki_llm_client.pricing.calc_price", side_effect=LookupError("unknown model")):
            result = calc_llm_cost(usage, "unknown/model", provider_api_url="https://unknown.api/v1")
            assert result is None

    def test_accepts_none_provider_api_url(self) -> None:
        mock_result = MagicMock()
        mock_result.total_price = Decimal("0.0")
        usage = MagicMock()
        with patch("nohiki_llm_client.pricing.calc_price", return_value=mock_result):
            cost = calc_llm_cost(usage, "some-model")
            assert cost == pytest.approx(0.0)

    def test_cost_converted_to_float(self) -> None:
        mock_result = MagicMock()
        mock_result.total_price = Decimal("1.23456789")
        usage = MagicMock()
        with patch("nohiki_llm_client.pricing.calc_price", return_value=mock_result):
            cost = calc_llm_cost(usage, "model")
            assert isinstance(cost, float)

    def test_zero_cost_returns_zero_float(self) -> None:
        mock_result = MagicMock()
        mock_result.total_price = Decimal(0)
        usage = MagicMock()
        with patch("nohiki_llm_client.pricing.calc_price", return_value=mock_result):
            cost = calc_llm_cost(usage, "model")
            assert cost == pytest.approx(0.0)
