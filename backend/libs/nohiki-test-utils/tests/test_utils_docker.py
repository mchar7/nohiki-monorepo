"""Tests for nohiki_test_utils utils.docker module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from nohiki_test_utils.utils.docker import (
    _can_connect_tcp,
    _can_connect_unix_socket,
    docker_daemon_available,
)


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


class TestDockerDaemonAvailable:
    """Tests for docker_daemon_available function."""

    @patch("nohiki_test_utils.utils.docker._can_connect_unix_socket")
    @patch("nohiki_test_utils.utils.docker.Path.exists")
    def test_docker_daemon_available_with_unix_socket(self, mock_exists: MagicMock, mock_connect: MagicMock) -> None:
        """docker_daemon_available checks unix socket by default."""
        mock_exists.return_value = True
        mock_connect.return_value = True
        result = docker_daemon_available()
        assert result is True

    @patch.dict("os.environ", {"DOCKER_HOST": "tcp://localhost:2375"})
    @patch("nohiki_test_utils.utils.docker._can_connect_tcp")
    def test_docker_daemon_available_with_tcp(self, mock_connect: MagicMock) -> None:
        """docker_daemon_available checks TCP when DOCKER_HOST is tcp."""
        mock_connect.return_value = True
        result = docker_daemon_available()
        assert result is True

    def test_docker_daemon_available_is_cached(self) -> None:
        """docker_daemon_available result is cached."""
        # Call twice, should use cached result
        result1 = docker_daemon_available()
        result2 = docker_daemon_available()
        assert result1 == result2
