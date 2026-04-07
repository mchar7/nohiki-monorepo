"""Tests for Python runtime metrics setup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nohiki_observability import Observability

_OBS_MODULE = "nohiki_observability.observability"


class TestRuntimeMetricsSetup:
    """Tests for _setup_runtime_metrics and its sub-methods."""

    def test_setup_runtime_metrics_calls_sub_methods(self) -> None:
        """Verify _setup_runtime_metrics delegates to instrument + event loop lag."""
        obs = Observability.builder().service("rt-test", "1.0.0").build()
        with (
            patch.object(Observability, "_instrument_system_metrics") as mock_sys,
            patch.object(Observability, "_setup_event_loop_lag_metric") as mock_lag,
        ):
            obs._setup_runtime_metrics()

        mock_sys.assert_called_once()
        mock_lag.assert_called_once()

    def test_instrument_system_metrics_available(self) -> None:
        """When system_metrics package is available, instrument is called."""
        obs = Observability.builder().service("rt-test", "1.0.0").build()
        mock_instrumentor = MagicMock()
        mock_module = MagicMock()
        mock_module.SystemMetricsInstrumentor.return_value = mock_instrumentor

        with patch(f"{_OBS_MODULE}.importlib.import_module", return_value=mock_module) as mock_import:
            obs._instrument_system_metrics()

        mock_import.assert_called_once_with("opentelemetry.instrumentation.system_metrics")
        mock_instrumentor.instrument.assert_called_once()

    def test_instrument_system_metrics_not_available(self) -> None:
        """When system_metrics package is missing, gracefully logs and continues."""
        obs = Observability.builder().service("rt-test", "1.0.0").build()

        with patch(f"{_OBS_MODULE}.importlib.import_module", side_effect=ImportError("not installed")):
            obs._instrument_system_metrics()

    def test_setup_event_loop_lag_metric_creates_gauge(self) -> None:
        """Event loop lag metric creates an observable gauge."""
        obs = Observability.builder().service("rt-test", "1.0.0").build()

        with patch.object(Observability, "_start_loop_lag_sampler"):
            obs._setup_event_loop_lag_metric()

        assert obs._loop_lag_seconds == 0.0

    def test_start_loop_lag_sampler_no_event_loop(self) -> None:
        """When no event loop exists, sampler setup is skipped gracefully."""
        obs = Observability.builder().service("rt-test", "1.0.0").build()
        obs._initialized = True

        with patch(f"{_OBS_MODULE}.asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            obs._start_loop_lag_sampler()

    def test_start_loop_lag_sampler_with_event_loop(self) -> None:
        """When event loop exists, sampler schedules callback."""
        obs = Observability.builder().service("rt-test", "1.0.0").build()
        obs._initialized = True

        mock_loop = MagicMock()
        with patch(f"{_OBS_MODULE}.asyncio.get_running_loop", return_value=mock_loop):
            obs._start_loop_lag_sampler()

        mock_loop.call_soon.assert_called_once()

    def test_loop_lag_seconds_initialized_to_zero(self) -> None:
        """_loop_lag_seconds is initialized to 0.0 in __init__."""
        obs = Observability.builder().service("rt-test", "1.0.0").build()
        assert obs._loop_lag_seconds == 0.0
