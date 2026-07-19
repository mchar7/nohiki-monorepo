"""Tests for subprocess environment isolation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ci_checks.core.process_env import sanitized_python_env


def test_sanitized_python_env_drops_host_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host interpreter paths must not leak into uv-managed children."""
    monkeypatch.setenv("PYTHONPATH", "/nix/store/host-python/site-packages")
    monkeypatch.setenv("PYTHONHOME", "/nix/store/host-python")
    monkeypatch.setenv("UNCHANGED", "present")

    child_env = sanitized_python_env()

    assert "PYTHONPATH" not in child_env
    assert "PYTHONHOME" not in child_env
    assert child_env["UNCHANGED"] == "present"


def test_sanitized_python_env_preserves_deliberate_import_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Explicit import paths and uv interpreter controls survive sanitization."""
    monkeypatch.setenv("PYTHONPATH", "/host/path")
    monkeypatch.setenv("UV_PYTHON", "/nix/store/python/bin/python")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", ".venv-nix")
    first = tmp_path / "plugin"
    second = tmp_path / "helpers"

    child_env = sanitized_python_env(python_paths=(first, second), extra={"OTEL_SDK_DISABLED": "true"})

    assert child_env["PYTHONPATH"] == os.pathsep.join((str(first), str(second)))
    assert child_env["OTEL_SDK_DISABLED"] == "true"
    assert "PYTHONHOME" not in child_env
    assert child_env["UV_PYTHON"] == "/nix/store/python/bin/python"
    assert child_env["UV_PROJECT_ENVIRONMENT"] == ".venv-nix"


def test_sanitized_python_env_drops_sensitive_inherited_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Credential-shaped inherited variables never reach CI subprocesses."""
    sensitive = {
        "CI_SYNTHETIC_API_KEY": "synthetic-api-value",
        "ci_Synthetic_Api_Key": "synthetic-mixed-case-value",
        "CI_SYNTHETIC_SECRET": "synthetic-secret-value",
        "CI_SYNTHETIC_PASSWORD": "synthetic-password-value",
        "CI_SYNTHETIC_CREDENTIAL": "synthetic-credential-value",
        "CI_SYNTHETIC_COOKIE": "synthetic-cookie-value",
        "CI_SYNTHETIC_DSN": "synthetic-dsn-value",
        "CI_SYNTHETIC_KUBECONFIG": "/synthetic/config",
    }
    for name, value in sensitive.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("CI_SYNTHETIC_OPERATIONAL_MODE", "unit")

    child_env = sanitized_python_env()

    assert all(name not in child_env for name in sensitive)
    assert child_env["CI_SYNTHETIC_OPERATIONAL_MODE"] == "unit"


def test_sanitized_python_env_extra_can_restore_required_synthetic_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callers can explicitly provide a required synthetic credential variable."""
    monkeypatch.setenv("CI_SYNTHETIC_API_KEY", "inherited-value")

    child_env = sanitized_python_env(extra={"CI_SYNTHETIC_API_KEY": "explicit-value"})

    assert child_env["CI_SYNTHETIC_API_KEY"] == "explicit-value"
