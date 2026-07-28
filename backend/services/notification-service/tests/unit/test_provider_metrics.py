"""Tests for notification provider metrics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestNotificationProviderMetrics:
    """Tests for NotificationProviderMetrics class."""

    def test_init_creates_all_metrics(self) -> None:
        """Verify all expected metrics are created during initialization."""
        with patch("notification_service.core.provider_metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from notification_service.core.provider_metrics import (
                NotificationProviderMetrics,
            )

            metrics_instance = NotificationProviderMetrics()

            mock_metrics.get_meter.assert_called_once_with("nohiki.notification")

            assert mock_meter.create_counter.call_count >= 6
            assert mock_meter.create_histogram.call_count >= 1
            assert mock_meter.create_up_down_counter.call_count >= 1

            assert metrics_instance.sends is not None
            assert metrics_instance.send_latency is not None
            assert metrics_instance.deliveries is not None
            assert metrics_instance.bounces is not None
            assert metrics_instance.complaints is not None
            assert metrics_instance.opens is not None
            assert metrics_instance.clicks is not None
            assert metrics_instance.unsubscribes is not None
            assert metrics_instance.errors is not None
            assert metrics_instance.rate_limits is not None
            assert metrics_instance.queue_size is not None

    def test_record_send_success(self) -> None:
        """Test recording a successful send operation."""
        with patch("notification_service.core.provider_metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_histogram = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = mock_histogram
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from notification_service.core.provider_metrics import (
                NotificationProviderMetrics,
            )

            metrics_instance = NotificationProviderMetrics()
            from notification_service.core.provider_metrics import SendMetricData

            metrics_instance.record_send(
                SendMetricData(
                    provider="resend",
                    channel="email",
                    template="job_notification",
                    duration_seconds=0.5,
                    success=True,
                )
            )

            mock_counter.add.assert_called()
            mock_histogram.record.assert_called()

    def test_record_send_failure(self) -> None:
        """Test recording a failed send operation."""
        with patch("notification_service.core.provider_metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_histogram = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = mock_histogram
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from notification_service.core.provider_metrics import (
                NotificationProviderMetrics,
            )

            metrics_instance = NotificationProviderMetrics()
            from notification_service.core.provider_metrics import SendMetricData

            metrics_instance.record_send(
                SendMetricData(
                    provider="resend",
                    channel="email",
                    template="job_notification",
                    duration_seconds=0.5,
                    success=False,
                )
            )

            assert mock_counter.add.call_count >= 2

    def test_record_send_with_recipient_domain(self) -> None:
        """Test recording send with recipient domain for analytics."""
        with patch("notification_service.core.provider_metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_histogram = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = mock_histogram
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from notification_service.core.provider_metrics import (
                NotificationProviderMetrics,
            )

            metrics_instance = NotificationProviderMetrics()
            from notification_service.core.provider_metrics import SendMetricData

            metrics_instance.record_send(
                SendMetricData(
                    provider="resend",
                    channel="email",
                    template="job_notification",
                    duration_seconds=0.5,
                    success=True,
                    recipient_domain="gmail.com",
                )
            )

            mock_counter.add.assert_called()

    def test_record_delivery_event_delivered(self) -> None:
        """Test recording delivered event."""
        with patch("notification_service.core.provider_metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from notification_service.core.provider_metrics import (
                NotificationProviderMetrics,
            )

            metrics_instance = NotificationProviderMetrics()
            metrics_instance.record_delivery_event("resend", "email", "delivered")

            mock_counter.add.assert_called()

    def test_record_delivery_event_bounce(self) -> None:
        """Test recording bounce event."""
        with patch("notification_service.core.provider_metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from notification_service.core.provider_metrics import (
                NotificationProviderMetrics,
            )

            metrics_instance = NotificationProviderMetrics()
            metrics_instance.record_delivery_event("resend", "email", "bounce")

            mock_counter.add.assert_called()

    def test_record_delivery_event_complaint(self) -> None:
        """Test recording complaint event."""
        with patch("notification_service.core.provider_metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from notification_service.core.provider_metrics import (
                NotificationProviderMetrics,
            )

            metrics_instance = NotificationProviderMetrics()
            metrics_instance.record_delivery_event("resend", "email", "complaint")

            mock_counter.add.assert_called()

    def test_record_delivery_event_open(self) -> None:
        """Test recording open event."""
        with patch("notification_service.core.provider_metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from notification_service.core.provider_metrics import (
                NotificationProviderMetrics,
            )

            metrics_instance = NotificationProviderMetrics()
            metrics_instance.record_delivery_event("resend", "email", "open")

            mock_counter.add.assert_called()

    def test_record_delivery_event_click(self) -> None:
        """Test recording click event."""
        with patch("notification_service.core.provider_metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from notification_service.core.provider_metrics import (
                NotificationProviderMetrics,
            )

            metrics_instance = NotificationProviderMetrics()
            metrics_instance.record_delivery_event("resend", "email", "click")

            mock_counter.add.assert_called()

    def test_record_delivery_event_unsubscribe(self) -> None:
        """Test recording unsubscribe event."""
        with patch("notification_service.core.provider_metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from notification_service.core.provider_metrics import (
                NotificationProviderMetrics,
            )

            metrics_instance = NotificationProviderMetrics()
            metrics_instance.record_delivery_event("resend", "email", "unsubscribe")

            mock_counter.add.assert_called()

    def test_record_rate_limit(self) -> None:
        """Test recording rate limit hit."""
        with patch("notification_service.core.provider_metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_meter.create_histogram.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            from notification_service.core.provider_metrics import (
                NotificationProviderMetrics,
            )

            metrics_instance = NotificationProviderMetrics()
            metrics_instance.record_rate_limit("resend", "email")

            mock_counter.add.assert_called_with(1, {"provider": "resend", "channel": "email"})

    def test_update_queue_size_positive(self) -> None:
        """Test increasing queue size."""
        with patch("notification_service.core.provider_metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_up_down = MagicMock()
            mock_meter.create_counter.return_value = MagicMock()
            mock_meter.create_histogram.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = mock_up_down
            mock_metrics.get_meter.return_value = mock_meter

            from notification_service.core.provider_metrics import (
                NotificationProviderMetrics,
            )

            metrics_instance = NotificationProviderMetrics()
            metrics_instance.update_queue_size(5)

            mock_up_down.add.assert_called_with(5)

    def test_update_queue_size_negative(self) -> None:
        """Test decreasing queue size."""
        with patch("notification_service.core.provider_metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_up_down = MagicMock()
            mock_meter.create_counter.return_value = MagicMock()
            mock_meter.create_histogram.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = mock_up_down
            mock_metrics.get_meter.return_value = mock_meter

            from notification_service.core.provider_metrics import (
                NotificationProviderMetrics,
            )

            metrics_instance = NotificationProviderMetrics()
            metrics_instance.update_queue_size(-3)

            mock_up_down.add.assert_called_with(-3)


class TestGetNotificationProviderMetrics:
    """Tests for get_notification_provider_metrics singleton function."""

    def teardown_method(self) -> None:
        """Clear the cached metrics instance after each test."""
        from notification_service.core.provider_metrics import (
            get_notification_provider_metrics,
        )

        get_notification_provider_metrics.cache_clear()

    def test_returns_singleton_instance(self) -> None:
        """Test that the function returns a singleton instance."""
        from notification_service.core.provider_metrics import (
            NotificationProviderMetrics,
            get_notification_provider_metrics,
        )

        get_notification_provider_metrics.cache_clear()

        instance1 = get_notification_provider_metrics()
        instance2 = get_notification_provider_metrics()

        assert instance1 is instance2
        assert isinstance(instance1, NotificationProviderMetrics)

    def test_has_expected_attributes(self) -> None:
        """Test that the singleton has all expected attributes."""
        from notification_service.core.provider_metrics import (
            get_notification_provider_metrics,
        )

        get_notification_provider_metrics.cache_clear()
        metrics = get_notification_provider_metrics()

        assert hasattr(metrics, "sends")
        assert hasattr(metrics, "send_latency")
        assert hasattr(metrics, "deliveries")
        assert hasattr(metrics, "bounces")
        assert hasattr(metrics, "complaints")
        assert hasattr(metrics, "opens")
        assert hasattr(metrics, "clicks")
        assert hasattr(metrics, "unsubscribes")
        assert hasattr(metrics, "errors")
        assert hasattr(metrics, "rate_limits")
        assert hasattr(metrics, "queue_size")
        assert hasattr(metrics, "record_send")
        assert hasattr(metrics, "record_delivery_event")
        assert hasattr(metrics, "record_rate_limit")
        assert hasattr(metrics, "update_queue_size")
