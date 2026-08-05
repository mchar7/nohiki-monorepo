"""Tests for nohiki_test_utils utils.docker module."""

from __future__ import annotations

import os
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from nohiki_test_utils.utils.docker import (
    DOCKER_ENDPOINT_VERDICT_ENV,
    _can_connect_tcp,
    _can_connect_unix_socket,
    _docker_context_host,
    docker_daemon_available,
    publish_docker_endpoint_verdict,
    resolve_docker_endpoint,
)


@pytest.fixture(autouse=True)
def _clear_docker_daemon_available_cache() -> Iterator[None]:
    """Keep the process-wide probe cache from leaking between tests."""
    resolve_docker_endpoint.cache_clear()
    yield
    resolve_docker_endpoint.cache_clear()


class TestCanConnectUnixSocket:
    """Tests for _can_connect_unix_socket function."""

    @patch("nohiki_test_utils.utils.docker.socket.socket")
    def test_can_connect_unix_socket_returns_true_on_success(self, mock_socket_class: MagicMock) -> None:
        """_can_connect_unix_socket returns True when socket connects."""
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket
        result = _can_connect_unix_socket(Path("/var/run/docker.sock"))
        assert result is True
        mock_socket.connect.assert_called_once()
        mock_socket.close.assert_called_once()

    @patch("nohiki_test_utils.utils.docker.socket.socket")
    def test_can_connect_unix_socket_returns_false_on_failure(self, mock_socket_class: MagicMock) -> None:
        """_can_connect_unix_socket returns False when socket fails."""
        mock_socket = MagicMock()
        mock_socket.connect.side_effect = OSError()
        mock_socket_class.return_value = mock_socket
        result = _can_connect_unix_socket(Path("/var/run/docker.sock"))
        assert result is False
        mock_socket.close.assert_called_once()


class TestCanConnectTcp:
    """Tests for _can_connect_tcp function."""

    @patch("nohiki_test_utils.utils.docker.socket.create_connection")
    def test_can_connect_tcp_returns_true_on_success(self, mock_create: MagicMock) -> None:
        """_can_connect_tcp returns True when TCP connects."""
        result = _can_connect_tcp("localhost", 2375)
        assert result is True
        mock_create.assert_called_once()

    @patch("nohiki_test_utils.utils.docker.socket.create_connection")
    def test_can_connect_tcp_returns_false_on_failure(self, mock_create: MagicMock) -> None:
        """_can_connect_tcp returns False when TCP fails."""
        mock_create.side_effect = OSError()
        result = _can_connect_tcp("localhost", 2375)
        assert result is False

    def test_can_connect_tcp_returns_false_without_host(self) -> None:
        """_can_connect_tcp returns False when host is None."""
        result = _can_connect_tcp(None, 2375)
        assert result is False

    def test_can_connect_tcp_returns_false_without_port(self) -> None:
        """_can_connect_tcp returns False when port is None."""
        result = _can_connect_tcp("localhost", None)
        assert result is False


class TestDockerEndpointDiscovery:
    """Tests for Docker endpoint discovery precedence."""

    def test_reads_active_docker_context(self, tmp_path: Path) -> None:
        """The active Docker CLI context contributes its configured endpoint."""
        config_dir = tmp_path / "docker"
        context_name = "remote"
        context_id = sha256(context_name.encode()).hexdigest()
        metadata_dir = config_dir / "contexts" / "meta" / context_id
        metadata_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text('{"currentContext": "remote"}', encoding="utf-8")
        (metadata_dir / "meta.json").write_text(
            '{"Endpoints": {"docker": {"Host": "tcp://context.example:2375"}}}',
            encoding="utf-8",
        )

        with patch.dict("os.environ", {"DOCKER_CONFIG": str(config_dir)}, clear=True):
            assert _docker_context_host() == "tcp://context.example:2375"

    @patch.dict("os.environ", {"XDG_RUNTIME_DIR": "/run/user/1000"}, clear=True)
    @patch("nohiki_test_utils.utils.docker._docker_context_host", return_value="tcp://context.example:2375")
    @patch("nohiki_test_utils.utils.docker._docker_endpoint_available", return_value=True)
    def test_uses_context_before_rootless_endpoints(
        self,
        mock_available: MagicMock,
        mock_context_host: MagicMock,
    ) -> None:
        """A reachable active context takes precedence over rootless sockets."""
        result = resolve_docker_endpoint()

        assert result == "tcp://context.example:2375"
        mock_available.assert_called_once_with("tcp://context.example:2375")
        mock_context_host.assert_called_once_with()

    @patch.dict(
        "os.environ",
        {
            "DOCKER_HOST": "tcp://explicit.example:2375",
            "XDG_RUNTIME_DIR": "/run/user/1000",
        },
        clear=True,
    )
    @patch("nohiki_test_utils.utils.docker._docker_context_host", return_value="tcp://context.example:2375")
    @patch("nohiki_test_utils.utils.docker._docker_endpoint_available", return_value=False)
    def test_does_not_replace_unreachable_explicit_host(
        self,
        mock_available: MagicMock,
        mock_context_host: MagicMock,
    ) -> None:
        """An explicit Docker host remains the SDK's single source of truth."""
        result = resolve_docker_endpoint()

        assert result is None
        mock_available.assert_called_once_with("tcp://explicit.example:2375")
        mock_context_host.assert_not_called()

    @patch.dict("os.environ", {"DOCKER_HOST": "tcp://dind:2375"}, clear=True)
    @patch("nohiki_test_utils.utils.docker._docker_endpoint_available")
    def test_published_verdict_answers_without_probing(self, mock_available: MagicMock) -> None:
        """The session verdict is the answer, so no reader after session start touches the network."""
        os.environ[DOCKER_ENDPOINT_VERDICT_ENV] = "tcp://dind:2375"

        result = resolve_docker_endpoint()

        assert result == "tcp://dind:2375"
        mock_available.assert_not_called()

    @patch.dict("os.environ", {"DOCKER_HOST": "tcp://dind:2375"}, clear=True)
    @patch("nohiki_test_utils.utils.docker._docker_endpoint_available")
    def test_published_absence_answers_without_probing(self, mock_available: MagicMock) -> None:
        """A published absence is as final as a published endpoint."""
        os.environ[DOCKER_ENDPOINT_VERDICT_ENV] = ""

        result = resolve_docker_endpoint()

        assert result is None
        mock_available.assert_not_called()

    @patch.dict("os.environ", {"DOCKER_HOST": "tcp://explicit.example:2375"}, clear=True)
    @patch("nohiki_test_utils.utils.docker._docker_endpoint_available", return_value=True)
    def test_publishing_records_the_endpoint_for_nested_sessions(self, mock_available: MagicMock) -> None:
        """A nested session re-importing this module still inherits the environment."""
        result = publish_docker_endpoint_verdict()

        assert result == "tcp://explicit.example:2375"
        assert os.environ[DOCKER_ENDPOINT_VERDICT_ENV] == "tcp://explicit.example:2375"
        mock_available.assert_called_once_with("tcp://explicit.example:2375")

    @patch.dict("os.environ", {"DOCKER_HOST": "tcp://dind:2375"}, clear=True)
    @patch("nohiki_test_utils.utils.docker._docker_endpoint_available", return_value=False)
    def test_publishing_records_an_absent_daemon_as_empty(self, mock_available: MagicMock) -> None:
        """Absence must be recorded, or a later reader probes and the guard rejects it."""
        result = publish_docker_endpoint_verdict()

        assert result is None
        assert os.environ[DOCKER_ENDPOINT_VERDICT_ENV] == ""
        mock_available.assert_called_once_with("tcp://dind:2375")

    @patch.dict("os.environ", {"XDG_RUNTIME_DIR": "/run/user/1000"}, clear=True)
    @patch("nohiki_test_utils.utils.docker._docker_context_host", return_value=None)
    @patch("nohiki_test_utils.utils.docker._docker_endpoint_available")
    def test_uses_rootless_podman_socket(
        self,
        mock_available: MagicMock,
        mock_context_host: MagicMock,
    ) -> None:
        """Podman's rootless socket is tried after Docker's rootless socket."""
        mock_available.side_effect = [False, True]

        result = resolve_docker_endpoint()

        assert result == "unix:///run/user/1000/podman/podman.sock"
        assert mock_available.call_args_list == [
            call("unix:///run/user/1000/docker.sock"),
            call("unix:///run/user/1000/podman/podman.sock"),
        ]
        mock_context_host.assert_called_once_with()

    @patch.dict("os.environ", {"XDG_RUNTIME_DIR": "/run/user/1000"}, clear=True)
    @patch("nohiki_test_utils.utils.docker._docker_context_host", return_value=None)
    @patch("nohiki_test_utils.utils.docker._docker_endpoint_available")
    def test_uses_legacy_socket_last(
        self,
        mock_available: MagicMock,
        mock_context_host: MagicMock,
    ) -> None:
        """The legacy Docker socket remains the final fallback."""
        mock_available.side_effect = [False, False, True]

        result = resolve_docker_endpoint()

        assert result == "unix:///var/run/docker.sock"
        assert mock_available.call_args_list == [
            call("unix:///run/user/1000/docker.sock"),
            call("unix:///run/user/1000/podman/podman.sock"),
            call("unix:///var/run/docker.sock"),
        ]
        mock_context_host.assert_called_once_with()


class TestDockerDaemonAvailable:
    """Tests for docker_daemon_available function."""

    @patch.dict("os.environ", {"DOCKER_HOST": "unix:///var/run/docker.sock"}, clear=True)
    @patch("nohiki_test_utils.utils.docker._docker_context_host", return_value=None)
    @patch("nohiki_test_utils.utils.docker._can_connect_unix_socket")
    @patch("nohiki_test_utils.utils.docker.Path.exists", return_value=True)
    def test_docker_daemon_available_with_unix_socket(
        self,
        mock_exists: MagicMock,
        mock_connect: MagicMock,
        mock_context_host: MagicMock,
    ) -> None:
        """docker_daemon_available checks unix socket by default."""
        mock_connect.return_value = True

        result = docker_daemon_available()

        assert result is True
        mock_exists.assert_called_once_with()
        mock_connect.assert_called_once_with(Path("/var/run/docker.sock"))
        mock_context_host.assert_not_called()

    @patch.dict("os.environ", {"DOCKER_HOST": "tcp://localhost:2375"}, clear=True)
    @patch("nohiki_test_utils.utils.docker._docker_context_host", return_value=None)
    @patch("nohiki_test_utils.utils.docker._can_connect_unix_socket", return_value=False)
    @patch("nohiki_test_utils.utils.docker.Path.exists", return_value=True)
    @patch("nohiki_test_utils.utils.docker._can_connect_tcp")
    def test_docker_daemon_available_with_tcp(
        self,
        mock_connect: MagicMock,
        mock_exists: MagicMock,
        mock_unix_connect: MagicMock,
        mock_context_host: MagicMock,
    ) -> None:
        """docker_daemon_available checks TCP when DOCKER_HOST is tcp."""
        mock_connect.return_value = True

        result = docker_daemon_available()

        assert result is True
        mock_connect.assert_called_once_with("localhost", 2375)
        mock_exists.assert_not_called()
        mock_unix_connect.assert_not_called()
        mock_context_host.assert_not_called()

    @patch.dict("os.environ", {"DOCKER_HOST": "tcp://localhost:2375"}, clear=True)
    @patch("nohiki_test_utils.utils.docker._docker_endpoint_available", return_value=True)
    def test_docker_daemon_available_is_cached(self, mock_probe: MagicMock) -> None:
        """docker_daemon_available probes only once per process."""
        assert docker_daemon_available() is True
        assert docker_daemon_available() is True
        mock_probe.assert_called_once_with("tcp://localhost:2375")
