"""Unit tests for Phoenix instrumentation helper functions."""

from __future__ import annotations

from unittest.mock import patch

from nohiki_llm_client.config.constants import PHOENIX_SERVICE_NAMESPACE
from nohiki_llm_client.observability.phoenix import (
    create_grpc_exporter,
    create_openinference_processor,
    create_phoenix_resource,
)


class TestCreatePhoenixResource:
    """Tests for create_phoenix_resource function."""

    def test_creates_resource_with_correct_attributes(self) -> None:
        """Test resource has project name and service attributes."""
        resource = create_phoenix_resource("test-project", "test-service")

        attrs = dict(resource.attributes)
        assert attrs["openinference.project.name"] == "test-project"
        assert attrs["service.name"] == "test-service"
        assert attrs["service.namespace"] == PHOENIX_SERVICE_NAMESPACE

    def test_handles_empty_project_name(self) -> None:
        """Test resource creation with empty project name."""
        resource = create_phoenix_resource("", "test-service")
        attrs = dict(resource.attributes)
        assert attrs["openinference.project.name"] == ""


class TestCreateGrpcExporter:
    """Tests for create_grpc_exporter function."""

    def test_creates_exporter_with_correct_endpoint(self) -> None:
        """Test exporter is created with correct endpoint configuration."""
        with patch("nohiki_llm_client.observability.phoenix.OTLPSpanExporter") as mock_exporter:
            create_grpc_exporter("http://localhost:4317", 10.0)

            mock_exporter.assert_called_once_with(
                endpoint="http://localhost:4317",
                insecure=True,
                timeout=10,
            )

    def test_removes_trailing_slash_from_endpoint(self) -> None:
        """Test trailing slash is removed from endpoint."""
        with patch("nohiki_llm_client.observability.phoenix.OTLPSpanExporter") as mock_exporter:
            create_grpc_exporter("http://localhost:4317/", 5.0)

            mock_exporter.assert_called_once_with(
                endpoint="http://localhost:4317",
                insecure=True,
                timeout=5,
            )


class TestCreateOpeninferenceProcessor:
    """Tests for create_openinference_processor function."""

    def test_creates_openinference_processor(self) -> None:
        """Test OpenInference processor is created."""
        processor = create_openinference_processor()
        assert processor is not None
