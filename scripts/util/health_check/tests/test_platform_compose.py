"""Tests for the ComposePlatform implementation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest
from health_check.checks.services.stale_services import StaleServicesCheck
from health_check.core.models import CheckStatus
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
    def test_known_service_returns_unqualified_compose_name(self) -> None:
        platform = ComposePlatform(runtime=ContainerRuntime.DOCKER)
        assert platform._container_name("postgres") == COMPOSE_NAME_MAP["postgres"]

    def test_unknown_service_returns_canonical_name(self) -> None:
        platform = ComposePlatform(runtime=ContainerRuntime.PODMAN)
        assert platform._container_name("unknown-service") == "unknown-service"


class TestComposePlatformGetServiceStatuses:
    """Tests for Compose-scoped service discovery."""

    def _platform(self, runtime: ContainerRuntime = ContainerRuntime.DOCKER) -> ComposePlatform:
        return ComposePlatform(runtime=runtime, compose_dir=Path(__file__).parent)

    def test_returns_empty_on_docker_compose_failure(self) -> None:
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(1, "", "error")) as run:
            result = platform.get_service_statuses()
        assert result == {}
        run.assert_called_once()

    def test_returns_empty_on_empty_json_output(self) -> None:
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, "[]", "")):
            result = platform.get_service_statuses()
        assert result == {}

    def test_docker_compose_json_maps_service_under_arbitrary_project(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("COMPOSE_PROJECT_NAME", "")
        platform = self._platform()
        output = json.dumps(
            [
                {
                    "Name": "arbitrary-project-nohiki-svc-bff-1",
                    "Service": "nohiki-svc-bff",
                    "Labels": "com.docker.compose.oneoff=False,com.docker.compose.service=nohiki-svc-bff",
                    "State": "running",
                    "Health": "healthy",
                    "RunningFor": "7 hours ago",
                },
                {
                    "Name": "arbitrary-project-nohiki-svc-bff-run-deadbeef",
                    "Service": "nohiki-svc-bff",
                    "Labels": "com.docker.compose.oneoff=True,com.docker.compose.service=nohiki-svc-bff",
                    "State": "exited",
                    "RunningFor": "1 minute ago",
                },
            ]
        )
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, output, "")) as run:
            result = platform.get_service_statuses()
        assert set(result) == {"bff-service"}
        assert result["bff-service"].status == ServiceStatus.HEALTHY
        assert result["bff-service"].uptime_seconds == pytest.approx(7 * 3600.0)
        assert platform._container_names["bff-service"] == "arbitrary-project-nohiki-svc-bff-1"
        assert run.call_args.args[0] == [
            ContainerRuntime.DOCKER.value,
            "compose",
            "-f",
            str(platform._compose_file),
            "ps",
            "--all",
            "--format",
            "json",
        ]

    async def test_docker_running_for_drives_aged_service_stale_detection(self) -> None:
        platform = self._platform()
        output = json.dumps(
            {
                "Name": "arbitrary-project-nohiki-svc-bff-1",
                "Service": "nohiki-svc-bff",
                "State": "running",
                "Health": "healthy",
                "RunningFor": "7 hours ago",
            }
        )

        def run_command(
            command: list[str],
            *,
            cwd: Path | None = None,
            timeout: int = 30,
        ) -> tuple[int, str, str]:
            del cwd, timeout
            if command[4] == "ps":
                return 0, output, ""
            if command[1] == "logs":
                return 0, "heartbeat failed: coordinator unavailable", ""
            if command[1] == "exec":
                return 0, "Consumer group has no active members", ""
            raise AssertionError(command)

        with mock.patch("health_check.platform.compose._run_cmd", side_effect=run_command):
            result = await StaleServicesCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert any("bff-service" in detail for detail in result.details)

    async def test_recent_restart_status_prevents_creation_age_false_stale_detection(self) -> None:
        platform = self._platform()
        output = json.dumps(
            {
                "Name": "arbitrary-project-nohiki-svc-bff-1",
                "Service": "nohiki-svc-bff",
                "State": "running",
                "Health": "healthy",
                "Status": "Up 1 hour (healthy)",
                "RunningFor": "7 hours ago",
            }
        )
        with mock.patch(
            "health_check.platform.compose._run_cmd",
            return_value=(0, output, ""),
        ) as run:
            result = await StaleServicesCheck().execute(platform)
        assert result.status == CheckStatus.PASSED
        run.assert_called_once()

    def test_podman_compose_retries_without_all_and_includes_exited_services(self) -> None:
        platform = self._platform(ContainerRuntime.PODMAN)
        output = json.dumps(
            [
                {
                    "Names": ["arbitrary_project_nohiki-svc-bff_1"],
                    "Labels": {
                        "com.docker.compose.service": "nohiki-svc-bff",
                        "io.podman.compose.service": "nohiki-svc-bff",
                        "com.docker.compose.project": "arbitrary_project",
                        "io.podman.compose.project": "arbitrary_project",
                    },
                    "State": "exited",
                    "Status": "Exited (1) 5 minutes ago",
                    "StartedAt": 1_700_000_000,
                },
                {
                    "Names": ["custom-bff-run"],
                    "Labels": {
                        "com.docker.compose.service": "nohiki-svc-bff",
                        "io.podman.compose.service": "nohiki-svc-bff",
                        "com.docker.compose.project": "arbitrary_project",
                        "io.podman.compose.project": "arbitrary_project",
                    },
                    "Status": "Up 1 minute (healthy)",
                },
            ]
        )
        with mock.patch(
            "health_check.platform.compose._run_cmd",
            side_effect=[(1, "", "unknown option --all"), (0, output, "")],
        ) as run:
            result = platform.get_service_statuses()
        assert result["bff-service"].status == ServiceStatus.CRASHED
        assert platform._container_names["bff-service"] == "arbitrary_project_nohiki-svc-bff_1"
        assert "--all" in run.call_args_list[0].args[0]
        assert run.call_args_list[1].args[0] == [
            ContainerRuntime.PODMAN.value,
            "compose",
            "-f",
            str(platform._compose_file),
            "ps",
            "--format",
            "json",
        ]

    def test_unqualified_service_name_is_fallback_when_service_field_missing(self) -> None:
        platform = self._platform()
        output = json.dumps([{"Name": "nohiki-infra-postgres", "Status": "Up 2 hours (healthy)", "State": "running"}])
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, output, "")):
            result = platform.get_service_statuses()
        assert result["postgres"].status == ServiceStatus.HEALTHY
        assert result["postgres"].uptime_seconds == pytest.approx(2 * 3600.0)

    def test_unknown_compose_service_is_retained_by_service_name(self) -> None:
        platform = self._platform()
        output = json.dumps(
            [
                {
                    "Name": "project-nohiki-infra-unknown-widget-1",
                    "Service": "nohiki-infra-unknown-widget",
                    "Status": "Up 1 hour (healthy)",
                }
            ]
        )
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, output, "")):
            result = platform.get_service_statuses()
        assert "nohiki-infra-unknown-widget" in result

    def test_non_nohiki_compose_service_is_filtered(self) -> None:
        platform = self._platform()
        output = json.dumps([{"Name": "other", "Service": "other", "Status": "Up 1 hour (healthy)"}])
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, output, "")):
            result = platform.get_service_statuses()
        assert result == {}


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
    def _platform(self, runtime: ContainerRuntime = ContainerRuntime.DOCKER) -> ComposePlatform:
        return ComposePlatform(runtime=runtime, compose_dir=Path(__file__).parent)

    def test_docker_logs_use_cached_exact_name_for_exited_container(self) -> None:
        platform = self._platform()
        exact_name = "arbitrary-project-nohiki-infra-postgres-1"
        output = json.dumps(
            {
                "Name": exact_name,
                "Service": "nohiki-infra-postgres",
                "State": "exited",
                "RunningFor": "7 hours ago",
            }
        )
        with mock.patch(
            "health_check.platform.compose._run_cmd",
            side_effect=[(0, output, ""), (0, "logs from exited container", "")],
        ) as run:
            platform.get_service_statuses()
            assert platform.get_logs("postgres") == "logs from exited container"
        assert run.call_args_list[1].args[0] == ["docker", "logs", "--tail", "50", exact_name]

    def test_podman_logs_use_cached_exact_name(self) -> None:
        platform = self._platform(ContainerRuntime.PODMAN)
        exact_name = "arbitrary_project_nohiki-infra-postgres_1"
        output = json.dumps(
            {
                "Names": [exact_name],
                "Labels": {
                    "com.docker.compose.service": "nohiki-infra-postgres",
                    "com.docker.compose.project": "arbitrary_project",
                },
                "State": "running",
                "Status": "Up 2 hours (healthy)",
            }
        )
        with mock.patch(
            "health_check.platform.compose._run_cmd",
            side_effect=[(0, output, ""), (0, "logs", "")],
        ) as run:
            platform.get_service_statuses()
            assert platform.get_logs("postgres", lines=20) == "logs"
        assert run.call_args_list[1].args[0] == ["podman", "logs", "--tail", "20", exact_name]

    def test_missing_mapping_fails_closed_without_runtime_command(self) -> None:
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd") as run:
            assert platform.get_logs("postgres") == ""
        run.assert_not_called()


class TestComposePlatformExecMethods:
    def _platform(self, runtime: ContainerRuntime = ContainerRuntime.DOCKER) -> ComposePlatform:
        return ComposePlatform(runtime=runtime, compose_dir=Path(__file__).parent)

    def test_docker_exec_uses_cached_exact_name(self) -> None:
        platform = self._platform()
        exact_name = "arbitrary-project-nohiki-infra-postgres-1"
        output = json.dumps(
            {
                "Name": exact_name,
                "Service": "nohiki-infra-postgres",
                "State": "running",
                "Health": "healthy",
            }
        )
        with mock.patch(
            "health_check.platform.compose._run_cmd",
            side_effect=[(0, output, ""), (0, "output", "")],
        ) as run:
            platform.get_service_statuses()
            assert platform.exec_in_service("postgres", ["pg_isready"])[0] == 0
        assert run.call_args_list[1].args[0] == ["docker", "exec", exact_name, "pg_isready"]

    def test_podman_exec_uses_cached_exact_name(self) -> None:
        platform = self._platform(ContainerRuntime.PODMAN)
        exact_name = "arbitrary_project_nohiki-infra-postgres_1"
        output = json.dumps(
            {
                "Names": [exact_name],
                "Labels": {
                    "com.docker.compose.service": "nohiki-infra-postgres",
                    "com.docker.compose.project": "arbitrary_project",
                },
                "State": "running",
                "Status": "Up 2 hours (healthy)",
            }
        )
        with mock.patch(
            "health_check.platform.compose._run_cmd",
            side_effect=[(0, output, ""), (0, "output", "")],
        ) as run:
            platform.get_service_statuses()
            platform.exec_in_service("postgres", ["pg_isready"])
        assert run.call_args_list[1].args[0] == ["podman", "exec", exact_name, "pg_isready"]

    def test_missing_mapping_fails_closed_without_runtime_command(self) -> None:
        platform = self._platform()
        with mock.patch("health_check.platform.compose._run_cmd") as run:
            code, _, error = platform.exec_in_service("postgres", ["pg_isready"])
        assert code == 1
        assert "not discovered" in error
        run.assert_not_called()

    def test_exec_psql_uses_cached_container(self) -> None:
        platform = self._platform()
        platform._container_names["postgres"] = "exact-postgres"
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, "a|b", "")) as run:
            platform.exec_psql("SELECT 1", field_separator="|")
        command = run.call_args.args[0]
        assert command[:3] == ["docker", "exec", "exact-postgres"]
        assert command[command.index("-F") + 1] == "|"

    def test_exec_kafka_cmd_uses_cached_container(self) -> None:
        platform = self._platform()
        platform._container_names["kafka"] = "exact-kafka"
        with mock.patch("health_check.platform.compose._run_cmd", return_value=(0, "topic\n", "")) as run:
            assert platform.exec_kafka_cmd(["kafka-topics", "--list"])[0] == 0
        assert run.call_args.args[0] == ["docker", "exec", "exact-kafka", "kafka-topics", "--list"]


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
        from health_check.config.kafka import connector_names_for

        connector = connector_names_for(PlatformTarget.COMPOSE)[0]
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
