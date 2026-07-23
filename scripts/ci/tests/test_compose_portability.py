"""Compose portability and fail-closed init coverage.

Pins the contributor-workstation decoupling contract: published host ports and
host-facing advertised URLs are environment-overrideable with defaults that
preserve current behaviour; the Compose preflight fails closed on a missing
runtime or secret path while only stat-ing secrets; rustfs/kafka init scripts
no longer mask real errors; and the Kafka Connect image registers connectors on
startup but runs destructive legacy cleanup only under an explicit subcommand.

Tests parse the shipped artefacts and drive the init scripts against fake
docker/mc/kafka-topics/curl/psql binaries, so they run without a live stack.
Set NOHIKI_PORTABILITY_TEST_ROOT to an alternate checkout (e.g. a
`git archive HEAD` export) to see the pre-portability tree fail these.
"""

from __future__ import annotations

import fcntl
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml
from ci_checks.core.repository import tracked_text_files

_ENV_ROOT = os.environ.get("NOHIKI_PORTABILITY_TEST_ROOT")
_REPO = Path(_ENV_ROOT).resolve() if _ENV_ROOT else Path(__file__).resolve().parents[3]

_COMPOSE = _REPO / "infra" / "compose" / "docker-compose.yml"
_ENV_EXAMPLE = _REPO / "infra" / "compose" / ".env.example"
_PREFLIGHT = _REPO / "infra" / "compose" / "scripts" / "preflight.sh"
_JUSTFILE = _REPO / "Justfile"
_FLAKE = _REPO / "flake.nix"
_ROOT_README = _REPO / "README.md"
_COMPOSE_README = _REPO / "infra" / "compose" / "README.md"
_RUSTFS_INIT = _REPO / "infra" / "compose" / "scripts" / "rustfs-init.sh"
_KAFKA_INIT = _REPO / "infra" / "compose" / "scripts" / "kafka-init.sh"
_REGISTER = _REPO / "infra" / "k8s" / "kafka-connect" / "scripts" / "register-connectors.sh"
_ENTRYPOINT = _REPO / "infra" / "k8s" / "kafka-connect" / "scripts" / "entrypoint.sh"


_compose_preflight_lock_state = threading.local()


@contextmanager
def _compose_preflight_lock() -> Iterator[None]:
    depth = getattr(_compose_preflight_lock_state, "depth", 0)
    if depth:
        _compose_preflight_lock_state.depth = depth + 1
        try:
            yield
        finally:
            _compose_preflight_lock_state.depth = depth
        return

    lock_path = _REPO / ".pytest_cache" / "compose-preflight.lock"
    lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        _compose_preflight_lock_state.depth = 1
        try:
            yield
        finally:
            _compose_preflight_lock_state.depth = 0


@pytest.fixture
def _serialized_compose_preflight() -> Iterator[None]:
    with _compose_preflight_lock():
        yield


# Historical published host:internal bindings the defaults must preserve.
# Host ports are unique, so a flat dict is an unambiguous baseline.
_EXPECTED_PUBLISHED: dict[str, str] = {
    "3000": "3000",  # gotenberg
    "5001": "5001",  # docling
    "8000": "80",  # traefik http
    "8443": "443",  # traefik https
    "8080": "8080",  # traefik dashboard
    "5432": "5432",  # postgres
    "5050": "80",  # pgadmin
    "29092": "9092",  # kafka HOST listener
    "8083": "8083",  # kafka connect
    "8082": "8080",  # kafka ui
    "6379": "6379",  # valkey
    "9002": "9000",  # rustfs s3 api
    "9003": "9001",  # rustfs console
    "6333": "6333",  # qdrant rest
    "6334": "6334",  # qdrant grpc
    "5000": "5000",  # mlflow
    "3100": "3100",  # loki
    "3200": "3200",  # tempo
    "9009": "9009",  # mimir
    "4040": "4040",  # pyroscope
    "4317": "4317",  # otel grpc
    "4318": "4318",  # otel http
    "8889": "8889",  # otel prometheus exporter
    "13133": "13133",  # otel health
    "6006": "6006",  # phoenix ui
    "4320": "4317",  # phoenix otlp
    "9090": "9090",  # prometheus
    "3001": "3000",  # grafana
}

# Matches an innermost ${VAR:-default} (default has no braces), applied
# repeatedly to resolve nested forms like ${A:-${B:-x}}.
_INNERMOST = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^{}]*)\}")


def _expand(text: str, env: dict[str, str]) -> str:
    for _ in range(20):
        new = _INNERMOST.sub(lambda m: env.get(m.group(1), m.group(2)), text)
        if new == text:
            break
        text = new
    assert "${" not in text, f"unresolved parameter expansion in {text!r}"
    return text


def _compose() -> dict[str, Any]:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def _published_ports() -> list[tuple[str, str]]:
    return [
        (name, mapping)
        for name, service in _compose()["services"].items()
        for mapping in service.get("ports", ())
        if isinstance(mapping, str)
    ]


def _find_env(key: str) -> str:
    matches = [
        service["environment"][key]
        for service in _compose()["services"].values()
        if isinstance(service.get("environment"), dict) and key in service["environment"]
    ]
    assert matches, f"no service declares environment key {key!r}"
    return str(matches[0])


def _make_exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _bin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    return d


def _path_with(bin_dir: Path) -> str:
    return os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])


def _sh(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )


# Host ports are environment-overrideable with preserved defaults.
def test_every_published_port_is_overrideable_and_preserves_defaults() -> None:
    entries = _published_ports()
    assert entries, "compose declares no published ports"

    resolved: dict[str, str] = {}
    for service, raw in entries:
        assert "${NOHIKI_HOST_IP:-127.0.0.1}" in raw, (service, raw)
        names = [name for name, _ in _INNERMOST.findall(raw)]
        assert "NOHIKI_HOST_IP" in names, (service, raw)
        port_vars = [n for n in names if n.startswith("NOHIKI_PORT_")]
        assert len(port_vars) == 1, (service, raw, port_vars)

        ip, host, internal = _expand(raw, {}).split(":")
        assert ip == "127.0.0.1", (service, raw)
        assert host not in resolved, f"duplicate published host port {host}"
        resolved[host] = internal

    assert resolved == _EXPECTED_PUBLISHED


def test_host_ip_and_port_overrides_change_the_published_binding() -> None:
    for service, raw in _published_ports():
        ((host_var, _),) = [(n, d) for n, d in _INNERMOST.findall(raw) if n == "NOHIKI_HOST_IP"]
        ((port_var, port_default),) = [(n, d) for n, d in _INNERMOST.findall(raw) if n.startswith("NOHIKI_PORT_")]
        _, _, internal = _expand(raw, {}).split(":")

        overridden = str(int(port_default) + 10000)
        ip, host, kept_internal = _expand(
            raw,
            {host_var: "0.0.0.0", port_var: overridden},  # noqa: S104 - fixture override exercises explicit all-interface binding
        ).split(":")
        assert ip == "0.0.0.0", (service, raw)  # noqa: S104
        assert host == overridden, (service, raw)
        assert kept_internal == internal, "internal container port must not change"


def test_env_example_documents_every_port_variable() -> None:
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    assert re.search(r"(?m)^NOHIKI_HOST_IP=127\.0\.0\.1$", text)

    used = {
        name for _, raw in _published_ports() for name, _ in _INNERMOST.findall(raw) if name.startswith("NOHIKI_PORT_")
    }
    documented = set(re.findall(r"(?m)^(NOHIKI_PORT_[A-Z0-9_]+)=", text))
    missing = used - documented
    assert not missing, f".env.example is missing port docs for: {sorted(missing)}"


# Columns: env key, default render, override env, overridden render.
_ADVERTISED = [
    (
        "USER_AUTH_JWT__ISSUER",
        "http://localhost:8000",
        {"NOHIKI_PORT_TRAEFIK_HTTP": "18000"},
        "http://localhost:18000",
    ),
    (
        "BFF_JWT__ISSUER",
        "http://localhost:8000",
        {"NOHIKI_PUBLIC_API_URL": "https://api.example.test"},
        "https://api.example.test",
    ),
    (
        "USER_AUTH_OAUTH__CALLBACK_BASE_URL",
        "http://localhost:8000",
        {"NOHIKI_PORT_TRAEFIK_HTTP": "18000"},
        "http://localhost:18000",
    ),
    (
        "USER_AUTH_OAUTH__SUCCESS_REDIRECT_URL",
        "http://localhost:5173/auth/callback",
        {"NOHIKI_FRONTEND_ORIGIN": "https://app.example.test"},
        "https://app.example.test/auth/callback",
    ),
    (
        "USER_AUTH_OAUTH__ERROR_REDIRECT_URL",
        "http://localhost:5173/auth/callback",
        {"NOHIKI_FRONTEND_ORIGIN": "https://app.example.test"},
        "https://app.example.test/auth/callback",
    ),
    (
        "BFF_S3__PUBLIC_URL",
        "http://localhost:9002",
        {"NOHIKI_PORT_RUSTFS_API": "19002"},
        "http://localhost:19002",
    ),
]


@pytest.mark.parametrize(
    ("key", "default_render", "override_env", "override_render"),
    _ADVERTISED,
    ids=[row[0] for row in _ADVERTISED],
)
def test_advertised_url_is_overrideable_with_preserved_default(
    key: str, default_render: str, override_env: dict[str, str], override_render: str
) -> None:
    raw = _find_env(key)
    assert "${" in raw, f"{key} must be parameterised, got literal {raw!r}"
    assert _expand(raw, {}) == default_render
    assert _expand(raw, override_env) == override_render


def test_kafka_advertised_host_listener_follows_the_port_variable() -> None:
    raw = _find_env("KAFKA_ADVERTISED_LISTENERS")
    # INTERNAL leg stays on fixed internal DNS; only the HOST leg is overrideable.
    assert "INTERNAL://nohiki-cp-kafka:29092" in _expand(raw, {})
    assert "HOST://localhost:29092" in _expand(raw, {})
    assert "HOST://localhost:39092" in _expand(raw, {"NOHIKI_PORT_KAFKA": "39092"})


def test_bff_cors_and_csrf_origins_follow_the_frontend_origin() -> None:
    for key in ("BFF_ORIGINS__CORS_ORIGINS", "BFF_ORIGINS__CSRF_ORIGINS"):
        raw = _find_env(key)
        assert "http://localhost:5173" in _expand(raw, {})
        assert "https://app.example.test" in _expand(raw, {"NOHIKI_FRONTEND_ORIGIN": "https://app.example.test"})


# Preflight fails closed and never reads secret contents.
_SECRET_DIRS = (
    "database",
    "redis",
    "s3",
    "jwt",
    "oauth",
    "jsearch",
    "llm",
    "gcp",
    "email",
    "qdrant",
    "s3-mlflow",
)
_SECRET_FILES = ("database/dsn", "s3/rustfs-root.env")
_SENTINEL = "TOP-SECRET-DO-NOT-PRINT-8f3c2a"


def _make_secrets(root: Path, *, omit_dir: str | None = None, omit_file: str | None = None) -> Path:
    secrets = root / "secrets"
    for category in _SECRET_DIRS:
        if category != omit_dir:
            (secrets / category).mkdir(parents=True, exist_ok=True)
    for rel in _SECRET_FILES:
        if rel != omit_file:
            f = secrets / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"{_SENTINEL}={rel}\n", encoding="utf-8")
    return secrets


def _fake_runtime(bin_dir: Path, *, compose_ok: bool = True) -> None:
    waiter = bin_dir / "fake-action-waiter"
    waiter.write_text(
        f"#!{sys.executable}\n"
        "import os, signal\n"
        "def stop(signum, _frame):\n"
        "    name = signal.Signals(signum).name.removeprefix('SIG')\n"
        "    with open(os.environ['FAKE_ACTION_SIGNAL_LOG'], 'w') as stream:\n"
        "        stream.write(name + '\\n')\n"
        "    raise SystemExit(128 + signum)\n"
        "for handled in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):\n"
        "    signal.signal(handled, stop)\n"
        "with open(os.environ['FAKE_ACTION_PID'], 'w') as stream:\n"
        "    stream.write(str(os.getpid()))\n"
        "if ready_fifo := os.environ.get('FAKE_ACTION_READY_FIFO'):\n"
        "    with open(ready_fifo, 'w') as stream:\n"
        "        stream.write('ready\\n')\n"
        "if ready := os.environ.get('FAKE_ACTION_READY'):\n"
        "    open(ready, 'w').close()\n"
        "while True:\n"
        "    signal.pause()\n",
        encoding="utf-8",
    )
    waiter.chmod(waiter.stat().st_mode | stat.S_IEXEC)
    _make_exe(
        bin_dir / "fakeruntime",
        f'if [ "$1" = "compose" ] && [ "$2" = "version" ]; then\n  exit {0 if compose_ok else 1}\nfi\n'
        'last=""\nfor argument in "$@"; do last=$argument; done\n'
        'if [ "$last" = "config" ] || '
        '[ "$last" = "--quiet" ]; then\n'
        '  echo "source-config" >> "${FAKE_RUNTIME_LOG:-/dev/null}"\n'
        '  if [ -n "${FAKE_CONFIG_TRACE:-}" ]; then\n'
        '    printf "config-pwd:%s\\n" "$PWD" >> "$FAKE_CONFIG_TRACE"\n'
        '    previous=""\n'
        '    for argument in "$@"; do\n'
        '      if [ "$previous" = "-f" ]; then printf "config-file:%s\\n" "$argument" >> "$FAKE_CONFIG_TRACE"; fi\n'
        '      if [ "$previous" = "--project-directory" ]; then '
        'printf "config-project:%s\\n" "$argument" >> "$FAKE_CONFIG_TRACE"; fi\n'
        "      previous=$argument\n"
        "    done\n"
        "  fi\n"
        '  if [ -n "${FAKE_RENDER_READY_FIFO:-}" ]; then\n'
        '    printf "ready\\n" > "$FAKE_RENDER_READY_FIFO"\n'
        '    read -r _release < "$FAKE_RENDER_RELEASE_FIFO"\n'
        "  fi\n"
        '  if [ "${FAKE_COMPOSE_CONFIG_FAIL:-0}" = 1 ]; then echo "$FAKE_RENDER_ERROR" >&2; exit 1; fi\n'
        '  [ "$last" = "--quiet" ] || cat "$FAKE_RENDERED_CONFIG"\n'
        "  exit 0\nfi\n"
        'action_file=""\naction_command=""\naction_project=""\nprevious=""\nafter_file=0\n'
        'for argument in "$@"; do\n'
        '  if [ "$previous" = "-f" ]; then action_file=$argument; after_file=1; previous=$argument; continue; fi\n'
        '  if [ "$previous" = "--project-directory" ]; then '
        "action_project=$argument; previous=$argument; continue; fi\n"
        '  if [ "$after_file" = 1 ]; then action_command=$argument; break; fi\n'
        "  previous=$argument\n"
        "done\n"
        'if [ "$1" = "compose" ] && [ -n "$action_file" ]; then\n'
        '  echo "action:$action_file:$action_command" >> "${FAKE_RUNTIME_LOG:-/dev/null}"\n'
        '  [ -z "${FAKE_CONFIG_TRACE:-}" ] || printf "action-pwd:%s\\n" "$PWD" >> "$FAKE_CONFIG_TRACE"\n'
        '  if [ -n "${FAKE_CONFIG_TRACE:-}" ] && [ -n "$action_project" ]; then\n'
        '    printf "action-project:%s\\n" "$action_project" >> "$FAKE_CONFIG_TRACE"\n'
        "  fi\n"
        '  if [ -n "${FAKE_ACTION_CONFIG_SNAPSHOT:-}" ]; then\n'
        '    if [ -n "${FAKE_ACTION_DECODE_RUNTIME:-}" ]; then\n'
        '      if [ -n "${FAKE_ACTION_PROJECT_DIRECTORY:-}" ]; then\n'
        '        (cd "$FAKE_ACTION_PROJECT_DIRECTORY" && '
        '"$FAKE_ACTION_DECODE_RUNTIME" -f "$action_file" config) '
        '> "$FAKE_ACTION_CONFIG_SNAPSHOT" || exit $?\n'
        "      else\n"
        '        "$FAKE_ACTION_DECODE_RUNTIME" -f "$action_file" config '
        '> "$FAKE_ACTION_CONFIG_SNAPSHOT" || exit $?\n'
        "      fi\n"
        "    else\n"
        '      cp "$action_file" "$FAKE_ACTION_CONFIG_SNAPSHOT"\n'
        "    fi\n"
        "  fi\n"
        '  [ -z "${FAKE_ACTION_CONFIG_MODE:-}" ] || stat -c "%a" "$action_file" > "$FAKE_ACTION_CONFIG_MODE"\n'
        '  if [ -n "${FAKE_ACTION_READY:-}" ]; then\n'
        "    exec fake-action-waiter\n"
        "  fi\n"
        '  exit "${FAKE_ACTION_EXIT:-0}"\nfi\n'
        "exit 1\n",
    )


def _mode_recording_python(bin_dir: Path) -> Path:
    proxy = bin_dir / "mode-recording-python"
    _make_exe(
        proxy,
        'last=""\nfor argument in "$@"; do last=$argument; done\n'
        'stat -c "%a" "$last" > "$FAKE_RENDERED_CONFIG_MODE"\n'
        'exec "$REAL_PYTHON" "$@"',
    )
    return proxy


def _canonical_compose_runtime() -> str:
    return _canonical_compose_runtime_for_path(os.environ.get("PATH", ""))


@cache
def _canonical_compose_runtime_for_path(path: str) -> str:
    runtime = shutil.which("podman-compose", path=path)
    if runtime is None:
        pytest.skip("pinned podman-compose is not installed; enter the Nix CI shell")
    result = subprocess.run(
        [runtime, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("pinned podman-compose is not usable")
    return runtime


def _compose_config(
    runtime: str,
    compose_file: Path,
    environment: dict[str, str],
    *,
    project_directory: Path | None = None,
    escape_dollars: bool = False,
) -> str:
    staged: Path | None = None
    if project_directory is None:
        project_directory = compose_file.parent
        compose_path = compose_file
    else:
        descriptor, name = tempfile.mkstemp(suffix=".yml", dir=project_directory)
        os.close(descriptor)
        staged = Path(name)
        contents = compose_file.read_text(encoding="utf-8")
        staged.write_text(
            contents.replace("$", "$$") if escape_dollars else contents,
            encoding="utf-8",
        )
        compose_path = staged

    try:
        result = subprocess.run(
            [runtime, "-f", str(compose_path), "config"],
            cwd=project_directory,
            env=os.environ | environment,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        if staged is not None:
            staged.unlink()
    assert result.returncode == 0, result.stderr
    return result.stdout


def _hermetic_compose_project(tmp_path: Path, env_text: str) -> Path:
    project = tmp_path / "compose-project"
    compose_dir = project / "infra" / "compose"
    compose_dir.mkdir(parents=True)
    compose_file = compose_dir / _COMPOSE.name
    shutil.copy2(_COMPOSE, compose_file)
    (compose_dir / ".env").write_text(env_text, encoding="utf-8")
    for service in yaml.safe_load(compose_file.read_text(encoding="utf-8"))["services"].values():
        entries = service.get("env_file", ())
        if isinstance(entries, str):
            entries = (entries,)
        for entry in entries:
            relative = entry["path"] if isinstance(entry, dict) else entry
            assert isinstance(relative, str)
            assert "${" not in relative
            env_file = (compose_dir / relative).resolve()
            assert env_file.is_relative_to(project.resolve())
            env_file.parent.mkdir(parents=True, exist_ok=True)
            env_file.write_text("", encoding="utf-8")
    return compose_file


def test_hermetic_compose_project_materializes_untracked_env_files(
    tmp_path: Path,
) -> None:
    compose_file = _hermetic_compose_project(
        tmp_path,
        "NOHIKI_LLM_OPENAI_BASE_URL=https://models.example.test/v1\n",
    )
    assert compose_file.read_bytes() == _COMPOSE.read_bytes()
    assert (compose_file.parent / ".env").is_file()
    assert (compose_file.parent / "../shared/secrets/s3/rustfs-root.env").resolve().is_file()


def test_compose_probe_selects_pinned_podman_compose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = _bin_dir(tmp_path)
    trace = tmp_path / "compose-probe.args"
    _make_exe(bin_dir / "podman-compose", 'printf "%s\n" "$*" > "$TRACE"\n')
    _make_exe(bin_dir / "docker", "exit 99\n")
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("TRACE", str(trace))
    assert _canonical_compose_runtime() == str(bin_dir / "podman-compose")
    assert trace.read_text(encoding="utf-8").splitlines() == ["--version"]


def _dotenv_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value.startswith(('"', "'")):
            quote = value[0]
            end = value.find(quote, 1)
            value = value[1:end] if end >= 0 else value
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key.strip()] = value
    return values


def _rendered_compose(endpoint_values: dict[str, str], path: Path) -> Path:
    compose = _compose()
    provider_inputs = compose["x-llm-provider-endpoints"]
    for variable in provider_inputs:
        provider_inputs[variable] = endpoint_values.get(variable, "")
    for service in compose["services"].values():
        environment = service.get("environment", {})
        if not isinstance(environment, dict):
            continue
        for key, value in environment.items():
            if key.endswith("__BASE_URL") and isinstance(value, str):
                if "NOHIKI_LLM_OPENAI_BASE_URL" in value:
                    environment[key] = endpoint_values.get("NOHIKI_LLM_OPENAI_BASE_URL", "")
                elif "NOHIKI_LLM_ANTHROPIC_BASE_URL" in value:
                    environment[key] = endpoint_values.get("NOHIKI_LLM_ANTHROPIC_BASE_URL", "")
    rendered = path / "rendered-compose.yml"
    rendered.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")
    return rendered


def _run_preflight(
    bin_dir: Path,
    secrets: Path,
    runtime: str = "fakeruntime",
    endpoint_env: dict[str, str] | None = None,
    env_text: str = "NOHIKI_LLM_OPENAI_BASE_URL=https://models.example.test/v1\n",
    compose_args: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    env_file = secrets.parent / ".env"
    env_file.write_text(env_text, encoding="utf-8")
    endpoint_values = _dotenv_values(env_text) | (endpoint_env or {})
    rendered = _rendered_compose(endpoint_values, secrets.parent)
    with _compose_preflight_lock():
        return _sh(
            ["sh", str(_PREFLIGHT), *compose_args],
            {
                "PATH": _path_with(bin_dir),
                "SECRETS_DIR": str(secrets),
                "CONTAINER_RUNTIME": runtime,
                "PYTHON": sys.executable,
                "FAKE_RENDERED_CONFIG": str(rendered),
                **(endpoint_env or {}),
            },
        )


def _run_endpoint_validator(
    tmp_path: Path,
    openai_endpoint: str,
    anthropic_endpoint: str,
    *,
    rendered_environment: dict[str, str] | None = None,
    source_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "source-compose.yml"
    rendered = tmp_path / "rendered-provider-compose.yml"
    source.write_text(
        "x-llm-provider-endpoints:\n"
        '  NOHIKI_LLM_OPENAI_BASE_URL: "${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}"\n'
        '  NOHIKI_LLM_ANTHROPIC_BASE_URL: "${NOHIKI_LLM_ANTHROPIC_BASE_URL:-}"\n'
        "services:\n"
        "  endpoints:\n"
        "    environment:\n"
        "      TEST_LLM__PROVIDER__MODELS__0__MODEL: openai:test-openai\n"
        "      TEST_LLM__PROVIDER__MODELS__0__BASE_URL: "
        '"${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}"\n'
        "      TEST_LLM__PROVIDER__MODELS__1__MODEL: anthropic:test-anthropic\n"
        "      TEST_LLM__PROVIDER__MODELS__1__BASE_URL: "
        '"${NOHIKI_LLM_ANTHROPIC_BASE_URL:?set NOHIKI_LLM_ANTHROPIC_BASE_URL}"\n'
        + "".join(f'      {key}: "{value}"\n' for key, value in (source_environment or {}).items()),
        encoding="utf-8",
    )
    rendered.write_text(
        "x-llm-provider-endpoints:\n"
        f'  NOHIKI_LLM_OPENAI_BASE_URL: "{openai_endpoint}"\n'
        f'  NOHIKI_LLM_ANTHROPIC_BASE_URL: "{anthropic_endpoint}"\n'
        "services:\n"
        "  endpoints:\n"
        "    environment:\n"
        "      TEST_LLM__PROVIDER__MODELS__0__MODEL: openai:test-openai\n"
        f'      TEST_LLM__PROVIDER__MODELS__0__BASE_URL: "{openai_endpoint}"\n'
        "      TEST_LLM__PROVIDER__MODELS__1__MODEL: anthropic:test-anthropic\n"
        f'      TEST_LLM__PROVIDER__MODELS__1__BASE_URL: "{anthropic_endpoint}"\n'
        + "".join(f'      {key}: "{value}"\n' for key, value in (rendered_environment or {}).items()),
        encoding="utf-8",
    )
    validator = _PREFLIGHT.with_name("validate-llm-endpoints.py")
    return _sh([sys.executable, str(validator), str(source), str(rendered)], {})


def test_validator_rejects_provider_inputs_without_any_protected_model(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-compose.yml"
    rendered = tmp_path / "rendered-compose.yml"
    source.write_text(
        "x-llm-provider-endpoints:\n"
        '  NOHIKI_LLM_OPENAI_BASE_URL: "${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}"\n'
        '  NOHIKI_LLM_ANTHROPIC_BASE_URL: "${NOHIKI_LLM_ANTHROPIC_BASE_URL:-}"\n'
        "services:\n  empty:\n    environment:\n      UNPROTECTED_VALUE: present\n",
        encoding="utf-8",
    )
    rendered.write_text(
        "x-llm-provider-endpoints:\n"
        '  NOHIKI_LLM_OPENAI_BASE_URL: "https://models.example.test/v1"\n'
        '  NOHIKI_LLM_ANTHROPIC_BASE_URL: ""\n'
        "services:\n  empty:\n    environment:\n      UNPROTECTED_VALUE: present\n",
        encoding="utf-8",
    )

    result = _sh(
        [
            sys.executable,
            str(_PREFLIGHT.with_name("validate-llm-endpoints.py")),
            str(source),
            str(rendered),
        ],
        {},
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "preflight: endpoint contract invalid: Compose must declare at least one protected __MODEL binding\n"
    )


_EXPECTED_LLM_MODELS = {
    (
        "nohiki-svc-job-ingest-enrichment",
        "JOB_INGEST_ENRICHMENT_LLM__PROVIDER__MODELS__0__MODEL",
    ): "openai:gpt-5.6-luna",
    (
        "nohiki-svc-doc-content",
        "DOC_CONTENT_LLM__PROVIDER__MODELS__0__MODEL",
    ): "openai:gpt-5.6-sol",
    (
        "nohiki-svc-doc-content",
        "DOC_CONTENT_LLM__CHAINS__DOC_TAILORING__MODELS__0__MODEL",
    ): "openai:gpt-5.6-sol",
}


def _llm_models() -> dict[tuple[str, str], tuple[str, str | None]]:
    models: dict[tuple[str, str], tuple[str, str | None]] = {}
    for service_name, service in _compose()["services"].items():
        environment = service.get("environment", {})
        if not isinstance(environment, dict):
            continue
        for key, model in environment.items():
            if re.search(r"_LLM__.*__MODELS__\d+__MODEL$", key):
                base_key = key.removesuffix("__MODEL") + "__BASE_URL"
                base_url = environment.get(base_key)
                models[(service_name, key)] = (
                    str(model),
                    str(base_url) if base_url is not None else None,
                )
    return models


def test_compose_renders_every_private_model_to_its_provider_endpoint() -> None:
    endpoint = "https://openai.models.example.test/v1"
    models = _llm_models()

    assert {key: model for key, (model, _) in models.items()} == _EXPECTED_LLM_MODELS
    for model, raw_base_url in models.values():
        assert model.startswith("openai:")
        assert raw_base_url == "${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}"
        rendered_base_url = raw_base_url.replace(
            "${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}", endpoint
        )
        assert rendered_base_url == endpoint
        assert f"{rendered_base_url.rstrip('/')}/models" == "https://openai.models.example.test/v1/models"


def test_luna_enrichment_has_no_unused_gcp_credentials_or_mount() -> None:
    service = _compose()["services"]["nohiki-svc-job-ingest-enrichment"]
    environment = service["environment"]
    assert environment["JOB_INGEST_ENRICHMENT_LLM__PROVIDER__MODELS__0__MODEL"] == "openai:gpt-5.6-luna"
    assert not any(key == "GOOGLE_APPLICATION_CREDENTIALS" or key.startswith("GOOGLE_") for key in environment)
    assert not any("/run/secrets/gcp" in volume for volume in service["volumes"])


def test_correlation_has_no_llm_provider_configuration_but_keeps_ml_ranking_assets() -> None:
    service = _compose()["services"]["nohiki-svc-job-correlation"]
    environment = service["environment"]
    assert not any("_LLM__" in key for key in environment)
    assert not any("/run/secrets/llm" in volume for volume in service["volumes"])
    assert environment["JOB_CORRELATION_EVAL_ML__PIPELINE__MIN_SCORE_THRESHOLD"] == "30"
    assert any(
        volume.endswith(":/app/data/config/semantic_representation_manifest.json:ro") for volume in service["volumes"]
    )


def test_compose_omits_direct_provider_defaults_and_derived_transport_fields() -> None:
    for service in _compose()["services"].values():
        environment = service.get("environment", {})
        if not isinstance(environment, dict):
            continue
        for key, model in environment.items():
            if not re.search(r"_LLM__.*__MODELS__\d+__MODEL$", key):
                continue
            base_key = key.removesuffix("__MODEL") + "__BASE_URL"
            provider = str(model).partition(":")[0]
            if provider == "openrouter":
                assert base_key not in environment
            else:
                assert base_key in environment
        assert not any(key.endswith(("__HEALTH_URL", "__TLS_CA_FILE")) for key in environment if "_LLM__" in key)


def test_compose_endpoint_sources_have_no_private_default_or_credential_literal() -> None:
    compose_text = _COMPOSE.read_text(encoding="utf-8")
    env_example = _ENV_EXAMPLE.read_text(encoding="utf-8")
    bases = [base for _, base in _llm_models().values()]

    assert bases
    assert all(base and base.startswith("${NOHIKI_LLM_") for base in bases)
    assert "api.openai.com" not in compose_text
    assert "api.anthropic.com" not in compose_text
    active_endpoint_inputs = {
        line.partition("=")[0]
        for line in env_example.splitlines()
        if re.fullmatch(r"NOHIKI_LLM_[A-Z0-9_]+_BASE_URL=.*", line)
    }
    assert active_endpoint_inputs == {"NOHIKI_LLM_OPENAI_BASE_URL"}
    assert not re.search(r"NOHIKI_LLM_.*(?:KEY|TOKEN|PASSWORD)\s*[:=]", compose_text)


def test_validator_accepts_separate_custom_openai_and_anthropic_conventions(
    tmp_path: Path,
) -> None:
    result = _run_endpoint_validator(
        tmp_path,
        "https://openai.models.example.test/v1",
        "https://anthropic.models.example.test",
    )

    assert result.returncode == 0, result.stderr
    assert "openai.models.example.test" not in result.stdout + result.stderr
    assert "anthropic.models.example.test" not in result.stdout + result.stderr


def test_validator_redacts_unsupported_provider_and_model_sentinels(
    tmp_path: Path,
) -> None:
    model_key = "SENTINEL_LLM__PROVIDER__MODELS__2__MODEL"
    provider_sentinel = "attacker-provider-7c91"
    model_sentinel = "attacker-model-02fe"
    model = f"{provider_sentinel}:{model_sentinel}"
    environment = {model_key: model}
    result = _run_endpoint_validator(
        tmp_path,
        "https://openai.models.example.test/v1",
        "https://anthropic.models.example.test",
        source_environment=environment,
        rendered_environment=environment,
    )

    assert result.returncode == 1
    assert model_key in result.stderr
    assert "unsupported provider" in result.stderr
    assert provider_sentinel not in result.stderr
    assert model_sentinel not in result.stderr


@pytest.mark.parametrize(
    "override_model",
    ["unsupported:private-model", "openai:override-only-model"],
    ids=("unsupported-provider", "arbitrary-provider-url"),
)
def test_validator_rejects_override_only_model_and_base_url_bindings(tmp_path: Path, override_model: str) -> None:
    arbitrary_url = "https://override-only.invalid/private/v1"
    model_key = "OVERRIDE_LLM__PROVIDER__MODELS__2__MODEL"
    result = _run_endpoint_validator(
        tmp_path,
        "https://openai.models.example.test/v1",
        "https://anthropic.models.example.test",
        rendered_environment={
            model_key: override_model,
            model_key.removesuffix("__MODEL") + "__BASE_URL": arbitrary_url,
        },
    )

    assert result.returncode == 1
    assert model_key in result.stderr
    assert arbitrary_url not in result.stdout + result.stderr
    assert override_model not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("rendered_key", "opaque_value"),
    [
        (
            "TEST_LLM__PROVIDER__MODELS__0__HEALTH_URL",
            "opaque-rendered-health-3a9d",
        ),
        (
            "TEST_LLM__PROVIDER__MODELS__0__TLS_CA_FILE",
            "opaque-rendered-ca-97bc",
        ),
        ("TEST_LLM__PROVIDER__API_KEY", "opaque-rendered-api-key-f823"),
        ("UNDECLARED_LLM__OPAQUE_SETTING", "opaque-rendered-service-50d1"),
        ("NOHIKI_LLM_UNDECLARED_GLOBAL", "opaque-rendered-global-a77e"),
        ("test_llm__provider__api_key", "opaque-rendered-lowercase-29c4"),
        ("NoHiKi_LlM_UnDeClArEd", "opaque-rendered-mixed-case-e181"),
    ],
    ids=(
        "health-url",
        "tls-ca-file",
        "api-key",
        "undeclared-service-llm",
        "undeclared-global-llm",
        "lowercase-service-llm",
        "mixed-case-global-llm",
    ),
)
def test_validator_rejects_rendered_only_protected_llm_bindings_without_echoing_value(
    tmp_path: Path, rendered_key: str, opaque_value: str
) -> None:
    result = _run_endpoint_validator(
        tmp_path,
        "https://openai.models.example.test/v1",
        "https://anthropic.models.example.test",
        rendered_environment={rendered_key: opaque_value},
    )

    assert result.returncode == 1
    assert rendered_key in result.stderr
    assert opaque_value not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("model_key", "rendered_model"),
    [
        ("TEST_LLM__PROVIDER__MODELS__0__MODEL", None),
        (
            "TEST_LLM__PROVIDER__MODELS__0__MODEL",
            "anthropic:mutated-private-model-41b7",
        ),
        ("ROUTER_LLM__PROVIDER__MODELS__2__MODEL", None),
        (
            "ROUTER_LLM__PROVIDER__MODELS__2__MODEL",
            "openai:mutated-openrouter-model-790e",
        ),
    ],
    ids=(
        "private-model-missing",
        "private-provider-changed",
        "openrouter-model-missing",
        "openrouter-provider-changed",
    ),
)
def test_validator_rejects_missing_models_and_provider_changes(
    tmp_path: Path, model_key: str, rendered_model: str | None
) -> None:
    openai_endpoint = "https://openai.models.example.test/v1"
    anthropic_endpoint = "https://anthropic.models.example.test"
    private_model_key = "TEST_LLM__PROVIDER__MODELS__0__MODEL"
    private_base_key = private_model_key.removesuffix("__MODEL") + "__BASE_URL"
    router_model_key = "ROUTER_LLM__PROVIDER__MODELS__2__MODEL"
    source_environment = {
        private_model_key: "openai:source-private-model",
        private_base_key: "${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}",
        router_model_key: "openrouter:source-public-model",
    }
    rendered_environment = {
        private_model_key: "openai:source-private-model",
        private_base_key: openai_endpoint,
        router_model_key: "openrouter:source-public-model",
    }
    if rendered_model is None:
        rendered_environment.pop(model_key)
    else:
        rendered_environment[model_key] = rendered_model
    source = tmp_path / "source-model-invariants.yml"
    rendered = tmp_path / "rendered-model-invariants.yml"
    source.write_text(
        "x-llm-provider-endpoints:\n"
        '  NOHIKI_LLM_OPENAI_BASE_URL: "${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}"\n'
        '  NOHIKI_LLM_ANTHROPIC_BASE_URL: "${NOHIKI_LLM_ANTHROPIC_BASE_URL:-}"\n'
        "services:\n  endpoints:\n    environment:\n"
        + "".join(f'      {key}: "{value}"\n' for key, value in source_environment.items()),
        encoding="utf-8",
    )
    rendered.write_text(
        "x-llm-provider-endpoints:\n"
        f'  NOHIKI_LLM_OPENAI_BASE_URL: "{openai_endpoint}"\n'
        f'  NOHIKI_LLM_ANTHROPIC_BASE_URL: "{anthropic_endpoint}"\n'
        "services:\n  endpoints:\n    environment:\n"
        + "".join(f'      {key}: "{value}"\n' for key, value in rendered_environment.items()),
        encoding="utf-8",
    )

    result = _sh(
        [
            sys.executable,
            str(_PREFLIGHT.with_name("validate-llm-endpoints.py")),
            str(source),
            str(rendered),
        ],
        {},
    )

    assert result.returncode == 1
    assert model_key in result.stderr
    if rendered_model is not None:
        assert rendered_model not in result.stdout + result.stderr


def test_validator_rejects_anthropic_v1_path_without_echoing_value(
    tmp_path: Path,
) -> None:
    anthropic_endpoint = "https://anthropic.example.test/v1"
    result = _run_endpoint_validator(tmp_path, "https://openai.example.test/v1", anthropic_endpoint)

    assert result.returncode == 1
    assert "must not end in /v1" in result.stderr
    assert anthropic_endpoint not in result.stdout + result.stderr


def test_validator_rejects_same_provider_origin_without_echoing_values(
    tmp_path: Path,
) -> None:
    openai_endpoint = "https://models.example.test/openai/v1"
    anthropic_endpoint = "https://models.example.test/anthropic"
    result = _run_endpoint_validator(tmp_path, openai_endpoint, anthropic_endpoint)

    assert result.returncode == 1
    assert "separate HTTPS origins" in result.stderr
    assert openai_endpoint not in result.stdout + result.stderr
    assert anthropic_endpoint not in result.stdout + result.stderr


def test_validator_normalizes_host_case_and_default_https_port_for_origin_separation(
    tmp_path: Path,
) -> None:
    openai_endpoint = "https://MODELS.Example.Test/v1"
    anthropic_endpoint = "https://models.example.test:443/anthropic"
    result = _run_endpoint_validator(tmp_path, openai_endpoint, anthropic_endpoint)

    assert result.returncode == 1
    assert "separate HTTPS origins" in result.stderr
    assert openai_endpoint not in result.stdout + result.stderr
    assert anthropic_endpoint not in result.stdout + result.stderr


def test_validator_accepts_distinct_bracketed_ipv6_origins(tmp_path: Path) -> None:
    result = _run_endpoint_validator(
        tmp_path,
        "https://[2001:db8::1]/v1",
        "https://[2001:db8::2]/anthropic",
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("endpoint_env", "expected_error"),
    [
        ({"NOHIKI_LLM_OPENAI_BASE_URL": ""}, "required endpoint variable"),
        (
            {"NOHIKI_LLM_OPENAI_BASE_URL": "http://models.example.test/v1"},
            "absolute HTTPS",
        ),
        (
            {"NOHIKI_LLM_OPENAI_BASE_URL": "https://models.example.test"},
            "must end in /v1",
        ),
    ],
)
def test_preflight_rejects_unsafe_or_provider_incompatible_endpoints(
    tmp_path: Path, endpoint_env: dict[str, str], expected_error: str
) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    result = _run_preflight(bin_dir, _make_secrets(tmp_path), endpoint_env=endpoint_env)

    assert result.returncode == 1
    assert expected_error in result.stderr
    assert not any(value and value in result.stdout + result.stderr for value in endpoint_env.values())


def test_preflight_rejects_userinfo_without_leaking_credentials(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    credential = "compose-endpoint-secret-4f19"
    endpoint = f"https://client:{credential}@models.example.test/v1"
    result = _run_preflight(
        bin_dir,
        _make_secrets(tmp_path),
        endpoint_env={"NOHIKI_LLM_OPENAI_BASE_URL": endpoint},
    )

    assert result.returncode == 1
    assert "must not contain user information" in result.stderr
    assert credential not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://2001:db8::1/v1",
        "https://[2001:db8::gg]/v1",
        "https://[]/v1",
        "https://[2001:db8::1/v1",
        "https://2001:db8::1]/v1",
        "https://models].example.test/v1",
        "https://models.example.test:/v1",
        "https://models.example.test:abc/v1",
        "https://models.example.test:443:444/v1",
        "https://models.example.test:0/v1",
        "https://models.example.test:65536/v1",
        "https://models.example.test/v1?tenant=private",
        "https://models.example.test/v1#private",
    ],
)
def test_preflight_rejects_invalid_authorities_without_echoing_values(tmp_path: Path, endpoint: str) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    result = _run_preflight(
        bin_dir,
        _make_secrets(tmp_path),
        endpoint_env={"NOHIKI_LLM_OPENAI_BASE_URL": endpoint},
    )

    assert result.returncode == 1
    assert "NOHIKI_LLM_OPENAI_BASE_URL" in result.stderr
    assert endpoint not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "endpoint",
    [
        pytest.param("https://mod\x00els.example.test/v1", id="nul-control"),
        pytest.param("https://mod\x01els.example.test/v1", id="soh-control"),
        pytest.param("https://mod\x1fels.example.test/v1", id="unit-separator-control"),
        pytest.param("https://mod\x7fels.example.test/v1", id="del-control"),
        pytest.param("https://mödels.example.test/v1", id="unicode-hostname"),
        pytest.param("https://models.example.test/vé/v1", id="unicode-path"),
        pytest.param("https://models.example.test/v1?tenant=café", id="unicode-query"),
        pytest.param("https://models.example.test/v1/é?tenant=x", id="unicode-path-before-query"),
    ],
)
def test_validator_rejects_control_or_non_ascii_endpoint_text_without_echoing_values(
    tmp_path: Path, endpoint: str
) -> None:
    result = _run_endpoint_validator(tmp_path, endpoint, "https://anthropic.example.test")

    assert result.returncode == 1
    assert endpoint not in result.stdout + result.stderr


def test_preflight_parses_compose_dotenv_quotes_and_inline_comments(
    tmp_path: Path,
) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    env_text = (
        'NOHIKI_LLM_OPENAI_BASE_URL="https://openai.example.test/v1" # double-quoted endpoint\n'
        "NOHIKI_LLM_ANTHROPIC_BASE_URL='https://anthropic.example.test' # single-quoted endpoint\n"
        "NOHIKI_DOTENV_UNQUOTED=https://unquoted.example.test/v1 # unquoted endpoint\n"
    )
    result = _run_preflight(bin_dir, _make_secrets(tmp_path), env_text=env_text)

    assert result.returncode == 0, result.stderr
    assert "openai.example.test" not in result.stdout + result.stderr
    assert "anthropic.example.test" not in result.stdout + result.stderr

    runtime = _canonical_compose_runtime()
    compose_file = _hermetic_compose_project(tmp_path, env_text)
    compose = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    compose["x-dotenv-parser-probe"] = {
        "double": "${NOHIKI_LLM_OPENAI_BASE_URL}",
        "single": "${NOHIKI_LLM_ANTHROPIC_BASE_URL}",
        "unquoted": "${NOHIKI_DOTENV_UNQUOTED}",
    }
    compose_file.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")
    compose_result = subprocess.run(
        [
            runtime,
            "--env-file",
            str(compose_file.parent / ".env"),
            "-f",
            str(compose_file),
            "config",
        ],
        cwd=compose_file.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert compose_result.returncode == 0, compose_result.stderr
    rendered = yaml.safe_load(compose_result.stdout)
    assert rendered["x-dotenv-parser-probe"] == {
        "double": "https://openai.example.test/v1",
        "single": "https://anthropic.example.test",
        "unquoted": "https://unquoted.example.test/v1",
    }


def test_preflight_preserves_quoted_hash_for_fragment_rejection(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    endpoint = "https://models.example.test/v1#private"
    env_text = f'NOHIKI_LLM_OPENAI_BASE_URL="{endpoint}" # outside comment\n'
    result = _run_preflight(bin_dir, _make_secrets(tmp_path), env_text=env_text)

    assert result.returncode == 1
    assert "query or fragment" in result.stderr
    assert endpoint not in result.stdout + result.stderr


def _compose_temporary_files() -> set[Path]:
    return (
        set(_COMPOSE.parent.glob(".nohiki-compose-source.*"))
        | set(_COMPOSE.parent.glob(".nohiki-compose-rendered.*"))
        | set(_COMPOSE.parent.glob(".nohiki-compose-action.*"))
        | set(_COMPOSE.parent.glob(".nohiki-compose-diagnostics.*"))
    )


def test_preflight_passes_all_compose_sources_to_validator_in_merge_order(
    tmp_path: Path,
) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    override = tmp_path / "compose.override.yml"
    override.write_text("services: {}\n", encoding="utf-8")
    validator_args = tmp_path / "validator.args"
    python_proxy = bin_dir / "python-proxy"
    _make_exe(
        python_proxy,
        'printf "%s\\n" "$@" > "$FAKE_VALIDATOR_ARGS"\nexec "$REAL_PYTHON" "$@"\n',
    )

    result = _run_preflight(
        bin_dir,
        _make_secrets(tmp_path),
        endpoint_env={
            "COMPOSE_OVERRIDE_FILE": str(override),
            "PYTHON": str(python_proxy),
            "REAL_PYTHON": sys.executable,
            "FAKE_VALIDATOR_ARGS": str(validator_args),
        },
    )

    assert result.returncode == 0, result.stderr
    invocation = validator_args.read_text(encoding="utf-8").splitlines()
    assert Path(invocation[0]) == _PREFLIGHT.with_name("validate-llm-endpoints.py")
    source_paths = [Path(path) for path in invocation[1:-1]]
    assert len(source_paths) == 2
    assert all(path.parent.resolve() == _COMPOSE.parent.resolve() for path in source_paths)
    assert all(path.name.startswith(".nohiki-compose-source.") for path in source_paths)
    assert not any(path.exists() for path in source_paths)
    assert Path(invocation[-1]).name.startswith(".nohiki-compose-rendered.")


@pytest.mark.usefixtures("_serialized_compose_preflight")
def test_preflight_snapshots_sources_before_render_and_uses_snapshot_bytes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "relative-context").mkdir()
    base = project / "compose.yml"
    override = project / "compose.override.yml"
    base_bytes = (
        b"x-llm-provider-endpoints:\n"
        b'  NOHIKI_LLM_OPENAI_BASE_URL: "${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}"\n'
        b'  NOHIKI_LLM_ANTHROPIC_BASE_URL: "${NOHIKI_LLM_ANTHROPIC_BASE_URL:-}"\n'
        b"services:\n"
        b"  endpoints:\n"
        b"    build:\n      context: ./relative-context\n"
        b"    environment:\n"
        b"      TEST_LLM__PROVIDER__MODELS__0__MODEL: openai:test-openai\n"
        b"      TEST_LLM__PROVIDER__MODELS__0__BASE_URL: "
        b'"${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}"\n'
    )
    override_bytes = b"services:\n  endpoints:\n    environment:\n      MERGED_FROM_RELATIVE_OVERRIDE: present\n"
    base.write_bytes(base_bytes)
    override.write_bytes(override_bytes)
    rendered = tmp_path / "rendered-compose.yml"
    rendered.write_text(
        "x-llm-provider-endpoints:\n"
        '  NOHIKI_LLM_OPENAI_BASE_URL: "https://models.example.test/v1"\n'
        '  NOHIKI_LLM_ANTHROPIC_BASE_URL: ""\n'
        "services:\n"
        "  endpoints:\n"
        "    build:\n      context: ./relative-context\n"
        "    environment:\n"
        "      TEST_LLM__PROVIDER__MODELS__0__MODEL: openai:test-openai\n"
        '      TEST_LLM__PROVIDER__MODELS__0__BASE_URL: "https://models.example.test/v1"\n'
        "      MERGED_FROM_RELATIVE_OVERRIDE: present\n",
        encoding="utf-8",
    )
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    validator_args = tmp_path / "validator.args"
    validator_captures = tmp_path / "validator-captures"
    validator_captures.mkdir()
    python_proxy = bin_dir / "python-proxy"
    python_proxy.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "if len(args) < 2 or args[1] not in ('--encode-action', '--validate-sources'):\n"
        "    pathlib.Path(os.environ['FAKE_VALIDATOR_ARGS']).write_text('\\n'.join(args) + '\\n')\n"
        "    capture = pathlib.Path(os.environ['FAKE_VALIDATOR_CAPTURES'])\n"
        "    for index, path in enumerate(args[1:-1]):\n"
        "        source = pathlib.Path(path)\n"
        "        (capture / f'{index}.yml').write_bytes(source.read_bytes())\n"
        "        (capture / f'{index}.mode').write_text(f'{source.stat().st_mode & 0o777:o}\\n')\n"
        "os.execv(os.environ['REAL_PYTHON'], [os.environ['REAL_PYTHON'], *args])\n",
        encoding="utf-8",
    )
    python_proxy.chmod(python_proxy.stat().st_mode | stat.S_IEXEC)
    ready_fifo = tmp_path / "render-ready.fifo"
    release_fifo = tmp_path / "render-release.fifo"
    os.mkfifo(ready_fifo)
    os.mkfifo(release_fifo)
    ready_fd = os.open(ready_fifo, os.O_RDWR | os.O_NONBLOCK)
    release_fd = os.open(release_fifo, os.O_RDWR | os.O_NONBLOCK)
    runtime_log = tmp_path / "runtime.log"
    trace = tmp_path / "runtime.trace"
    action_snapshot = tmp_path / "action.yml"
    action_mode = tmp_path / "action.mode"
    secrets = _make_secrets(tmp_path)
    (tmp_path / ".env").write_text(
        "NOHIKI_LLM_OPENAI_BASE_URL=https://models.example.test/v1\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        ["sh", str(_PREFLIGHT), "up", "-d"],
        cwd=_REPO,
        env={
            **os.environ,
            "PATH": _path_with(bin_dir),
            "COMPOSE_FILE": str(base),
            "COMPOSE_OVERRIDE_FILE": override.name,
            "SECRETS_DIR": str(secrets),
            "CONTAINER_RUNTIME": "fakeruntime",
            "FAKE_RENDERED_CONFIG": str(rendered),
            "FAKE_RUNTIME_LOG": str(runtime_log),
            "FAKE_CONFIG_TRACE": str(trace),
            "FAKE_RENDER_READY_FIFO": str(ready_fifo),
            "FAKE_RENDER_RELEASE_FIFO": str(release_fifo),
            "FAKE_VALIDATOR_ARGS": str(validator_args),
            "FAKE_VALIDATOR_CAPTURES": str(validator_captures),
            "FAKE_ACTION_CONFIG_SNAPSHOT": str(action_snapshot),
            "FAKE_ACTION_CONFIG_MODE": str(action_mode),
            "PYTHON": str(python_proxy),
            "REAL_PYTHON": sys.executable,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        readable, _, _ = select.select([ready_fd], [], [], 3)
        assert readable, "renderer did not reach the post-snapshot barrier"
        assert os.read(ready_fd, 32).strip() == b"ready"
        trace_lines = trace.read_text(encoding="utf-8").splitlines()
        traced_paths = [
            Path(line.removeprefix("config-file:")) for line in trace_lines if line.startswith("config-file:")
        ]
        source_paths = [path if path.is_absolute() else project / path for path in traced_paths]
        assert len(source_paths) == 2
        assert all(path.parent == project for path in source_paths)
        assert all(path.name.startswith(".nohiki-compose-source.") for path in source_paths)
        assert [path.read_bytes() for path in source_paths] == [
            base_bytes,
            override_bytes,
        ]
        assert [stat.S_IMODE(path.stat().st_mode) for path in source_paths] == [
            0o600,
            0o600,
        ]
        base.write_text("mutated: base\n", encoding="utf-8")
        override.write_text("mutated: override\n", encoding="utf-8")
        os.write(release_fd, b"release\n")
        stdout, stderr = process.communicate(timeout=3)
    except AssertionError, subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise
    finally:
        os.close(ready_fd)
        os.close(release_fd)

    assert process.returncode == 0, stdout + stderr
    assert runtime_log.read_text(encoding="utf-8").splitlines().count("source-config") == 1
    invocation = validator_args.read_text(encoding="utf-8").splitlines()
    validator_sources = [
        path if path.is_absolute() else project / path for path in (Path(value) for value in invocation[1:-1])
    ]
    assert validator_sources == source_paths
    assert [(validator_captures / f"{index}.yml").read_bytes() for index in range(2)] == [base_bytes, override_bytes]
    assert [(validator_captures / f"{index}.mode").read_text().strip() for index in range(2)] == ["600", "600"]
    final_trace = trace.read_text(encoding="utf-8").splitlines()
    assert final_trace.count(f"config-pwd:{project}") == 1
    assert final_trace.count(f"action-pwd:{project}") == 1
    assert not any(line.startswith(("config-project:", "action-project:")) for line in final_trace)
    assert action_mode.read_text(encoding="utf-8").strip() == "600"
    assert action_snapshot.read_bytes() == rendered.read_bytes().replace(b"$", b"$$")
    assert not any(path.exists() for path in source_paths)
    assert not list(project.glob(".nohiki-compose-*"))


@pytest.mark.parametrize(
    "source_text",
    [
        "  include: compose.fragment.yml\n  services: {}\n",
        "{include: compose.fragment.yml, services: {}}\n",
        "? include\n: compose.fragment.yml\nservices: {}\n",
        "x-root: &root\n  include: compose.fragment.yml\n<<: *root\nservices: {}\n",
        "x-include-key: &include-key include\n*include-key: compose.fragment.yml\nservices: {}\n",
        '"\\u0069nclude": compose.fragment.yml\nservices: {}\n',
        '{"incl\\x75de": compose.fragment.yml, services: {}}\n',
        '? "\\U00000069nclude"\n: compose.fragment.yml\nservices: {}\n',
        'x-include-key: &include-key "\\u0069nclude"\n*include-key: compose.fragment.yml\nservices: {}\n',
        '"in\\<LF>  clude": compose.fragment.yml\nservices: {}\n'.replace("<LF>", "\n"),
        '"in\\<CRLF>  clude": compose.fragment.yml\nservices: {}\n'.replace("<CRLF>", "\r\n"),
        '{"in\\<LF>  clude": compose.fragment.yml, services: {}}\n'.replace("<LF>", "\n"),
        '{"in\\<CRLF>  clude": compose.fragment.yml, services: {}}\n'.replace("<CRLF>", "\r\n"),
        '? "in\\<LF>  clude"\n: compose.fragment.yml\nservices: {}\n'.replace("<LF>", "\n"),
        '? "in\\<CRLF>  clude"\n: compose.fragment.yml\nservices: {}\n'.replace("<CRLF>", "\r\n"),
        'x-include-key: &include-key "in\\<LF>  clude"\n*include-key: compose.fragment.yml\nservices: {}\n'.replace(
            "<LF>", "\n"
        ),
        'x-include-key: &include-key "in\\<CRLF>  clude"\n*include-key: compose.fragment.yml\nservices: {}\n'.replace(
            "<CRLF>", "\r\n"
        ),
        "{? include: compose.fragment.yml, services: {}}\n",
        '{? "\\u0069nclude": compose.fragment.yml, services: {}}\n',
        "--- {include: compose.fragment.yml, services: {}}\n",
        '--- {? "in\\<CRLF>  clude": compose.fragment.yml, services: {}}\n'.replace("<CRLF>", "\r\n"),
        "{? &include-key include: compose.fragment.yml, services: {}}\n",
        "{x-key: &include-key include, ? *include-key: compose.fragment.yml, services: {}}\n",
    ],
    ids=(
        "uniformly-indented-include",
        "flow-mapping-include",
        "explicit-key-include",
        "merge-key",
        "alias",
        "unicode-escape-block-key",
        "hex-escape-flow-key",
        "long-unicode-explicit-key",
        "escaped-anchored-alias-key",
        "continued-block-key-lf",
        "continued-block-key-crlf",
        "continued-flow-key-lf",
        "continued-flow-key-crlf",
        "continued-explicit-key-lf",
        "continued-explicit-key-crlf",
        "continued-alias-key-lf",
        "continued-alias-key-crlf",
        "explicit-flow-literal-key",
        "explicit-flow-decoded-key",
        "document-marker-flow-key",
        "document-marker-explicit-continued-key-crlf",
        "explicit-flow-anchored-key",
        "explicit-flow-alias-key",
    ),
)
def test_preflight_rejects_unsnapshotted_yaml_composition_before_render(
    tmp_path: Path,
    source_text: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "compose.yml"
    source.write_text(source_text, encoding="utf-8")
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    runtime_log = tmp_path / "runtime.log"
    sentinel = "unsnapshotted-include-secret-41d7"

    result = _run_preflight(
        bin_dir,
        _make_secrets(tmp_path),
        compose_args=("up", "-d"),
        endpoint_env={
            "COMPOSE_FILE": str(source),
            "FAKE_RUNTIME_LOG": str(runtime_log),
            "UNSNAPSHOTTED_SENTINEL": sentinel,
        },
    )

    assert result.returncode == 1
    assert "provenance" in result.stderr.lower()
    assert sentinel not in result.stdout + result.stderr
    operations = runtime_log.read_text().splitlines() if runtime_log.exists() else []
    assert "source-config" not in operations
    assert not any(operation.startswith("action:") for operation in operations)
    assert not list(project.glob(".nohiki-compose-*"))


@pytest.mark.parametrize(
    "source_text",
    [
        'services: {safe: {environment: {"\\u0069nclude": safe}}}\n',
        'services: {safe: {environment: {SAFE: "incl\\x75de"}}}\n',
        'x-value: "\\U00000069nclude"\nservices: {}\n',
        'services: {safe: {environment: {SAFE: "in\\<LF>  clude"}}}\n'.replace("<LF>", "\n"),
        'x-value: "in\\<CRLF>  clude"\nservices: {}\n'.replace("<CRLF>", "\r\n"),
    ],
    ids=(
        "nested-environment-key",
        "nested-environment-value",
        "extension-value",
        "continued-nested-value-lf",
        "continued-extension-value-crlf",
    ),
)
def test_source_provenance_rejects_exact_decoded_include_token_anywhere(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "exact-include-token.yml"
    source.write_text(source_text, encoding="utf-8")

    result = _sh(
        [
            sys.executable,
            str(_PREFLIGHT.with_name("validate-llm-endpoints.py")),
            "--validate-sources",
            str(source),
        ],
        {},
    )

    assert result.returncode == 1
    assert "provenance" in result.stderr.lower()
    assert result.stdout == ""


@pytest.mark.parametrize(
    "safe_candidate",
    [
        "included",
        "include_path",
        "https://example.test/include",
        "word included word",
        r"\u0069ncluded",
        "in\\<LF>  cluded".replace("<LF>", "\n"),
        "include\\<CRLF>  _path".replace("<CRLF>", "\r\n"),
    ],
    ids=(
        "included",
        "include-path",
        "url",
        "words",
        "decoded-included",
        "continued-included-lf",
        "continued-include-path-crlf",
    ),
)
def test_source_provenance_allows_nonexact_include_candidates(
    tmp_path: Path,
    safe_candidate: str,
) -> None:
    source = tmp_path / "safe-include-candidates.yml"
    source.write_text(
        "services:\n"
        "  safe:\n"
        "    image: example.invalid/safe:latest\n"
        "    environment:\n"
        f'      "{safe_candidate}": "{safe_candidate}"\n'
        f'x-safe-value: "{safe_candidate}"\n',
        encoding="utf-8",
    )

    result = _sh(
        [
            sys.executable,
            str(_PREFLIGHT.with_name("validate-llm-endpoints.py")),
            "--validate-sources",
            str(source),
        ],
        {},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_preflight_rejects_top_level_include_before_render_or_action(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "compose.yml"
    source.write_text(
        "include:\n  - compose.fragment.yml\n"
        "x-llm-provider-endpoints:\n"
        '  NOHIKI_LLM_OPENAI_BASE_URL: "${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}"\n'
        "services: {}\n",
        encoding="utf-8",
    )
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    runtime_log = tmp_path / "runtime.log"

    result = _run_preflight(
        bin_dir,
        _make_secrets(tmp_path),
        compose_args=("up", "-d"),
        endpoint_env={
            "COMPOSE_FILE": str(source),
            "FAKE_RUNTIME_LOG": str(runtime_log),
        },
    )

    assert result.returncode == 1
    assert "Compose include is not allowed" in result.stderr
    operations = runtime_log.read_text().splitlines() if runtime_log.exists() else []
    assert "source-config" not in operations
    assert not any(operation.startswith("action:") for operation in operations)
    assert not list(project.glob(".nohiki-compose-*"))


def test_preflight_action_round_trips_literal_dollars_through_real_compose(
    tmp_path: Path,
) -> None:
    runtime = _canonical_compose_runtime()
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    openai_binding = "${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}"
    endpoint = "https://models.example.test/$role/${password_file}/$category/$(command)/v1"
    source = tmp_path / "dollar-source-compose.yml"
    source.write_text(
        yaml.safe_dump(
            {
                "x-llm-provider-endpoints": {
                    "NOHIKI_LLM_OPENAI_BASE_URL": openai_binding,
                    "NOHIKI_LLM_ANTHROPIC_BASE_URL": "${NOHIKI_LLM_ANTHROPIC_BASE_URL:-}",
                },
                "services": {
                    "endpoints": {
                        "image": "example.invalid/endpoints:latest",
                        "environment": {
                            "TEST_LLM__PROVIDER__MODELS__0__MODEL": "openai:test-openai",
                            "TEST_LLM__PROVIDER__MODELS__0__BASE_URL": openai_binding,
                            "LITERAL_ROLE": "$$role",
                            "LITERAL_PASSWORD_FILE": "$${password_file}",
                            "LITERAL_CATEGORY": "$$category",
                            "LITERAL_COMMAND": "$$(command)",
                        },
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    first_render = _compose_config(
        runtime,
        source,
        {
            "NOHIKI_LLM_OPENAI_BASE_URL": endpoint,
            "role": "first-parse-corruption",
            "password_file": "first-parse-corruption",
            "category": "first-parse-corruption",
        },
    )
    rendered = tmp_path / "normal-first-render.yml"
    rendered.write_text(first_render, encoding="utf-8")
    expected = yaml.safe_load(
        _compose_config(
            runtime,
            rendered,
            {},
            project_directory=tmp_path,
            escape_dollars=True,
        )
    )
    environment = expected["services"]["endpoints"]["environment"]
    assert environment["TEST_LLM__PROVIDER__MODELS__0__BASE_URL"] == endpoint
    assert environment["LITERAL_ROLE"] == "$role"
    assert environment["LITERAL_PASSWORD_FILE"] == "${password_file}"
    assert environment["LITERAL_CATEGORY"] == "$category"
    assert environment["LITERAL_COMMAND"] == "$(command)"

    snapshot = tmp_path / "decoded-action-compose.yml"
    runtime_log = tmp_path / "runtime.log"
    result = _run_preflight(
        bin_dir,
        _make_secrets(tmp_path),
        env_text=(
            f"NOHIKI_LLM_OPENAI_BASE_URL='{endpoint}'\n"
            "role=second-parse-corruption\n"
            "password_file=second-parse-corruption\n"
            "category=second-parse-corruption\n"
        ),
        compose_args=("up", "-d"),
        endpoint_env={
            "COMPOSE_FILE": str(source),
            "FAKE_RENDERED_CONFIG": str(rendered),
            "FAKE_RUNTIME_LOG": str(runtime_log),
            "FAKE_ACTION_CONFIG_SNAPSHOT": str(snapshot),
            "FAKE_ACTION_DECODE_RUNTIME": runtime,
            "FAKE_ACTION_PROJECT_DIRECTORY": str(source.parent),
            "role": "second-parse-corruption",
            "password_file": "second-parse-corruption",
            "category": "second-parse-corruption",
        },
    )

    assert result.returncode == 0, result.stderr
    action = next(line for line in runtime_log.read_text().splitlines() if line.startswith("action:"))
    action_path = Path(action.split(":", 2)[1])
    decoded = yaml.safe_load(snapshot.read_text(encoding="utf-8"))
    assert decoded == expected
    assert decoded["services"]["endpoints"]["environment"]["TEST_LLM__PROVIDER__MODELS__0__BASE_URL"] == endpoint
    assert action_path.name.startswith(".nohiki-compose-action.")


@pytest.mark.usefixtures("_serialized_compose_preflight")
def test_preflight_action_uses_the_validated_render_once_without_source_rerender(
    tmp_path: Path,
) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    runtime = _canonical_compose_runtime()
    compose_file = _hermetic_compose_project(
        tmp_path,
        "NOHIKI_LLM_OPENAI_BASE_URL=https://models.example.test/v1\n",
    )
    python_proxy = _mode_recording_python(bin_dir)
    log = tmp_path / "runtime.log"
    snapshot = tmp_path / "action-compose.yml"
    mode = tmp_path / "action-compose.mode"
    rendered_mode = tmp_path / "rendered-compose.mode"
    before = _compose_temporary_files()
    result = _run_preflight(
        bin_dir,
        _make_secrets(tmp_path),
        compose_args=("up", "-d"),
        endpoint_env={
            "FAKE_RUNTIME_LOG": str(log),
            "FAKE_ACTION_CONFIG_SNAPSHOT": str(snapshot),
            "FAKE_ACTION_CONFIG_MODE": str(mode),
            "FAKE_ACTION_DECODE_RUNTIME": runtime,
            "FAKE_ACTION_PROJECT_DIRECTORY": str(compose_file.parent),
            "COMPOSE_FILE": str(compose_file),
            "FAKE_RENDERED_CONFIG_MODE": str(rendered_mode),
            "PYTHON": str(python_proxy),
            "REAL_PYTHON": sys.executable,
        },
    )

    assert result.returncode == 0, result.stderr
    operations = log.read_text(encoding="utf-8").splitlines()
    assert operations[0] == "source-config"
    assert len(operations) == 2
    action, rendered_path, command = operations[1].split(":", 2)
    assert action == "action"
    assert command == "up"
    assert Path(rendered_path).name.startswith(".nohiki-compose-action.")
    assert Path(rendered_path).name != _COMPOSE.name
    decoded = yaml.safe_load(snapshot.read_text(encoding="utf-8"))
    assert decoded["x-llm-provider-endpoints"] == {
        "NOHIKI_LLM_ANTHROPIC_BASE_URL": "",
        "NOHIKI_LLM_OPENAI_BASE_URL": "https://models.example.test/v1",
    }
    assert rendered_mode.read_text(encoding="utf-8").strip() == "600"
    assert mode.read_text(encoding="utf-8").strip() == "600"
    assert _compose_temporary_files() == before


@pytest.mark.usefixtures("_serialized_compose_preflight")
def test_preflight_cleans_render_and_diagnostics_after_action_failure(
    tmp_path: Path,
) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    python_proxy = _mode_recording_python(bin_dir)
    rendered_mode = tmp_path / "rendered-compose.mode"
    action_mode = tmp_path / "action-compose.mode"
    before = _compose_temporary_files()
    result = _run_preflight(
        bin_dir,
        _make_secrets(tmp_path),
        compose_args=("up", "-d"),
        endpoint_env={
            "FAKE_ACTION_EXIT": "23",
            "FAKE_ACTION_CONFIG_MODE": str(action_mode),
            "FAKE_RENDERED_CONFIG_MODE": str(rendered_mode),
            "PYTHON": str(python_proxy),
            "REAL_PYTHON": sys.executable,
        },
    )

    assert result.returncode == 23
    assert rendered_mode.read_text(encoding="utf-8").strip() == "600"
    assert action_mode.read_text(encoding="utf-8").strip() == "600"
    assert _compose_temporary_files() == before


def _assert_action_rejected_before_render(
    tmp_path: Path,
    compose_args: tuple[str, ...],
    *,
    endpoint_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    runtime_log = tmp_path / "runtime.log"
    result = _run_preflight(
        bin_dir,
        _make_secrets(tmp_path),
        compose_args=compose_args,
        endpoint_env={"FAKE_RUNTIME_LOG": str(runtime_log), **(endpoint_env or {})},
    )

    assert result.returncode == 1
    operations = runtime_log.read_text().splitlines() if runtime_log.exists() else []
    assert "source-config" not in operations
    assert not any(operation.startswith("action:") for operation in operations)
    assert _SENTINEL not in result.stdout + result.stderr
    return result


def test_preflight_rejects_config_before_resolving_or_printing_env_file_credentials(
    tmp_path: Path,
) -> None:
    credential = "config-env-file-credential-4d91"
    secrets = _make_secrets(tmp_path)
    (secrets / "s3" / "rustfs-root.env").write_text(
        f"RUSTFS_ROOT_PASSWORD={credential}\n",
        encoding="utf-8",
    )
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    runtime_log = tmp_path / "runtime.log"

    result = _run_preflight(
        bin_dir,
        secrets,
        compose_args=("config",),
        endpoint_env={"FAKE_RUNTIME_LOG": str(runtime_log)},
    )

    assert result.returncode == 1
    assert credential not in result.stdout + result.stderr
    assert _SENTINEL not in result.stdout + result.stderr
    operations = runtime_log.read_text().splitlines() if runtime_log.exists() else []
    assert operations == []


@pytest.mark.parametrize(
    "compose_args",
    [
        ("run", "--rm", "-e", "NOHIKI_LLM_OPENAI_BASE_URL=protected-1", "service"),
        (
            "run",
            "--rm",
            "--env",
            "NOHIKI_LLM_ANTHROPIC_BASE_URL=protected-2",
            "service",
        ),
        ("run", "--rm", "-eTEST_LLM__PROVIDER__API_KEY=protected-3", "service"),
        (
            "run",
            "--rm",
            "--env=TEST_LLM__PROVIDER__MODELS__0__MODEL=protected-4",
            "service",
        ),
        ("run", "--rm", "--env-file", "protected.env", "service"),
        ("run", "--rm", "--env-file=protected.env", "service"),
        ("run", "--rm", "--env-from-file", "protected.env", "service"),
        ("run", "--rm", "--env-from-file=protected.env", "service"),
    ],
    ids=(
        "short-env-separated",
        "long-env-separated",
        "short-env-attached",
        "long-env-equals",
        "env-file-separated",
        "env-file-equals",
        "env-from-file-separated",
        "env-from-file-equals",
    ),
)
def test_preflight_rejects_protected_run_environment_overrides_before_render(
    tmp_path: Path,
    compose_args: tuple[str, ...],
) -> None:
    sentinel = "protected-run-override-secret-c572"
    (tmp_path / "protected.env").write_text(
        f"NOHIKI_LLM_OPENAI_BASE_URL={sentinel}\n",
        encoding="utf-8",
    )

    result = _assert_action_rejected_before_render(tmp_path, compose_args)

    assert "preflight:" in result.stderr.lower()
    assert sentinel not in result.stdout + result.stderr
    assert not any(
        value in result.stdout + result.stderr for value in ("protected-1", "protected-2", "protected-3", "protected-4")
    )


@pytest.mark.parametrize(
    "compose_args",
    [
        ("up", "--no-recreate"),
        ("start", "--no-recreate"),
        ("restart", "--no-recreate"),
        ("up", "--no-deps"),
        ("run", "--rm", "--no-deps", "service"),
        ("start", "--no-deps", "service"),
    ],
    ids=(
        "up-no-recreate",
        "start-no-recreate",
        "restart-no-recreate",
        "up-no-deps",
        "run-no-deps",
        "start-no-deps",
    ),
)
def test_preflight_rejects_stale_container_reuse_and_dependency_bypasses_before_render(
    tmp_path: Path,
    compose_args: tuple[str, ...],
) -> None:
    result = _assert_action_rejected_before_render(tmp_path, compose_args)

    assert "not allowed" in result.stderr.lower()


def test_preflight_allows_the_production_refresh_reason_run_override(
    tmp_path: Path,
) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    runtime_log = tmp_path / "runtime.log"

    result = _run_preflight(
        bin_dir,
        _make_secrets(tmp_path),
        compose_args=(
            "run",
            "--rm",
            "-e",
            "REFRESH_REASON=manual trigger",
            "nohiki-job-snapshot-refresh",
        ),
        endpoint_env={"FAKE_RUNTIME_LOG": str(runtime_log)},
    )

    assert result.returncode == 0, result.stderr
    operations = runtime_log.read_text(encoding="utf-8").splitlines()
    assert operations[0] == "source-config"
    assert [operation.rsplit(":", 1)[-1] for operation in operations[1:]] == [
        "up",
        "run",
    ]
    assert _SENTINEL not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "compose_args",
    [
        ("-f", "unvalidated.yml", "up"),
        ("--file", "unvalidated.yml", "up"),
        ("--file=unvalidated.yml", "up"),
        ("up", "-f", "unvalidated.yml"),
        ("up", "--file", "unvalidated.yml"),
        ("up", "--file=unvalidated.yml"),
        ("--env-file", "unvalidated.env", "up"),
        ("--env-file=unvalidated.env", "up"),
        ("up", "--env-file", "unvalidated.env"),
        ("up", "--env-file=unvalidated.env"),
        ("--project-directory", "unvalidated-project", "up"),
        ("--project-directory=unvalidated-project", "up"),
        ("up", "--project-directory", "unvalidated-project"),
        ("up", "--project-directory=unvalidated-project"),
    ],
    ids=(
        "short-before-action",
        "long-before-action",
        "long-equals-before-action",
        "short-after-action",
        "long-after-action",
        "long-equals-after-action",
        "env-file-before-action",
        "env-file-equals-before-action",
        "env-file-after-action",
        "env-file-equals-after-action",
        "project-directory-before-action",
        "project-directory-equals-before-action",
        "project-directory-after-action",
        "project-directory-equals-after-action",
    ),
)
def test_preflight_rejects_action_compose_file_options(tmp_path: Path, compose_args: tuple[str, ...]) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    runtime_log = tmp_path / "runtime.log"

    result = _run_preflight(
        bin_dir,
        _make_secrets(tmp_path),
        compose_args=compose_args,
        endpoint_env={"FAKE_RUNTIME_LOG": str(runtime_log)},
    )

    assert result.returncode == 1
    assert "preflight:" in result.stderr.lower()
    operations = runtime_log.read_text(encoding="utf-8").splitlines() if runtime_log.exists() else []
    assert not any(operation.startswith("action:") for operation in operations)


@pytest.mark.usefixtures("_serialized_compose_preflight")
@pytest.mark.parametrize(
    ("sent_signal", "expected_status"),
    [(signal.SIGHUP, 129), (signal.SIGINT, 130), (signal.SIGTERM, 143)],
    ids=("hup", "int", "term"),
)
def test_preflight_forwards_action_signals_reaps_child_and_cleans_temporary_files(
    tmp_path: Path, sent_signal: signal.Signals, expected_status: int
) -> None:
    bin_dir = _bin_dir(tmp_path)
    python_proxy = _mode_recording_python(bin_dir)
    rendered_mode = tmp_path / "rendered-compose.mode"
    action_mode = tmp_path / "action-compose.mode"
    _fake_runtime(bin_dir)
    secrets = _make_secrets(tmp_path)
    env_file = secrets.parent / ".env"
    env_file.write_text(
        "NOHIKI_LLM_OPENAI_BASE_URL=https://models.example.test/v1\n",
        encoding="utf-8",
    )
    rendered = _rendered_compose(_dotenv_values(env_file.read_text()), tmp_path)
    ready_fifo = tmp_path / "action-ready.fifo"
    os.mkfifo(ready_fifo)
    pid_file = tmp_path / "action.pid"
    signal_log = tmp_path / "action.signal"
    before = _compose_temporary_files()
    process = subprocess.Popen(
        ["sh", str(_PREFLIGHT), "up", "-d"],
        cwd=_REPO,
        env={
            **os.environ,
            "PATH": _path_with(bin_dir),
            "SECRETS_DIR": str(secrets),
            "CONTAINER_RUNTIME": "fakeruntime",
            "FAKE_RENDERED_CONFIG": str(rendered),
            "FAKE_ACTION_READY_FIFO": str(ready_fifo),
            "FAKE_ACTION_READY": str(tmp_path / "action.ready"),
            "FAKE_ACTION_CONFIG_MODE": str(action_mode),
            "FAKE_RENDERED_CONFIG_MODE": str(rendered_mode),
            "PYTHON": str(python_proxy),
            "REAL_PYTHON": sys.executable,
            "FAKE_ACTION_PID": str(pid_file),
            "FAKE_ACTION_SIGNAL_LOG": str(signal_log),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    with ready_fifo.open(encoding="utf-8") as ready:
        assert ready.readline().strip() == "ready"

    child_pid = int(pid_file.read_text(encoding="utf-8"))
    process.send_signal(sent_signal)
    try:
        stdout, stderr = process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        for temporary in _compose_temporary_files() - before:
            temporary.unlink(missing_ok=True)
        pytest.fail("preflight did not terminate after receiving a signal")

    assert process.returncode == expected_status, stdout + stderr
    assert signal_log.read_text(encoding="utf-8").strip() == sent_signal.name.removeprefix("SIG")
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    assert rendered_mode.read_text(encoding="utf-8").strip() == "600"
    assert action_mode.read_text(encoding="utf-8").strip() == "600"
    assert _compose_temporary_files() == before


@pytest.mark.usefixtures("_serialized_compose_preflight")
@pytest.mark.parametrize(
    ("sent_signal", "expected_status"),
    [(signal.SIGHUP, 129), (signal.SIGINT, 130), (signal.SIGTERM, 143)],
    ids=("pending-hup", "pending-int", "pending-term"),
)
def test_preflight_forwards_signal_between_action_spawn_and_pid_publication(
    tmp_path: Path, sent_signal: signal.Signals, expected_status: int
) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    python_proxy = _mode_recording_python(bin_dir)
    rendered_mode = tmp_path / "rendered-compose.mode"
    action_mode = tmp_path / "action-compose.mode"
    secrets = _make_secrets(tmp_path)
    env_file = secrets.parent / ".env"
    env_file.write_text(
        "NOHIKI_LLM_OPENAI_BASE_URL=https://models.example.test/v1\n",
        encoding="utf-8",
    )
    rendered = _rendered_compose(_dotenv_values(env_file.read_text()), tmp_path)
    instrumented = tmp_path / "preflight.sh"
    validator = tmp_path / "validate-llm-endpoints.py"
    validator.write_bytes(_PREFLIGHT.with_name("validate-llm-endpoints.py").read_bytes())
    wrapper_text = _PREFLIGHT.read_text(encoding="utf-8")
    pending_traps = (
        ("trap 'pending_signal=HUP; pending_status=129' HUP", "HUP", 129),
        ("trap 'pending_signal=INT; pending_status=130' INT", "INT", 130),
        ("trap 'pending_signal=TERM; pending_status=143' TERM", "TERM", 143),
    )
    for pending_trap, signal_name, status in pending_traps:
        assert pending_trap in wrapper_text
        wrapper_text = wrapper_text.replace(
            pending_trap,
            "trap 'pending_signal="
            f"{signal_name}; pending_status={status}; "
            'printf "handled\\n" > "${FAKE_SIGNAL_HANDLED_FIFO}"\''
            f" {signal_name}",
            1,
        )
    spawn_boundary = "fi\naction_pid=$!"
    assert spawn_boundary in wrapper_text
    wrapper_text = wrapper_text.replace(
        spawn_boundary,
        'fi\nprintf \'spawned\\n\' > "${FAKE_ACTION_SPAWNED_FIFO}"\nkill -STOP "$$"\naction_pid=$!',
        1,
    )
    instrumented.write_text(wrapper_text, encoding="utf-8")

    spawned_fifo = tmp_path / "action-spawned.fifo"
    ready_fifo = tmp_path / "action-ready.fifo"
    handled_fifo = tmp_path / "signal-handled.fifo"
    for fifo in (spawned_fifo, ready_fifo, handled_fifo):
        os.mkfifo(fifo)
    pid_file = tmp_path / "action.pid"
    signal_log = tmp_path / "action.signal"
    before = _compose_temporary_files()
    process = subprocess.Popen(
        ["sh", str(instrumented), "up", "-d"],
        cwd=_REPO,
        env={
            **os.environ,
            "PATH": _path_with(bin_dir),
            "COMPOSE_FILE": str(_COMPOSE),
            "SECRETS_DIR": str(secrets),
            "CONTAINER_RUNTIME": "fakeruntime",
            "FAKE_RENDERED_CONFIG": str(rendered),
            "FAKE_ACTION_SPAWNED_FIFO": str(spawned_fifo),
            "FAKE_ACTION_READY_FIFO": str(ready_fifo),
            "FAKE_ACTION_READY": str(tmp_path / "action.ready"),
            "FAKE_ACTION_CONFIG_MODE": str(action_mode),
            "FAKE_RENDERED_CONFIG_MODE": str(rendered_mode),
            "PYTHON": str(python_proxy),
            "REAL_PYTHON": sys.executable,
            "FAKE_ACTION_PID": str(pid_file),
            "FAKE_ACTION_SIGNAL_LOG": str(signal_log),
            "FAKE_SIGNAL_HANDLED_FIFO": str(handled_fifo),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    with spawned_fifo.open(encoding="utf-8") as spawned:
        assert spawned.readline().strip() == "spawned"
    with ready_fifo.open(encoding="utf-8") as ready:
        assert ready.readline().strip() == "ready"
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    process.send_signal(sent_signal)
    process.send_signal(signal.SIGCONT)
    with handled_fifo.open(encoding="utf-8") as handled:
        assert handled.readline().strip() == "handled"
    process.wait(timeout=3)

    forwarded = signal_log.exists() and signal_log.read_text(encoding="utf-8").strip() == sent_signal.name.removeprefix(
        "SIG"
    )
    try:
        os.kill(child_pid, 0)
    except ProcessLookupError:
        child_reaped = True
    else:
        child_reaped = False
        os.killpg(process.pid, signal.SIGKILL)
    stdout, stderr = process.communicate()

    assert process.returncode == expected_status, stdout + stderr
    assert forwarded
    assert child_reaped
    assert rendered_mode.read_text(encoding="utf-8").strip() == "600"
    assert action_mode.read_text(encoding="utf-8").strip() == "600"
    assert _compose_temporary_files() == before


def test_all_supported_just_compose_commands_use_the_validation_gate() -> None:
    justfile = _JUSTFILE.read_text(encoding="utf-8")
    gate = "CONTAINER_RUNTIME={{docker}} sh infra/compose/scripts/preflight.sh"
    expected_commands = (
        gate,
        f"{gate} up -d nohiki-infra-postgres nohiki-infra-valkey nohiki-cp-kafka nohiki-cp-kafka-init",
        f"{gate} down",
        f"{gate} up -d",
        f"{gate} run --rm nohiki-cp-kafka-connect /kafka/scripts/register-connectors.sh migrate-legacy",
        f"{gate} build nohiki-job-snapshot-refresh",
        f'{gate} run --rm -e REFRESH_REASON="{{{{reason}}}}" nohiki-job-snapshot-refresh',
        f"{gate} down",
        f"{gate} logs -f {{{{service}}}}",
    )
    actual_commands = tuple(line.strip() for line in justfile.splitlines() if line.strip().startswith(gate))

    assert "{{compose}}" not in justfile
    assert sorted(actual_commands) == sorted(expected_commands)


@cache
def _tracked_repo_text_files() -> tuple[tuple[Path, str], ...]:
    return tracked_text_files(_REPO)


@cache
def _direct_compose_action_patterns() -> tuple[re.Pattern[str], ...]:
    actions = r"build|config|down|exec|logs|ps|pull|restart|run|start|stop|up"
    return (
        re.compile(
            rf"\b(?:docker|podman)[ \t]+compose\b"
            rf"(?:[^\n]*\\\r?\n)*[^\n]*\b(?:{actions})\b"
        ),
        re.compile(
            rf"\b(?:docker|podman)[ \t]+compose\b[^\n]*"
            rf"(?:['\"]\s*\n\s*(?:[rubfRUBF]{{0,2}})?['\"][^\n]*)+"
            rf"\b(?:{actions})\b"
        ),
        re.compile(
            rf"(?P<quote>'''|\"\"\")"
            rf"(?:(?!(?P=quote))[\s\S]){{0,2000}}?"
            rf"\b(?:docker|podman)[ \t]+compose\b"
            rf"(?:(?!(?P=quote))[\s\S]){{0,2000}}?\b(?:{actions})\b"
        ),
        re.compile(
            rf"\(\s*['\"](?:docker|podman)['\"]\s*,\s*['\"]compose['\"]"
            rf"(?:(?!\n[ \t]*\n)[\s\S]){{0,2000}}?['\"](?:{actions})['\"]"
        ),
        re.compile(
            rf"\[\s*['\"](?:docker|podman)['\"]\s*,\s*['\"]compose['\"]"
            rf"[^]]{{0,2000}}?['\"](?:{actions})['\"][^]]*]"
        ),
    )


def _direct_compose_bypasses(relative: Path, text: str) -> list[str]:
    bypasses: list[str] = []
    for pattern in _direct_compose_action_patterns():
        for match in pattern.finditer(text):
            line_number = text.count("\n", 0, match.start()) + 1
            command = " ".join(match.group().split())
            bypasses.append(f"{relative.as_posix()}:{line_number}: {command}")
    return bypasses


def test_production_wrapper_callsites_use_the_accepted_action_grammar() -> None:
    call_pattern = re.compile(
        r"infra/compose/scripts/preflight\.sh(?P<args>[^\n`]*?)\s*(?:$|['\"])",
        re.MULTILINE,
    )
    accepted_actions = {"up", "run", "build", "down", "logs"}
    rejected_options = {"--no-recreate", "--no-deps", "--env-file", "--env-from-file"}
    invalid: list[str] = []

    for relative, text in _tracked_repo_text_files():
        if relative.parts[:3] == ("scripts", "ci", "tests"):
            continue
        for match in call_pattern.finditer(text):
            arguments = match.group("args").strip().removesuffix(".")
            tokens = arguments.split()
            if not tokens:
                continue
            action = tokens[0]
            if action not in accepted_actions or rejected_options.intersection(tokens):
                invalid.append(f"{relative.as_posix()}: {arguments}")
                continue
            for index, token in enumerate(tokens):
                if token in {"-e", "--env"} and (
                    index + 1 == len(tokens) or not tokens[index + 1].startswith("REFRESH_REASON=")
                ):
                    invalid.append(f"{relative.as_posix()}: {arguments}")
                    break

    assert invalid == [], "wrapper calls outside accepted grammar:\n" + "\n".join(invalid)


def test_repo_runtime_strings_and_docs_use_the_main_compose_validation_gate() -> None:
    bypasses: list[str] = []
    for relative, text in _tracked_repo_text_files():
        bypasses.extend(_direct_compose_bypasses(relative, text))

    assert bypasses == [], "direct main-stack Compose bypasses:\n" + "\n".join(bypasses)
    documentation = _ROOT_README.read_text() + _COMPOSE_README.read_text()
    assert "just compose-up" in documentation
    assert "infra/compose/scripts/preflight.sh" in documentation


def test_tracked_repo_string_scan_ignores_untracked_files_and_detects_tracked_bypasses(tmp_path: Path) -> None:
    docker = "docker"
    podman = "podman"
    tracked = tmp_path / "tracked.md"
    tracked.write_text(f"{docker} compose up\n", encoding="utf-8")
    (tmp_path / "untracked.md").write_text(f"{podman} compose down\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", tracked.name], cwd=tmp_path, check=True)

    scanned = tracked_text_files(tmp_path)

    assert tuple(relative for relative, _ in scanned) == (Path(tracked.name),)
    assert _direct_compose_bypasses(*scanned[0]) == [f"tracked.md:1: {docker} compose up"]


@pytest.mark.parametrize(
    "recipe",
    [
        "compose-preflight",
        "infra-up",
        "infra-down",
        "compose-up",
        "compose-down",
        "connect-migrate-legacy",
        "snapshot-refresh",
        "logs bff",
    ],
)
def test_just_dry_run_routes_compose_recipes_through_preflight(recipe: str) -> None:
    just = shutil.which("just")
    if just is None:
        pytest.skip("just is not installed")
    result = subprocess.run(
        [just, "--dry-run", *recipe.split()],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert "infra/compose/scripts/preflight.sh" in output
    assert re.search(r"\b(?:docker|podman)\s+compose\b", output) is None


def test_infra_and_k8s_nix_shells_include_the_pinned_validator_runtime() -> None:
    flake = _FLAKE.read_text(encoding="utf-8")

    assert "python = pkgs.python314;" in flake
    for shell in ("infra", "k8s"):
        block = flake.split(f"devShells.{shell} = pkgs.mkShell", 1)[1].split("};", 1)[0]
        assert "++ [ python ]" in block
    ci_block = flake.split("devShells.ci = pkgs.mkShell", 1)[1].split("};", 1)[0]
    assert "pkgs.podman-compose" in ci_block


def test_preflight_passes_with_runtime_and_full_secret_contract(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    result = _run_preflight(bin_dir, _make_secrets(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "preflight: OK" in result.stdout


def test_preflight_fails_when_a_required_secret_directory_is_missing(
    tmp_path: Path,
) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    result = _run_preflight(bin_dir, _make_secrets(tmp_path, omit_dir="qdrant"))
    assert result.returncode == 1
    assert "qdrant" in result.stderr
    assert "README" in result.stderr


def test_preflight_fails_when_a_required_secret_file_is_missing(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    result = _run_preflight(bin_dir, _make_secrets(tmp_path, omit_file="database/dsn"))
    assert result.returncode == 1
    assert "database/dsn" in result.stderr


def test_preflight_fails_when_container_runtime_is_absent(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)  # no fake runtime installed
    result = _run_preflight(bin_dir, _make_secrets(tmp_path), runtime="nohiki-absent-runtime")
    assert result.returncode == 1
    assert "runtime" in result.stderr.lower()


def test_preflight_fails_when_compose_plugin_is_absent(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir, compose_ok=False)
    result = _run_preflight(bin_dir, _make_secrets(tmp_path))
    assert result.returncode == 1
    assert "compose" in result.stderr.lower()


@pytest.mark.usefixtures("_serialized_compose_preflight")
def test_preflight_redacts_renderer_errors_but_remains_actionable(
    tmp_path: Path,
) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    endpoint = "https://sensitive.models.example.test/v1"
    secret = "renderer-secret-58d4"
    opaque_values = {
        "MODEL_BASE_URL": "opaque-base-value-43c9",
        "MODEL_HEALTH_URL": "opaque-health-value-24df",
        "MODEL_TLS_CA_FILE": "opaque-ca-value-a812",
    }
    before = _compose_temporary_files()
    result = _run_preflight(
        bin_dir,
        _make_secrets(tmp_path),
        endpoint_env={
            "NOHIKI_LLM_OPENAI_BASE_URL": endpoint,
            "FAKE_COMPOSE_CONFIG_FAIL": "1",
            "FAKE_RENDER_ERROR": "invalid NOHIKI_LLM_API_KEY="
            f"{secret} at {endpoint}; " + "; ".join(f"{key}={value}" for key, value in opaque_values.items()),
        },
    )

    assert result.returncode == 1
    assert "Compose configuration could not be rendered" in result.stderr
    assert "renderer diagnostics were suppressed" in result.stderr
    assert endpoint not in result.stdout + result.stderr
    assert secret not in result.stdout + result.stderr
    assert not any(value in result.stdout + result.stderr for value in opaque_values.values())
    assert _compose_temporary_files() == before


@pytest.mark.usefixtures("_serialized_compose_preflight")
@pytest.mark.parametrize(
    ("renderer_error", "sentinel"),
    [
        ("invalid MODEL=renderer-model-equals-73a1", "renderer-model-equals-73a1"),
        (
            "invalid PROVIDER: renderer-provider-colon-f80b",
            "renderer-provider-colon-f80b",
        ),
        ("invalid URL renderer-url-whitespace-5d2c", "renderer-url-whitespace-5d2c"),
        ("invalid API_KEY=renderer-secret-equals-a911", "renderer-secret-equals-a911"),
        (
            "invalid UNKNOWN_LLM__SETTING=renderer-unknown-equals-18ce",
            "renderer-unknown-equals-18ce",
        ),
        (
            "invalid UNKNOWN_LLM__SETTING:\n  renderer-multiline-opaque-642f",
            "renderer-multiline-opaque-642f",
        ),
    ],
    ids=(
        "model-equals",
        "provider-colon",
        "url-whitespace",
        "secret-equals",
        "unknown-protected-equals",
        "unknown-protected-multiline",
    ),
)
def test_preflight_redacts_all_protected_renderer_error_value_forms(
    tmp_path: Path, renderer_error: str, sentinel: str
) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    before = _compose_temporary_files()

    result = _run_preflight(
        bin_dir,
        _make_secrets(tmp_path),
        endpoint_env={
            "FAKE_COMPOSE_CONFIG_FAIL": "1",
            "FAKE_RENDER_ERROR": renderer_error,
        },
    )

    assert result.returncode == 1
    assert "Compose configuration could not be rendered" in result.stderr
    assert sentinel not in result.stdout + result.stderr
    assert _compose_temporary_files() == before


def test_preflight_never_reads_secret_contents(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_runtime(bin_dir)
    result = _run_preflight(bin_dir, _make_secrets(tmp_path))
    assert _SENTINEL not in result.stdout
    assert _SENTINEL not in result.stderr

    # Preflight may read Compose sources to snapshot and reject include, but it
    # never parses secret or endpoint values itself. It delegates endpoint
    # validation to the stdlib-only validator.
    code = "\n".join(
        line for line in _PREFLIGHT.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")
    )
    readers = r"cat|head|tail|less|more|awk|sed|xxd|hexdump|base64|strings|od|grep|read"
    reader_lines = [
        line
        for line in code.splitlines()
        if re.search(
            rf"(?:^|[|&;(`]|\bthen\b|\bdo\b|\belse\b)\s*({readers})\b",
            line,
        )
    ]
    assert all("SECRETS_DIR" not in line for line in reader_lines)
    assert 'chmod 0600 "${rendered_config}"' in code
    assert '"${PYTHON}" "${VALIDATOR}"' in code
    assert "$(<" not in code


# rustfs-init.sh fails closed and classifies exists-vs-error.
def _fake_mc(bin_dir: Path) -> None:
    _make_exe(
        bin_dir / "mc",
        'cmd="$1 $2 $3"\n'
        'case "$cmd" in\n'
        '  "admin user add"*)\n'
        '    [ "${MC_USERADD_FAIL:-0}" = 1 ] && { echo "mc: <ERROR> add user: connection refused" >&2; exit 1; }\n'
        "    exit 0;;\n"
        '  "admin user info"*)\n'
        '    [ "${MC_USERINFO_FAIL:-0}" = 1 ] && exit 1\n'
        "    exit 0;;\n"
        '  "admin policy attach"*)\n'
        '    [ "${MC_ATTACH_FAIL:-0}" = 1 ] && { echo "mc: <ERROR> attach: boom" >&2; exit 1; }\n'
        '    [ "${MC_ATTACH_EXISTS:-0}" = 1 ] && { echo "mc: the policy change is already in effect" >&2; exit 1; }\n'
        "    exit 0;;\n"
        "esac\n"
        "exit 0\n",
    )


def _run_rustfs(bin_dir: Path, tmp_path: Path, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    policies = tmp_path / "policies"
    policies.mkdir(exist_ok=True)
    (policies / "bff-service.json").write_text("{}", encoding="utf-8")
    env = {
        "PATH": _path_with(bin_dir),
        "RUSTFS_ROOT_USER": "root",
        "RUSTFS_ROOT_PASSWORD": "rootpw",
        "POLICIES_DIR": str(policies),
        "SVC_BFF_ACCESS_KEY": "bffkey",
        "SVC_BFF_SECRET_KEY": "bffsecret",
        **extra_env,
    }
    return _sh(["sh", str(_RUSTFS_INIT)], env)


def test_rustfs_init_fails_closed_on_user_creation_error(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_mc(bin_dir)
    result = _run_rustfs(bin_dir, tmp_path, {"MC_USERADD_FAIL": "1", "MC_USERINFO_FAIL": "1"})
    assert result.returncode != 0, "a genuine user-creation failure must not be masked"


def test_rustfs_init_fails_closed_on_policy_attach_error(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_mc(bin_dir)
    result = _run_rustfs(bin_dir, tmp_path, {"MC_ATTACH_FAIL": "1"})
    assert result.returncode != 0, "a genuine policy-attach failure must not be masked"


def test_rustfs_init_treats_existing_user_as_success(tmp_path: Path) -> None:
    # user add fails but user info confirms the user exists, so it is not an error.
    bin_dir = _bin_dir(tmp_path)
    _fake_mc(bin_dir)
    result = _run_rustfs(bin_dir, tmp_path, {"MC_USERADD_FAIL": "1", "MC_USERINFO_FAIL": "0"})
    assert result.returncode == 0, result.stderr


def test_rustfs_init_treats_already_in_effect_policy_as_success(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_mc(bin_dir)
    result = _run_rustfs(bin_dir, tmp_path, {"MC_ATTACH_EXISTS": "1"})
    assert result.returncode == 0, result.stderr


def test_rustfs_init_does_not_mask_user_or_policy_commands() -> None:
    for line in _RUSTFS_INIT.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(("mc admin user add", "mc admin policy attach")):
            assert not stripped.endswith("|| true"), f"masked failure: {line!r}"


# kafka-init.sh exits non-zero on real failure; counts are truthful.
def _topics() -> list[str]:
    block = re.search(
        r'TOPICS="\n(?P<body>.*?)\n"',
        _KAFKA_INIT.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert block is not None
    return [t for t in block.group("body").splitlines() if t.strip()]


def _fake_kafka_topics(bin_dir: Path) -> None:
    _make_exe(
        bin_dir / "kafka-topics",
        "list=0; create=0; topic=\n"
        "while [ $# -gt 0 ]; do\n"
        '  case "$1" in\n'
        "    --list) list=1;;\n"
        "    --create) create=1;;\n"
        '    --topic) shift; topic="$1";;\n'
        "  esac\n"
        "  shift\n"
        "done\n"
        'if [ "$list" = 1 ]; then\n'
        '  [ -f "$KAFKA_STATE" ] && cat "$KAFKA_STATE"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$create" = 1 ]; then\n'
        '  if [ "$topic" = "${KAFKA_FAIL_TOPIC:-}" ]; then echo "err: $topic" >&2; exit 1; fi\n'
        '  printf \'%s\\n\' "$topic" >> "$KAFKA_STATE"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
    )


def _run_kafka_init(bin_dir: Path, state: Path, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _sh(
        ["bash", str(_KAFKA_INIT)],
        {"PATH": _path_with(bin_dir), "KAFKA_STATE": str(state), **extra_env},
    )


def _parse_counts(stdout: str) -> tuple[int, int, int]:
    m = re.search(r"created=(\d+) skipped=(\d+) total=(\d+)", stdout)
    assert m is not None, stdout
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def test_kafka_init_fails_closed_when_a_topic_cannot_be_created(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_kafka_topics(bin_dir)
    state = tmp_path / "topics.state"  # absent, so it starts empty
    doomed = _topics()[0]
    result = _run_kafka_init(bin_dir, state, {"KAFKA_FAIL_TOPIC": doomed})
    assert result.returncode != 0, "a real create failure must produce a non-zero exit"
    assert doomed in result.stderr


def test_kafka_init_reports_truthful_counts_when_all_topics_created(
    tmp_path: Path,
) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_kafka_topics(bin_dir)
    result = _run_kafka_init(bin_dir, tmp_path / "topics.state", {})
    assert result.returncode == 0, result.stderr
    created, skipped, total = _parse_counts(result.stdout)
    expected = len(_topics())
    assert (created, skipped, total) == (expected, 0, expected)


def test_kafka_init_counts_preexisting_topics_as_skipped(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)
    _fake_kafka_topics(bin_dir)
    state = tmp_path / "topics.state"
    preexisting = _topics()[:5]
    unmanaged = "unmanaged-" + "x" * (128 * 1024)
    state.write_text("\n".join([*preexisting, unmanaged]) + "\n", encoding="utf-8")
    result = _run_kafka_init(bin_dir, state, {})
    assert result.returncode == 0, result.stderr
    created, skipped, _total = _parse_counts(result.stdout)
    assert skipped == len(preexisting)
    assert created == len(_topics()) - len(preexisting)


# Connector destructive cleanup is explicit, not run at startup.
def _connect_bins(bin_dir: Path) -> None:
    _make_exe(
        bin_dir / "curl",
        "cat >/dev/null 2>&1 || true\n"
        'printf \'%s\\n\' "$*" >> "$CURL_LOG"\n'
        'case " $* " in\n'
        '  *" -X DELETE "*) echo "404"; exit 0;;\n'
        '  *" -X POST "*) exit 0;;\n'
        '  *" -X PUT "*) exit 0;;\n'
        "esac\n"
        'case " $* " in\n'
        '  *"/connectors/"*) exit 22;;\n'  # existence GET, report not-found
        "esac\n"
        "exit 0\n",
    )
    # slot-state SELECT returns empty; DROP statements succeed.
    _make_exe(bin_dir / "psql", 'printf \'%s\\n\' "$*" >> "$PSQL_LOG"\nexit 0\n')


def _run_register(bin_dir: Path, tmp_path: Path, args: list[str]) -> tuple[subprocess.CompletedProcess[str], str, str]:
    secrets = tmp_path / "secrets" / "database"
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / "dsn").write_text("postgresql://svc:pw@db.internal:5432/nohiki_db\n", encoding="utf-8")
    curl_log = tmp_path / "curl.log"
    psql_log = tmp_path / "psql.log"
    env = {
        "PATH": _path_with(bin_dir),
        "SECRETS_DIR": str(tmp_path / "secrets"),
        "CONNECT_URL": "http://connect.internal:8083",
        "CURL_LOG": str(curl_log),
        "PSQL_LOG": str(psql_log),
    }
    proc = _sh(["bash", str(_REGISTER), *args], env)
    return (
        proc,
        curl_log.read_text(encoding="utf-8") if curl_log.exists() else "",
        psql_log.read_text(encoding="utf-8") if psql_log.exists() else "",
    )


@pytest.mark.parametrize("args", [[], ["register"]], ids=["default", "register"])
def test_startup_registration_performs_no_destructive_cleanup(tmp_path: Path, args: list[str]) -> None:
    bin_dir = _bin_dir(tmp_path)
    _connect_bins(bin_dir)
    proc, curl_log, psql_log = _run_register(bin_dir, tmp_path, args)
    assert proc.returncode == 0, proc.stderr
    assert " -X POST " in curl_log, "connectors must still be registered on startup"
    assert " -X DELETE " not in curl_log, "startup must not delete any connector"
    assert psql_log.strip() == "", "startup must not touch replication slots/publications"


def test_migrate_legacy_performs_destructive_cleanup(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)
    _connect_bins(bin_dir)
    proc, curl_log, psql_log = _run_register(bin_dir, tmp_path, ["migrate-legacy"])
    assert proc.returncode == 0, proc.stderr
    assert " -X DELETE " in curl_log, "migrate-legacy must delete legacy connectors"
    assert "nohiki-outbox-user_auth" in curl_log
    assert "pg_replication_slots" in psql_log or "DROP PUBLICATION" in psql_log
    assert " -X POST " in curl_log, "migrate-legacy must also re-register connectors"


def test_unknown_command_is_rejected(tmp_path: Path) -> None:
    bin_dir = _bin_dir(tmp_path)
    _connect_bins(bin_dir)
    proc, _, _ = _run_register(bin_dir, tmp_path, ["definitely-not-a-command"])
    assert proc.returncode == 2, "an unknown subcommand must fail with usage, not run"


def test_entrypoint_invokes_registration_only() -> None:
    entrypoint = _ENTRYPOINT.read_text(encoding="utf-8")
    assert re.search(r"register-connectors\.sh[\"']?\s+register\b", entrypoint), (
        "startup entrypoint must call the non-destructive register subcommand"
    )
    assert "migrate-legacy" not in re.sub(r"#.*", "", entrypoint), (
        "entrypoint must never run destructive legacy migration at startup"
    )
