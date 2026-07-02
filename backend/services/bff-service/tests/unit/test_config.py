"""Unit tests for bff-service configuration."""

from __future__ import annotations

from bff_service.core.config import Settings, SSESettings


class TestSSESettingsDefaults:
    """Verify SSESettings default values."""

    def test_heartbeat_interval_default(self) -> None:
        """heartbeat_interval_seconds defaults to 10."""
        assert SSESettings().heartbeat_interval_seconds == 10

    def test_max_stream_duration_default(self) -> None:
        """max_stream_duration_seconds defaults to 600."""
        assert SSESettings().max_stream_duration_seconds == 600

    def test_reconnect_interval_default(self) -> None:
        """reconnect_interval_ms defaults to 5000."""
        assert SSESettings().reconnect_interval_ms == 5000

    def test_stale_cutoff_hours_default(self) -> None:
        """stale_cutoff_hours defaults to 24."""
        assert SSESettings().stale_cutoff_hours == 24

    def test_settings_has_sse_attribute(self) -> None:
        """Settings instance exposes .sse of type SSESettings."""
        settings = Settings()
        assert isinstance(settings.sse, SSESettings)
