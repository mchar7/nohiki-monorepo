"""Unit tests for LLM metrics module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nohiki_llm_client.config.constants import (
    METRIC_LLM_CACHE_HITS,
    METRIC_LLM_COMPLETION_TOKENS,
    METRIC_LLM_COST,
    METRIC_LLM_ERRORS,
    METRIC_LLM_PROMPT_TOKENS,
    METRIC_LLM_REQUEST_DURATION,
    METRIC_LLM_REQUESTS_TOTAL,
    OTEL_METER_NAME,
)
from nohiki_llm_client.observability.metrics import (
    LLMMetrics,
    RequestMetricsParams,
    get_llm_metrics,
)


class TestLLMMetrics:
    """Tests for LLMMetrics class."""

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_init_creates_meter(self, mock_get_meter: MagicMock) -> None:
        """Initializes with OpenTelemetry meter."""
        mock_meter = MagicMock()
        mock_get_meter.return_value = mock_meter

        LLMMetrics()

        mock_get_meter.assert_called_once_with(OTEL_METER_NAME)

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_init_creates_requests_counter(self, mock_get_meter: MagicMock) -> None:
        """Creates requests counter with correct name."""
        mock_meter = MagicMock()
        mock_get_meter.return_value = mock_meter

        LLMMetrics()

        mock_meter.create_counter.assert_any_call(
            METRIC_LLM_REQUESTS_TOTAL,
            description="Total LLM API requests",
            unit="1",
        )

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_init_creates_latency_histogram(self, mock_get_meter: MagicMock) -> None:
        """Creates latency histogram with correct name."""
        mock_meter = MagicMock()
        mock_get_meter.return_value = mock_meter

        LLMMetrics()

        mock_meter.create_histogram.assert_called_once_with(
            METRIC_LLM_REQUEST_DURATION,
            description="LLM request latency",
            unit="s",
        )

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_init_creates_prompt_tokens_counter(
        self,
        mock_get_meter: MagicMock,
    ) -> None:
        """Creates prompt tokens counter with correct name."""
        mock_meter = MagicMock()
        mock_get_meter.return_value = mock_meter

        LLMMetrics()

        mock_meter.create_counter.assert_any_call(
            METRIC_LLM_PROMPT_TOKENS,
            description="Total prompt tokens used",
            unit="1",
        )

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_init_creates_completion_tokens_counter(
        self,
        mock_get_meter: MagicMock,
    ) -> None:
        """Creates completion tokens counter with correct name."""
        mock_meter = MagicMock()
        mock_get_meter.return_value = mock_meter

        LLMMetrics()

        mock_meter.create_counter.assert_any_call(
            METRIC_LLM_COMPLETION_TOKENS,
            description="Total completion tokens generated",
            unit="1",
        )

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_init_creates_errors_counter(self, mock_get_meter: MagicMock) -> None:
        """Creates errors counter with correct name."""
        mock_meter = MagicMock()
        mock_get_meter.return_value = mock_meter

        LLMMetrics()

        mock_meter.create_counter.assert_any_call(
            METRIC_LLM_ERRORS,
            description="LLM request errors",
            unit="1",
        )

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_init_creates_cost_counter(self, mock_get_meter: MagicMock) -> None:
        """Creates cost counter with correct name."""
        mock_meter = MagicMock()
        mock_get_meter.return_value = mock_meter

        LLMMetrics()

        mock_meter.create_counter.assert_any_call(
            METRIC_LLM_COST,
            description="Estimated cost in micro-dollars (1/1,000,000 USD)",
            unit="1",
        )

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_init_creates_cache_hits_counter(self, mock_get_meter: MagicMock) -> None:
        """Creates cache hits counter with correct name."""
        mock_meter = MagicMock()
        mock_get_meter.return_value = mock_meter

        LLMMetrics()

        mock_meter.create_counter.assert_any_call(
            METRIC_LLM_CACHE_HITS,
            description="Prompt cache hits",
            unit="1",
        )


class TestLLMMetricsRecordRequest:
    """Tests for LLMMetrics.record_request method."""

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_records_success_request(self, mock_get_meter: MagicMock) -> None:
        """Records successful request with correct attributes."""
        mock_requests = MagicMock()
        mock_latency = MagicMock()
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = [
            mock_requests,  # requests
            MagicMock(),  # prompt_tokens
            MagicMock(),  # completion_tokens
            MagicMock(),  # errors
            MagicMock(),  # cost_microdollars
            MagicMock(),  # cache_hits
            MagicMock(),  # cache_read_tokens
            MagicMock(),  # cache_write_tokens
        ]
        mock_meter.create_histogram.return_value = mock_latency
        mock_get_meter.return_value = mock_meter
        m = LLMMetrics()

        m.record_request(RequestMetricsParams(model="gpt-4", provider="openai", duration_seconds=1.5, success=True))

        expected_attrs = {"model": "gpt-4", "provider": "openai", "status": "success"}
        mock_requests.add.assert_called_once_with(1, expected_attrs)
        mock_latency.record.assert_called_once_with(1.5, expected_attrs)

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_records_error_request(self, mock_get_meter: MagicMock) -> None:
        """Records failed request and increments error counter."""
        mock_errors = MagicMock()
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = [
            MagicMock(),  # requests
            MagicMock(),  # prompt_tokens
            MagicMock(),  # completion_tokens
            mock_errors,  # errors
            MagicMock(),  # cost_microdollars
            MagicMock(),  # cache_hits
            MagicMock(),  # cache_read_tokens
            MagicMock(),  # cache_write_tokens
        ]
        mock_get_meter.return_value = mock_meter
        m = LLMMetrics()

        m.record_request(
            RequestMetricsParams(
                model="gpt-4",
                provider="openai",
                duration_seconds=0.5,
                success=False,
                error_type="RateLimitError",
            )
        )

        expected_attrs = {
            "model": "gpt-4",
            "provider": "openai",
            "status": "error",
            "error_type": "RateLimitError",
        }
        mock_errors.add.assert_called_once_with(1, expected_attrs)

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_records_prompt_tokens(self, mock_get_meter: MagicMock) -> None:
        """Records prompt tokens when provided."""
        mock_prompt_tokens = MagicMock()
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = [
            MagicMock(),  # requests
            mock_prompt_tokens,  # prompt_tokens
            MagicMock(),  # completion_tokens
            MagicMock(),  # errors
            MagicMock(),  # cost_microdollars
            MagicMock(),  # cache_hits
            MagicMock(),  # cache_read_tokens
            MagicMock(),  # cache_write_tokens
        ]
        mock_get_meter.return_value = mock_meter
        m = LLMMetrics()

        m.record_request(
            RequestMetricsParams(
                model="gpt-4",
                provider="openai",
                duration_seconds=1.0,
                prompt_tokens=100,
            )
        )

        expected_attrs = {"model": "gpt-4", "provider": "openai", "status": "success"}
        mock_prompt_tokens.add.assert_called_once_with(100, expected_attrs)

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_skips_zero_prompt_tokens(self, mock_get_meter: MagicMock) -> None:
        """Does not record prompt tokens when zero."""
        mock_prompt_tokens = MagicMock()
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = [
            MagicMock(),  # requests
            mock_prompt_tokens,  # prompt_tokens
            MagicMock(),  # completion_tokens
            MagicMock(),  # errors
            MagicMock(),  # cost_microdollars
            MagicMock(),  # cache_hits
            MagicMock(),  # cache_read_tokens
            MagicMock(),  # cache_write_tokens
        ]
        mock_get_meter.return_value = mock_meter
        m = LLMMetrics()

        m.record_request(RequestMetricsParams(model="gpt-4", provider="openai", duration_seconds=1.0, prompt_tokens=0))

        mock_prompt_tokens.add.assert_not_called()

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_records_completion_tokens(self, mock_get_meter: MagicMock) -> None:
        """Records completion tokens when provided."""
        mock_completion_tokens = MagicMock()
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = [
            MagicMock(),  # requests
            MagicMock(),  # prompt_tokens
            mock_completion_tokens,  # completion_tokens
            MagicMock(),  # errors
            MagicMock(),  # cost_microdollars
            MagicMock(),  # cache_hits
            MagicMock(),  # cache_read_tokens
            MagicMock(),  # cache_write_tokens
        ]
        mock_get_meter.return_value = mock_meter
        m = LLMMetrics()

        m.record_request(
            RequestMetricsParams(
                model="gpt-4",
                provider="openai",
                duration_seconds=1.0,
                completion_tokens=50,
            )
        )

        expected_attrs = {"model": "gpt-4", "provider": "openai", "status": "success"}
        mock_completion_tokens.add.assert_called_once_with(50, expected_attrs)

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_skips_zero_completion_tokens(self, mock_get_meter: MagicMock) -> None:
        """Does not record completion tokens when zero."""
        mock_completion_tokens = MagicMock()
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = [
            MagicMock(),  # requests
            MagicMock(),  # prompt_tokens
            mock_completion_tokens,  # completion_tokens
            MagicMock(),  # errors
            MagicMock(),  # cost_microdollars
            MagicMock(),  # cache_hits
            MagicMock(),  # cache_read_tokens
            MagicMock(),  # cache_write_tokens
        ]
        mock_get_meter.return_value = mock_meter
        m = LLMMetrics()

        m.record_request(
            RequestMetricsParams(
                model="gpt-4",
                provider="openai",
                duration_seconds=1.0,
                completion_tokens=0,
            )
        )

        mock_completion_tokens.add.assert_not_called()

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_records_cache_read_tokens(self, mock_get_meter: MagicMock) -> None:
        """Records cache hit and cache read tokens when provided."""
        mock_cache_hits = MagicMock()
        mock_cache_read = MagicMock()
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = [
            MagicMock(),  # requests
            MagicMock(),  # prompt_tokens
            MagicMock(),  # completion_tokens
            MagicMock(),  # errors
            MagicMock(),  # cost_microdollars
            mock_cache_hits,  # cache_hits
            mock_cache_read,  # cache_read_tokens
            MagicMock(),  # cache_write_tokens
        ]
        mock_get_meter.return_value = mock_meter
        m = LLMMetrics()

        m.record_request(
            RequestMetricsParams(
                model="gpt-4",
                provider="openai",
                duration_seconds=1.0,
                cache_read_tokens=25,
            )
        )

        expected_attrs = {"model": "gpt-4", "provider": "openai", "status": "success"}
        mock_cache_hits.add.assert_called_once_with(1, expected_attrs)
        mock_cache_read.add.assert_called_once_with(25, expected_attrs)

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_skips_zero_cache_read_tokens(self, mock_get_meter: MagicMock) -> None:
        """Does not record cache hit when zero cache read tokens."""
        mock_cache_hits = MagicMock()
        mock_cache_read = MagicMock()
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = [
            MagicMock(),  # requests
            MagicMock(),  # prompt_tokens
            MagicMock(),  # completion_tokens
            MagicMock(),  # errors
            MagicMock(),  # cost_microdollars
            mock_cache_hits,  # cache_hits
            mock_cache_read,  # cache_read_tokens
            MagicMock(),  # cache_write_tokens
        ]
        mock_get_meter.return_value = mock_meter
        m = LLMMetrics()

        m.record_request(
            RequestMetricsParams(
                model="gpt-4",
                provider="openai",
                duration_seconds=1.0,
                cache_read_tokens=0,
            )
        )

        mock_cache_hits.add.assert_not_called()
        mock_cache_read.add.assert_not_called()

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_records_cache_write_tokens(self, mock_get_meter: MagicMock) -> None:
        """Records cache write tokens when provided."""
        mock_cache_write = MagicMock()
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = [
            MagicMock(),  # requests
            MagicMock(),  # prompt_tokens
            MagicMock(),  # completion_tokens
            MagicMock(),  # errors
            MagicMock(),  # cost_microdollars
            MagicMock(),  # cache_hits
            MagicMock(),  # cache_read_tokens
            mock_cache_write,  # cache_write_tokens
        ]
        mock_get_meter.return_value = mock_meter
        m = LLMMetrics()

        m.record_request(
            RequestMetricsParams(
                model="gpt-4",
                provider="openai",
                duration_seconds=1.0,
                cache_write_tokens=30,
            )
        )

        expected_attrs = {"model": "gpt-4", "provider": "openai", "status": "success"}
        mock_cache_write.add.assert_called_once_with(30, expected_attrs)

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_records_cost(self, mock_get_meter: MagicMock) -> None:
        """Records cost when provided."""
        mock_cost = MagicMock()
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = [
            MagicMock(),  # requests
            MagicMock(),  # prompt_tokens
            MagicMock(),  # completion_tokens
            MagicMock(),  # errors
            mock_cost,  # cost_microdollars
            MagicMock(),  # cache_hits
            MagicMock(),  # cache_read_tokens
            MagicMock(),  # cache_write_tokens
        ]
        mock_get_meter.return_value = mock_meter
        m = LLMMetrics()

        m.record_request(
            RequestMetricsParams(
                model="gpt-4",
                provider="openai",
                duration_seconds=1.0,
                cost_microdollars=500,
            )
        )

        expected_attrs = {"model": "gpt-4", "provider": "openai", "status": "success"}
        mock_cost.add.assert_called_once_with(500, expected_attrs)

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_skips_none_cost(self, mock_get_meter: MagicMock) -> None:
        """Does not record cost when None."""
        mock_cost = MagicMock()
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = [
            MagicMock(),  # requests
            MagicMock(),  # prompt_tokens
            MagicMock(),  # completion_tokens
            MagicMock(),  # errors
            mock_cost,  # cost_microdollars
            MagicMock(),  # cache_hits
            MagicMock(),  # cache_read_tokens
            MagicMock(),  # cache_write_tokens
        ]
        mock_get_meter.return_value = mock_meter
        m = LLMMetrics()

        m.record_request(
            RequestMetricsParams(
                model="gpt-4",
                provider="openai",
                duration_seconds=1.0,
                cost_microdollars=None,
            )
        )

        mock_cost.add.assert_not_called()

    @patch("nohiki_llm_client.observability.metrics.metrics.get_meter")
    def test_includes_use_case_attribute(self, mock_get_meter: MagicMock) -> None:
        """Includes use_case in attributes when provided."""
        mock_requests = MagicMock()
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = [
            mock_requests,  # requests
            MagicMock(),  # prompt_tokens
            MagicMock(),  # completion_tokens
            MagicMock(),  # errors
            MagicMock(),  # cost_microdollars
            MagicMock(),  # cache_hits
            MagicMock(),  # cache_read_tokens
            MagicMock(),  # cache_write_tokens
        ]
        mock_get_meter.return_value = mock_meter
        m = LLMMetrics()

        m.record_request(
            RequestMetricsParams(
                model="gpt-4",
                provider="openai",
                duration_seconds=1.0,
                use_case="resume_tailoring",
            )
        )

        expected_attrs = {
            "model": "gpt-4",
            "provider": "openai",
            "status": "success",
            "use_case": "resume_tailoring",
        }
        mock_requests.add.assert_called_once_with(1, expected_attrs)


class TestGetLLMMetrics:
    """Tests for get_llm_metrics function."""

    def teardown_method(self) -> None:
        """Clear the cached metrics instance after each test."""
        get_llm_metrics.cache_clear()

    def test_returns_llm_metrics_instance(self) -> None:
        """Returns an LLMMetrics instance."""
        get_llm_metrics.cache_clear()
        result = get_llm_metrics()
        assert isinstance(result, LLMMetrics)

    def test_returns_singleton(self) -> None:
        """Returns the same instance on subsequent calls."""
        get_llm_metrics.cache_clear()
        first = get_llm_metrics()
        second = get_llm_metrics()
        assert first is second
