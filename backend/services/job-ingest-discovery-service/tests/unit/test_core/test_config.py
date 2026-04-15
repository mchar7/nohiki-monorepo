"""Tests for configuration module."""

from __future__ import annotations

import pytest


class TestSettings:
    """Tests for Settings class."""

    def test_default_values(self) -> None:
        """Test that default values are set correctly."""
        from job_ingest_discovery_service.core.config import Settings

        settings = Settings()
        assert settings.service_name == "job-ingest-discovery-service"
        assert settings.service_version == "0.1.0"
        assert settings.debug is False
        assert settings.host == "127.0.0.1"
        assert settings.port == 8000

    def test_discovery_settings(self) -> None:
        """Test discovery-related settings via nested DiscoverySettings."""
        from job_ingest_discovery_service.core.config import Settings

        settings = Settings()
        assert settings.discovery.max_concurrent == 10
        assert settings.discovery.timeout_seconds == 30
        assert settings.discovery.rate_limit_delay_seconds == pytest.approx(1.0)

    def test_database_settings(self) -> None:
        """Test database-backed idempotency/reservation config via DatabaseMixin."""
        from job_ingest_discovery_service.core.config import Settings

        settings = Settings()
        assert hasattr(settings, "database")
        assert settings.database.schema_name == "job_ingest_discovery_schema"
        assert settings.database_url == settings.database.connection_string

    def test_dedup_ttl_settings(self) -> None:
        """Test deduplication TTL setting."""
        from job_ingest_discovery_service.core.config import Settings

        settings = Settings()
        # Dedup TTL should be 30 days (2592000 seconds)
        assert settings.caching.dedup_ttl_seconds == 2592000

    def test_redis_settings(self) -> None:
        """Test Redis settings via RedisMixin."""
        from job_ingest_discovery_service.core.config import Settings

        settings = Settings()
        assert settings.redis is not None
        # redis_url property from mixin
        assert "redis" in settings.redis_url

    def test_caching_settings(self) -> None:
        """Test caching settings with extended DiscoveryCachingSettings."""
        from job_ingest_discovery_service.core.config import Settings

        settings = Settings()
        assert settings.caching is not None

        # Check default TTL values from base CachingSettings
        assert settings.caching.ttls.fallback_state == 86400
        assert settings.caching.ttls.short == 300
        assert settings.caching.ttls.medium == 3600

        # Check job cache TTL (service-specific)
        assert settings.caching.job_cache_ttl_seconds == 3600

        # Check JSearch API config
        assert settings.caching.jsearch_api.name == "jsearch"
        assert settings.caching.jsearch_api.requests_per_minute == 10
        assert settings.caching.jsearch_api.requests_per_hour == 1000
        assert settings.caching.jsearch_api.requests_per_day == 5000
        assert settings.caching.jsearch_api.fallback_ttl_seconds == 86400

    def test_caching_settings_key_builders(self) -> None:
        """Test caching settings key builder methods."""
        from job_ingest_discovery_service.core.config import Settings

        settings = Settings()

        # Test JSearch API rate limit key builder
        assert settings.caching.jsearch_api.rate_limit_key("hour") == "api:jsearch:ratelimit:hour"
        assert settings.caching.jsearch_api.fallback_key() == "api:jsearch:fallback"
        assert settings.caching.jsearch_api.health_key() == "api:jsearch:health"

        # Test base build_key method
        assert settings.caching.build_key("test", "key") == "test:key"

    def test_kafka_settings(self) -> None:
        """Test Kafka settings via KafkaMixin."""
        from job_ingest_discovery_service.core.config import Settings

        settings = Settings()
        # Bootstrap servers from kafka settings
        assert ":" in settings.kafka.bootstrap_servers
        # Consumer group from kafka_consumer_group property
        assert len(settings.kafka_consumer_group) > 0

    def test_observability_settings(self) -> None:
        """Test observability settings via nested ObservabilitySettings."""
        from job_ingest_discovery_service.core.config import Settings

        settings = Settings()
        assert settings.observability.otel_insecure is True
        assert settings.observability.logging.level == "INFO"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that environment variables override defaults."""
        monkeypatch.setenv("JOB_INGEST_DISCOVERY_DEBUG", "true")
        monkeypatch.setenv("JOB_INGEST_DISCOVERY_PORT", "9000")
        monkeypatch.setenv("JOB_INGEST_DISCOVERY_DISCOVERY__MAX_CONCURRENT", "20")

        from job_ingest_discovery_service.core.config import Settings

        # Create new instance to pick up env vars
        settings = Settings()
        assert settings.debug is True
        assert settings.port == 9000
        assert settings.discovery.max_concurrent == 20


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings_instance(self) -> None:
        """Test that get_settings returns a Settings instance."""
        from job_ingest_discovery_service.core.config import Settings, get_settings

        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_cached(self) -> None:
        """Test that get_settings returns cached instance."""
        from job_ingest_discovery_service.core.config import get_settings

        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2
