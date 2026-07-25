"""Tests for job discovery provider metrics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestDiscoveryProviderMetrics:
    """Tests for DiscoveryProviderMetrics class."""

    def test_init_creates_all_metrics(self) -> None:
        """Verify all expected metrics are created during initialization."""
        with patch("job_ingest_discovery_service.providers.metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from job_ingest_discovery_service.providers.metrics import (
                DiscoveryProviderMetrics,
            )

            metrics_instance = DiscoveryProviderMetrics()

            mock_metrics.get_meter.assert_called_once_with("nohiki.discovery")

            assert mock_meter.create_counter.call_count >= 5
            assert mock_meter.create_histogram.call_count >= 1
            assert mock_meter.create_up_down_counter.call_count >= 1

            assert metrics_instance.discoveries is not None
            assert metrics_instance.discovery_duration is not None
            assert metrics_instance.jobs_discovered is not None
            assert metrics_instance.jobs_duplicates is not None
            assert metrics_instance.jobs_invalid is not None
            assert metrics_instance.errors is not None
            assert metrics_instance.rate_limits is not None
            assert metrics_instance.timeouts is not None
            assert metrics_instance.source_availability is not None

    def test_record_discovery_success(self) -> None:
        """Test recording a successful discovery operation."""
        with patch("job_ingest_discovery_service.providers.metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_histogram = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = mock_histogram
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from job_ingest_discovery_service.providers.metrics import (
                DiscoveryProviderMetrics,
            )

            metrics_instance = DiscoveryProviderMetrics()
            from job_ingest_discovery_service.providers.metrics import (
                DiscoveryMetricData,
            )

            metrics_instance.record_discovery(
                DiscoveryMetricData(
                    provider="jobspy",
                    source="indeed",
                    duration_seconds=5.0,
                    listings_found=25,
                    success=True,
                )
            )

            mock_counter.add.assert_called()
            mock_histogram.record.assert_called()

    def test_record_discovery_failure(self) -> None:
        """Test recording a failed discovery operation."""
        with patch("job_ingest_discovery_service.providers.metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_histogram = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = mock_histogram
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from job_ingest_discovery_service.providers.metrics import (
                DiscoveryProviderMetrics,
            )

            metrics_instance = DiscoveryProviderMetrics()
            from job_ingest_discovery_service.providers.metrics import (
                DiscoveryMetricData,
            )

            metrics_instance.record_discovery(
                DiscoveryMetricData(
                    provider="jobspy",
                    source="linkedin",
                    duration_seconds=2.5,
                    success=False,
                    error_type="TimeoutError",
                )
            )

            assert mock_counter.add.call_count >= 2

    def test_record_discovery_with_duplicates_and_invalid(self) -> None:
        """Test recording discovery with duplicate and invalid listing counts."""
        with patch("job_ingest_discovery_service.providers.metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_histogram = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = mock_histogram
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from job_ingest_discovery_service.providers.metrics import (
                DiscoveryProviderMetrics,
            )

            metrics_instance = DiscoveryProviderMetrics()
            from job_ingest_discovery_service.providers.metrics import (
                DiscoveryMetricData,
            )

            metrics_instance.record_discovery(
                DiscoveryMetricData(
                    provider="jsearch",
                    source="google",
                    duration_seconds=3.0,
                    listings_found=50,
                    duplicates=10,
                    invalid=5,
                    success=True,
                )
            )

            assert mock_counter.add.call_count >= 4

    def test_record_rate_limit(self) -> None:
        """Test recording rate limit hit."""
        with patch("job_ingest_discovery_service.providers.metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from job_ingest_discovery_service.providers.metrics import (
                DiscoveryProviderMetrics,
            )

            metrics_instance = DiscoveryProviderMetrics()
            metrics_instance.record_rate_limit("jobspy", "linkedin")

            mock_counter.add.assert_called_with(1, {"provider": "jobspy", "source": "linkedin"})

    def test_record_timeout(self) -> None:
        """Test recording timeout."""
        with patch("job_ingest_discovery_service.providers.metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from job_ingest_discovery_service.providers.metrics import (
                DiscoveryProviderMetrics,
            )

            metrics_instance = DiscoveryProviderMetrics()
            metrics_instance.record_timeout("jsearch", "glassdoor")

            mock_counter.add.assert_called_with(1, {"provider": "jsearch", "source": "glassdoor"})

    def test_update_source_availability_up(self) -> None:
        """Test marking source as available."""
        with patch("job_ingest_discovery_service.providers.metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_up_down = MagicMock()
            mock_meter.create_counter.return_value = MagicMock()
            mock_meter.create_histogram.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = mock_up_down
            mock_metrics.get_meter.return_value = mock_meter

            from job_ingest_discovery_service.providers.metrics import (
                DiscoveryProviderMetrics,
            )

            metrics_instance = DiscoveryProviderMetrics()
            metrics_instance.update_source_availability("indeed", is_available=True)

            mock_up_down.add.assert_called_with(1, {"source": "indeed"})

    def test_update_source_availability_down(self) -> None:
        """Test marking source as unavailable."""
        with patch("job_ingest_discovery_service.providers.metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_up_down = MagicMock()
            mock_meter.create_counter.return_value = MagicMock()
            mock_meter.create_histogram.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = mock_up_down
            mock_metrics.get_meter.return_value = mock_meter

            from job_ingest_discovery_service.providers.metrics import (
                DiscoveryProviderMetrics,
            )

            metrics_instance = DiscoveryProviderMetrics()
            metrics_instance.update_source_availability("linkedin", is_available=False)

            mock_up_down.add.assert_called_with(-1, {"source": "linkedin"})


class TestGetDiscoveryProviderMetrics:
    """Tests for get_discovery_provider_metrics singleton function."""

    def teardown_method(self) -> None:
        """Clear the cached metrics instance after each test."""
        from job_ingest_discovery_service.providers.metrics import (
            get_discovery_provider_metrics,
        )

        get_discovery_provider_metrics.cache_clear()

    def test_returns_singleton_instance(self) -> None:
        """Test that the function returns a singleton instance."""
        from job_ingest_discovery_service.providers.metrics import (
            DiscoveryProviderMetrics,
            get_discovery_provider_metrics,
        )

        get_discovery_provider_metrics.cache_clear()

        instance1 = get_discovery_provider_metrics()
        instance2 = get_discovery_provider_metrics()

        assert instance1 is instance2
        assert isinstance(instance1, DiscoveryProviderMetrics)

    def test_has_expected_attributes(self) -> None:
        """Test that the singleton has all expected attributes."""
        from job_ingest_discovery_service.providers.metrics import (
            get_discovery_provider_metrics,
        )

        get_discovery_provider_metrics.cache_clear()
        metrics = get_discovery_provider_metrics()

        assert hasattr(metrics, "discoveries")
        assert hasattr(metrics, "discovery_duration")
        assert hasattr(metrics, "jobs_discovered")
        assert hasattr(metrics, "jobs_duplicates")
        assert hasattr(metrics, "jobs_invalid")
        assert hasattr(metrics, "errors")
        assert hasattr(metrics, "rate_limits")
        assert hasattr(metrics, "timeouts")
        assert hasattr(metrics, "source_availability")
        assert hasattr(metrics, "record_discovery")
        assert hasattr(metrics, "record_rate_limit")
        assert hasattr(metrics, "record_timeout")
        assert hasattr(metrics, "update_source_availability")
