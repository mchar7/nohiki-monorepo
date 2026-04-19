"""Unit tests for events/__init__.py module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_imports_handlers_and_starts_consumers(self) -> None:
        """Test that start_event_consumer imports handlers and starts Kafka consumers."""
        with (
            patch("job_storage_service.events.kafka_client") as mock_kafka,
            patch("job_storage_service.events.logger") as mock_logger,
        ):
            mock_kafka.start_consumers = MagicMock()

            from job_storage_service.events import start_event_consumer

            start_event_consumer()

            mock_kafka.start_consumers.assert_called_once()
            mock_logger.info.assert_called()

    def test_logs_service_name_on_start(self) -> None:
        """Test that start_event_consumer logs the service name."""
        with (
            patch("job_storage_service.events.kafka_client") as mock_kafka,
            patch("job_storage_service.events.logger") as mock_logger,
            patch("job_storage_service.events.settings") as mock_settings,
        ):
            mock_kafka.start_consumers = MagicMock()
            mock_settings.service_name = "job-storage-service"

            from job_storage_service.events import start_event_consumer

            start_event_consumer()

            mock_logger.info.assert_called_with(
                "Starting event consumer",
                service="job-storage-service",
            )


class TestPublisherExports:
    """Tests for publisher function exports."""

    def test_exports_publish_context(self) -> None:
        """Test that PublishContext is exported."""
        from job_storage_service.events import PublishContext

        assert PublishContext is not None

    def test_exports_build_listing_snapshot(self) -> None:
        """Test that build_listing_snapshot is exported."""
        from job_storage_service.events import build_listing_snapshot

        assert callable(build_listing_snapshot)

    def test_exports_publish_listing_created_event(self) -> None:
        """Test that publish_listing_created_event is exported."""
        from job_storage_service.events import publish_listing_created_event

        assert callable(publish_listing_created_event)

    def test_exports_publish_listing_updated_event(self) -> None:
        """Test that publish_listing_updated_event is exported."""
        from job_storage_service.events import publish_listing_updated_event

        assert callable(publish_listing_updated_event)

    def test_exports_publish_listing_deleted_event(self) -> None:
        """Test that publish_listing_deleted_event is exported."""
        from job_storage_service.events import publish_listing_deleted_event

        assert callable(publish_listing_deleted_event)

    def test_exports_publish_listing_accepted_event(self) -> None:
        """Test that publish_listing_accepted_event is exported."""
        from job_storage_service.events import publish_listing_accepted_event

        assert callable(publish_listing_accepted_event)

    def test_exports_publish_duplicate_detected_event(self) -> None:
        """Test that publish_duplicate_detected_event is exported."""
        from job_storage_service.events import publish_duplicate_detected_event

        assert callable(publish_duplicate_detected_event)


class TestAllExports:
    """Tests for __all__ exports."""

    def test_all_contains_expected_exports(self) -> None:
        """Test that __all__ contains all expected exports."""
        from job_storage_service.events import __all__

        expected = [
            "PublishContext",
            "build_listing_snapshot",
            "publish_duplicate_detected_event",
            "publish_listing_accepted_event",
            "publish_listing_created_event",
            "publish_listing_deleted_event",
            "publish_listing_updated_event",
            "start_event_consumer",
        ]

        for export in expected:
            assert export in __all__, f"{export} missing from __all__"
