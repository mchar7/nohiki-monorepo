from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

import yaml

_ORIGINAL_RUN = subprocess.run
_SAFE_LOADER = yaml.CSafeLoader if yaml.__with_libyaml__ else yaml.SafeLoader


_RUNTIME_ENVIRONMENTS = {"dev", "staging", "prod"}


class RenderCache:
    """Cache manifest renders on disk for all xdist workers."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _is_render(command: tuple[str, ...]) -> bool:
        executable = Path(command[0]).name
        return (
            (executable == "helm" and len(command) > 1 and command[1] == "template")
            or (executable == "kustomize" and len(command) > 1 and command[1] == "build")
            or (executable == "kubectl" and len(command) > 1 and command[1] == "kustomize")
        )

    @staticmethod
    def _identity(command: tuple[str, ...], cwd: Path) -> tuple[str, ...]:
        executable = Path(command[0]).name
        if executable == "helm":
            identity = [executable, *command[1:4]]
            identity[3] = str((cwd / identity[3]).resolve()) if not Path(identity[3]).is_absolute() else identity[3]
            index = 4
            while index < len(command):
                argument = command[index]
                if argument in {"--values", "-f"} and index + 1 < len(command):
                    value_path = Path(command[index + 1])
                    value_path = value_path if value_path.is_absolute() else cwd / value_path
                    value_identity = (
                        hashlib.sha256(value_path.read_bytes()).hexdigest()
                        if value_path.is_file()
                        else str(value_path.resolve())
                    )
                    identity.extend((argument, value_identity))
                    index += 2
                else:
                    identity.append(argument)
                    index += 1
            return tuple(identity)
        return (executable, *command[1:-1], str((cwd / command[-1]).resolve()))

    def run(
        self,
        command: Sequence[str | os.PathLike[str]],
        *args: object,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        """Drop-in subprocess.run wrapper caching only manifest render commands."""
        passthrough = cast(
            "Callable[..., subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]]",
            _ORIGINAL_RUN,
        )
        normalized = tuple(str(part) for part in command)
        if (
            not self._is_render(normalized)
            or args
            or kwargs.get("input") is not None
            or kwargs.get("env") is not None
            or not kwargs.get("text", False)
        ):
            return passthrough(command, *args, **kwargs)

        cwd_option = kwargs.get("cwd")
        cwd = (Path(cwd_option) if isinstance(cwd_option, str | Path) else Path.cwd()).resolve()
        identity = self._identity(normalized, cwd)
        key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        result_path = self._directory / f"{key}.json"
        lock_path = self._directory / f"{key}.lock"
        with lock_path.open("w", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if result_path.exists():
                cached_state = json.loads(result_path.read_text(encoding="utf-8"))
                result = subprocess.CompletedProcess(
                    command,
                    cached_state["returncode"],
                    cached_state["stdout"],
                    cached_state["stderr"],
                )
            else:
                run_kwargs = kwargs | {"check": False}
                result = passthrough(command, **run_kwargs)
                temporary = result_path.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(
                        {
                            "returncode": result.returncode,
                            "stdout": result.stdout,
                            "stderr": result.stderr,
                        }
                    ),
                    encoding="utf-8",
                )
                temporary.replace(result_path)

        if kwargs.get("check") and result.returncode:
            raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout, stderr=result.stderr)
        return result

    def _run(self, command: tuple[str, ...], cwd: Path) -> tuple[dict[str, object], ...]:
        result = self.run(command, cwd=cwd, capture_output=True, text=True, check=True)
        return tuple(
            document for document in yaml.load_all(result.stdout, Loader=_SAFE_LOADER) if isinstance(document, dict)
        )

    def helm(
        self,
        chart: Path,
        *,
        release: str = "nohiki",
        values: tuple[Path, ...] = (),
        args: tuple[str, ...] = (),
        cwd: Path | None = None,
    ) -> tuple[dict[str, object], ...]:
        """Render a chart once for a chart, values, and extra-argument combination."""
        command = ["helm", "template", release, str(chart)]
        for values_file in values:
            command.extend(("--values", str(values_file)))
        command.extend(args)
        return self._run(tuple(command), cwd or chart.parent)

    def kustomize(self, path: Path, *, cwd: Path | None = None) -> tuple[dict[str, object], ...]:
        """Build a Kustomize tree once, using the available CLI implementation."""
        if executable := shutil.which("kustomize"):
            command = (executable, "build", str(path))
        elif executable := shutil.which("kubectl"):
            command = (executable, "kustomize", str(path))
        else:
            message = "kustomize or kubectl is required to render manifests"
            raise RuntimeError(message)
        return self._run(command, cwd or path.parent)


def runtime_eso_args(environment: str) -> list[str]:
    """Return deterministic runtime-injected ESO coordinates for shared renders."""
    if environment not in _RUNTIME_ENVIRONMENTS:
        return []
    return [
        "--set-string",
        "global.eso.azure.keyVaultUrl=https://nohiki-test-kv.vault.azure.net",
        "--set-string",
        "global.eso.azure.clientId=00000000-0000-4000-8000-000000000000",
        "--set-string",
        "global.eso.azure.tenantId=11111111-1111-4111-8111-111111111111",
    ]
