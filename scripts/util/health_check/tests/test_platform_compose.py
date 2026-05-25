"""Tests for the ComposePlatform implementation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest
from health_check.platform.compose import (
    COMPOSE_NAME_MAP,
    ComposePlatform,
    _parse_compose_status,
    _parse_compose_uptime_hours,
    _run_cmd,
)
from health_check.platform.models import PlatformTarget, ServiceStatus
from health_check.platform.runtime import ContainerRuntime

# _run_cmd


class TestRunCmd:
    """Tests for the _run_cmd subprocess wrapper."""

    def test_success_returns_exit_code_and_output(self) -> None:
        proc = mock.MagicMock(spec=subprocess.CompletedProcess)
        proc.returncode = 0
        proc.stdout = "hello"
        proc.stderr = ""
        with mock.patch("subprocess.run", return_value=proc) as m:
            code, stdout, _ = _run_cmd(["echo", "hello"])
        assert code == 0
        assert stdout == "hello"
        m.assert_called_once()

    def test_nonzero_exit_code_returned(self) -> None:
        proc = mock.MagicMock(spec=subprocess.CompletedProcess)
        proc.returncode = 1
        proc.stdout = ""
        proc.stderr = "error"
        with mock.patch("subprocess.run", return_value=proc):
            code, _, stderr = _run_cmd(["false"])
        assert code == 1
        assert "error" in stderr

    def test_timeout_returns_exit_1(self) -> None:
        exc = subprocess.TimeoutExpired(["cmd"], 5)
        exc.stdout = b"partial"
        with mock.patch("subprocess.run", side_effect=exc):
            code, _, stderr = _run_cmd(["cmd"], timeout=5)
        assert code == 1
        assert "timed out" in stderr

    def test_timeout_with_none_stdout(self) -> None:
        exc = subprocess.TimeoutExpired(["cmd"], 5)
        exc.stdout = None
        with mock.patch("subprocess.run", side_effect=exc):
            code, stdout, _ = _run_cmd(["cmd"])
        assert code == 1
        assert stdout == ""

    def test_file_not_found_returns_127(self) -> None:
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            code, _, stderr = _run_cmd(["nonexistent_binary"])
        assert code == 127
        assert "not found" in stderr

    def test_custom_cwd_passed_to_subprocess(self, tmp_path: Path) -> None:
        proc = mock.MagicMock(spec=subprocess.CompletedProcess)
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        with mock.patch("subprocess.run", return_value=proc) as m:
            _run_cmd(["ls"], cwd=tmp_path)
        _, kwargs = m.call_args
        assert kwargs.get("cwd") == tmp_path or m.call_args[0][0] == ["ls"]


# _parse_compose_status


class TestParseComposeStatus:
    """Tests for _parse_compose_status()."""

    def test_healthy(self) -> None:
        assert _parse_compose_status("Up 2 hours (healthy)") == ServiceStatus.HEALTHY

    def test_unhealthy(self) -> None:
        assert _parse_compose_status("Up 3 hours (unhealthy)") == ServiceStatus.CRASHED

    def test_exited(self) -> None:
        assert _parse_compose_status("Exited (1) 5 minutes ago") == ServiceStatus.CRASHED

    def test_starting(self) -> None:
        assert _parse_compose_status("Up 10 seconds (health: starting)") == ServiceStatus.STARTING

    def test_unknown_defaults_to_unhealthy(self) -> None:
        assert _parse_compose_status("Up 1 minute") == ServiceStatus.UNHEALTHY

    def test_case_insensitive(self) -> None:
        assert _parse_compose_status("Up 1 hour (HEALTHY)") == ServiceStatus.HEALTHY


# _parse_compose_uptime_hours


class TestParseComposeUptimeHours:
    """Tests for _parse_compose_uptime_hours()."""

    def test_no_up_prefix_returns_zero(self) -> None:
        assert _parse_compose_uptime_hours("Exited (1) 5 minutes ago") == 0.0

    def test_seconds(self) -> None:
        result = _parse_compose_uptime_hours("Up 3600 seconds (healthy)")
        assert abs(result - 1.0) < 0.01

    def test_minutes(self) -> None:
        result = _parse_compose_uptime_hours("Up 60 minutes (healthy)")
        assert abs(result - 1.0) < 0.01

    def test_hours(self) -> None:
        result = _parse_compose_uptime_hours("Up 5 hours (healthy)")
        assert result == 5.0

    def test_days(self) -> None:
        result = _parse_compose_uptime_hours("Up 2 days (healthy)")
        assert result == 48.0

    def test_weeks(self) -> None:
        result = _parse_compose_uptime_hours("Up 1 week (healthy)")
        assert result == 168.0

    def test_up_no_unit_match_returns_zero(self) -> None:
        result = _parse_compose_uptime_hours("Up (healthy)")
        assert result == 0.0


# ComposePlatform


class TestComposePlatformInit:
    """Tests for ComposePlatform initialisation."""

    def test_default_runtime_auto_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/podman" if x == "podman" else None)
        platform = ComposePlatform()
        assert platform.runtime == ContainerRuntime.PODMAN

    def test_explicit_runtime_accepted(self) -> None:
        platform = ComposePlatform(runtime=ContainerRuntime.DOCKER)
        assert platform.runtime == ContainerRuntime.DOCKER

    def test_custom_compose_dir(self, tmp_path: Path) -> None:
        platform = ComposePlatform(runtime=ContainerRuntime.DOCKER, compose_dir=tmp_path)
        assert platform._compose_dir == tmp_path

    def test_custom_compose_file(self, tmp_path: Path) -> None:
        platform = ComposePlatform(
            runtime=ContainerRuntime.DOCKER,
            compose_dir=tmp_path,
            compose_file="custom-compose.yml",
        )
        assert platform._compose_file == tmp_path / "custom-compose.yml"


class TestComposePlatformProperties:
    """Tests for ComposePlatform property accessors."""

    def _platform(self) -> ComposePlatform:
        return ComposePlatform(runtime=ContainerRuntime.DOCKER)

    def test_target_is_compose(self) -> None:
        assert self._platform().target == PlatformTarget.COMPOSE

    def test_api_base_url_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("E2E_BASE_URL", raising=False)
        url = self._platform().api_base_url
        assert url.startswith("http://")

    def test_api_base_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("E2E_BASE_URL", "http://custom-host:9000")
        assert self._platform().api_base_url == "http://custom-host:9000"

    def test_kafka_bootstrap_server(self) -> None:
        assert ":" in self._platform().kafka_bootstrap_server

    def test_is_infra_managed(self) -> None:
        assert self._platform().is_infra_managed() is True

    def test_service_url_uses_host_published_port(self) -> None:
        assert self._platform().service_url("qdrant", 6333) == "http://localhost:6333"

    def test_runtime_property(self) -> None:
        platform = ComposePlatform(runtime=ContainerRuntime.DOCKER)
        assert platform.runtime == ContainerRuntime.DOCKER


class TestComposePlatformContainerName:
    def test_known_service_returns_compose_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
        platform = ComposePlatform(runtime=ContainerRuntime.DOCKER)
        assert platform._container_name("postgres") == COMPOSE_NAME_MAP["postgres"]

    def test_unknown_service_returns_canonical(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
        platform = ComposePlatform(runtime=ContainerRuntime.DOCKER)
        assert platform._container_name("unknown-service") == "unknown-service"

    def test_project_qualifies_mapped_and_unknown_services(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPOSE_PROJECT_NAME", "nohiki-test")
        platform = ComposePlatform(runtime=ContainerRuntime.DOCKER)
        assert platform._container_name("postgres") == "nohiki-test_nohiki-infra-postgres_1"
        assert platform._container_name("unknown-service") == "nohiki-test_unknown-service_1"


class TestComposePlatformGetServiceStatuses:
    """Tests for get_service_statuses()."""

    def _platform(self) -> ComposePlatform:
        return ComposePlatform(runtime=ContainerRuntime.DOCKER)

    def test_returns_empty_on_command_failure(self) -> None:
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(1, "", "error")):
            result = platform.get_service_statuses()
        assert result == {}

    def test_returns_empty_on_empty_output(self) -> None:
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, "", "")):
            result = platform.get_service_statuses()
        assert result == {}

    def test_parses_healthy_container(self) -> None:
        platform = self._platform()
        ps_output = "nohiki-infra-postgres Up 2 hours (healthy)\n"
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, ps_output, "")):
            result = platform.get_service_statuses()
        assert "postgres" in result
        assert result["postgres"].status == ServiceStatus.HEALTHY
        assert result["postgres"].ready is True

    def test_parses_unhealthy_container(self) -> None:
        platform = self._platform()
        ps_output = "nohiki-svc-bff Up 1 hour (unhealthy)\n"
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, ps_output, "")):
            result = platform.get_service_statuses()
        assert "bff-service" in result
        assert result["bff-service"].status == ServiceStatus.CRASHED

    def test_project_container_name_reverse_maps_to_canonical_service(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPOSE_PROJECT_NAME", "nohiki-test")
        platform = self._platform()
        ps_output = "nohiki-test_nohiki-svc-bff_1 Up 1 hour (healthy)\n"
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, ps_output, "")):
            result = platform.get_service_statuses()
        assert set(result) == {"bff-service"}
        assert result["bff-service"].status == ServiceStatus.HEALTHY

    def test_non_nohiki_containers_filtered(self) -> None:
        platform = self._platform()
        ps_output = "some-other-container Up 1 hour (healthy)\n"
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, ps_output, "")):
            result = platform.get_service_statuses()
        assert result == {}

    def test_uptime_propagated(self) -> None:
        platform = self._platform()
        ps_output = "nohiki-infra-valkey Up 3 hours (healthy)\n"
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, ps_output, "")):
            result = platform.get_service_statuses()
        assert result["redis"].uptime_seconds == pytest.approx(3 * 3600.0)

    def test_unmapped_nohiki_container_uses_name_as_key(self) -> None:
        platform = self._platform()
        ps_output = "nohiki-infra-unknown-widget Up 1 hour (healthy)\n"
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, ps_output, "")):
            result = platform.get_service_statuses()
        assert "nohiki-infra-unknown-widget" in result


class TestComposePlatformKubernetesOnlyChecks:
    def test_check_pending_pods_returns_typed_empty_without_running_command(
        self,
    ) -> None:
        platform = ComposePlatform(runtime=ContainerRuntime.DOCKER)
        with mock.patch("health_check.platform.compose._run_cmd") as run:
            result: list[tuple[str, str]] = platform.check_pending_pods()

        assert result == []
        run.assert_not_called()

    def test_get_resource_usage_returns_typed_empty_without_running_command(
        self,
    ) -> None:
        platform = ComposePlatform(runtime=ContainerRuntime.DOCKER)
        with mock.patch("health_check.platform.compose._run_cmd") as run:
            result: dict[str, dict[str, str]] = platform.get_resource_usage()

        assert result == {}
        run.assert_not_called()


class TestComposePlatformGetLogs:
    def _platform(self) -> ComposePlatform:
        return ComposePlatform(runtime=ContainerRuntime.DOCKER)

    def test_returns_stdout_on_success(self) -> None:
        platform = self._platform()
        with mock.patch(
            "health_check.platform.compose._run_cmd",
            return_value=(0, "log line 1\nlog line 2\n", ""),
        ):
            logs = platform.get_logs("postgres")
        assert "log line 1" in logs

    def test_returns_empty_on_failure(self) -> None:
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(1, "", "not found")):
            logs = platform.get_logs("missing-service")
        assert logs == ""

    def test_default_tail_lines(self) -> None:
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, "", "")) as m:
            platform.get_logs("postgres")
        cmd_args = m.call_args[0][0]
        assert "50" in cmd_args


class TestComposePlatformExecMethods:
    def _platform(self) -> ComposePlatform:
        return ComposePlatform(runtime=ContainerRuntime.DOCKER)

    def test_exec_in_service_calls_docker_exec(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, "output", "")) as m:
            code, _, __ = platform.exec_in_service("postgres", ["pg_isready"])
        assert code == 0
        cmd = m.call_args[0][0]
        assert "exec" in cmd
        assert "nohiki-infra-postgres" in cmd

    def test_exec_in_service_uses_compose_project_container(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPOSE_PROJECT_NAME", "nohiki-test")
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, "output", "")) as m:
            platform.exec_in_service("postgres", ["pg_isready"])
        assert m.call_args[0][0][:3] == [
            "docker",
            "exec",
            "nohiki-test_nohiki-infra-postgres_1",
        ]

    def test_exec_psql_without_separator(self) -> None:
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, "result", "")) as m:
            code, _, __ = platform.exec_psql("SELECT 1")
        assert code == 0
        cmd = m.call_args[0][0]
        assert "psql" in cmd
        assert "-F" not in cmd

    def test_exec_psql_with_separator(self) -> None:
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, "a|b", "")) as m:
            platform.exec_psql("SELECT 1", field_separator="|")
        cmd = m.call_args[0][0]
        assert "-F" in cmd
        assert "|" in cmd

    def test_exec_psql_uses_compose_project_container(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPOSE_PROJECT_NAME", "nohiki-test")
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, "result", "")) as m:
            platform.exec_psql("SELECT 1")
        cmd = m.call_args[0][0]
        assert cmd[:3] == ["docker", "exec", "nohiki-test_nohiki-infra-postgres_1"]

    def test_exec_kafka_cmd(self) -> None:
        platform = self._platform()
        with mock.patch(
            "health_check.platform.compose._run_cmd",
            return_value=(0, "topic1\ntopic2\n", ""),
        ) as m:
            code, _, __ = platform.exec_kafka_cmd(["kafka-topics", "--list"])
        assert code == 0
        cmd = m.call_args[0][0]
        assert "nohiki-cp-kafka" in cmd
        assert "kafka-topics" in cmd

    def test_exec_kafka_cmd_uses_compose_project_container(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPOSE_PROJECT_NAME", "nohiki-test")
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, "topic\n", "")) as m:
            platform.exec_kafka_cmd(["kafka-topics", "--list"])
        cmd = m.call_args[0][0]
        assert cmd[:3] == ["docker", "exec", "nohiki-test_nohiki-cp-kafka_1"]


class TestComposePlatformCheckPort:
    def _platform(self) -> ComposePlatform:
        return ComposePlatform(runtime=ContainerRuntime.DOCKER)

    def test_returns_true_on_successful_connection(self) -> None:
        platform = self._platform()
        mock_sock = mock.MagicMock()
        mock_sock.__enter__ = mock.MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = mock.MagicMock(return_value=False)
        mock_sock.connect.return_value = None
        with mock.patch("socket.socket", return_value=mock_sock):
            assert platform.check_port("localhost", 5432) is True

    def test_returns_false_on_connection_error(self) -> None:
        platform = self._platform()
        mock_sock = mock.MagicMock()
        mock_sock.__enter__ = mock.MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = mock.MagicMock(return_value=False)
        mock_sock.connect.side_effect = OSError("refused")
        with mock.patch("socket.socket", return_value=mock_sock):
            assert platform.check_port("localhost", 9999) is False


class TestComposePlatformCurl:
    def _platform(self) -> ComposePlatform:
        return ComposePlatform(runtime=ContainerRuntime.DOCKER)

    def test_curl_success(self) -> None:
        platform = self._platform()
        with mock.patch(
            "health_check.platform.compose._run_cmd",
            return_value=(0, '{"status": "ok"}', ""),
        ):
            code, body, _ = platform.curl("http://localhost:9090/-/healthy")
        assert code == 0
        assert "ok" in body

    def test_curl_failure(self) -> None:
        platform = self._platform()
        with mock.patch(
            "health_check.platform.compose._run_cmd",
            return_value=(1, "", "connection refused"),
        ):
            code, _, _ = platform.curl("http://localhost:9999/health")
        assert code == 1


class TestComposePlatformRestartKafkaConnector:
    def test_uses_exact_scoped_post_and_timeout(self) -> None:
        from health_check.config.kafka import OUTBOX_CONNECTOR_NAMES

        connector = OUTBOX_CONNECTOR_NAMES[0]
        platform = ComposePlatform(runtime=ContainerRuntime.DOCKER)
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, "ok", "")) as run:
            assert platform.restart_kafka_connector(connector, timeout=7) == (
                0,
                "ok",
                "",
            )
        args, kwargs = run.call_args
        assert args[0] == [
            "curl",
            "-fsS",
            "-X",
            "POST",
            f"http://localhost:8083/connectors/{connector}/restart?includeTasks=true&onlyFailed=true",
        ]
        assert kwargs["timeout"] == 7

    def test_rejects_noncanonical_name_before_subprocess(self) -> None:
        platform = ComposePlatform(runtime=ContainerRuntime.DOCKER)
        with (
            mock.patch("health_check.platform.compose._run_cmd") as run,
            pytest.raises(
                ValueError,
                match=r"^Non-canonical connector rejected: \.\./\.\./arbitrary$",
            ),
        ):
            platform.restart_kafka_connector("../../arbitrary")
        run.assert_not_called()
