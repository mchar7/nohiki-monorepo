"""Unit tests for core/config.py module."""

from __future__ import annotations


class TestSchedulerSettings:
    """Tests for SchedulerSettings."""

    def test_default_values(self) -> None:
        """Test default scheduler settings values."""
        from job_ingest_schedule_service.core.config import SchedulerSettings

        settings = SchedulerSettings()
        assert settings.default_hours_old == 72
        assert settings.default_results_wanted == 50
        assert settings.batch_limit == 100

    def test_custom_values(self) -> None:
        """Test custom scheduler settings values."""
        from job_ingest_schedule_service.core.config import SchedulerSettings

        settings = SchedulerSettings(
            default_hours_old=24,
            default_results_wanted=100,
            batch_limit=50,
        )
        assert settings.default_hours_old == 24
        assert settings.default_results_wanted == 100
        assert settings.batch_limit == 50


class TestSettings:
    """Tests for Settings."""

    def test_service_name(self) -> None:
        """Test default service name."""
        from job_ingest_schedule_service.core.config import get_settings

        settings = get_settings()
        assert settings.service_name == "job-ingest-schedule-service"

    def test_service_version(self) -> None:
        """Test default service version."""
        from job_ingest_schedule_service.core.config import get_settings

        settings = get_settings()
        assert settings.service_version == "0.1.0"

    def test_service_friendly_names(self) -> None:
        """Test friendly service names."""
        from job_ingest_schedule_service.core.config import get_settings

        settings = get_settings()
        assert settings.service_name_friendly == "Scrape Scheduler Service"
        assert "scrapes" in settings.service_desc_friendly.lower()

    def test_scheduler_settings_available(self) -> None:
        """Test that scheduler settings are available."""
        from job_ingest_schedule_service.core.config import get_settings

        settings = get_settings()
        assert settings.scheduler is not None
        assert settings.scheduler.batch_limit > 0


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings_instance(self) -> None:
        """Test that get_settings returns a Settings instance."""
        from job_ingest_schedule_service.core.config import Settings, get_settings

        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_is_cached(self) -> None:
        """Test that get_settings returns cached instance."""
        from job_ingest_schedule_service.core.config import get_settings

        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2


def test_initial_migration_keeps_schema_and_frequency_constraint_without_outbox() -> None:
    """The schedule schema remains explicit while its retired outbox stays absent."""
    from pathlib import Path

    migration = (Path(__file__).resolve().parents[2] / "alembic" / "versions" / "001_initial_migration.py").read_text(
        encoding="utf-8"
    )

    assert 'SCHEMA_NAME = "job_schedule_schema"' in migration
    assert "frequency > INTERVAL '0 seconds'" in migration
    assert 'name="ck_schedule_frequency_positive"' in migration
    assert "outbox" not in migration.lower()
