"""Pinned base-image digest freshness probe.

Registries garbage-collect manifests when tags are re-pushed, so a
digest-pinned ``FROM`` can silently stop resolving. This check probes every
pinned digest in tracked Dockerfiles and fails when one is dead, surfacing
rot on a schedule instead of inside a release build.

Requires ``skopeo`` (provided by ``devShells.ci``).
"""

import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.table import Table

from ci_checks.core.packages import REPO_ROOT

# FROM [--platform=...] name[:tag]@sha256:digest: the only pin shape we allow.
_PIN_RE = re.compile(
    r"^FROM\s+(?:--platform=\S+\s+)?(?P<ref>\S+?@sha256:[0-9a-f]{64})",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class PinProbe:
    """Result of probing one pinned reference."""

    ref: str
    alive: bool
    tag_digest: str
    detail: str


def _tracked_dockerfiles() -> list[str]:
    """Return repo-relative paths of every tracked Dockerfile.

    Returns:
        Sorted unique paths reported by git.

    Raises:
        RuntimeError: If git fails; callers must not treat that as "no pins".
    """
    result = subprocess.run(
        ["git", "ls-files", "--", "Dockerfile*", "**/Dockerfile*"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        msg = f"git ls-files failed: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return sorted({line for line in result.stdout.splitlines() if line})


def collect_pins(dockerfiles: list[str]) -> dict[str, list[str]]:
    """Map each pinned reference to the Dockerfiles using it.

    Args:
        dockerfiles: Repo-relative Dockerfile paths.

    Returns:
        Pinned ``name[:tag]@sha256:...`` reference -> sorted using files.
    """
    pins: dict[str, list[str]] = {}
    for path in dockerfiles:
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        for match in _PIN_RE.finditer(text):
            pins.setdefault(match.group("ref"), []).append(path)
    return {ref: sorted(set(files)) for ref, files in pins.items()}


def _skopeo(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["skopeo", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def probe_pin(ref: str) -> PinProbe:
    """Probe one pinned reference against its registry.

    Args:
        ref: ``name[:tag]@sha256:...`` reference from a Dockerfile.

    Returns:
        Probe outcome; ``alive`` is True only when the exact digest still
        resolves. ``tag_digest`` reports where the tag points now (empty
        when the reference carries no tag or the lookup fails).
    """
    tagged, _, digest = ref.partition("@")
    head, sep, candidate = tagged.rpartition(":")
    # A colon only introduces a tag in the final path component; otherwise
    # it is a registry port (registry.example:5000/team/image).
    tag = candidate if sep and "/" not in candidate else ""
    bare = head if tag else tagged
    pinned = _skopeo(["inspect", "--raw", f"docker://{bare}@{digest}"])
    tag_digest = ""
    if tag:
        current = _skopeo(["inspect", "--format", "{{.Digest}}", f"docker://{tagged}"])
        tag_digest = current.stdout.strip() if current.returncode == 0 else ""
    detail = "" if pinned.returncode == 0 else pinned.stderr.strip().splitlines()[-1][:200]
    return PinProbe(ref=ref, alive=pinned.returncode == 0, tag_digest=tag_digest, detail=detail)


def freshness_cmd() -> None:
    """Fail when any digest-pinned base image no longer resolves.

    Raises:
        typer.Exit: Code 1 when at least one pin is dead or no pins exist
            (an empty scan means the collector broke, not a clean repo).
    """
    console = Console()
    pins = collect_pins(_tracked_dockerfiles())
    if not pins:
        console.print("[red]no digest-pinned FROM lines found; collector is broken[/red]")
        raise typer.Exit(1)

    with ThreadPoolExecutor(max_workers=8) as pool:
        probes = list(pool.map(probe_pin, sorted(pins)))

    table = Table(title=f"Base-image digest freshness ({len(probes)} pins)")
    table.add_column("pin")
    table.add_column("status")
    table.add_column("tag now")
    dead = 0
    for probe in probes:
        _, _, digest = probe.ref.partition("@")
        drift = "same" if probe.tag_digest == digest else (probe.tag_digest[:19] or "?")
        if probe.alive:
            table.add_row(probe.ref, "[green]alive[/green]", drift)
        else:
            dead += 1
            table.add_row(probe.ref, f"[red]DEAD[/red] {probe.detail}", drift)
    console.print(table)

    if dead:
        for probe in probes:
            if not probe.alive:
                for path in pins[probe.ref]:
                    console.print(f"[red]{path}: {probe.ref}[/red]")
        console.print(f"[red]{dead} pinned base digest(s) no longer resolve; repin before the next build[/red]")
        raise typer.Exit(1)
    console.print(f"[green]all {len(probes)} pinned base digests resolve[/green]")
