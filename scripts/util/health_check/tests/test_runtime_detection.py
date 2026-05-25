"""Tests for container runtime detection and platform factory."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from health_check.core.exceptions import RuntimeDetectionError
from health_check.platform.factory import _resolve_target, get_platform
from health_check.platform.models import PlatformTarget
from health_check.platform.runtime import ContainerRuntime, detect_container_runtime


class TestContainerRuntime:
    def test_values_are_strings(self) -> None:
        assert ContainerRuntime.DOCKER == "docker"
        assert ContainerRuntime.PODMAN == "podman"


class TestDetectContainerRuntime:
    def test_env_override_docker_found(self) -> None:
        with (
            patch.dict(os.environ, {"CONTAINER_RUNTIME": "docker"}),
            patch("shutil.which", return_value="/usr/bin/docker"),
        ):
            assert detect_container_runtime() == ContainerRuntime.DOCKER

    def test_env_override_podman_found(self) -> None:
        with (
            patch.dict(os.environ, {"CONTAINER_RUNTIME": "podman"}),
            patch("shutil.which", return_value="/usr/bin/podman"),
        ):
            assert detect_container_runtime() == ContainerRuntime.PODMAN

    def test_env_override_binary_not_found_raises(self) -> None:
        with (
            patch.dict(os.environ, {"CONTAINER_RUNTIME": "docker"}),
            patch("shutil.which", return_value=None),
            pytest.raises(RuntimeDetectionError, match="not found in PATH"),
        ):
            detect_container_runtime()

    def test_env_override_unsupported_runtime_raises(self) -> None:
        with (
            patch.dict(os.environ, {"CONTAINER_RUNTIME": "containerd"}),
            patch("shutil.which", return_value="/usr/bin/containerd"),
            pytest.raises(RuntimeDetectionError, match="not a supported runtime"),
        ):
            detect_container_runtime()

    def test_auto_detects_podman_first(self) -> None:
        def _which(name: str) -> str | None:
            return "/usr/bin/podman" if name == "podman" else None

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("shutil.which", side_effect=_which),
        ):
            env = {k: v for k, v in os.environ.items() if k != "CONTAINER_RUNTIME"}
            with patch.dict(os.environ, env, clear=True):
                result = detect_container_runtime()
        assert result == ContainerRuntime.PODMAN

    def test_falls_back_to_docker(self) -> None:
        def _which(name: str) -> str | None:
            return "/usr/bin/docker" if name == "docker" else None

        original_env = os.environ.copy()
        original_env.pop("CONTAINER_RUNTIME", None)
        with (
            patch.dict(os.environ, original_env, clear=True),
            patch("shutil.which", side_effect=_which),
        ):
            result = detect_container_runtime()
        assert result == ContainerRuntime.DOCKER

    def test_no_runtime_raises(self) -> None:
        original_env = os.environ.copy()
        original_env.pop("CONTAINER_RUNTIME", None)
        with (
            patch.dict(os.environ, original_env, clear=True),
            patch("shutil.which", return_value=None),
            pytest.raises(RuntimeDetectionError, match="No container runtime found"),
        ):
            detect_container_runtime()


class TestResolveTarget:
    def test_explicit_compose(self) -> None:
        assert _resolve_target(PlatformTarget.COMPOSE) == PlatformTarget.COMPOSE

    def test_explicit_kubernetes(self) -> None:
        assert _resolve_target(PlatformTarget.KUBERNETES) == PlatformTarget.KUBERNETES

    def test_none_reads_env_var(self) -> None:
        with patch.dict(os.environ, {"NOHIKI_TARGET": "k8s"}):
            assert _resolve_target(None) == PlatformTarget.KUBERNETES

    def test_none_defaults_to_compose(self) -> None:
        original_env = os.environ.copy()
        original_env.pop("NOHIKI_TARGET", None)
        with patch.dict(os.environ, original_env, clear=True):
            assert _resolve_target(None) == PlatformTarget.COMPOSE

    def test_invalid_env_var_is_rejected(self) -> None:
        with (
            patch.dict(os.environ, {"NOHIKI_TARGET": "invalid_target"}),
            pytest.raises(ValueError, match="Unknown NOHIKI_TARGET"),
        ):
            _resolve_target(None)


class TestGetPlatform:
    def test_compose_platform(self) -> None:
        from health_check.platform.compose import ComposePlatform

        with patch(
            "health_check.platform.factory.detect_container_runtime",
            return_value=ContainerRuntime.DOCKER,
        ):
            p = get_platform(PlatformTarget.COMPOSE)
        assert isinstance(p, ComposePlatform)
        assert p.target == PlatformTarget.COMPOSE

    def test_kubernetes_platform(self) -> None:
        from health_check.platform.kubernetes import KubernetesPlatform

        p = get_platform(PlatformTarget.KUBERNETES)
        assert isinstance(p, KubernetesPlatform)
        assert p.target == PlatformTarget.KUBERNETES
