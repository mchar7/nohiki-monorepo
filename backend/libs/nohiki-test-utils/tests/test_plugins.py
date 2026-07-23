"""Tests for nohiki_test_utils plugins module."""

from __future__ import annotations

from importlib import reload
from unittest.mock import MagicMock, patch

import nohiki_test_utils
import pytest
from nohiki_test_utils import plugins


class TestPytestConfigure:
    """Tests for pytest plugin configuration."""

    def test_pytest_configure_adds_markers(self, pytestconfig: pytest.Config) -> None:
        """Plugin configures pytest with custom markers."""
        plugins.pytest_configure(pytestconfig)
        markers = pytestconfig.getini("markers")
        assert any("integration" in str(m) for m in markers)

    def test_plugin_and_package_exports_reload_cleanly(self) -> None:
        """Entrypoint and lazy package exports remain valid on normal Python reload."""
        reloaded_package = reload(nohiki_test_utils)
        reloaded_plugin = reload(plugins)

        assert callable(reloaded_package.docker_daemon_available)
        assert reloaded_plugin.pytest_collection_modifyitems is not None
        with pytest.raises(AttributeError, match="has no attribute 'missing_export'"):
            reloaded_package.__getattr__("missing_export")


class TestCollectionModifyItems:
    """Tests for pytest_collection_modifyitems docker-skip behaviour."""

    def test_no_skip_when_docker_available(self) -> None:
        """Items are not modified when Docker daemon is available."""
        mock_item = MagicMock(spec=pytest.Item)
        mock_item.keywords = {"requires_docker": True}
        mock_item.fixturenames = []

        with patch("nohiki_test_utils.plugins._docker_daemon_available", return_value=True):
            plugins.pytest_collection_modifyitems([mock_item])

        mock_item.add_marker.assert_not_called()

    def test_skips_docker_items_when_daemon_unavailable(self) -> None:
        """Items with requires_docker are skipped when Docker is unavailable."""
        docker_item = MagicMock(spec=pytest.Item)
        docker_item.keywords = {"requires_docker": True}
        docker_item.fixturenames = ["postgres_container"]
        normal_item = MagicMock(spec=pytest.Item)
        normal_item.keywords = {}
        normal_item.fixturenames = []

        with patch("nohiki_test_utils.plugins._docker_daemon_available", return_value=False):
            plugins.pytest_collection_modifyitems([docker_item, normal_item])

        docker_item.add_marker.assert_called_once()
        normal_item.add_marker.assert_not_called()

    def test_errors_list_every_unmarked_container_fixture(self) -> None:
        """One usage error identifies every container-backed test missing the marker."""
        postgres_item = MagicMock(spec=pytest.Function)
        postgres_item.nodeid = "tests/test_postgres.py::test_query"
        postgres_item.fixturenames = ["async_engine", "postgres_container"]
        postgres_item.keywords = {}
        redis_item = MagicMock(spec=pytest.Function)
        redis_item.nodeid = "tests/test_redis.py::test_get"
        redis_item.fixturenames = ["redis_client", "redis_container"]
        redis_item.keywords = {}

        with pytest.raises(pytest.UsageError) as error:
            plugins.pytest_collection_modifyitems([postgres_item, redis_item])

        message = str(error.value)
        assert "tests/test_postgres.py::test_query (fixtures: async_engine, postgres_container)" in message
        assert "tests/test_redis.py::test_get (fixtures: redis_client, redis_container)" in message


class TestPluginMarkers:
    """Tests for custom pytest markers."""

    @pytest.mark.integration
    def test_integration_marker_is_available(self) -> None:
        """Integration test marker is available and usable."""

    @pytest.mark.requires_docker
    def test_requires_docker_marker_is_available(self) -> None:
        """Docker requirement marker is available and usable."""
