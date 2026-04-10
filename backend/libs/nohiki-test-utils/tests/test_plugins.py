"""Tests for nohiki_test_utils plugins module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from nohiki_test_utils import plugins


class TestPytestConfigure:
    """Tests for pytest plugin configuration."""

    def test_pytest_configure_adds_markers(self, pytestconfig: pytest.Config) -> None:
        """Plugin configures pytest with custom markers."""
        plugins.pytest_configure(pytestconfig)
        markers = pytestconfig.getini("markers")
        assert any("integration" in str(m) for m in markers)


class TestCollectionModifyItems:
    """Tests for pytest_collection_modifyitems docker-skip behaviour."""

    def test_no_skip_when_docker_available(self, pytestconfig: pytest.Config) -> None:
        """Items are not modified when Docker daemon is available."""
        mock_item = MagicMock(spec=pytest.Item)
        mock_item.keywords = {"requires_docker": True}

        with patch("nohiki_test_utils.plugins.docker_daemon_available", return_value=True):
            plugins.pytest_collection_modifyitems(pytestconfig, [mock_item])

        mock_item.add_marker.assert_not_called()

    def test_skips_docker_items_when_daemon_unavailable(self, pytestconfig: pytest.Config) -> None:
        """Items with requires_docker are skipped when Docker is unavailable."""
        docker_item = MagicMock(spec=pytest.Item)
        docker_item.keywords = {"requires_docker": True}
        normal_item = MagicMock(spec=pytest.Item)
        normal_item.keywords = {}

        with patch("nohiki_test_utils.plugins.docker_daemon_available", return_value=False):
            plugins.pytest_collection_modifyitems(pytestconfig, [docker_item, normal_item])

        docker_item.add_marker.assert_called_once()
        normal_item.add_marker.assert_not_called()


class TestPluginMarkers:
    """Tests for custom pytest markers."""

    @pytest.mark.integration
    def test_integration_marker_is_available(self) -> None:
        """Integration test marker is available and usable."""

    @pytest.mark.requires_docker
    def test_requires_docker_marker_is_available(self) -> None:
        """Docker requirement marker is available and usable."""
