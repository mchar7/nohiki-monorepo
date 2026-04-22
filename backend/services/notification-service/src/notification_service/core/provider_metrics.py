"""Provider-level notification metrics."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from opentelemetry import metrics


@dataclass(frozen=True, slots=True)
class SendMetricData:
    """Data for recording a notification send attempt."""

    provider: str
    channel: str
    template: str
    duration_seconds: float
    success: bool
    recipient_domain: str | None = None


class NotificationProviderMetrics:
    """Per-provider notification metrics for monitoring and optimization."""

    def __init__(self) -> None:
        """Initialize notification provider metrics with OTEL meter."""
        self._meter = metrics.get_meter("nohiki.notification")

        self.sends = self._meter.create_counter(
            "nohiki_notification_sends_total",
            description="Notification send attempts by provider",
            unit="1",
        )
        self.send_latency = self._meter.create_histogram(
            "nohiki_notification_send_duration_seconds",
            description="Time to send notification via provider",
            unit="s",
        )

        self.deliveries = self._meter.create_counter(
            "nohiki_notification_deliveries_total",
            description="Notifications successfully delivered",
            unit="1",
        )
        self.bounces = self._meter.create_counter(
            "nohiki_notification_bounces_total",
            description="Notifications that bounced",
            unit="1",
        )
        self.complaints = self._meter.create_counter(
            "nohiki_notification_complaints_total",
            description="Spam complaints received",
            unit="1",
        )

        self.opens = self._meter.create_counter(
            "nohiki_notification_opens_total",
            description="Notifications opened by recipient",
            unit="1",
        )
        self.clicks = self._meter.create_counter(
            "nohiki_notification_clicks_total",
            description="Links clicked in notifications",
            unit="1",
        )
        self.unsubscribes = self._meter.create_counter(
            "nohiki_notification_unsubscribes_total",
            description="Unsubscribe requests",
            unit="1",
        )

        self.errors = self._meter.create_counter(
            "nohiki_notification_errors_total",
            description="Notification send errors",
            unit="1",
        )
        self.rate_limits = self._meter.create_counter(
            "nohiki_notification_rate_limits_total",
            description="Provider rate limit hits",
            unit="1",
        )

        self.queue_size = self._meter.create_up_down_counter(
            "nohiki_notification_queue_size",
            description="Current notification queue size",
            unit="1",
        )

    def record_send(self, data: SendMetricData) -> None:
        """Record a notification send attempt.

        Args:
            data: SendMetricData containing all send metric information.

        """
        attrs: dict[str, str] = {
            "provider": data.provider,
            "channel": data.channel,
            "template": data.template,
            "status": "success" if data.success else "error",
        }
        if data.recipient_domain:
            attrs["recipient_domain"] = data.recipient_domain

        self.sends.add(1, attrs)
        self.send_latency.record(data.duration_seconds, attrs)

        if not data.success:
            self.errors.add(1, attrs)

    def record_delivery_event(
        self,
        provider: str,
        channel: str,
        event_type: str,
    ) -> None:
        """Record a delivery event from provider webhook.

        Event types: delivered, bounce, complaint, open, click, unsubscribe
        """
        attrs = {"provider": provider, "channel": channel}

        match event_type:
            case "delivered":
                self.deliveries.add(1, attrs)
            case "bounce":
                self.bounces.add(1, attrs)
            case "complaint":
                self.complaints.add(1, attrs)
            case "open":
                self.opens.add(1, attrs)
            case "click":
                self.clicks.add(1, attrs)
            case "unsubscribe":
                self.unsubscribes.add(1, attrs)

    def record_rate_limit(self, provider: str, channel: str) -> None:
        """Record a rate limit hit from provider."""
        self.rate_limits.add(1, {"provider": provider, "channel": channel})

    def update_queue_size(self, delta: int) -> None:
        """Update the notification queue size."""
        self.queue_size.add(delta)


@lru_cache(maxsize=1)
def get_notification_provider_metrics() -> NotificationProviderMetrics:
    """Get singleton NotificationProviderMetrics instance."""
    return NotificationProviderMetrics()
