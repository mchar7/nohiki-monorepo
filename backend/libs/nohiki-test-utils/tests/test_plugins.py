"""Tests for nohiki_test_utils plugins module."""

from __future__ import annotations

import importlib
import os
import socket
import sys
from pathlib import Path
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

    def test_configures_resolved_docker_host_when_unset(self) -> None:
        """Plugin setup exports the same endpoint that resolution selected."""
        endpoint = "unix:///run/user/1000/podman/podman.sock"
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("nohiki_test_utils.plugins.resolve_docker_endpoint", return_value=endpoint),
        ):
            plugins._configure_docker_host()

            assert os.environ["DOCKER_HOST"] == endpoint

    def test_preserves_user_configured_docker_host(self) -> None:
        """Plugin setup never replaces an explicit Docker endpoint."""
        endpoint = "tcp://explicit.example:2375"
        with (
            patch.dict(os.environ, {"DOCKER_HOST": endpoint}, clear=True),
            patch("nohiki_test_utils.plugins.resolve_docker_endpoint") as mock_resolve,
        ):
            plugins._configure_docker_host()

            assert os.environ["DOCKER_HOST"] == endpoint
            mock_resolve.assert_not_called()

    def test_plugin_and_package_exports_reload_cleanly(self) -> None:
        """Entrypoint and lazy package exports remain valid on a fresh import."""
        with patch.dict(sys.modules):
            for name in tuple(sys.modules):
                if name == "nohiki_test_utils" or name.startswith("nohiki_test_utils."):
                    del sys.modules[name]

            reloaded_package = importlib.import_module("nohiki_test_utils")
            reloaded_plugin = importlib.import_module("nohiki_test_utils.plugins")

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

        with patch(
            "nohiki_test_utils.plugins.resolve_docker_endpoint",
            return_value="unix:///var/run/docker.sock",
        ):
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

        with patch("nohiki_test_utils.plugins.resolve_docker_endpoint", return_value=None):
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


class TestOutboundNetworkIsolation:
    """Tests for the unit-test network boundary."""

    def test_unmarked_test_cannot_resolve_a_network_peer(self) -> None:
        """The guard bypasses dependency exception wrappers before DNS or transport I/O."""

        def resolve_through_dependency_wrapper() -> None:
            try:
                socket.getaddrinfo("example.com", 443)
            except Exception:
                pytest.fail("The network guard was hidden by a dependency exception wrapper")

        with pytest.raises(
            plugins._OutboundNetworkProhibited,
            match=r"Unmocked outbound network.*socket\.getaddrinfo.*Stub the network-facing function",
        ):
            resolve_through_dependency_wrapper()

    def test_import_time_block_retains_the_guard_diagnostic(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An import-time network attempt reports the blocked call instead of a broken module."""
        module_name = "_network_guard_import_probe"
        (tmp_path / f"{module_name}.py").write_text(
            'import socket\nsocket.getaddrinfo("example.com", 443)\n',
            encoding="utf-8",
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        with pytest.raises(
            plugins._OutboundNetworkProhibited,
            match=r"Unmocked outbound network.*socket\.getaddrinfo.*Stub the network-facing function",
        ):
            importlib.import_module(module_name)

        assert module_name not in sys.modules

    @pytest.mark.parametrize("host", ["127.0.0.1", "::1", "203.0.113.10"])
    def test_numeric_address_resolution_stays_local(self, host: str) -> None:
        """Parsing an IP literal does not perform DNS or transport I/O."""
        assert socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)

    @pytest.mark.parametrize("marker", sorted(plugins._NETWORK_ALLOWED_MARKERS))
    def test_ci_excluded_markers_allow_network(self, marker: str) -> None:
        """Every marker excluded from the unit lane is an explicit guard opt-out."""
        request = MagicMock(spec=pytest.FixtureRequest)
        request.node.get_closest_marker.side_effect = lambda candidate: object() if candidate == marker else None
        monkeypatch = MagicMock(spec=pytest.MonkeyPatch)

        plugins._enforce_no_outbound_network(request, monkeypatch)

        monkeypatch.setattr.assert_not_called()


class TestPluginMarkers:
    """Tests for custom pytest markers."""

    @pytest.mark.integration
    def test_integration_marker_is_available(self) -> None:
        """Integration test marker is available and usable."""

    @pytest.mark.requires_docker
    def test_requires_docker_marker_is_available(self) -> None:
        """Docker requirement marker is available and usable."""


class TestSecretsIsolation:
    """Tests for session-wide file-secret isolation."""

    def test_session_secrets_dir_is_an_empty_existing_directory(self) -> None:
        """Every session runs against a secrets tree that exists and holds no secrets."""
        secrets_dir = Path(os.environ["SECRETS_DIR"])

        assert secrets_dir.is_dir()
        assert list(secrets_dir.iterdir()) == []

    def test_teardown_removes_the_directory_the_hook_created(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The session secrets tree does not outlive the session that created it."""
        monkeypatch.setenv("SECRETS_DIR", os.environ["SECRETS_DIR"])
        config = MagicMock(spec=pytest.Config)
        config.stash = pytest.Stash()

        plugins.pytest_load_initial_conftests(config)
        created = Path(config.stash[plugins._EMPTY_SECRETS_DIR_KEY])
        assert created.is_dir()
        assert os.environ["SECRETS_DIR"] == str(created)

        plugins.pytest_unconfigure(config)

        assert not created.exists()
