"""Unit tests for the event_metadata module."""

from __future__ import annotations

from nohiki.common.v1 import EventMetadata
from nohiki_db_utils import EVENT_VERSION, create_event_metadata


class TestCreateEventMetadata:
    """Tests for create_event_metadata helper function."""

    def test_creates_valid_metadata(self) -> None:
        """Test that metadata is created with required fields."""
        metadata = create_event_metadata("test-service")

        assert metadata.event_id is not None
        assert len(metadata.event_id) == 36  # UUID format
        assert metadata.timestamp is not None
        assert metadata.source_service == "test-service"
        assert metadata.version == "v1"

    def test_generates_unique_event_ids(self) -> None:
        """Test that each call generates a unique event_id."""
        metadata1 = create_event_metadata("test-service")
        metadata2 = create_event_metadata("test-service")

        assert metadata1.event_id != metadata2.event_id

    def test_timestamp_is_datetime(self) -> None:
        """Test that timestamp is a datetime object."""
        metadata = create_event_metadata("test-service")

        # Timestamp should be a datetime-compatible object
        assert metadata.timestamp is not None
        # Check it has datetime attributes
        assert hasattr(metadata.timestamp, "year")
        assert hasattr(metadata.timestamp, "month")
        assert hasattr(metadata.timestamp, "day")

    def test_includes_correlation_id_when_provided(self) -> None:
        """Test that correlation_id is included when provided."""
        metadata = create_event_metadata("test-service", "correlation-123")

        assert metadata.correlation_id == "correlation-123"

    def test_correlation_id_is_none_when_not_provided(self) -> None:
        """Test that correlation_id is None when not provided."""
        metadata = create_event_metadata("test-service")

        assert metadata.correlation_id is None or metadata.correlation_id == ""

    def test_includes_causation_id_when_provided(self) -> None:
        """Test that causation_id is included when provided."""
        metadata = create_event_metadata("test-service", causation_id="causation-456")

        assert metadata.causation_id == "causation-456"

    def test_allows_custom_version(self) -> None:
        """Test that a custom version can be provided."""
        metadata = create_event_metadata("test-service", version="v2")

        assert metadata.version == "v2"

    def test_default_version_is_v1(self) -> None:
        """Test that default version is v1."""
        metadata = create_event_metadata("test-service")

        assert metadata.version == EVENT_VERSION
        assert metadata.version == "v1"

    def test_returns_event_metadata_instance(self) -> None:
        """Test that the return type is EventMetadata."""
        metadata = create_event_metadata("test-service")

        assert isinstance(metadata, EventMetadata)

    def test_all_parameters_together(self) -> None:
        """Test creating metadata with all parameters."""
        metadata = create_event_metadata(
            source_service="my-service",
            correlation_id="corr-123",
            causation_id="cause-456",
            version="v3",
        )

        assert metadata.source_service == "my-service"
        assert metadata.correlation_id == "corr-123"
        assert metadata.causation_id == "cause-456"
        assert metadata.version == "v3"


class TestEventVersion:
    """Tests for EVENT_VERSION constant."""

    def test_event_version_is_v1(self) -> None:
        """Test that EVENT_VERSION is v1."""
        assert EVENT_VERSION == "v1"
