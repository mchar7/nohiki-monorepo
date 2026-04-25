"""Unit tests for service configuration."""

from __future__ import annotations

from unittest.mock import patch

from skill_graph_service.core.config import (
    Settings,
    get_manifest,
    get_settings,
)


class TestConfig:
    """Tests for configuration loading and manifest handling."""

    def test_get_settings(self) -> None:
        """Test that settings are loaded correctly."""
        settings = get_settings()
        assert isinstance(settings, Settings)
        assert settings.service_name == "skill-graph-service"

    def test_get_manifest_caching(self) -> None:
        """Test that get_manifest delegates to ManifestCache which caches."""
        with patch("skill_graph_service.core.config.ManifestCache") as mock_cache:
            mock_cache.get.return_value = "mock_manifest"

            m1 = get_manifest()
            m2 = get_manifest()

            assert m1 == "mock_manifest"
            assert m1 == m2

    def test_settings_kafka_consumer_group(self) -> None:
        """Test the kafka_consumer_group property."""
        settings = Settings()
        settings.service_name = "test-service"
        assert settings.kafka_consumer_group == "test-service-mention-primary"
