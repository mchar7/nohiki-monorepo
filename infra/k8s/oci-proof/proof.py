#!/usr/bin/env python3
"""Binary proof of deterministic, signed OCI Helm delivery for Nohiki.

The live ``run`` command is deliberately destructive only to a uniquely named,
transient native-k3s unit.  Pure packaging and template helpers are public so
CI can exercise the fail-closed contracts without a cluster.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime as dt
import enum
import gzip
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Final, Never
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SCHEMA_VERSION: Final = "nohiki.oci-helm-proof/v1"
PRIVILEGED_HELPER: Final = "nohiki-oci-proof-privileged"
DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
TOKEN_RE: Final = re.compile(r"__[A-Z][A-Z0-9_]*__")
RUN_ID_RE: Final = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
HELM_DEPENDENCY_FIELDS: Final = 3
TAR_ROOT_PARTS: Final = 2
HTTP_OK: Final = 200
PORT_PROBE_ADDRESS: Final = socket.inet_ntoa(socket.INADDR_ANY.to_bytes(4, "big"))
_TRUSTED_SUBPROCESS_RUN = subprocess.run
_TRUSTED_SUBPROCESS_POPEN = subprocess.Popen
_TRUSTED_URLOPEN = urlopen
EXPECTED_RELEASE_PATCH_DOCUMENTS: Final = 2
PRIVATE_PATTERN: Final = re.compile(
    r"(?i)(BEGIN (?:ENCRYPTED )?PRIVATE KEY|COSIGN_PASSWORD|SOPS_AGE_KEY|"
    r"\.dockerconfigjson|authorization\s*[:=]|password\s*[:=])"
)
EXPECTED_LOCK_DIGESTS: Final = {
    "infra/k8s/helm-foundation": "sha256:7ed402df68de52e372e2d6a68f354c2c373cf7deea903c0b1a256c3a9c3c9fda",
    "infra/k8s/helm": "sha256:043a4eb780a219fa598a86df676f0c3b2bd4069e0a813916501299bad6ef4a13",
}
ARCHIVE_FILE_NAMES: Final = {
    (
        "strimzi-kafka-operator",
        "1.1.0",
    ): "strimzi-kafka-operator-helm-3-chart-1.1.0.tgz",
}
CHARTS: Final = (
    ("infra/k8s/helm-foundation", "nohiki-foundation", "0.1.0", "0.1.1"),
    ("infra/k8s/helm", "nohiki", "0.2.0", "0.2.1"),
)
CONTRACTS: Final = frozenset(
    {
        "PREREQ_HOST",
        "PREREQ_NATIVE_K3S_PRIVILEGE",
        "SOURCE_LOCK_AUTHORITY",
        "PACKAGE_REPRODUCIBLE",
        "BOOTSTRAP_CYCLE",
        "REGISTRY_REACHABILITY_OR_AUTH",
        "REGISTRY_SIGNATURE_COMPATIBILITY",
        "COSIGN_ENFORCEMENT",
        "AUTH_OR_DIGEST_ENFORCEMENT",
        "DIRECT_CHARTREF_OPERATION",
        "DEPENDENCY_ISOLATION",
        "DRIFT_CORRECTION",
        "END_TO_END_HEALTH",
        "TEARDOWN_INCOMPLETE",
    }
)


class Phase(enum.StrEnum):
    """Ordered phases of the fail-closed proof."""

    PREFLIGHT = "preflight"
    K3S = "native-k3s"
    BOOTSTRAP = "flux-registry-bootstrap"
    BUILD = "deterministic-build-publication"
    NEGATIVE = "fail-before-helm-negative-cases"
    V1 = "positive-v1"
    UPGRADE = "isolated-upgrade-v2"
    ROLLBACK = "rollback-drift-verification"
    TEARDOWN = "unconditional-teardown"


PHASE_FAILURE_CONTRACT: Final = {
    Phase.PREFLIGHT: "PREREQ_HOST",
    Phase.K3S: "PREREQ_NATIVE_K3S_PRIVILEGE",
    Phase.BOOTSTRAP: "BOOTSTRAP_CYCLE",
    Phase.BUILD: "PACKAGE_REPRODUCIBLE",
    Phase.NEGATIVE: "COSIGN_ENFORCEMENT",
    Phase.V1: "DIRECT_CHARTREF_OPERATION",
    Phase.UPGRADE: "DEPENDENCY_ISOLATION",
    Phase.ROLLBACK: "END_TO_END_HEALTH",
    Phase.TEARDOWN: "TEARDOWN_INCOMPLETE",
}


class ContractError(RuntimeError):
    """A fail-closed proof contract violation."""

    def __init__(self, contract: str, message: str) -> None:
        """Initialize a violation for a known proof contract."""
        if contract not in CONTRACTS:
            msg = f"unknown proof contract: {contract}"
            raise ValueError(msg)
        super().__init__(message)
        self.contract = contract


@dataclasses.dataclass(frozen=True, slots=True)
class ArchiveCoordinate:
    """Reviewed Helm dependency archive coordinates."""

    name: str
    version: str
    repository: str
    archive: Path
    sha256: str


@dataclasses.dataclass(frozen=True, slots=True)
class Package:
    """Canonical chart package and its verified registry identity."""

    chart: str
    version: str
    path: Path
    sha256: str
    registry_digest: str = ""


@dataclasses.dataclass(slots=True)
class ProofPaths:
    """Filesystem locations owned by one proof run."""

    repo: Path
    runtime: Path
    evidence: Path
    clone: Path
    bare: Path
    kubeconfig: Path
    registry_config: Path
    docker_config: Path


def utc_now() -> str:
    """Return the current UTC instant in proof-schema format."""
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclasses.dataclass(slots=True)
class ProofState:
    """Mutable state accumulated by one proof run."""

    paths: ProofPaths
    run_id: str
    head: str
    branch: str
    phase: Phase = Phase.PREFLIGHT
    unit: str = ""
    git_process: subprocess.Popen[bytes] | None = None
    node_ip: str = ""
    registry: str = ""
    username: str = ""
    password: str = ""
    cosign_password: str = ""
    wrong_cosign_password: str = ""
    packages: dict[tuple[str, str], Package] = dataclasses.field(default_factory=dict)
    commits: dict[str, str] = dataclasses.field(default_factory=dict)
    started: str = dataclasses.field(default_factory=utc_now)


def sha256_file(path: Path) -> str:
    """Return the hexadecimal SHA-256 checksum of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    """Atomically write a deterministic JSON document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


@dataclasses.dataclass(frozen=True, slots=True)
class RunContext:
    """Working directory and environment for a trusted command."""

    cwd: Path | None = None
    env: Mapping[str, str] | None = None


def run(
    argv: Sequence[str | os.PathLike[str]],
    *,
    context: RunContext | None = None,
    input_text: str | None = None,
    check: bool = True,
    redact_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a trusted tool without a shell and capture its combined output."""
    command = [os.fspath(item) for item in argv]
    executable = command[0]
    if os.sep not in executable:
        resolved = shutil.which(executable)
        if resolved is not None:
            command[0] = resolved
    run_context = context or RunContext()
    completed = _TRUSTED_SUBPROCESS_RUN(
        command,
        cwd=run_context.cwd,
        env=None if run_context.env is None else dict(run_context.env),
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if check and completed.returncode:
        output = "[redacted]" if redact_output else redact(completed.stdout[-4000:])
        msg = f"command failed ({completed.returncode}): {executable}\n{output}"
        raise RuntimeError(msg)
    return completed


def _privileged_helper_path() -> Path:
    helper = shutil.which(PRIVILEGED_HELPER)
    if helper is None:
        msg = f"privileged proof helper missing: {PRIVILEGED_HELPER}"
        _fail("PREREQ_NATIVE_K3S_PRIVILEGE", msg)
    return Path(helper).resolve()


def _privileged(*args: str | os.PathLike[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(("sudo", "-n", _privileged_helper_path(), *args), check=check)


def require(*, condition: bool, contract: str, message: str) -> None:
    """Raise a contract violation unless ``condition`` holds."""
    if not condition:
        raise ContractError(contract, message)


def _fail(contract: str, message: str) -> Never:
    raise ContractError(contract, message)


def redact(value: object) -> object:
    """Recursively redact Kubernetes secrets and credential-shaped values."""
    if isinstance(value, dict):
        result: dict[str, object] = {}
        kind = str(value.get("kind", ""))
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if (kind == "Secret" and key in {"data", "stringData"}) or re.search(
                r"(?i)(password|token|authorization|private.?key|dockerconfig)", key
            ):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact(raw_value)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return PRIVATE_PATTERN.sub("[REDACTED]", value)
    return value


def render_template(path: Path, tokens: Mapping[str, str]) -> str:
    """Render an allowlisted token template and reject unresolved placeholders."""
    text = path.read_text(encoding="utf-8")
    for name, value in tokens.items():
        token = f"__{name}__"
        if token not in text:
            msg = f"template {path} does not contain {token}"
            raise ValueError(msg)
        if not value or "\n" in value or "\r" in value:
            msg = f"invalid value for {token}"
            raise ValueError(msg)
        text = text.replace(token, value)
    unresolved = sorted(set(TOKEN_RE.findall(text)))
    if unresolved:
        msg = f"unresolved template tokens in {path}: {', '.join(unresolved)}"
        raise ValueError(msg)
    validate_rendered_manifest(text)
    return text


def _validate_oci_repository_document(document: str) -> None:
    if re.search(r"(?m)^\s*(tag|semver):\s*", document):
        msg = "OCI tag/semver selectors are forbidden; use ref.digest"
        raise ValueError(msg)
    digests = re.findall(r"(?m)^\s*digest:\s*([^\s#]+)", document)
    if len(digests) != 1:
        msg = "OCIRepository must contain exactly one ref.digest"
        raise ValueError(msg)
    verification = re.findall(
        r"(?m)^\s*verify:\s*$\n\s+provider:\s*cosign\s*$\n\s+secretRef:\s*$\n\s+name:\s*[^\s#]+\s*$",
        document,
    )
    if len(verification) != 1:
        msg = "OCIRepository must enforce cosign verification with one public-key secretRef"
        raise ValueError(msg)


def validate_rendered_manifest(text: str) -> None:
    """Reject private material, unresolved tokens, and non-digest OCI selectors."""
    unresolved = TOKEN_RE.findall(text)
    if unresolved:
        msg = f"unresolved template tokens: {sorted(set(unresolved))}"
        raise ValueError(msg)
    if PRIVATE_PATTERN.search(text):
        msg = "private or credential material is forbidden in rendered Git manifests"
        raise ValueError(msg)
    for document in re.split(r"(?m)^---\s*$", text):
        if re.search(r"(?m)^kind:\s*OCIRepository\s*$", document):
            _validate_oci_repository_document(document)
    for match in re.finditer(r"(?m)^\s*digest:\s*([^\s#]+)", text):
        if not DIGEST_RE.fullmatch(match.group(1)):
            msg = f"OCI ref.digest must be sha256: {match.group(1)}"
            raise ValueError(msg)
    for match in re.finditer(r"(?m)^\s*url:\s*(oci://[^\s#]+)", text):
        if "@" in match.group(1) or re.search(r":[^/:]+$", match.group(1)):
            msg = f"OCI repository URL must not contain a tag or digest: {match.group(1)}"
            raise ValueError(msg)
    if re.search(r"(?m)^\s*(privateKey|password|COSIGN_PASSWORD):", text):
        msg = "secret/private field forbidden in rendered Git manifest"
        raise ValueError(msg)


def mutated_digest(digest: str) -> str:
    """Return a different, still well-formed SHA-256 digest."""
    if not DIGEST_RE.fullmatch(digest):
        msg = f"invalid sha256 digest: {digest}"
        raise ValueError(msg)
    replacement = "1" if digest[-1] == "0" else "0"
    return digest[:-1] + replacement


def _lock_data(lock_path: Path) -> tuple[str, tuple[tuple[str, str, str], ...]]:
    """Parse the deliberately simple Helm Chart.lock subset without a YAML dependency."""
    digest = ""
    dependencies: list[tuple[str, str, str]] = []
    current: dict[str, str] = {}
    for raw in lock_path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped.startswith("- name:"):
            if current:
                dependencies.append((current["name"], current["version"], current["repository"]))
            current = {"name": stripped.split(":", 1)[1].strip().strip("\"'")}
        elif current and re.match(r"^(version|repository):", stripped):
            key, value = stripped.split(":", 1)
            current[key] = value.strip().strip("\"'")
        elif stripped.startswith("digest:"):
            digest = stripped.split(":", 1)[1].strip()
    if current:
        dependencies.append((current["name"], current["version"], current["repository"]))
    if not DIGEST_RE.fullmatch(digest):
        msg = f"invalid or missing Helm lock digest in {lock_path}"
        raise ValueError(msg)
    if not dependencies or any(len(item) != HELM_DEPENDENCY_FIELDS or not all(item) for item in dependencies):
        msg = f"invalid dependency closure in {lock_path}"
        raise ValueError(msg)
    return digest, tuple(dependencies)


def source_hashes(chart_dir: Path) -> dict[Path, str]:
    """Hash all source-authority files while excluding disposable archives."""
    return {
        path.relative_to(chart_dir): sha256_file(path)
        for path in sorted(chart_dir.rglob("*"))
        if path.is_file() and path.suffix != ".tgz"
    }


def _archive_chart_metadata(archive: Path) -> tuple[str, str]:
    with tarfile.open(archive, "r:gz") as package:
        roots = [
            member
            for member in package.getmembers()
            if member.isfile()
            and len(PurePosixPath(member.name).parts) == TAR_ROOT_PARTS
            and PurePosixPath(member.name).name == "Chart.yaml"
        ]
        if len(roots) != 1:
            msg = f"archive has no unique root Chart.yaml: {archive}"
            _fail("SOURCE_LOCK_AUTHORITY", msg)
        stream = package.extractfile(roots[0])
        if stream is None:
            msg = f"archive Chart.yaml is unreadable: {archive}"
            _fail("SOURCE_LOCK_AUTHORITY", msg)
        text = stream.read().decode("utf-8")
    name = re.search(r"(?m)^name:\s*[\"']?([^\s\"']+)", text)
    version = re.search(r"(?m)^version:\s*[\"']?([^\s\"']+)", text)
    if name is None or version is None:
        msg = f"archive Chart.yaml lacks name/version: {archive}"
        _fail("SOURCE_LOCK_AUTHORITY", msg)
    return name.group(1), version.group(1)


def validate_package_closure(
    chart_dir: Path, expected_source: Mapping[Path, str] | None = None
) -> tuple[ArchiveCoordinate, ...]:
    """Require exact one-to-one lock dependency/archive coverage and source stability."""
    if expected_source is not None and dict(expected_source) != source_hashes(chart_dir):
        msg = f"tracked chart source changed: {chart_dir}"
        _fail("SOURCE_LOCK_AUTHORITY", msg)
    lock_digest, dependencies = _lock_data(chart_dir / "Chart.lock")
    expected_digest = EXPECTED_LOCK_DIGESTS.get(chart_dir.as_posix())
    if expected_digest is None:
        for suffix, value in EXPECTED_LOCK_DIGESTS.items():
            if chart_dir.as_posix().endswith(suffix):
                expected_digest = value
                break
    if expected_digest is not None:
        require(
            condition=lock_digest == expected_digest,
            contract="SOURCE_LOCK_AUTHORITY",
            message=f"unreviewed lock digest: {chart_dir}",
        )
    archives = tuple(sorted((chart_dir / "charts").glob("*.tgz")))
    require(
        condition=len(archives) == len(dependencies),
        contract="SOURCE_LOCK_AUTHORITY",
        message=f"missing or extra lock dependency archives for {chart_dir}",
    )
    metadata = {archive: _archive_chart_metadata(archive) for archive in archives}
    remaining = set(archives)
    coordinates: list[ArchiveCoordinate] = []
    for name, version, repository in dependencies:
        archive_name = ARCHIVE_FILE_NAMES.get((name, version), f"{name}-{version}.tgz")
        exact = [
            archive for archive in remaining if metadata[archive] == (name, version) and archive.name == archive_name
        ]
        require(
            condition=len(exact) == 1,
            contract="SOURCE_LOCK_AUTHORITY",
            message=f"dependency/archive mapping is missing or ambiguous: {name}:{version}",
        )
        archive = exact[0]
        remaining.remove(archive)
        coordinates.append(ArchiveCoordinate(name, version, repository, archive, sha256_file(archive)))
    require(
        condition=not remaining,
        contract="SOURCE_LOCK_AUTHORITY",
        message=f"unmatched dependency archives: {sorted(path.name for path in remaining)}",
    )
    return tuple(coordinates)


def _safe_member_name(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        msg = f"unsafe tar member: {name}"
        raise ValueError(msg)
    return path.as_posix().lstrip("./")


def canonicalize_chart(source_tgz: Path, destination_tgz: Path) -> None:
    """Rewrite a Helm package into a byte-stable tar/gzip stream."""
    members: list[tuple[str, tarfile.TarInfo, bytes]] = []
    with tarfile.open(source_tgz, "r:gz") as archive:
        for original in archive.getmembers():
            name = _safe_member_name(original.name)
            if not name:
                continue
            payload = b""
            if original.isfile():
                extracted = archive.extractfile(original)
                if extracted is None:
                    msg = f"unable to read tar member: {name}"
                    raise ValueError(msg)
                payload = extracted.read()
            elif not (original.isdir() or original.issym() or original.islnk()):
                msg = f"unsupported tar member type: {name}"
                raise ValueError(msg)
            members.append((name, original, payload))
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, original, payload in sorted(members, key=lambda item: item[0]):
            info = tarfile.TarInfo(name)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.pax_headers = {}
            if original.isdir():
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.size = 0
            elif original.issym() or original.islnk():
                info.type = tarfile.SYMTYPE if original.issym() else tarfile.LNKTYPE
                info.linkname = _safe_member_name(original.linkname)
                info.mode = 0o777
                info.size = 0
            else:
                info.type = tarfile.REGTYPE
                info.mode = 0o755 if original.mode & stat.S_IXUSR else 0o644
                info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload) if info.isfile() else None)
    destination_tgz.parent.mkdir(parents=True, exist_ok=True)
    with (
        destination_tgz.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as compressed,
    ):
        compressed.write(output.getvalue())


def _package_payloads(package: Path) -> tuple[str, dict[str, bytes]]:
    version = ""
    payloads: dict[str, bytes] = {}
    with tarfile.open(package, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                msg = f"unreadable package member: {member.name}"
                raise ValueError(msg)
            data = extracted.read()
            relative = "/".join(PurePosixPath(member.name).parts[1:])
            if relative == "Chart.yaml":
                text = data.decode()
                match = re.search(r"(?m)^version:\s*[\"']?([^\s\"']+)", text)
                if match is None:
                    msg = "packaged Chart.yaml has no version"
                    raise ValueError(msg)
                version = match.group(1)
                data = re.sub(rb"(?m)^version:\s*[^\r\n]+", b"version: __VERSION__", data, count=1)
            payloads[relative] = data
    if not version:
        msg = "package has no root Chart.yaml"
        raise ValueError(msg)
    return version, payloads


def validate_version_only_packages(
    v1_tgz: Path,
    v2_tgz: Path,
    expected_versions: tuple[str, str] | None = None,
) -> tuple[str, str]:
    """Require packages to differ only by root Chart.yaml ``version``."""
    v1, first = _package_payloads(v1_tgz)
    v2, second = _package_payloads(v2_tgz)
    if expected_versions is not None and (v1, v2) != expected_versions:
        msg = f"unexpected versions {(v1, v2)}"
        _fail("PACKAGE_REPRODUCIBLE", msg)
    require(
        condition=first == second,
        contract="PACKAGE_REPRODUCIBLE",
        message="package mutation was not version-only",
    )
    return v1, v2


def _port_free(port: int) -> bool:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((PORT_PROBE_ADDRESS, port))
        except OSError:
            return False
    return True


def _tool_versions() -> dict[str, str]:
    commands: dict[str, tuple[str, ...]] = {
        "flux": ("flux", "--version"),
        "helm": ("helm", "version", "--short"),
        "cosign": ("cosign", "version"),
        "k3s": ("k3s", "--version"),
        "kubectl": ("kubectl", "version", "--client=true"),
        "kustomize": ("kustomize", "version"),
        "skopeo": ("skopeo", "--version"),
        "jq": ("jq", "--version"),
        "yq": ("yq", "--version"),
        "python": (sys.executable, "--version"),
        "uv": ("uv", "--version"),
        "git": ("git", "--version"),
        "apacheHttpd": ("httpd", "-v"),
    }
    versions: dict[str, str] = {}
    for name, argv in commands.items():
        executable = shutil.which(argv[0]) if argv[0] != sys.executable else sys.executable
        require(
            condition=executable is not None,
            contract="PREREQ_HOST",
            message=f"required tool missing: {argv[0]}",
        )
        completed = run(argv, check=False)
        require(
            condition=completed.returncode == 0,
            contract="PREREQ_HOST",
            message=f"cannot query {name} version",
        )
        versions[name] = completed.stdout.strip()[:1000]
    return versions


def _absolute_secret(name: str) -> Path:
    raw = os.environ.get(name, "")
    path = Path(raw)
    require(
        condition=raw != "" and path.is_absolute() and path.exists(),
        contract="PREREQ_HOST",
        message=f"{name} must name an existing absolute path",
    )
    return path


def preflight(repo: Path, evidence: Path) -> tuple[str, dict[str, str]]:
    """Validate the host, checkout, tools, secrets, ports, and chart locks."""
    require(
        condition=sys.platform.startswith("linux"),
        contract="PREREQ_HOST",
        message="native proof requires Linux",
    )
    require(
        condition=sys.version_info[:2] >= (3, 14),
        contract="PREREQ_HOST",
        message="Python 3.14+ required",
    )
    require(
        condition=repo
        == Path(run(("git", "rev-parse", "--show-toplevel"), context=RunContext(cwd=repo)).stdout.strip()),
        contract="PREREQ_HOST",
        message="run from repository root",
    )
    status = run(
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        context=RunContext(cwd=repo),
    ).stdout
    require(
        condition=not status,
        contract="SOURCE_LOCK_AUTHORITY",
        message="proof requires a completely clean checkout",
    )
    head = run(("git", "rev-parse", "--verify", "HEAD^{commit}"), context=RunContext(cwd=repo)).stdout.strip()
    require(
        condition=bool(re.fullmatch(r"[0-9a-f]{40}", head)),
        contract="SOURCE_LOCK_AUTHORITY",
        message="HEAD is not a commit",
    )
    _absolute_secret("SOPS_AGE_KEY_FILE")
    secret_sources = _absolute_secret("NOHIKI_LOCAL_SECRETS_DIR")
    run(
        (
            "uv",
            "run",
            "python",
            "scripts/infra/validate_local_secret_sources.py",
            "--secrets-dir",
            secret_sources,
        ),
        context=RunContext(cwd=repo),
        redact_output=True,
    )
    require(
        condition=all(_port_free(port) for port in (6443, 19418, 30500)),
        contract="PREREQ_HOST",
        message="API, Git, or registry port occupied",
    )
    _privileged_helper_path()
    helper_check = _privileged("check", check=False)
    require(
        condition=helper_check.returncode == 0,
        contract="PREREQ_NATIVE_K3S_PRIVILEGE",
        message="privileged proof helper unavailable through non-interactive sudo",
    )
    active_units = any(
        run(("systemctl", "is-active", unit), check=False).returncode == 0 for unit in ("k3s", "k3s-agent")
    )
    k3s_process = False
    for comm in Path("/proc").glob("[0-9]*/comm"):
        try:
            if comm.read_text(encoding="utf-8").strip() in {
                "k3s",
                "k3s-agent",
                "k3s-server",
            }:
                k3s_process = True
                break
        except OSError:
            continue
    stale_state = Path("/var/lib/rancher/k3s").exists()
    require(
        condition=not active_units and not k3s_process and not stale_state,
        contract="PREREQ_NATIVE_K3S_PRIVILEGE",
        message="existing k3s unit, process, or state is forbidden",
    )
    tools = _tool_versions()
    require(
        condition=helper_check.stdout.strip() == tools["k3s"],
        contract="PREREQ_NATIVE_K3S_PRIVILEGE",
        message="privileged helper k3s version does not match the selected k3s",
    )
    atomic_json(evidence / "tools.json", {"schemaVersion": SCHEMA_VERSION, "versions": tools})
    source: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "head": head,
        "clean": True,
        "charts": {},
    }
    for relative, _, _, _ in CHARTS:
        chart = repo / relative
        lock_digest, dependencies = _lock_data(chart / "Chart.lock")
        require(
            condition=lock_digest == EXPECTED_LOCK_DIGESTS[relative],
            contract="SOURCE_LOCK_AUTHORITY",
            message=f"unexpected reviewed lock digest: {relative}",
        )
        source["charts"][relative] = {  # type: ignore[index]
            "chartYamlSha256": sha256_file(chart / "Chart.yaml"),
            "chartLockSha256": sha256_file(chart / "Chart.lock"),
            "lockDigest": lock_digest,
            "dependencies": [{"name": n, "version": v, "repository": r} for n, v, r in dependencies],
        }
    atomic_json(evidence / "source.json", source)
    return head, tools


def _private_write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def _docker_config(registries: Iterable[str], username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return json.dumps(
        {"auths": {registry: {"auth": encoded} for registry in registries}},
        separators=(",", ":"),
    )


def _kubectl(
    state: ProofState, *args: str, input_text: str | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return run(
        ("kubectl", "--kubeconfig", state.paths.kubeconfig, *args),
        input_text=input_text,
        check=check,
    )


def _wait_resource(state: ProofState, kind: str, name: str, namespace: str, timeout: str = "65m") -> None:
    _kubectl(
        state,
        "wait",
        f"{kind}/{name}",
        "-n",
        namespace,
        "--for=condition=Ready",
        f"--timeout={timeout}",
    )


def start_k3s(state: ProofState) -> None:
    """Start isolated k3s and configure its authenticated registry client."""
    state.phase = Phase.K3S
    state.username = "nohiki-proof"
    state.password = secrets.token_urlsafe(36)
    htpasswd = run(
        ("htpasswd", "-Bni", state.username),
        input_text=state.password + "\n",
        redact_output=True,
    ).stdout
    _private_write(state.paths.runtime / "htpasswd", htpasswd)
    registry_yaml = (
        'mirrors:\n  "localhost:5000":\n    endpoint:\n'
        '      - "http://127.0.0.1:30500"\nconfigs:\n  "127.0.0.1:30500":\n'
        f'    auth:\n      username: "{state.username}"\n'
        f'      password: "{state.password}"\n'
    )
    _private_write(state.paths.registry_config, registry_yaml)
    state.unit = f"nohiki-oci-proof-{state.run_id.lower()}"
    _privileged("start", state.unit, state.paths.runtime)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline and not state.paths.kubeconfig.exists():
        time.sleep(1)
    require(
        condition=state.paths.kubeconfig.exists(),
        contract="PREREQ_NATIVE_K3S_PRIVILEGE",
        message="k3s did not write kubeconfig",
    )
    _privileged("chown-kubeconfig", state.paths.runtime)
    _kubectl(state, "wait", "node", "--all", "--for=condition=Ready", "--timeout=5m")
    nodes = json.loads(_kubectl(state, "get", "nodes", "-o", "json").stdout)
    addresses = nodes["items"][0]["status"]["addresses"]
    state.node_ip = next(item["address"] for item in addresses if item["type"] == "InternalIP")
    state.registry = f"{state.node_ip}:30500"
    _private_write(
        state.paths.docker_config,
        _docker_config(
            ("localhost:5000", "127.0.0.1:30500", state.registry),
            state.username,
            state.password,
        ),
    )


def _copy_secret_sources(state: ProofState) -> None:
    age = _absolute_secret("SOPS_AGE_KEY_FILE").read_bytes()
    require(
        condition=b"AGE-SECRET-KEY-" in age,
        contract="PREREQ_HOST",
        message="SOPS age identity is invalid",
    )
    secret = run(
        (
            "kubectl",
            "create",
            "secret",
            "generic",
            "sops-age",
            "-n",
            "flux-system",
            f"--from-file=age.agekey={_absolute_secret('SOPS_AGE_KEY_FILE')}",
            "--dry-run=client",
            "-o",
            "yaml",
        )
    ).stdout
    _kubectl(state, "apply", "-f", "-", input_text=secret)


def _git_commit(state: ProofState, message: str) -> str:
    run(
        ("git", "add", "infra/k8s/oci-proof/generated"),
        context=RunContext(cwd=state.paths.clone),
    )
    run(
        ("git", "commit", "-m", message, "--no-verify"),
        context=RunContext(cwd=state.paths.clone),
    )
    commit = run(("git", "rev-parse", "HEAD"), context=RunContext(cwd=state.paths.clone)).stdout.strip()
    run(
        ("git", "push", "--force", "origin", f"HEAD:{state.branch}"),
        context=RunContext(cwd=state.paths.clone),
    )
    return commit


def _generated_root(state: ProofState) -> Path:
    return state.paths.clone / "infra/k8s/oci-proof/generated"


def _write_initial_overlay(state: ProofState) -> None:
    root = _generated_root(state)
    shutil.rmtree(root, ignore_errors=True)
    (root / "registry").mkdir(parents=True)
    (root / "cluster").mkdir(parents=True)
    (root / "registry/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\n"
        "kind: Kustomization\nresources:\n  - ../../../gitops/registry\n"
        "patches:\n  - path: ../../manifests/registry-auth-patch.yaml\n",
        encoding="utf-8",
    )
    (root / "cluster/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n  - registry.yaml\n",
        encoding="utf-8",
    )
    (root / "cluster/registry.yaml").write_text(
        (state.paths.clone / "infra/k8s/gitops/clusters/local/registry.yaml")
        .read_text()
        .replace("./infra/k8s/gitops/registry", "./infra/k8s/oci-proof/generated/registry"),
        encoding="utf-8",
    )
    validate_generated_tree(root)


def validate_generated_tree(root: Path) -> None:
    """Validate every generated manifest before it enters Git."""
    for path in root.rglob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        validate_rendered_manifest(text)
        if PRIVATE_PATTERN.search(text):
            msg = f"private material in generated Git tree: {path}"
            _fail("BOOTSTRAP_CYCLE", msg)


def bootstrap_flux_registry(state: ProofState) -> None:
    """Bootstrap Flux and the authenticated in-cluster OCI registry."""
    state.phase = Phase.BOOTSTRAP
    run(("git", "clone", "--no-hardlinks", state.paths.repo, state.paths.clone))
    run(
        ("git", "checkout", "-b", state.branch),
        context=RunContext(cwd=state.paths.clone),
    )
    run(
        ("git", "config", "user.name", "Nohiki OCI Proof"),
        context=RunContext(cwd=state.paths.clone),
    )
    run(
        ("git", "config", "user.email", "oci-proof@localhost"),
        context=RunContext(cwd=state.paths.clone),
    )
    run(
        ("git", "config", "commit.gpgSign", "false"),
        context=RunContext(cwd=state.paths.clone),
    )
    run(("git", "init", "--bare", state.paths.bare))
    run(
        ("git", "remote", "add", "proof", state.paths.bare),
        context=RunContext(cwd=state.paths.clone),
    )
    # origin is the bare repository consumed by git daemon; retain source as upstream.
    run(
        ("git", "remote", "rename", "origin", "upstream"),
        context=RunContext(cwd=state.paths.clone),
    )
    run(
        ("git", "remote", "rename", "proof", "origin"),
        context=RunContext(cwd=state.paths.clone),
    )
    _write_initial_overlay(state)
    state.commits["initial"] = _git_commit(state, "proof: bootstrap authenticated registry")
    git = shutil.which("git")
    if git is None:
        msg = "required tool missing: git"
        _fail("PREREQ_HOST", msg)
    state.git_process = _TRUSTED_SUBPROCESS_POPEN(
        (
            git,
            "daemon",
            "--reuseaddr",
            "--base-path",
            state.paths.runtime,
            "--export-all",
            "--enable=upload-pack",
            "--disable=receive-pack",
            "--listen",
            state.node_ip,
            "--port",
            "19418",
            state.paths.bare,
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    run(
        (
            "flux",
            "install",
            "--namespace=flux-system",
            "--components=source-controller,kustomize-controller,helm-controller,notification-controller",
        ),
        context=RunContext(env=os.environ | {"KUBECONFIG": str(state.paths.kubeconfig)}),
    )
    run(
        ("flux", "check"),
        context=RunContext(env=os.environ | {"KUBECONFIG": str(state.paths.kubeconfig)}),
    )
    htpasswd = state.paths.runtime / "htpasswd"
    auth_secret = run(
        (
            "kubectl",
            "create",
            "secret",
            "generic",
            "nohiki-registry-auth",
            "-n",
            "nohiki-registry",
            f"--from-file=htpasswd={htpasswd}",
            "--dry-run=client",
            "-o",
            "yaml",
        )
    ).stdout
    # Namespace and secret must precede the Deployment reconciliation.
    _kubectl(state, "create", "namespace", "nohiki-registry", check=False)
    _kubectl(state, "apply", "-f", "-", input_text=auth_secret)
    docker_secret = run(
        (
            "kubectl",
            "create",
            "secret",
            "generic",
            "nohiki-oci-registry-auth",
            "-n",
            "flux-system",
            "--type=kubernetes.io/dockerconfigjson",
            f"--from-file=.dockerconfigjson={state.paths.docker_config}",
            "--dry-run=client",
            "-o",
            "yaml",
        )
    ).stdout
    _kubectl(state, "apply", "-f", "-", input_text=docker_secret)
    invalid = state.paths.runtime / "invalid-docker.json"
    _private_write(
        invalid,
        _docker_config((state.registry,), state.username, secrets.token_urlsafe(32)),
    )
    invalid_secret = run(
        (
            "kubectl",
            "create",
            "secret",
            "generic",
            "nohiki-oci-registry-auth-invalid",
            "-n",
            "flux-system",
            "--type=kubernetes.io/dockerconfigjson",
            f"--from-file=.dockerconfigjson={invalid}",
            "--dry-run=client",
            "-o",
            "yaml",
        )
    ).stdout
    _kubectl(state, "apply", "-f", "-", input_text=invalid_secret)
    _copy_secret_sources(state)
    template = state.paths.repo / "infra/k8s/oci-proof/manifests/bootstrap-source.yaml.in"
    rendered = render_template(
        template,
        {
            "GIT_BRANCH": state.branch,
            "GIT_URL": f"git://{state.node_ip}:19418/nohiki.git",
        },
    )
    _kubectl(state, "apply", "-f", "-", input_text=rendered)
    _wait_resource(state, "gitrepository", "flux-system", "flux-system", "5m")
    _wait_resource(state, "kustomization", "flux-system", "flux-system", "10m")
    _wait_resource(state, "kustomization", "registry", "flux-system", "10m")
    _wait_registry(state)


def _wait_registry(state: ProofState) -> None:
    encoded = base64.b64encode(f"{state.username}:{state.password}".encode()).decode()
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        request = Request(
            f"http://{state.registry}/v2/",
            headers={"Authorization": f"Basic {encoded}"},
        )
        parsed = urlsplit(request.full_url)
        if parsed.scheme != "http" or parsed.netloc != state.registry:
            msg = "registry readiness URL escaped the authenticated HTTP endpoint"
            _fail("REGISTRY_REACHABILITY_OR_AUTH", msg)
        try:
            with _TRUSTED_URLOPEN(request, timeout=3) as response:
                if response.status == HTTP_OK:
                    return
        except HTTPError, URLError, TimeoutError:
            time.sleep(2)
    msg = "authenticated registry never became ready"
    _fail("REGISTRY_REACHABILITY_OR_AUTH", msg)


def _helm_env(state: ProofState) -> dict[str, str]:
    return os.environ | {
        "HELM_REGISTRY_CONFIG": str(state.paths.docker_config),
        "HELM_REPOSITORY_CACHE": str(state.paths.runtime / "helm-cache"),
        "HELM_REPOSITORY_CONFIG": str(state.paths.runtime / "helm-repositories.yaml"),
    }


def _cosign_env(state: ProofState, *, wrong: bool = False) -> dict[str, str]:
    return os.environ | {"COSIGN_PASSWORD": state.wrong_cosign_password if wrong else state.cosign_password}


def _build_one(state: ProofState, chart_dir: Path, chart_name: str, version: str, label: str) -> Package:
    raw_a = state.paths.runtime / "packages" / label / "raw-a"
    raw_b = state.paths.runtime / "packages" / label / "raw-b"
    raw_a.mkdir(parents=True)
    raw_b.mkdir(parents=True)
    for output in (raw_a, raw_b):
        run(
            (
                "helm",
                "package",
                chart_dir,
                "--version",
                version,
                "--destination",
                output,
            ),
            context=RunContext(env=_helm_env(state)),
        )
    first = raw_a / f"{chart_name}-{version}.tgz"
    second = raw_b / f"{chart_name}-{version}.tgz"
    canonical_a = state.paths.runtime / "packages" / label / f"{chart_name}-{version}-a.tgz"
    canonical_b = state.paths.runtime / "packages" / label / f"{chart_name}-{version}-b.tgz"
    canonicalize_chart(first, canonical_a)
    canonicalize_chart(second, canonical_b)
    require(
        condition=canonical_a.read_bytes() == canonical_b.read_bytes(),
        contract="PACKAGE_REPRODUCIBLE",
        message=f"repeated package differs: {chart_name}:{version}",
    )
    final = state.paths.runtime / "packages" / f"{chart_name}-{version}.tgz"
    shutil.copyfile(canonical_a, final)
    return Package(chart_name, version, final, sha256_file(final))


def _skopeo_digest(state: ProofState, repository: str, tag: str) -> str:
    output = run(
        (
            "skopeo",
            "inspect",
            "--authfile",
            state.paths.docker_config,
            "--tls-verify=false",
            f"docker://{repository}:{tag}",
        )
    ).stdout
    digest = json.loads(output)["Digest"]
    require(
        condition=bool(DIGEST_RE.fullmatch(digest)),
        contract="REGISTRY_REACHABILITY_OR_AUTH",
        message=f"registry returned invalid digest: {digest}",
    )
    return digest


def _sign(state: ProofState, repository: str, digest: str, *, wrong: bool = False) -> None:
    key = state.paths.runtime / ("wrong.key" if wrong else "trusted.key")
    try:
        run(
            (
                "cosign",
                "sign",
                "--yes",
                "--key",
                key,
                "--allow-insecure-registry",
                "--tlog-upload=false",
                f"{repository}@{digest}",
            ),
            context=RunContext(env=_cosign_env(state, wrong=wrong)),
            redact_output=True,
        )
    except RuntimeError as exc:
        msg = f"registry could not store Cosign signature for {repository}@{digest}"
        error = ContractError("REGISTRY_SIGNATURE_COMPATIBILITY", msg)
        raise error from exc


def build_publish(state: ProofState) -> None:
    """Build canonical packages, publish them, and verify signed digests."""
    state.phase = Phase.BUILD
    before = {relative: source_hashes(state.paths.clone / relative) for relative, *_ in CHARTS}
    run(
        ("just", "helm-dependencies"),
        context=RunContext(cwd=state.paths.clone, env=_helm_env(state)),
    )
    package_evidence: list[dict[str, object]] = []
    for relative, chart_name, v1, v2 in CHARTS:
        chart_dir = state.paths.clone / relative
        closure = validate_package_closure(chart_dir, before[relative])
        p1 = _build_one(state, chart_dir, chart_name, v1, f"{chart_name}-v1")
        p2 = _build_one(state, chart_dir, chart_name, v2, f"{chart_name}-v2")
        validate_version_only_packages(p1.path, p2.path, (v1, v2))
        state.packages[(chart_name, v1)] = p1
        state.packages[(chart_name, v2)] = p2
        package_evidence.extend(
            {
                "chart": item.chart,
                "version": item.version,
                "sha256": item.sha256,
                "size": item.path.stat().st_size,
                "lockArchives": [dataclasses.asdict(c) | {"archive": c.archive.name} for c in closure],
            }
            for item in (p1, p2)
        )
    atomic_json(
        state.paths.evidence / "packages.json",
        {"schemaVersion": SCHEMA_VERSION, "packages": package_evidence},
    )
    # Publish first-party images before chart reconciliation.
    runtime = os.environ.get("CONTAINER_RUNTIME", "podman")
    run(
        (
            "uv",
            "run",
            "python",
            "infra/k8s/local/image_foundation.py",
            "build",
            "--runtime",
            runtime,
        ),
        context=RunContext(cwd=state.paths.clone),
    )
    digest_values = state.paths.clone / "infra/k8s/gitops/platform/local/image-digests.values.yaml"
    digest_inventory = state.paths.runtime / "image-digests.json"
    run(
        (
            "uv",
            "run",
            "python",
            "infra/k8s/local/image_foundation.py",
            "publish",
            "--runtime",
            runtime,
            "--registry-auth-file",
            state.paths.docker_config,
            "--digests",
            digest_inventory,
        ),
        context=RunContext(cwd=state.paths.clone),
        redact_output=True,
    )
    rendered_values = run(
        (
            "uv",
            "run",
            "python",
            "infra/k8s/local/image_foundation.py",
            "render-values",
            "--digests",
            digest_inventory,
        ),
        context=RunContext(cwd=state.paths.clone),
    ).stdout
    digest_values.write_text(rendered_values, encoding="utf-8")
    state.cosign_password = secrets.token_urlsafe(36)
    state.wrong_cosign_password = secrets.token_urlsafe(36)
    run(
        (
            "cosign",
            "generate-key-pair",
            "--output-key-prefix",
            state.paths.runtime / "trusted",
        ),
        context=RunContext(env=_cosign_env(state)),
        redact_output=True,
    )
    run(
        (
            "cosign",
            "generate-key-pair",
            "--output-key-prefix",
            state.paths.runtime / "wrong",
        ),
        context=RunContext(env=_cosign_env(state, wrong=True)),
        redact_output=True,
    )
    registry_inventory: list[dict[str, str]] = []
    for key, package in tuple(state.packages.items()):
        repository = f"{state.registry}/nohiki/charts/{package.chart}"
        run(
            (
                "helm",
                "push",
                package.path,
                f"oci://{state.registry}/nohiki/charts",
                "--plain-http",
            ),
            context=RunContext(env=_helm_env(state)),
            redact_output=True,
        )
        digest = _skopeo_digest(state, repository, package.version)
        state.packages[key] = dataclasses.replace(package, registry_digest=digest)
        registry_inventory.append({"repository": repository, "tag": package.version, "digest": digest})
    for chart, version in (
        ("nohiki-foundation", "0.1.0"),
        ("nohiki", "0.2.0"),
        ("nohiki", "0.2.1"),
    ):
        package = state.packages[(chart, version)]
        repository = f"{state.registry}/nohiki/charts/{chart}"
        _sign(state, repository, package.registry_digest)
        run(
            (
                "cosign",
                "verify",
                "--key",
                state.paths.runtime / "trusted.pub",
                "--allow-insecure-registry",
                "--insecure-ignore-tlog",
                f"{repository}@{package.registry_digest}",
            ),
            redact_output=True,
        )
    atomic_json(
        state.paths.evidence / "registry.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "endpoint": state.registry,
            "artifacts": registry_inventory,
        },
    )
    atomic_json(
        state.paths.evidence / "keys.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "trustedPublicSha256": sha256_file(state.paths.runtime / "trusted.pub"),
            "wrongPublicSha256": sha256_file(state.paths.runtime / "wrong.pub"),
            "privateMaterialRecorded": False,
        },
    )


def _object_json(state: ProofState, kind: str, name: str, namespace: str) -> dict[str, object] | None:
    completed = _kubectl(state, "get", kind, name, "-n", namespace, "-o", "json", check=False)
    if completed.returncode:
        return None
    return json.loads(completed.stdout)


def _negative_case(state: ProofState, case: str, digest: str, auth_secret: str, failure_contract: str) -> None:
    case_name = case.lower().replace("_", "-")
    rendered = render_template(
        state.paths.repo / "infra/k8s/oci-proof/manifests/negative-case.yaml.in",
        {
            "CASE": case_name,
            "REGISTRY": state.registry,
            "DIGEST": digest,
            "AUTH_SECRET": auth_secret,
        },
    )
    namespace = f"nohiki-proof-negative-{case_name}"
    require(
        condition=_object_json(state, "namespace", namespace, "default") is None,
        contract=failure_contract,
        message=f"negative namespace exists before {case}",
    )
    _kubectl(state, "apply", "-f", "-", input_text=rendered)
    run(
        (
            "flux",
            "reconcile",
            "source",
            "oci",
            f"nohiki-foundation-negative-{case_name}",
            "-n",
            "flux-system",
            "--timeout=2m",
        ),
        context=RunContext(env=os.environ | {"KUBECONFIG": str(state.paths.kubeconfig)}),
        check=False,
    )
    deadline = time.monotonic() + 180
    source: dict[str, object] | None = None
    while time.monotonic() < deadline:
        source = _object_json(
            state,
            "ocirepository",
            f"nohiki-foundation-negative-{case_name}",
            "flux-system",
        )
        if source and source.get("status", {}).get("observedGeneration") == source.get("metadata", {}).get(
            "generation"
        ):
            conditions = source.get("status", {}).get("conditions", [])
            if any(item.get("type") == "Ready" and item.get("status") == "False" for item in conditions):
                break
        time.sleep(2)
    require(
        condition=source is not None,
        contract=failure_contract,
        message=f"negative OCIRepository vanished: {case}",
    )
    status = source.get("status", {})
    conditions = status.get("conditions", [])
    require(
        condition=any(item.get("type") == "Ready" and item.get("status") == "False" for item in conditions),
        contract=failure_contract,
        message=f"source did not fail: {case}",
    )
    require(
        condition="artifact" not in status,
        contract=failure_contract,
        message=f"failed source produced artifact: {case}",
    )
    require(
        condition=not any(item.get("type") == "SourceVerified" and item.get("status") == "True" for item in conditions),
        contract=failure_contract,
        message=f"failed source reported successful verification: {case}",
    )
    condition_text = " ".join(f"{item.get('reason', '')} {item.get('message', '')}" for item in conditions).lower()
    expected_failure = {
        "UNSIGNED": r"signature|verification|no signatures",
        "WRONG_KEY": r"signature|verification|public key",
        "AUTH": r"unauthorized|authentication|401",
        "DIGEST": r"manifest unknown|not found|404|digest",
    }[case]
    require(
        condition=re.search(expected_failure, condition_text) is not None,
        contract=failure_contract,
        message=f"source failed for the wrong reason in {case}: {condition_text}",
    )
    release = (
        _object_json(
            state,
            "helmrelease",
            f"nohiki-foundation-negative-{case_name}",
            "flux-system",
        )
        or {}
    )
    release_status = release.get("status", {})
    require(
        condition=not release_status.get("history") and not release_status.get("lastAttemptedReleaseAction"),
        contract=failure_contract,
        message=f"Helm began negative case: {case}",
    )
    require(
        condition=_object_json(state, "namespace", namespace, "default") is None,
        contract=failure_contract,
        message=f"Helm created namespace for negative case: {case}",
    )
    secrets_result = _kubectl(
        state,
        "get",
        "secret",
        "-n",
        namespace,
        "-l",
        "owner=helm",
        "-o",
        "json",
        check=False,
    )
    require(
        condition=secrets_result.returncode != 0 or not json.loads(secrets_result.stdout).get("items"),
        contract=failure_contract,
        message=f"Helm storage exists: {case}",
    )
    events = _kubectl(
        state,
        "get",
        "events",
        "-n",
        "flux-system",
        "--field-selector",
        f"involvedObject.name=nohiki-foundation-negative-{case_name}",
        "-o",
        "json",
        check=False,
    )
    event_document = json.loads(events.stdout) if events.returncode == 0 else {}
    event_text = json.dumps(event_document).lower()
    require(
        condition="installstarted" not in event_text and "installsucceeded" not in event_text,
        contract=failure_contract,
        message=f"Helm install event exists for negative case: {case}",
    )
    controller_logs = str(redact(_controller_logs(state)[-8000:]))
    evidence = {
        "schemaVersion": SCHEMA_VERSION,
        "case": case,
        "source": redact(source),
        "release": redact(release),
        "events": redact(event_document),
        "targetNamespaceAbsent": True,
        "helmStorageAbsent": True,
        "helmInstallEventsAbsent": True,
        "controllerLogs": controller_logs,
        "verdict": "PASS",
    }
    atomic_json(state.paths.evidence / "negative" / case.lower() / "result.json", evidence)
    _kubectl(state, "delete", "-f", "-", "--ignore-not-found", input_text=rendered)


def prove_negatives(state: ProofState) -> None:
    """Prove wrong-signature, wrong-key, and wrong-auth cases fail before Helm."""
    state.phase = Phase.NEGATIVE
    foundation_v1 = state.packages[("nohiki-foundation", "0.1.0")]
    foundation_v2 = state.packages[("nohiki-foundation", "0.1.1")]
    _negative_case(
        state,
        "UNSIGNED",
        foundation_v2.registry_digest,
        "nohiki-oci-registry-auth",
        "COSIGN_ENFORCEMENT",
    )
    repository = f"{state.registry}/nohiki/charts/nohiki-foundation"
    _sign(state, repository, foundation_v2.registry_digest, wrong=True)
    _negative_case(
        state,
        "WRONG_KEY",
        foundation_v2.registry_digest,
        "nohiki-oci-registry-auth",
        "COSIGN_ENFORCEMENT",
    )
    _negative_case(
        state,
        "AUTH",
        foundation_v1.registry_digest,
        "nohiki-oci-registry-auth-invalid",
        "AUTH_OR_DIGEST_ENFORCEMENT",
    )
    _negative_case(
        state,
        "DIGEST",
        mutated_digest(foundation_v1.registry_digest),
        "nohiki-oci-registry-auth",
        "AUTH_OR_DIGEST_ENFORCEMENT",
    )
    _sign(state, repository, foundation_v2.registry_digest)
    run(
        (
            "cosign",
            "verify",
            "--key",
            state.paths.runtime / "trusted.pub",
            "--allow-insecure-registry",
            "--insecure-ignore-tlog",
            f"{repository}@{foundation_v2.registry_digest}",
        ),
        redact_output=True,
    )


def _write_full_overlay(state: ProofState, versions: Mapping[str, str]) -> None:
    root = _generated_root(state)
    for directory in (root / "trust", root / "foundation", root / "platform"):
        directory.mkdir(parents=True, exist_ok=True)
    public_key = (state.paths.runtime / "trusted.pub").read_text(encoding="utf-8")
    encoded_public = base64.b64encode(public_key.encode()).decode()
    (root / "trust/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n  - public-key.yaml\n",
        encoding="utf-8",
    )
    (root / "trust/public-key.yaml").write_text(
        "apiVersion: v1\nkind: Secret\nmetadata:\n"
        "  name: nohiki-oci-cosign-public-key\n  namespace: flux-system\n"
        f"type: Opaque\ndata:\n  cosign.pub: {encoded_public}\n",
        encoding="utf-8",
    )
    foundation = state.packages[("nohiki-foundation", versions["nohiki-foundation"])]
    platform = state.packages[("nohiki", versions["nohiki"])]
    (root / "foundation/source.yaml").write_text(
        render_template(
            state.paths.repo / "infra/k8s/oci-proof/manifests/foundation-ocirepository.yaml.in",
            {"REGISTRY": state.registry, "DIGEST": foundation.registry_digest},
        ),
        encoding="utf-8",
    )
    release_patches = (
        (state.paths.repo / "infra/k8s/oci-proof/manifests/helmrelease-patches.yaml")
        .read_text(encoding="utf-8")
        .split("\n---\n")
    )
    require(
        condition=len(release_patches) == EXPECTED_RELEASE_PATCH_DOCUMENTS,
        contract="BOOTSTRAP_CYCLE",
        message="reviewed HelmRelease patch file must contain exactly two documents",
    )
    (root / "foundation/release-patch.yaml").write_text(release_patches[0] + "\n", encoding="utf-8")
    (root / "platform/release-patch.yaml").write_text(release_patches[1] + "\n", encoding="utf-8")
    (root / "foundation/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\n"
        "kind: Kustomization\nresources:\n"
        "  - ../../../gitops/infrastructure/local\n  - source.yaml\n"
        "patches:\n  - path: release-patch.yaml\n",
        encoding="utf-8",
    )
    (root / "platform/source.yaml").write_text(
        render_template(
            state.paths.repo / "infra/k8s/oci-proof/manifests/platform-ocirepository.yaml.in",
            {"REGISTRY": state.registry, "DIGEST": platform.registry_digest},
        ),
        encoding="utf-8",
    )
    values = (state.paths.clone / "infra/k8s/helm/values.local.yaml").read_text(encoding="utf-8")
    digest_values = (state.paths.clone / "infra/k8s/gitops/platform/local/image-digests.values.yaml").read_text(
        encoding="utf-8"
    )
    for name, content in (
        ("local-values.yaml", values),
        ("image-digests.yaml", digest_values),
    ):
        (root / "platform" / name).write_text(content, encoding="utf-8")
    values_hash = hashlib.sha256(values.encode()).hexdigest()
    (root / "platform/kustomization.yaml").write_text(
        f"""apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../../gitops/platform/base
  - source.yaml
configMapGenerator:
  - name: nohiki-oci-local-values
    namespace: flux-system
    files:
      - values.yaml=local-values.yaml
    options:
      annotations:
        nohiki.io/source-sha256: {values_hash}
  - name: nohiki-image-digests
    namespace: flux-system
    files:
      - values.yaml=image-digests.yaml
generatorOptions:
  disableNameSuffixHash: true
patches:
  - path: release-patch.yaml
""",
        encoding="utf-8",
    )
    cluster = root / "cluster"
    cluster.mkdir(parents=True, exist_ok=True)
    resources = [
        "gateway-api-crds.yaml",
        "registry.yaml",
        "oci-trust.yaml",
        "infrastructure.yaml",
        "runtime-secrets.yaml",
        "platform.yaml",
        "observability.yaml",
        "health.yaml",
        "verification-api.yaml",
        "verification-playwright.yaml",
    ]
    (cluster / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n"
        + "".join(f"  - {item}\n" for item in resources),
        encoding="utf-8",
    )
    local = state.paths.clone / "infra/k8s/gitops/clusters/local"
    for filename in resources:
        if filename == "oci-trust.yaml":
            text = """apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: oci-trust
  namespace: flux-system
spec:
  interval: 10m
  path: ./infra/k8s/oci-proof/generated/trust
  prune: true
  sourceRef: {kind: GitRepository, name: flux-system}
  wait: true
"""
        else:
            text = (local / filename).read_text(encoding="utf-8")
            if filename == "infrastructure.yaml":
                text = text.replace(
                    "    - name: gateway-api-crds\n",
                    "    - name: gateway-api-crds\n    - name: registry\n    - name: oci-trust\n",
                ).replace(
                    "./infra/k8s/gitops/infrastructure/local",
                    "./infra/k8s/oci-proof/generated/foundation",
                )
            elif filename == "platform.yaml":
                text = text.replace(
                    "./infra/k8s/gitops/platform/local",
                    "./infra/k8s/oci-proof/generated/platform",
                )
        (cluster / filename).write_text(text, encoding="utf-8")
    validate_generated_tree(root)


def _reconcile_stack(state: ProofState, name: str, timeout: str = "65m") -> None:
    run(
        (
            "flux",
            "reconcile",
            "kustomization",
            name,
            "-n",
            "flux-system",
            "--with-source",
            f"--timeout={timeout}",
        ),
        context=RunContext(env=os.environ | {"KUBECONFIG": str(state.paths.kubeconfig)}),
    )


def _assert_positive(
    state: ProofState,
    versions: Mapping[str, str],
    evidence_dir: str,
    minimum_history: int,
) -> None:
    result: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "sources": {},
        "releases": {},
    }
    for source_name, chart_name in (
        ("nohiki-foundation-chart", "nohiki-foundation"),
        ("nohiki-platform-chart", "nohiki"),
    ):
        package = state.packages[(chart_name, versions[chart_name])]
        source = _object_json(state, "ocirepository", source_name, "flux-system") or {}
        conditions = source.get("status", {}).get("conditions", [])
        require(
            condition=source.get("status", {}).get("observedGeneration")
            == source.get("metadata", {}).get("generation"),
            contract="DIRECT_CHARTREF_OPERATION",
            message=f"source has not observed its current generation: {source_name}",
        )
        require(
            condition=any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions),
            contract="DIRECT_CHARTREF_OPERATION",
            message=f"source not Ready: {source_name}",
        )
        require(
            condition=any(c.get("type") == "SourceVerified" and c.get("status") == "True" for c in conditions),
            contract="DIRECT_CHARTREF_OPERATION",
            message=f"source not verified: {source_name}",
        )
        revision = str(source.get("status", {}).get("artifact", {}).get("revision", ""))
        require(
            condition=revision.endswith(package.registry_digest),
            contract="DIRECT_CHARTREF_OPERATION",
            message=f"source revision is not exact digest: {source_name}",
        )
        result["sources"][source_name] = redact(source)  # type: ignore[index]
        release = _object_json(state, "helmrelease", chart_name, "flux-system") or {}
        release_conditions = release.get("status", {}).get("conditions", [])
        require(
            condition=any(c.get("type") == "Ready" and c.get("status") == "True" for c in release_conditions),
            contract="DIRECT_CHARTREF_OPERATION",
            message=f"HelmRelease not Ready: {chart_name}",
        )
        history = release.get("status", {}).get("history", [])
        require(
            condition=len(history) >= minimum_history,
            contract="DIRECT_CHARTREF_OPERATION",
            message=f"release history too short: {chart_name}",
        )
        revisions = [int(item.get("version", 0)) for item in history]
        require(
            condition=revisions and max(revisions) == minimum_history,
            contract="DIRECT_CHARTREF_OPERATION",
            message=f"unexpected Helm history revision for {chart_name}: {revisions}",
        )
        attempted = str(release.get("status", {}).get("lastAttemptedRevision", ""))
        require(
            condition=attempted.startswith(versions[chart_name] + "+")
            and package.registry_digest.removeprefix("sha256:")[:12] in attempted,
            contract="DIRECT_CHARTREF_OPERATION",
            message=f"wrong attempted revision: {chart_name}: {attempted}",
        )
        result["releases"][chart_name] = redact(release)  # type: ignore[index]
    atomic_json(state.paths.evidence / evidence_dir / "state.json", result)
    jobs = _kubectl(state, "get", "jobs", "-A", "-o", "json", check=False)
    atomic_json(
        state.paths.evidence / evidence_dir / "jobs.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "jobs": redact(json.loads(jobs.stdout)) if jobs.returncode == 0 else {"unavailable": True},
        },
    )


def positive_v1(state: ProofState) -> None:
    """Reconcile and verify the initial signed chart versions."""
    state.phase = Phase.V1
    versions = {"nohiki-foundation": "0.1.0", "nohiki": "0.2.0"}
    _write_full_overlay(state, versions)
    state.commits["v1"] = _git_commit(state, "proof: reconcile signed OCI charts at v1 digests")
    for stack in (
        "flux-system",
        "gateway-api-crds",
        "registry",
        "oci-trust",
        "infrastructure",
        "runtime-secrets",
        "platform",
        "observability",
        "health-verification",
        "api-verification",
        "playwright-verification",
    ):
        _reconcile_stack(state, stack)
    _assert_positive(state, versions, "reconcile-v1", 1)


def _set_isolation(state: ProofState) -> None:
    no_proxy = (
        f"127.0.0.1,localhost,.svc,.cluster.local,kubernetes.default.svc,{state.node_ip},{state.registry.split(':')[0]}"
    )
    for deployment in ("source-controller", "helm-controller"):
        _kubectl(
            state,
            "set",
            "env",
            f"deployment/{deployment}",
            "-n",
            "flux-system",
            "HTTP_PROXY=http://127.0.0.1:9",
            "HTTPS_PROXY=http://127.0.0.1:9",
            f"NO_PROXY={no_proxy}",
        )
        _kubectl(
            state,
            "rollout",
            "status",
            f"deployment/{deployment}",
            "-n",
            "flux-system",
            "--timeout=5m",
        )
    atomic_json(
        state.paths.evidence / "isolation/config.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "httpProxy": "http://127.0.0.1:9",
            "noProxy": no_proxy,
        },
    )


def _controller_logs(state: ProofState) -> str:
    chunks = []
    for deployment in ("source-controller", "helm-controller"):
        completed = _kubectl(
            state,
            "logs",
            f"deployment/{deployment}",
            "-n",
            "flux-system",
            "--since=2h",
            check=False,
        )
        chunks.append(completed.stdout)
    return "\n".join(chunks)


def _assert_dependency_isolation(state: ProofState) -> None:
    endpoints: set[str] = set()
    for relative, *_ in CHARTS:
        _, dependencies = _lock_data(state.paths.clone / relative / "Chart.lock")
        for _, _, repository in dependencies:
            match = re.match(r"(?:https?|oci)://([^/]+)", repository)
            if match:
                endpoints.add(match.group(1).lower())
    logs = _controller_logs(state).lower()
    contacted = sorted(endpoint for endpoint in endpoints if endpoint in logs)
    require(
        condition=not contacted,
        contract="DEPENDENCY_ISOLATION",
        message=f"controller contacted dependency endpoints: {contacted}",
    )
    atomic_json(
        state.paths.evidence / "isolation/endpoints.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "blocked": sorted(endpoints),
            "contacted": contacted,
        },
    )


def isolated_upgrade(state: ProofState) -> None:
    """Upgrade both charts while proving dependency-network isolation."""
    state.phase = Phase.UPGRADE
    _set_isolation(state)
    shutil.rmtree(state.paths.runtime / "helm-cache", ignore_errors=True)
    versions = {"nohiki-foundation": "0.1.1", "nohiki": "0.2.1"}
    _write_full_overlay(state, versions)
    state.commits["upgrade"] = _git_commit(state, "proof: advance both OCI sources to v2 digests")
    for stack in (
        "flux-system",
        "infrastructure",
        "platform",
        "observability",
        "health-verification",
        "api-verification",
        "playwright-verification",
    ):
        _reconcile_stack(state, stack)
    _assert_positive(state, versions, "upgrade-v2", 2)
    _assert_dependency_isolation(state)


def _verify_tail(state: ProofState) -> None:
    env = os.environ | {
        "KUBECONFIG": str(state.paths.kubeconfig),
        "K8S_LOCAL_CONTEXT": run(
            (
                "kubectl",
                "--kubeconfig",
                state.paths.kubeconfig,
                "config",
                "current-context",
            )
        ).stdout.strip(),
        "K8S_EVIDENCE_DIR": str(state.paths.evidence / "jobs"),
        "NOHIKI_REGISTRY_AUTH_FILE": str(state.paths.docker_config),
    }
    completed = run(
        ("infra/k8s/local/lifecycle.sh", "verify"),
        context=RunContext(cwd=state.paths.clone, env=env),
        redact_output=True,
    )
    output = state.paths.evidence / "jobs/verify-output.redacted.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(str(redact(completed.stdout)), encoding="utf-8")


def rollback_drift_verify(state: ProofState) -> None:
    """Roll back, correct live drift, and run end-to-end verification."""
    state.phase = Phase.ROLLBACK
    versions = {"nohiki-foundation": "0.1.0", "nohiki": "0.2.0"}
    _write_full_overlay(state, versions)
    state.commits["rollback"] = _git_commit(state, "proof: roll both OCI sources back to v1 digests")
    for stack in (
        "flux-system",
        "infrastructure",
        "platform",
        "observability",
        "health-verification",
        "api-verification",
        "playwright-verification",
    ):
        _reconcile_stack(state, stack)
    _assert_positive(state, versions, "rollback-v1", 3)
    _assert_dependency_isolation(state)
    before = json.loads(_kubectl(state, "get", "gateway", "nohiki-gateway", "-n", "nohiki", "-o", "json").stdout)
    original = before.get("metadata", {}).get("labels", {}).get("nohiki.io/oci-proof-drift")
    _kubectl(
        state,
        "label",
        "gateway/nohiki-gateway",
        "-n",
        "nohiki",
        "nohiki.io/oci-proof-drift=tampered",
        "--overwrite",
    )
    tampered = json.loads(_kubectl(state, "get", "gateway", "nohiki-gateway", "-n", "nohiki", "-o", "json").stdout)
    deadline = time.monotonic() + 600
    after: dict[str, object] = {}
    while time.monotonic() < deadline:
        after = json.loads(_kubectl(state, "get", "gateway", "nohiki-gateway", "-n", "nohiki", "-o", "json").stdout)
        current = after.get("metadata", {}).get("labels", {}).get("nohiki.io/oci-proof-drift")
        if current == original:
            break
        time.sleep(5)
    require(
        condition=after.get("metadata", {}).get("labels", {}).get("nohiki.io/oci-proof-drift") == original,
        contract="DRIFT_CORRECTION",
        message="helm-controller did not correct Gateway drift",
    )
    atomic_json(
        state.paths.evidence / "drift/state.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "before": redact(before),
            "tampered": redact(tampered),
            "after": redact(after),
        },
    )
    _verify_tail(state)


def write_git_evidence(state: ProofState) -> None:
    """Write redacted Git commit and rendered-manifest evidence."""
    generated = _generated_root(state)
    manifests: dict[str, object] = {}
    if generated.exists():
        for path in sorted(generated.rglob("*.yaml")):
            manifests[path.relative_to(generated).as_posix()] = redact(path.read_text(encoding="utf-8"))
    atomic_json(
        state.paths.evidence / "git.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "url": f"git://{state.node_ip}:19418/nohiki.git" if state.node_ip else None,
            "branch": state.branch,
            "readOnly": True,
            "commits": state.commits,
            "changedPathAllowlist": ["infra/k8s/oci-proof/generated/**"],
            "renderedManifests": manifests,
        },
    )


def capture_failure(state: ProofState) -> None:
    """Capture redacted cluster and controller evidence after failure."""
    snapshots: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "phase": state.phase,
    }
    for kind in ("ocirepositories", "kustomizations", "helmreleases", "jobs", "events"):
        completed = _kubectl(state, "get", kind, "-A", "-o", "json", check=False)
        snapshots[kind] = (
            redact(json.loads(completed.stdout))
            if completed.returncode == 0 and completed.stdout
            else {"unavailable": True}
        )
    atomic_json(state.paths.evidence / "failure-snapshot.json", snapshots)
    logs = _controller_logs(state)
    (state.paths.evidence / "controller-logs.redacted.txt").write_text(str(redact(logs)), encoding="utf-8")
    if state.unit:
        journal = _privileged("journal", state.unit, check=False)
        (state.paths.evidence / "k3s-journal.redacted.txt").write_text(str(redact(journal.stdout)), encoding="utf-8")


def teardown(state: ProofState) -> dict[str, object]:
    """Unconditionally remove runtime state and record absence checks."""
    state.phase = Phase.TEARDOWN
    if state.git_process is not None:
        state.git_process.terminate()
        try:
            state.git_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            state.git_process.kill()
            state.git_process.wait(timeout=5)
    if state.unit:
        _privileged("stop", state.unit, state.paths.runtime, check=False)
    shutil.rmtree(state.paths.runtime, ignore_errors=True)
    checks = {
        "runtimeAbsent": not state.paths.runtime.exists(),
        "gitPortClosed": _port_free(19418),
        "apiPortClosed": _port_free(6443),
        "registryPortClosed": _port_free(30500),
        "unitInactive": not state.unit or run(("systemctl", "is-active", state.unit), check=False).returncode != 0,
        "privateMaterialAbsent": all(
            not path.exists()
            for path in (
                state.paths.runtime / "trusted.key",
                state.paths.runtime / "wrong.key",
                state.paths.docker_config,
                state.paths.registry_config,
            )
        ),
    }
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "checks": checks,
        "complete": all(checks.values()),
    }
    atomic_json(state.paths.evidence / "teardown.json", result)
    return result


def _archive_evidence(evidence: Path) -> tuple[Path, str]:
    archive_path = evidence / "evidence.tar.gz"
    staging = evidence.parent / f".{evidence.name}-archive"
    raw_tar = io.BytesIO()
    with tarfile.open(fileobj=raw_tar, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted(evidence.rglob("*")):
            if not path.is_file() or path.name.startswith("evidence.tar.gz"):
                continue
            info = archive.gettarinfo(path, arcname=path.relative_to(evidence).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.pax_headers = {}
            with path.open("rb") as stream:
                archive.addfile(info, stream)
    with (
        staging.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as compressed,
    ):
        compressed.write(raw_tar.getvalue())
    staging.replace(archive_path)
    checksum = sha256_file(archive_path)
    (evidence / "evidence.tar.gz.sha256").write_text(f"{checksum}  evidence.tar.gz\n", encoding="utf-8")
    return archive_path, checksum


def _paths(repo: Path, run_id: str) -> ProofPaths:
    evidence = repo / ".artifacts/oci-helm-proof" / run_id
    evidence.mkdir(parents=True, mode=0o700)
    runtime = Path(tempfile.mkdtemp(prefix=f"nohiki-oci-proof-{run_id}-"))
    runtime.chmod(0o700)
    return ProofPaths(
        repo,
        runtime,
        evidence,
        runtime / "clone",
        runtime / "nohiki.git",
        runtime / "kubeconfig.yaml",
        runtime / "registries.yaml",
        runtime / "docker-config.json",
    )


def execute(repo: Path) -> int:
    """Execute the destructive proof and return its CLI status code."""
    os.umask(0o077)
    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    if not RUN_ID_RE.fullmatch(run_id):
        msg = "invalid internal run id"
        raise AssertionError(msg)
    paths = _paths(repo, run_id)
    state = ProofState(paths, run_id, "", f"oci-proof/{run_id.lower()}")
    decision = "FAIL"
    failed_contract: str | None = None
    message = "proof did not complete"
    atomic_json(
        paths.evidence / "result.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "decision": "FAIL",
            "failedContract": None,
            "message": "proof in progress",
            "startedAt": state.started,
            "head": "",
            "commits": {},
            "phase": state.phase,
            "teardown": "pending",
        },
    )
    try:
        state.head, _ = preflight(repo, paths.evidence)
        start_k3s(state)
        bootstrap_flux_registry(state)
        build_publish(state)
        prove_negatives(state)
        positive_v1(state)
        isolated_upgrade(state)
        rollback_drift_verify(state)
        decision = "PASS"
        message = "all deterministic signed OCI Helm delivery contracts passed"
    except ContractError as exc:
        failed_contract = exc.contract
        message = str(exc)
        if paths.kubeconfig.exists():
            capture_failure(state)
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        failed_contract = PHASE_FAILURE_CONTRACT[state.phase]
        message = f"{type(exc).__name__}: {exc}"
        if paths.kubeconfig.exists():
            capture_failure(state)
    finally:
        pre_teardown = {
            "schemaVersion": SCHEMA_VERSION,
            "decision": decision,
            "failedContract": failed_contract,
            "message": message,
            "startedAt": state.started,
            "endedAt": utc_now(),
            "head": state.head,
            "commits": state.commits,
            "phase": state.phase,
        }
        atomic_json(paths.evidence / "result.json", pre_teardown | {"teardown": "pending"})
        write_git_evidence(state)
        teardown_result = teardown(state)
        if not teardown_result["complete"]:
            decision = "FAIL"
            failed_contract = "TEARDOWN_INCOMPLETE"
            message = "one or more teardown absence assertions failed"
        result = pre_teardown | {
            "decision": decision,
            "failedContract": failed_contract,
            "message": message,
            "endedAt": utc_now(),
            "teardown": "PASS" if teardown_result["complete"] else "FAIL",
        }
        atomic_json(paths.evidence / "result.json", result)
        _, checksum = _archive_evidence(paths.evidence)
        sys.stdout.write(f"{decision}: {message}\nevidence={paths.evidence}\nevidenceSha256={checksum}\n")
    return 0 if decision == "PASS" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    live = subparsers.add_parser("run", help="run the destructive disposable native-k3s proof")
    live.add_argument(
        "--repository",
        type=Path,
        default=Path.cwd(),
        help="clean repository root (default: current directory)",
    )
    canonicalize = subparsers.add_parser("canonicalize", help="canonicalize a Helm chart package")
    canonicalize.add_argument("--source", type=Path, required=True)
    canonicalize.add_argument("--destination", type=Path, required=True)
    check = subparsers.add_parser("self-check", help="validate tracked templates and pure fail-closed helpers")
    check.add_argument("--repository", type=Path, default=Path.cwd())
    return parser


def self_check(repo: Path) -> None:
    """Validate tracked templates and pure fail-closed helpers."""
    manifest_dir = repo / "infra/k8s/oci-proof/manifests"
    digest = "sha256:" + "a" * 64
    render_template(
        manifest_dir / "bootstrap-source.yaml.in",
        {
            "GIT_BRANCH": "oci-proof/check",
            "GIT_URL": "git://127.0.0.1:19418/nohiki.git",
        },
    )
    render_template(
        manifest_dir / "foundation-ocirepository.yaml.in",
        {"REGISTRY": "127.0.0.1:30500", "DIGEST": digest},
    )
    render_template(
        manifest_dir / "platform-ocirepository.yaml.in",
        {"REGISTRY": "127.0.0.1:30500", "DIGEST": digest},
    )
    render_template(
        manifest_dir / "negative-case.yaml.in",
        {
            "CASE": "unsigned",
            "REGISTRY": "127.0.0.1:30500",
            "DIGEST": digest,
            "AUTH_SECRET": "nohiki-oci-registry-auth",
        },
    )
    validate_rendered_manifest((manifest_dir / "registry-auth-patch.yaml").read_text())
    validate_rendered_manifest((manifest_dir / "helmrelease-patches.yaml").read_text())
    if mutated_digest(digest) == digest:
        msg = "digest mutation did not change the digest"
        raise AssertionError(msg)
    sys.stdout.write("OCI Helm proof self-check: PASS\n")


def main(argv: Sequence[str] | None = None) -> Never:
    """Parse proof CLI arguments and exit with the selected command status."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "canonicalize":
        source = args.source.resolve()
        destination = args.destination.resolve()
        if source == destination:
            parser.error("--source and --destination must resolve to different paths")
        canonicalize_chart(source, destination)
        raise SystemExit(0)
    repo = args.repository.resolve()
    if args.command == "self-check":
        self_check(repo)
        raise SystemExit(0)
    raise SystemExit(execute(repo))


if __name__ == "__main__":
    main()
