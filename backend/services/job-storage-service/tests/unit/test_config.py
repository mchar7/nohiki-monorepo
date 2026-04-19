"""Unit tests for core/config.py module."""

from __future__ import annotations


class TestSettings:
    """Tests for Settings model."""

    def test_service_name(self) -> None:
        """Test that service name is correct."""
        from job_storage_service.core.config import get_settings

        settings = get_settings()
        assert settings.service_name == "job-storage-service"

    def test_service_version(self) -> None:
        """Test that service version is set."""
        from job_storage_service.core.config import get_settings

        settings = get_settings()
        assert settings.service_version == "0.1.0"

    def test_service_friendly_names(self) -> None:
        """Test that friendly names are set."""
        from job_storage_service.core.config import get_settings

        settings = get_settings()
        assert settings.service_name_friendly == "Listing Store Service"
        assert "storage" in settings.service_desc_friendly.lower()


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings_instance(self) -> None:
        """Test that get_settings returns a Settings instance."""
        from job_storage_service.core.config import Settings, get_settings

        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_caching(self) -> None:
        """Test that get_settings returns cached instance."""
        from job_storage_service.core.config import get_settings

        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2
