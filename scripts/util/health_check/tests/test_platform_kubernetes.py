"""Tests for the KubernetesPlatform implementation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from health_check.config.kafka import connector_names_for
from health_check.platform.kubernetes import (
    _CRASH_REASONS,
    K8S_NAME_MAP,
    KubernetesPlatform,
    _ContainerStatus,
    _get_waiting_reason,
    _has_crash_state,
    _parse_k8s_phase,
    _parse_pod_list,
    _run_kubectl,
)
from health_check.platform.models import PlatformTarget, ServiceStatus

# _parse_pod_list


def _make_pod(name: str, phase: str, container_statuses: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build a minimal pod JSON dict."""
    return {
        "metadata": {"name": name},
        "status": {
            "phase": phase,
            "containerStatuses": container_statuses or [],
        },
    }


class TestParsePodList:
    """Tests for _parse_pod_list."""

    def test_parses_valid_pod_list(self) -> None:
        """Returns typed pod list from valid kubectl JSON."""
        data = {"items": [_make_pod("my-pod", "Running")]}
        pods = _parse_pod_list(json.dumps(data))
        assert len(pods) == 1
        assert (pods[0].get("metadata") or {}).get("name") == "my-pod"

    def test_empty_items(self) -> None:
        """Returns empty list when items array is empty."""
        pods = _parse_pod_list(json.dumps({"items": []}))
        assert pods == []

    def test_invalid_json(self) -> None:
        """Returns empty list on malformed JSON."""
        assert _parse_pod_list("not-json") == []

    def test_non_dict_root(self) -> None:
        """Returns empty list when root is not a dict."""
        assert _parse_pod_list(json.dumps([1, 2, 3])) == []

    def test_items_not_a_list(self) -> None:
        """Returns empty list when items is not a list."""
        assert _parse_pod_list(json.dumps({"items": "bad"})) == []

    def test_non_dict_items_filtered_out(self) -> None:
        """Filters out non-dict items from the list."""
        data = {"items": [_make_pod("pod-a", "Running"), "not-a-pod", 42]}
        pods = _parse_pod_list(json.dumps(data))
        assert len(pods) == 1

    def test_multiple_pods(self) -> None:
        """Parses multiple pods correctly."""
        data = {"items": [_make_pod("pod-a", "Running"), _make_pod("pod-b", "Pending")]}
        pods = _parse_pod_list(json.dumps(data))
        assert len(pods) == 2


# _get_waiting_reason


class TestGetWaitingReason:
    """Tests for _get_waiting_reason."""

    def test_returns_reason_when_present(self) -> None:
        """Extracts waiting reason from valid container status."""
        cs: _ContainerStatus = {"state": {"waiting": {"reason": "CrashLoopBackOff"}}}
        assert _get_waiting_reason(cs) == "CrashLoopBackOff"

    def test_returns_none_when_no_state(self) -> None:
        """Returns None when state key is absent."""
        cs: _ContainerStatus = {}
        assert _get_waiting_reason(cs) is None

    def test_returns_none_when_no_waiting(self) -> None:
        """Returns None when waiting key is absent."""
        cs: _ContainerStatus = {"state": {}}
        assert _get_waiting_reason(cs) is None

    def test_returns_none_when_no_reason(self) -> None:
        """Returns None when reason key is absent."""
        cs: _ContainerStatus = {"state": {"waiting": {}}}
        assert _get_waiting_reason(cs) is None

    def test_returns_reason_for_image_pull(self) -> None:
        """Extracts ImagePullBackOff reason."""
        cs: _ContainerStatus = {"state": {"waiting": {"reason": "ImagePullBackOff"}}}
        assert _get_waiting_reason(cs) == "ImagePullBackOff"


# _has_crash_state


class TestHasCrashState:
    """Tests for _has_crash_state."""

    @pytest.mark.parametrize("reason", sorted(_CRASH_REASONS))
    def test_detects_all_crash_reasons(self, reason: str) -> None:
        """Detects every crash reason in _CRASH_REASONS."""
        cs: _ContainerStatus = {"state": {"waiting": {"reason": reason}}}
        assert _has_crash_state([cs]) is True

    def test_returns_false_for_healthy_container(self) -> None:
        """Returns False when no container is in a crash state."""
        cs: _ContainerStatus = {"state": {"running": {}}}
        assert _has_crash_state([cs]) is False

    def test_returns_false_for_empty_list(self) -> None:
        """Returns False for an empty container list."""
        assert _has_crash_state([]) is False

    def test_returns_true_if_any_container_crashed(self) -> None:
        """Returns True when at least one container is in crash state."""
        healthy: _ContainerStatus = {"state": {"running": {}}}
        crashed: _ContainerStatus = {"state": {"waiting": {"reason": "CrashLoopBackOff"}}}
        assert _has_crash_state([healthy, crashed]) is True


# _parse_k8s_phase


class TestParseK8sPhase:
    """Tests for _parse_k8s_phase."""

    def test_running_and_ready_is_healthy(self) -> None:
        """Running + ready = HEALTHY."""
        assert _parse_k8s_phase("Running", [], ready=True) == ServiceStatus.HEALTHY

    def test_running_not_ready_with_crash_is_crashed(self) -> None:
        """Running + not ready + crash reason = CRASHED."""
        cs: _ContainerStatus = {"state": {"waiting": {"reason": "CrashLoopBackOff"}}}
        result = _parse_k8s_phase("Running", [cs], ready=False)
        assert result == ServiceStatus.CRASHED

    def test_running_not_ready_no_crash_is_starting(self) -> None:
        """Running + not ready + no crash = STARTING."""
        cs: _ContainerStatus = {}
        assert _parse_k8s_phase("Running", [cs], ready=False) == ServiceStatus.STARTING

    def test_pending_is_starting(self) -> None:
        """Pending phase = STARTING."""
        assert _parse_k8s_phase("Pending", [], ready=False) == ServiceStatus.STARTING

    def test_failed_is_crashed(self) -> None:
        """Failed phase = CRASHED."""
        assert _parse_k8s_phase("Failed", [], ready=False) == ServiceStatus.CRASHED

    def test_unknown_is_crashed(self) -> None:
        """Unknown phase = CRASHED."""
        assert _parse_k8s_phase("Unknown", [], ready=False) == ServiceStatus.CRASHED

    def test_succeeded_is_stopped(self) -> None:
        """Succeeded phase = STOPPED (job completed)."""
        assert _parse_k8s_phase("Succeeded", [], ready=False) == ServiceStatus.STOPPED

    def test_unrecognised_phase_is_unhealthy(self) -> None:
        """Unrecognised phase falls through to UNHEALTHY."""
        assert _parse_k8s_phase("Terminating", [], ready=False) == ServiceStatus.UNHEALTHY


# KubernetesPlatform


class TestKubernetesPlatformInit:
    """Tests for KubernetesPlatform initialisation."""

    def test_default_namespace(self) -> None:
        """Uses 'nohiki' namespace by default."""
        with patch.dict("os.environ", {}, clear=False):
            platform = KubernetesPlatform()
        assert platform.namespace == "nohiki"

    def test_custom_namespace_via_env(self) -> None:
        """Reads K8S_NAMESPACE environment variable."""
        with patch.dict("os.environ", {"K8S_NAMESPACE": "staging"}):
            platform = KubernetesPlatform()
        assert platform.namespace == "staging"

    def test_custom_namespace_via_arg(self) -> None:
        """Constructor argument takes precedence over env var."""
        with patch.dict("os.environ", {"K8S_NAMESPACE": "staging"}):
            platform = KubernetesPlatform(namespace="production")
        assert platform.namespace == "production"

    def test_target_is_kubernetes(self) -> None:
        """Target property returns KUBERNETES."""
        assert KubernetesPlatform().target == PlatformTarget.KUBERNETES

    def test_api_base_url_default(self) -> None:
        """api_base_url defaults to localhost:8000."""
        with patch.dict("os.environ", {}, clear=False):
            platform = KubernetesPlatform()
        assert "8000" in platform.api_base_url

    def test_local_mode_default_true(self) -> None:
        """Local mode defaults to True (local k3s setup)."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "true"}):
            platform = KubernetesPlatform()
        assert platform._local_mode is True

    def test_is_infra_managed_false_in_local_mode(self) -> None:
        """is_infra_managed returns False in local mode."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "true"}):
            platform = KubernetesPlatform()
        assert platform.is_infra_managed() is False

    def test_is_infra_managed_true_in_non_local_mode(self) -> None:
        """is_infra_managed returns True when not in local mode."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "false"}):
            platform = KubernetesPlatform()
        assert platform.is_infra_managed() is True

    def test_service_url_uses_localhost_in_local_mode(self) -> None:
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "true"}):
            assert KubernetesPlatform().service_url("qdrant", 6333) == "http://localhost:6333"

    def test_service_url_uses_selected_namespace_in_cluster(self) -> None:
        platform = KubernetesPlatform(namespace="audit", local_mode=False)
        assert platform.service_url("qdrant", 6333) == "http://qdrant.audit.svc.cluster.local:6333"

    def test_service_url_resolves_canonical_kafka_connect_name(self) -> None:
        platform = KubernetesPlatform(namespace="audit", local_mode=False)
        assert platform.service_url("kafka-connect", 8083) == "http://nohiki-connect-api.audit.svc.cluster.local:8083"


class TestKubernetesPlatformKafkaBootstrap:
    """Tests for kafka_bootstrap_server property."""

    def test_local_mode_uses_localhost(self) -> None:
        """Local mode uses localhost:29092 for Kafka."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "true"}):
            platform = KubernetesPlatform()
        assert "localhost" in platform.kafka_bootstrap_server

    def test_non_local_mode_reads_env(self) -> None:
        """Non-local mode reads KAFKA_BOOTSTRAP_SERVERS."""
        with patch.dict(
            "os.environ",
            {"K8S_LOCAL_MODE": "false", "KAFKA_BOOTSTRAP_SERVERS": "kafka:9092"},
        ):
            platform = KubernetesPlatform()
            assert platform.kafka_bootstrap_server == "kafka:9092"


class TestKubernetesPlatformGetServiceStatuses:
    """Tests for get_service_statuses method."""

    def _pod_json(self, name_prefix: str, canonical: str, phase: str, *, ready: bool) -> dict[str, Any]:
        """Create a pod JSON entry for a known canonical service."""
        k8s_name = K8S_NAME_MAP.get(canonical, f"nohiki-{canonical}")
        pod_name = f"{k8s_name}-abc123"
        return {
            "metadata": {"name": pod_name},
            "status": {
                "phase": phase,
                "containerStatuses": [{"ready": ready, "restartCount": 0}],
            },
        }

    def test_returns_empty_on_kubectl_failure(self) -> None:
        """Returns empty dict when kubectl fails."""
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(1, "", "error")):
            result = platform.get_service_statuses()
        assert result == {}

    def test_returns_empty_on_empty_pod_list(self) -> None:
        """Returns empty dict when no pods exist."""
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, json.dumps({"items": []}), "")):
            result = platform.get_service_statuses()
        assert result == {}

    def test_healthy_pod_mapped_correctly(self) -> None:
        """Maps a running+ready pod to HEALTHY status."""
        pod = self._pod_json("nohiki-bff-service", "bff-service", "Running", ready=True)
        data = json.dumps({"items": [pod]})
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, data, "")):
            result = platform.get_service_statuses()
        assert "bff-service" in result
        assert result["bff-service"].status == ServiceStatus.HEALTHY

    def test_pods_not_in_name_map_are_skipped(self) -> None:
        """Pods without a matching canonical name are silently ignored."""
        pod = {
            "metadata": {"name": "unknown-pod-xyz"},
            "status": {"phase": "Running", "containerStatuses": []},
        }
        data = json.dumps({"items": [pod]})
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, data, "")):
            result = platform.get_service_statuses()
        assert result == {}

    def test_restart_count_summed(self) -> None:
        """Restart counts are summed across containers."""
        k8s_name = K8S_NAME_MAP["bff-service"]
        pod = {
            "metadata": {"name": f"{k8s_name}-abc"},
            "status": {
                "phase": "Running",
                "containerStatuses": [
                    {"ready": True, "restartCount": 3},
                    {"ready": True, "restartCount": 2},
                ],
            },
        }
        data = json.dumps({"items": [pod]})
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, data, "")):
            result = platform.get_service_statuses()
        assert result["bff-service"].restarts == 5


class TestKubernetesPlatformCheckOomKilled:
    """Tests for check_oom_killed method."""

    def test_returns_empty_when_no_oom(self) -> None:
        """Returns empty list when no pods are OOM-killed."""
        pod = {
            "metadata": {"name": "my-pod"},
            "status": {"containerStatuses": [{"lastState": {"terminated": {"reason": "Completed"}}}]},
        }
        data = json.dumps({"items": [pod]})
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, data, "")):
            result = platform.check_oom_killed()
        assert result == []

    def test_returns_pod_names_with_oom(self) -> None:
        """Returns pod names where a container was OOMKilled."""
        pod = {
            "metadata": {"name": "oom-pod"},
            "status": {"containerStatuses": [{"lastState": {"terminated": {"reason": "OOMKilled"}}}]},
        }
        data = json.dumps({"items": [pod]})
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, data, "")):
            result = platform.check_oom_killed()
        assert "oom-pod" in result

    def test_returns_empty_on_kubectl_failure(self) -> None:
        """Returns empty list when kubectl fails."""
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(1, "", "error")):
            result = platform.check_oom_killed()
        assert result == []


class TestKubernetesPlatformCheckPendingPods:
    """Tests for check_pending_pods method."""

    def test_returns_empty_when_no_pending(self) -> None:
        """Returns empty list when no pending pods."""
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, json.dumps({"items": []}), "")):
            result = platform.check_pending_pods()
        assert result == []

    def test_returns_pod_with_reason(self) -> None:
        """Returns (name, reason) for a pending pod."""
        pod = {
            "metadata": {"name": "stuck-pod"},
            "status": {
                "conditions": [
                    {
                        "type": "PodScheduled",
                        "status": "False",
                        "reason": "Insufficient memory",
                    }
                ]
            },
        }
        data = json.dumps({"items": [pod]})
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, data, "")):
            result = platform.check_pending_pods()
        assert len(result) == 1
        assert result[0] == ("stuck-pod", "Insufficient memory")

    def test_uses_unknown_reason_when_not_scheduled_condition(self) -> None:
        """Uses 'Unknown' when PodScheduled condition is absent."""
        pod = {"metadata": {"name": "no-conditions-pod"}, "status": {"conditions": []}}
        data = json.dumps({"items": [pod]})
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, data, "")):
            result = platform.check_pending_pods()
        assert result[0][1] == "Unknown"

    def test_returns_empty_on_kubectl_failure(self) -> None:
        """Returns empty list when kubectl fails."""
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(1, "", "error")):
            result = platform.check_pending_pods()
        assert result == []


class TestKubernetesPlatformCheckPort:
    """Tests for check_port method."""

    def test_returns_true_on_open_port(self) -> None:
        """Returns True when the port is reachable."""
        platform = KubernetesPlatform()
        with patch("socket.socket") as mock_socket:
            mock_socket.return_value.__enter__.return_value.connect.return_value = None
            result = platform.check_port("localhost", 8080)
        assert result is True

    def test_returns_false_on_connection_error(self) -> None:
        """Returns False when connection is refused."""
        platform = KubernetesPlatform()
        with patch("socket.socket") as mock_socket:
            mock_socket.return_value.__enter__.return_value.connect.side_effect = OSError("refused")
            result = platform.check_port("localhost", 9999)
        assert result is False


class TestKubernetesPlatformCurl:
    """Tests for curl method."""

    def test_returns_zero_on_success(self) -> None:
        """Returns (0, body, '') on successful curl."""
        platform = KubernetesPlatform()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
            code, stdout, _ = platform.curl("http://localhost:9090/-/healthy")
        assert code == 0
        assert stdout == "OK"

    def test_returns_nonzero_on_subprocess_timeout(self) -> None:
        """Returns non-zero on TimeoutExpired."""
        platform = KubernetesPlatform()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("curl", 10)):
            code, _, err = platform.curl("http://localhost:9090/-/healthy")
        assert code == 1
        assert "timed out" in err.lower() or "timeout" in err.lower()


class TestKubernetesPlatformRestartKafkaConnector:
    def test_local_mode_uses_exact_scoped_post_and_timeout(self) -> None:

        connector = connector_names_for(PlatformTarget.KUBERNETES)[0]
        platform = KubernetesPlatform(local_mode=True)
        with patch(
            "health_check.platform.kubernetes._restart_request",
            return_value=(0, "ok", ""),
        ) as request:
            assert platform.restart_kafka_connector(connector, timeout=9) == (
                0,
                "ok",
                "",
            )
        request.assert_called_once_with(
            f"http://localhost:8083/connectors/{connector}/restart?includeTasks=true&onlyFailed=true",
            9,
        )

    def test_cluster_mode_has_identical_endpoint_semantics(self) -> None:

        connector = connector_names_for(PlatformTarget.KUBERNETES)[0]
        platform = KubernetesPlatform(namespace="audit", local_mode=False)
        with patch(
            "health_check.platform.kubernetes._restart_request",
            return_value=(22, "", "denied"),
        ) as request:
            result = platform.restart_kafka_connector(connector, timeout=4)
        assert result == (22, "", "denied")
        request.assert_called_once_with(
            f"http://nohiki-connect-api.audit.svc.cluster.local:8083/connectors/{connector}/restart?includeTasks=true&onlyFailed=true",
            4,
        )

    def test_accepts_kubernetes_sink_connector(self) -> None:
        platform = KubernetesPlatform()
        with patch(
            "health_check.platform.kubernetes._restart_request",
            return_value=(0, "ok", ""),
        ) as request:
            platform.restart_kafka_connector("qdrant-embedding-sink")
        request.assert_called_once()

    def test_rejects_noncanonical_name_before_request(self) -> None:
        platform = KubernetesPlatform()
        with (
            patch("health_check.platform.kubernetes._restart_request") as request,
            pytest.raises(ValueError, match=r"^Non-canonical connector rejected: not-canonical$"),
        ):
            platform.restart_kafka_connector("not-canonical")
        request.assert_not_called()


class TestKubernetesPlatformGetLogs:
    """Tests for get_logs method."""

    def test_returns_empty_when_pod_not_found(self) -> None:
        """Returns empty string when pod can't be found."""
        platform = KubernetesPlatform()
        with patch.object(platform, "_get_pod_name", return_value=None):
            result = platform.get_logs("bff-service")
        assert result == ""

    def test_returns_log_output(self) -> None:
        """Returns stdout from kubectl logs."""
        platform = KubernetesPlatform()
        with (
            patch.object(platform, "_get_pod_name", return_value="bff-pod-abc"),
            patch.object(platform, "_kubectl", return_value=(0, "log line 1\nlog line 2", "")),
        ):
            result = platform.get_logs("bff-service")
        assert "log line 1" in result


def _dependency_command(*modules: str) -> list[str]:
    checks = " and ".join(f"__import__('importlib.util').util.find_spec('{module}') is not None" for module in modules)
    return ["python", "-c", f"{checks} or exit(1)"]


class TestKubernetesPlatformExecInService:
    """Tests for exec_in_service method."""

    def test_returns_error_when_pod_not_found(self) -> None:
        """Returns non-zero exit code when pod not found."""
        platform = KubernetesPlatform()
        with patch.object(platform, "_get_pod_name", return_value=None):
            code, _, err = platform.exec_in_service("bff-service", ["ls"])
        assert code == 1
        assert "No running pod" in err

    def test_delegates_to_kubectl_exec(self) -> None:
        """Delegates to kubectl exec when pod found."""
        platform = KubernetesPlatform()
        with (
            patch.object(platform, "_get_pod_name", return_value="bff-pod-abc"),
            patch.object(platform, "_kubectl", return_value=(0, "output", "")) as mock_kc,
        ):
            code, _, __ = platform.exec_in_service("bff-service", ["echo", "hello"])
        assert code == 0
        called_args = mock_kc.call_args[0][0]
        assert "exec" in called_args
        assert "bff-pod-abc" in called_args

    def test_local_dependency_probe_uses_pod_exec_without_job_evidence(self) -> None:
        platform = KubernetesPlatform(local_mode=True)
        command = _dependency_command("nohiki_kafka_client", "nohiki_db_utils")
        with (
            patch.object(platform, "_get_pod_name", return_value="user-pref-pod"),
            patch.object(platform, "_kubectl", return_value=(0, "dependencies present", "")) as kubectl,
            patch("health_check.platform.kubernetes._service_dependency_evidence") as evidence,
        ):
            result = platform.exec_in_service("user-pref-service", command)

        assert result == (0, "dependencies present", "")
        evidence.assert_not_called()
        kubectl.assert_called_once_with(["exec", "user-pref-pod", "--", *command], timeout=30)

    def test_service_dependency_evidence_passes_for_exact_digest_pinned_probe(self, tmp_path: Path) -> None:
        evidence = {
            "nohiki_kafka_client": True,
            "nohiki_db_utils": True,
        }
        tmp_path.joinpath("user-pref-service.json").write_text(json.dumps(evidence), encoding="utf-8")
        with patch.dict("os.environ", {"K8S_SERVICE_DEPENDENCY_EVIDENCE_DIR": str(tmp_path)}):
            code, output, error = KubernetesPlatform(local_mode=False).exec_in_service(
                "user-pref-service",
                _dependency_command("nohiki_kafka_client", "nohiki_db_utils"),
            )
        assert (code, output, error) == (0, "service image dependencies verified", "")

    @pytest.mark.parametrize("contents", [None, "{", "{}", '{"nohiki_kafka_client": true}'])
    def test_service_dependency_evidence_fails_closed(
        self,
        tmp_path: Path,
        contents: str | None,
    ) -> None:
        if contents is not None:
            tmp_path.joinpath("user-pref-service.json").write_text(contents, encoding="utf-8")
        with patch.dict("os.environ", {"K8S_SERVICE_DEPENDENCY_EVIDENCE_DIR": str(tmp_path)}):
            code, _, error = KubernetesPlatform(local_mode=False).exec_in_service(
                "user-pref-service",
                _dependency_command("nohiki_kafka_client", "nohiki_db_utils"),
            )
        assert code == 2
        assert "evidence" in error

    def test_service_dependency_evidence_reports_missing_module(self, tmp_path: Path) -> None:
        evidence = {
            "nohiki_kafka_client": True,
            "nohiki_db_utils": False,
        }
        tmp_path.joinpath("user-pref-service.json").write_text(json.dumps(evidence), encoding="utf-8")
        with patch.dict("os.environ", {"K8S_SERVICE_DEPENDENCY_EVIDENCE_DIR": str(tmp_path)}):
            code, _, error = KubernetesPlatform(local_mode=False).exec_in_service(
                "user-pref-service",
                _dependency_command("nohiki_kafka_client", "nohiki_db_utils"),
            )
        assert code == 1
        assert error == "service image is missing dependencies: nohiki_db_utils"


class TestKubernetesPlatformExecPsql:
    """Tests for exec_psql in local mode."""

    def test_local_mode_uses_podman_exec(self) -> None:
        """In local mode, psql runs through podman exec."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "true"}):
            platform = KubernetesPlatform()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="result", stderr="")
            code, out, _ = platform.exec_psql("SELECT 1")
        assert code == 0
        assert out == "result"
        cmd = mock_run.call_args[0][0]
        assert "podman" in cmd
        assert "nohiki-infra-postgres" in cmd

    def test_local_mode_handles_timeout(self) -> None:
        """Returns non-zero on timeout in local mode."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "true"}):
            platform = KubernetesPlatform()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("psql", 10)):
            code, _, __ = platform.exec_psql("SELECT 1")
        assert code == 1

    def test_non_local_mode_delegates_to_exec_in_service(self) -> None:
        """In non-local mode, psql runs via exec_in_service."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "false"}):
            platform = KubernetesPlatform()
        with patch.object(platform, "exec_in_service", return_value=(0, "1", "")) as mock_exec:
            code, _, __ = platform.exec_psql("SELECT 1")
        assert code == 0
        assert mock_exec.called


class TestKubernetesPlatformExecKafkaCmd:
    """Tests for exec_kafka_cmd in local and non-local modes."""

    def test_local_mode_uses_podman_exec(self) -> None:
        """In local mode, kafka command runs through podman exec."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "true"}):
            platform = KubernetesPlatform()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="topics", stderr="")
            code, _, __ = platform.exec_kafka_cmd(["kafka-topics.sh", "--list"])
        assert code == 0
        cmd = mock_run.call_args[0][0]
        assert "podman" in cmd
        assert "nohiki-cp-kafka" in cmd

    def test_non_local_mode_delegates_to_exec_in_service(self) -> None:
        """In non-local mode, kafka runs via exec_in_service."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "false"}):
            platform = KubernetesPlatform()
        with patch.object(platform, "exec_in_service", return_value=(0, "topics", "")) as mock_exec:
            code, _, __ = platform.exec_kafka_cmd(["kafka-topics.sh", "--list"])
        assert code == 0
        assert mock_exec.called


class TestKubernetesPlatformGetResourceUsage:
    """Tests for get_resource_usage method."""

    def test_parses_kubectl_top_output(self) -> None:
        """Parses CPU/memory from kubectl top pods output."""
        top_output = "pod-a    100m   256Mi\npod-b    50m    128Mi\n"
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, top_output, "")):
            result = platform.get_resource_usage()
        assert result.get("pod-a") == {"cpu": "100m", "memory": "256Mi"}
        assert result.get("pod-b") == {"cpu": "50m", "memory": "128Mi"}

    def test_returns_empty_on_kubectl_failure(self) -> None:
        """Returns empty dict when kubectl top fails."""
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(1, "", "error")):
            result = platform.get_resource_usage()
        assert result == {}

    def test_skips_malformed_lines(self) -> None:
        """Skips lines with fewer than 3 fields."""
        top_output = "pod-a    100m   256Mi\nbad-line\n"
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, top_output, "")):
            result = platform.get_resource_usage()
        assert "pod-a" in result
        assert "bad-line" not in result


# _run_kubectl direct tests (covers lines 94-108)


class TestRunKubectl:
    """Direct unit tests for the _run_kubectl module-level function."""

    def test_success_returns_output(self) -> None:
        """Normal execution returns (returncode, stdout, stderr)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="result", stderr="")
            code, stdout, _ = _run_kubectl(["get", "pods"], namespace="nohiki")
        assert code == 0
        assert stdout == "result"

    def test_nonzero_exit_returned(self) -> None:
        """Non-zero returncode from kubectl is propagated as-is."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
            code, _, stderr = _run_kubectl(["get", "pods"], namespace="nohiki")
        assert code == 1
        assert "not found" in stderr

    def test_timeout_returns_1_and_message(self) -> None:
        """TimeoutExpired yields (1, '', 'kubectl timed out ...')."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("kubectl", 5)):
            code, _, stderr = _run_kubectl(["get", "pods"], namespace="nohiki", timeout=5)
        assert code == 1
        assert "timed out" in stderr

    def test_file_not_found_returns_127(self) -> None:
        """FileNotFoundError yields (127, '', 'kubectl not found ...')."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            code, _, stderr = _run_kubectl(["get", "pods"], namespace="nohiki")
        assert code == 127
        assert "not found" in stderr

    def test_namespace_included_in_command(self) -> None:
        """The '-n namespace' flag is injected into the command."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _run_kubectl(["get", "pods"], namespace="staging")
        called_cmd = mock_run.call_args[0][0]
        assert "-n" in called_cmd
        assert "staging" in called_cmd


# KubernetesPlatform._kubectl + _get_pod_name (covers lines 246, 257-288)


class TestKubernetesPlatformKubectl:
    """Tests that exercise _kubectl() to cover line 246."""

    def test_kubectl_delegates_to_run_kubectl(self) -> None:
        """_kubectl calls _run_kubectl with the platform's namespace."""
        platform = KubernetesPlatform(namespace="myns")
        with patch("health_check.platform.kubernetes._run_kubectl", return_value=(0, "ok", "")) as mock_rk:
            code, out, _ = platform._kubectl(["get", "nodes"])
        assert code == 0
        assert out == "ok"
        mock_rk.assert_called_once_with(["get", "nodes"], namespace="myns", timeout=30)


class TestKubernetesPlatformGetPodName:
    """Tests for _get_pod_name fallback path (lines 257-288)."""

    def test_returns_name_from_label_selector_on_first_try(self) -> None:
        """Returns pod name when the label-selector kubectl call succeeds."""
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, "bff-pod-abc", "")):
            result = platform._get_pod_name("bff-service")
        assert result == "bff-pod-abc"

    def test_fallback_to_listing_all_pods(self) -> None:
        """Falls back to listing all pods when label selector returns nothing."""
        platform = KubernetesPlatform()
        k8s_name = K8S_NAME_MAP["bff-service"]
        pods_output = f"{k8s_name}-abc Running\nother-pod Pending"
        responses = [
            (0, "", ""),
            (0, pods_output, ""),
        ]
        with patch.object(platform, "_kubectl", side_effect=responses):
            result = platform._get_pod_name("bff-service")
        assert result == f"{k8s_name}-abc"

    def test_fallback_kubectl_failure_returns_none(self) -> None:
        """Returns None when both kubectl calls fail."""
        platform = KubernetesPlatform()
        responses = [
            (0, "", ""),
            (1, "", "error"),
        ]
        with patch.object(platform, "_kubectl", side_effect=responses):
            result = platform._get_pod_name("bff-service")
        assert result is None

    def test_returns_none_when_no_matching_pod_in_fallback(self) -> None:
        """Returns None when fallback pod list has no matching pod."""
        platform = KubernetesPlatform()
        pods_output = "completely-different-pod Running"
        responses = [
            (0, "", ""),
            (0, pods_output, ""),
        ]
        with patch.object(platform, "_kubectl", side_effect=responses):
            result = platform._get_pod_name("bff-service")
        assert result is None


# exec_psql with field_separator (covers lines 357, 368)


class TestKubernetesPlatformExecPsqlFieldSeparator:
    """Tests for exec_psql with field_separator in both modes."""

    def test_local_mode_with_field_separator(self) -> None:
        """In local mode, field_separator extends the psql command."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "true"}):
            platform = KubernetesPlatform()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="a,b", stderr="")
            _code, _out, _ = platform.exec_psql("SELECT 1", field_separator=",")
        cmd = mock_run.call_args[0][0]
        assert "-F" in cmd
        assert "," in cmd

    def test_non_local_mode_with_field_separator(self) -> None:
        """In non-local mode, field_separator is passed to exec_in_service."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "false"}):
            platform = KubernetesPlatform()
        with patch.object(platform, "exec_in_service", return_value=(0, "a,b", "")) as mock_exec:
            _code2, _out2, _ = platform.exec_psql("SELECT 1", field_separator=",")
        psql_cmd = mock_exec.call_args[0][1]
        assert "-F" in psql_cmd
        assert "," in psql_cmd

    def test_local_mode_file_not_found_returns_1(self) -> None:
        """FileNotFoundError (podman missing) returns (1, '', error_msg)."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "true"}):
            platform = KubernetesPlatform()
        with patch("subprocess.run", side_effect=FileNotFoundError("podman not found")):
            code, _, err = platform.exec_psql("SELECT 1")
        assert code == 1
        assert len(err) > 0


# exec_kafka_cmd error handling in local mode (covers lines 383-384)


class TestKubernetesPlatformExecKafkaCmdErrors:
    """Tests for exec_kafka_cmd error paths in local mode."""

    def test_local_mode_file_not_found(self) -> None:
        """FileNotFoundError (podman missing) returns (1, '', error_msg)."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "true"}):
            platform = KubernetesPlatform()
        with patch("subprocess.run", side_effect=FileNotFoundError("podman not found")):
            code, _, err = platform.exec_kafka_cmd(["kafka-topics.sh", "--list"])
        assert code == 1
        assert len(err) > 0

    def test_local_mode_timeout(self) -> None:
        """TimeoutExpired in local mode returns (1, '', error_msg)."""
        with patch.dict("os.environ", {"K8S_LOCAL_MODE": "true"}):
            platform = KubernetesPlatform()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 15)):
            code, _, _err = platform.exec_kafka_cmd(["kafka-topics.sh", "--list"])
        assert code == 1


# check_pending_pods with non-matching conditions (covers branch 462->461)


class TestKubernetesPlatformPendingPodsConditionBranch:
    """Tests for the conditions loop branch in check_pending_pods."""

    def test_non_matching_condition_uses_unknown_reason(self) -> None:
        """Loop iterates conditions but none match PodScheduled=False → Unknown."""
        pod = {
            "metadata": {"name": "stuck-pod"},
            "status": {
                "conditions": [
                    {"type": "Initialized", "status": "True"},
                    {"type": "ContainersReady", "status": "False"},
                ]
            },
        }
        data = json.dumps({"items": [pod]})
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, data, "")):
            result = platform.check_pending_pods()
        assert result[0] == ("stuck-pod", "Unknown")

    def test_matching_condition_after_non_match_uses_reason(self) -> None:
        """PodScheduled=False found after non-matching conditions."""
        pod = {
            "metadata": {"name": "stuck-pod"},
            "status": {
                "conditions": [
                    {"type": "Initialized", "status": "True"},
                    {
                        "type": "PodScheduled",
                        "status": "False",
                        "reason": "Unschedulable",
                    },
                ]
            },
        }
        data = json.dumps({"items": [pod]})
        platform = KubernetesPlatform()
        with patch.object(platform, "_kubectl", return_value=(0, data, "")):
            result = platform.check_pending_pods()
        assert result[0] == ("stuck-pod", "Unschedulable")
