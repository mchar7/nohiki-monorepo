"""Pinned container-reference freshness probe.

Registries garbage-collect manifests when tags are re-pushed and release
CDNs delete old artifacts, so a digest-pinned reference or a checksum-pinned
download can silently stop resolving. This check probes every pin in tracked
Dockerfiles and the checked-in production image overlay, surfacing rot on a
schedule instead of making the offline unit gate depend on registry availability.

Requires ``skopeo`` (provided by ``devShells.ci``).
"""

import functools
import os
import re
import subprocess
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http import HTTPStatus

import typer
import yaml
from rich.console import Console
from rich.table import Table

from ci_checks.core.image_inventory import split_registry_pin
from ci_checks.core.packages import REPO_ROOT

# FROM [--platform=...] ref and COPY [--flag ...] --from=ref, both pinned as
# name[:tag]@sha256:digest. The mandatory digest is what separates a registry
# reference from a build-stage name, which can never carry one.
_REGISTRY_PIN_RE = re.compile(
    r"^(?:FROM\s+(?:--platform=\S+\s+)?|COPY\s+(?:--\S+\s+)*?--from=)(?P<ref>\S+?@sha256:[0-9a-f]{64})",
    re.IGNORECASE | re.MULTILINE,
)

# ADD [--flag ...] --checksum=sha256:digest <url>: a content pin on a plain
# download, optionally split across a line continuation.
_CHECKSUM_PIN_RE = re.compile(
    r"^ADD\s+(?=(?:--\S+\s+)*--checksum=sha256:[0-9a-f]{64}\s)(?:--\S+\s+)+(?:\\\s+)?(?P<ref>https?://\S+)",
    re.IGNORECASE | re.MULTILINE,
)

_URL_TIMEOUT_SECONDS = 30
_PRODUCTION_DIGEST_OVERLAY = "infra/k8s/helm/values.prod.digests.yaml"
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class PinProbe:
    """Result of probing one pinned reference."""

    ref: str
    alive: bool
    tag_digest: str
    detail: str


def _tracked_dockerfiles() -> list[str]:
    """Return repo-relative paths of every tracked Dockerfile and the production digest overlay.

    Returns:
        Sorted unique paths reported by git.

    Raises:
        RuntimeError: If git fails; callers must not treat that as "no pins".
    """
    result = subprocess.run(
        ["git", "ls-files", "--", "Dockerfile*", "**/Dockerfile*", _PRODUCTION_DIGEST_OVERLAY],
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
    """Map each pinned reference to its tracked source files.

    Args:
        dockerfiles: Repo-relative Dockerfile paths, optionally including the
            checked-in production digest overlay.

    Returns:
        Pinned reference -> sorted using files. A reference is either a
        ``name[:tag]@sha256:...`` registry pin or a checksum-pinned URL.

    Raises:
        RuntimeError: If the production digest overlay has an invalid shape.
    """
    pins: dict[str, list[str]] = {}
    for path in dockerfiles:
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        if path == _PRODUCTION_DIGEST_OVERLAY:
            values = yaml.safe_load(text)
            global_values = values.get("global") if isinstance(values, dict) else None
            digests = global_values.get("imageDigests") if isinstance(global_values, dict) else None
            if not isinstance(digests, dict):
                msg = "global.imageDigests must be a mapping"
                raise RuntimeError(msg)
            for repository, digest in digests.items():
                if not isinstance(repository, str) or not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
                    msg = f"invalid production image digest: {repository!r}: {digest!r}"
                    raise RuntimeError(msg)
                pins.setdefault(f"{repository}@{digest}", []).append(path)
            continue
        for pattern in (_REGISTRY_PIN_RE, _CHECKSUM_PIN_RE):
            for match in pattern.finditer(text):
                pins.setdefault(match.group("ref"), []).append(path)
    return {ref: sorted(set(files)) for ref, files in pins.items()}


@functools.cache
def _registries_conf() -> str:
    """Write a minimal registries.conf so probes never parse host container config.

    Hosted runners ship an /etc/containers/registries.conf that this skopeo
    build cannot parse, which marked every pin DEAD with "loading registries
    configuration" instead of probing anything.
    """
    descriptor, path = tempfile.mkstemp(suffix=".conf", prefix="registries-", text=True)
    with os.fdopen(descriptor, "w") as handle:
        handle.write('unqualified-search-registries = ["docker.io"]\n')
    return path


def _skopeo(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["skopeo", *args],
        capture_output=True,
        text=True,
        check=False,
        env=os.environ | {"CONTAINERS_REGISTRIES_CONF": _registries_conf()},
    )


def _probe_url(ref: str) -> PinProbe:
    """Probe a checksum-pinned download URL.

    Args:
        ref: ``http(s)://`` URL from an ``ADD --checksum`` instruction.

    Returns:
        Probe outcome; ``tag_digest`` is always empty because a content pin
        has no moving tag to drift against.
    """
    # S310: the collector regex fixes the scheme to http(s); no caller-supplied URL reaches here.
    request = urllib.request.Request(ref, method="HEAD")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=_URL_TIMEOUT_SECONDS) as response:  # noqa: S310
            status = int(response.status)
    except OSError as exc:
        return PinProbe(ref=ref, alive=False, tag_digest="", detail=str(exc)[:200])
    alive = status == HTTPStatus.OK
    return PinProbe(ref=ref, alive=alive, tag_digest="", detail="" if alive else f"HTTP {status}")


def probe_pin(ref: str) -> PinProbe:
    """Probe one pinned reference against its origin.

    Args:
        ref: ``name[:tag]@sha256:...`` registry reference from a Dockerfile,
            or a checksum-pinned ``http(s)://`` URL.

    Returns:
        Probe outcome; ``alive`` is True only when the exact pin still
        resolves. ``tag_digest`` reports where the tag points now (empty
        when the reference carries no tag or the lookup fails).
    """
    if ref.startswith(("http://", "https://")):
        return _probe_url(ref)
    tagged, bare, digest = split_registry_pin(ref)
    pinned = _skopeo(["inspect", "--raw", f"docker://{bare}@{digest}"])
    tag_digest = ""
    if tagged != bare:
        current = _skopeo(["inspect", "--format", "{{.Digest}}", f"docker://{tagged}"])
        tag_digest = current.stdout.strip() if current.returncode == 0 else ""
    detail = "" if pinned.returncode == 0 else pinned.stderr.strip().splitlines()[-1][:200]
    return PinProbe(ref=ref, alive=pinned.returncode == 0, tag_digest=tag_digest, detail=detail)


def freshness_cmd() -> None:
    """Fail when any pinned reference no longer resolves.

    Raises:
        typer.Exit: Code 1 when at least one pin is dead or no pins exist
            (an empty scan means the collector broke, not a clean repo).
    """
    console = Console()
    pins = collect_pins(_tracked_dockerfiles())
    if not pins:
        console.print("[red]no digest-pinned references found; collector is broken[/red]")
        raise typer.Exit(1)

    with ThreadPoolExecutor(max_workers=8) as pool:
        probes = list(pool.map(probe_pin, sorted(pins)))

    table = Table(title=f"Pinned reference freshness ({len(probes)} pins)")
    table.add_column("pin")
    table.add_column("status")
    table.add_column("tag now")
    dead = 0
    for probe in probes:
        _, _, digest = probe.ref.partition("@")
        drift = "n/a" if not digest else ("same" if probe.tag_digest == digest else probe.tag_digest[:19] or "?")
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
        console.print(f"[red]{dead} pinned reference(s) no longer resolve; repin before the next build[/red]")
        raise typer.Exit(1)
    console.print(f"[green]all {len(probes)} pinned references resolve[/green]")
