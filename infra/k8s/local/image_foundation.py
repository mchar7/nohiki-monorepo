#!/usr/bin/env python3
"""Build and publish immutable local images without coupling publication to Flux."""

from __future__ import annotations

import argparse
import http.client
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn, NotRequired, TypedDict, cast


class Image(TypedDict):
    """A validated first-party image inventory entry."""

    name: str
    context: str
    dockerfile: str
    local: bool
    buildArgs: NotRequired[dict[str, str]]


class DigestEntry(TypedDict):
    """An immutable image tag and registry digest pair."""

    tag: str
    digest: str


class DigestDocument(TypedDict):
    """The validated immutable image digest inventory."""

    schemaVersion: int
    registry: str
    images: dict[str, DigestEntry]


type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]

ROOT = Path(__file__).resolve().parents[3]
INVENTORY = Path(__file__).with_name("images.json")
LOCAL_IMAGE_ID_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TAG_RE = re.compile(r"^sha256-[0-9a-f]{64}$")
NAME_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
LOCAL_ENDPOINT_RE = re.compile(r"http://(?:127\.0\.0\.1|localhost):[0-9]{2,5}")
LOGICAL_REGISTRY = "localhost:5000"
DEFAULT_ENDPOINT = "http://127.0.0.1:30500"
HTTP_OK = http.client.OK
PORT_FORWARD_TIMEOUT_SECONDS = 15
COMMANDS = frozenset({"docker", "kubectl", "podman"})
PUBLISH_MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)
STATUS_MANIFEST_ACCEPT = (
    "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"
)

# These aliases are the single subprocess trust boundary. Every argv reaches them
# only after _trusted_argv validates the executable against COMMANDS.
_TRUSTED_RUN = subprocess.run
_TRUSTED_POPEN = subprocess.Popen


def fail(message: str) -> NoReturn:
    """Exit with an operator-facing error message."""
    msg = f"ERROR: {message}"
    raise SystemExit(msg)


def _canonical_image_digest(image_id: str, source: str) -> str:
    """Normalize a runtime image ID to the canonical sha256 digest form."""
    if LOCAL_IMAGE_ID_RE.fullmatch(image_id):
        return f"sha256:{image_id}"
    if DIGEST_RE.fullmatch(image_id):
        return image_id
    fail(f"local image {source} has no content digest; run build first")


def _write_line(message: str) -> None:
    sys.stdout.write(f"{message}\n")


def load_json(path: Path) -> dict[str, JsonValue]:
    """Load a JSON object from a path, failing closed on invalid input."""
    try:
        value = cast(JsonValue, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read valid JSON from {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"{path} must contain a JSON object")
    return value


def _validate_image(index: int, value: JsonValue, names: set[str]) -> Image:
    if not isinstance(value, dict):
        fail(f"images[{index}] must be an object")
    missing = {"name", "context", "dockerfile", "local"} - value.keys()
    if missing:
        fail(f"images[{index}] is missing {', '.join(sorted(missing))}")
    name = value["name"]
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        fail(f"images[{index}].name is invalid")
    if name in names:
        fail(f"duplicate image name: {name}")
    names.add(name)
    if not isinstance(value["local"], bool):
        fail(f"{name}.local must be boolean")
    context = value["context"]
    dockerfile = value["dockerfile"]
    if not isinstance(context, str) or not isinstance(dockerfile, str):
        fail(f"{name} context and dockerfile must be strings")
    context_path = (ROOT / context).resolve()
    if not context_path.is_relative_to(ROOT):
        fail(f"{name} context escapes the repository")
    if not context_path.is_dir() or not (context_path / dockerfile).is_file():
        fail(f"{name} build source does not exist: {context}/{dockerfile}")
    build_args = value.get("buildArgs", {})
    if not isinstance(build_args, dict) or not all(
        isinstance(key, str) and isinstance(argument, str) for key, argument in build_args.items()
    ):
        fail(f"{name}.buildArgs must map strings to strings")
    return cast(Image, value)


def inventory() -> list[Image]:
    """Load and validate the authoritative first-party image inventory."""
    doc = load_json(INVENTORY)
    values = doc.get("images")
    if doc.get("schemaVersion") != 1 or not isinstance(values, list):
        fail(f"{INVENTORY} must have schemaVersion 1 and an images array")
    names: set[str] = set()
    images = [_validate_image(index, value, names) for index, value in enumerate(values)]
    if not images:
        fail("image inventory is empty")
    return images


def local_images() -> list[Image]:
    """Return the inventory entries built for the local cluster."""
    return [image for image in inventory() if image["local"]]


def runtime_argv(value: str) -> list[str]:
    """Validate a requested container runtime and return its argv prefix."""
    if value not in {"docker", "podman"}:
        fail("--runtime must be exactly docker or podman")
    return [value]


def _trusted_argv(argv: list[str]) -> list[str]:
    if not argv or argv[0] not in COMMANDS:
        fail("refusing to execute a command outside the trusted tool allowlist")
    executable = shutil.which(argv[0])
    if executable is None:
        fail(f"required command not found: {argv[0]}")
    return [executable, *argv[1:]]


def run(argv: list[str], *, capture: bool = False) -> str:
    """Run an allowlisted release command from the repository root."""
    trusted_argv = _trusted_argv(argv)
    try:
        result = _TRUSTED_RUN(
            trusted_argv,
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else f"exit {exc.returncode}"
        fail(f"command failed ({' '.join(argv)}): {detail}")
    return result.stdout.strip() if capture and result.stdout else ""


def mirror_text(endpoint: str) -> str:
    """Render the exact native k3s mirror configuration."""
    if not LOCAL_ENDPOINT_RE.fullmatch(endpoint):
        fail("mirror endpoint must be plaintext HTTP on localhost with an explicit port")
    return f'mirrors:\n  "{LOGICAL_REGISTRY}":\n    endpoint:\n      - "{endpoint}"\n'


def load_digests(path: Path) -> DigestDocument:
    """Load and validate the complete immutable digest inventory."""
    source = load_json(path)
    candidate = source.get("imageFoundation", source)
    if (
        not isinstance(candidate, dict)
        or candidate.get("schemaVersion") != 1
        or candidate.get("registry") != LOGICAL_REGISTRY
    ):
        fail(f"{path} must contain imageFoundation schemaVersion 1 for registry {LOGICAL_REGISTRY}")
    entries = candidate.get("images")
    if not isinstance(entries, dict):
        fail(f"{path}.images must be an object")
    if not all(isinstance(name, str) for name in entries):
        fail(f"{path}.images keys must be strings")
    required = {image["name"] for image in local_images()}
    entry_names = cast(set[str], set(entries))
    if entry_names != required:
        missing = sorted(required - entry_names)
        extra = sorted(entry_names - required)
        fail(f"digest inventory mismatch; missing={missing}, extra={extra}")
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            fail(f"digest entry {name} must be an object")
        digest = entry.get("digest")
        tag = entry.get("tag")
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            fail(f"digest entry {name} has an invalid digest")
        if not isinstance(tag, str) or not TAG_RE.fullmatch(tag):
            fail(f"digest entry {name} tag is not content-addressed")
    return cast(DigestDocument, candidate)


def cmd_validate(_: argparse.Namespace) -> None:
    """Validate and summarize the authoritative image inventory."""
    images = inventory()
    if "frontend" not in {image["name"] for image in images}:
        fail("authoritative inventory must include frontend")
    _write_line(f"valid: {len(images)} first-party images ({len(local_images())} local)")


def cmd_mirror_config(args: argparse.Namespace) -> None:
    """Write native k3s mirror configuration to standard output."""
    sys.stdout.write(mirror_text(args.endpoint))


def cmd_mirror_preflight(args: argparse.Namespace) -> None:
    """Require the installed native k3s mirror configuration to match exactly."""
    expected = mirror_text(args.endpoint)
    try:
        actual = Path(args.config).read_text(encoding="utf-8")
    except OSError as exc:
        fail(
            f"native k3s mirror config {args.config} is unavailable ({exc}); "
            "install the exact output of mirror-config and restart k3s explicitly"
        )
    if actual != expected:
        fail(
            f"native k3s mirror config {args.config} does not exactly map "
            f"{LOGICAL_REGISTRY} to {args.endpoint}; refusing any host-registry fallback"
        )
    _write_line(f"ready: native k3s mirror {LOGICAL_REGISTRY} -> {args.endpoint}")


def cmd_build(args: argparse.Namespace) -> None:
    """Build local or complete first-party image inventory in declaration order."""
    runtime = runtime_argv(args.runtime)
    images = inventory() if args.all else local_images()
    for image in images:
        target = f"nohiki-build/{image['name']}:local"
        command = [
            *runtime,
            "build",
            "--file",
            str(Path(image["context"]) / image["dockerfile"]),
            "--tag",
            target,
        ]
        for key, value in sorted(image.get("buildArgs", {}).items()):
            command.extend(("--build-arg", f"{key}={value}"))
        command.append(image["context"])
        run(command)


def _http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    timeout: float,
) -> tuple[int, http.client.HTTPMessage]:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        fail(f"refusing non-HTTP(S) or malformed registry URL: {url}")
    try:
        port = parsed.port
    except ValueError as exc:
        fail(f"invalid registry URL {url}: {exc}")
    target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = connection_type(parsed.hostname, port, timeout=timeout)
    try:
        connection.request(method, target, headers=headers or {})
        response = connection.getresponse()
        response.read()
        return response.status, response.headers
    finally:
        connection.close()


@contextmanager
def registry_forward() -> Iterator[None]:
    """Forward the in-cluster registry to an exclusively owned local port."""
    probe = socket.socket()
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 5000))
    except OSError as exc:
        fail(f"localhost:5000 is already in use; refusing to publish through an unowned endpoint: {exc}")
    finally:
        probe.close()
    process = _TRUSTED_POPEN(
        _trusted_argv(
            [
                "kubectl",
                "--namespace",
                "nohiki-registry",
                "port-forward",
                "service/nohiki-registry",
                "5000:5000",
                "--address",
                "127.0.0.1",
            ]
        ),
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + PORT_FORWARD_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is not None:
                detail = process.stderr.read().strip() if process.stderr else ""
                fail(f"registry port-forward exited before readiness: {detail or process.returncode}")
            try:
                status, _ = _http_request("http://127.0.0.1:5000/v2/", timeout=1)
                if status == HTTP_OK:
                    yield
                    return
            except OSError, http.client.HTTPException:
                time.sleep(0.1)
        fail(
            "registry port-forward did not become ready at localhost:5000 "
            f"within {PORT_FORWARD_TIMEOUT_SECONDS} seconds"
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def cmd_publish(args: argparse.Namespace) -> None:
    """Publish local images and atomically record verified registry digests."""
    runtime = runtime_argv(args.runtime)
    entries: dict[str, DigestEntry] = {}
    with registry_forward():
        for image in local_images():
            name = image["name"]
            source = f"nohiki-build/{name}:local"
            image_id = run(
                [*runtime, "image", "inspect", "--format", "{{.Id}}", source],
                capture=True,
            )
            digest = _canonical_image_digest(image_id, source)
            tag = f"sha256-{digest.removeprefix('sha256:')}"
            target = f"{LOGICAL_REGISTRY}/{name}:{tag}"
            run([*runtime, "tag", source, target])
            push = [*runtime, "push"]
            if args.runtime == "podman":
                push.append("--tls-verify=false")
            run([*push, target])
            try:
                _, response_headers = _http_request(
                    f"http://127.0.0.1:5000/v2/{name}/manifests/{tag}",
                    method="HEAD",
                    headers={"Accept": PUBLISH_MANIFEST_ACCEPT},
                    timeout=3,
                )
            except (OSError, http.client.HTTPException) as exc:
                fail(f"cannot verify published manifest {target}: {exc}")
            digest = response_headers.get("Docker-Content-Digest", "")
            if not DIGEST_RE.fullmatch(digest):
                fail(f"registry did not return a canonical manifest digest for {target}")
            entries[name] = {"tag": tag, "digest": digest}
    output = Path(args.digests)
    output.parent.mkdir(parents=True, exist_ok=True)
    document: DigestDocument = {
        "schemaVersion": 1,
        "registry": LOGICAL_REGISTRY,
        "images": entries,
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(output)
    _write_line(f"published: {len(entries)} immutable images; digests recorded in {output}")


def cmd_render_values(args: argparse.Namespace) -> None:
    """Render validated immutable digest values for the local Helm release."""
    digests = load_digests(Path(args.digests))
    document = {
        "global": {
            "imageTag": "immutable",
            "nohikiImage": {
                "registry": LOGICAL_REGISTRY,
                "owner": "",
                "repositoryName": "",
                "pullPolicy": "IfNotPresent",
            },
            "imageDigests": {name: entry["digest"] for name, entry in sorted(digests["images"].items())},
        },
        "imageFoundation": digests,
    }
    json.dump(document, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _node_image_names(value: JsonValue) -> tuple[str, set[str]]:
    """Return one node name and its validated image provenance."""
    if not isinstance(value, dict):
        fail("node JSON lacks status.images provenance")
    metadata = value.get("metadata")
    status = value.get("status")
    if not isinstance(metadata, dict) or not isinstance(status, dict):
        fail("node JSON lacks status.images provenance")
    node_name = metadata.get("name")
    records = status.get("images")
    if not isinstance(node_name, str) or not isinstance(records, list):
        fail("node JSON lacks status.images provenance")
    names: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            fail("node JSON lacks status.images provenance")
        record_names = record.get("names")
        if not isinstance(record_names, list) or not all(isinstance(name, str) for name in record_names):
            fail("node JSON lacks status.images provenance")
        names.update(cast(list[str], record_names))
    return node_name, names


def cmd_prove_pulls(args: argparse.Namespace) -> None:
    """Prove every node pulled every required canonical registry digest."""
    doc = load_digests(Path(args.digests))
    if args.nodes_json:
        nodes = load_json(Path(args.nodes_json))
    else:
        raw = run(["kubectl", "get", "nodes", "-o", "json"], capture=True)
        try:
            parsed = cast(JsonValue, json.loads(raw))
        except json.JSONDecodeError:
            fail("kubectl returned invalid node JSON")
        if not isinstance(parsed, dict):
            fail("kubectl returned invalid node JSON")
        nodes = parsed
    items = nodes.get("items")
    if not isinstance(items, list) or not items:
        fail("node inventory is empty")
    required = {f"{LOGICAL_REGISTRY}/{name}@{entry['digest']}" for name, entry in doc["images"].items()}
    for node in items:
        node_name, names = _node_image_names(node)
        missing = sorted(required - names)
        if missing:
            fail(f"node {node_name} lacks canonical registry digest pulls: {', '.join(missing)}")
    _write_line(f"proven: {len(required)} immutable registry pulls on {len(items)} nodes")


def cmd_status(args: argparse.Namespace) -> None:
    """Require the registry to serve every recorded immutable manifest."""
    doc = load_digests(Path(args.digests))
    base = args.registry.rstrip("/")
    try:
        status, _ = _http_request(f"{base}/v2/", timeout=3)
        if status != HTTP_OK:
            fail(f"registry returned HTTP {status}")
        for name, entry in doc["images"].items():
            status, _ = _http_request(
                f"{base}/v2/{name}/manifests/{entry['digest']}",
                method="HEAD",
                headers={"Accept": STATUS_MANIFEST_ACCEPT},
                timeout=3,
            )
            if status != HTTP_OK:
                fail(f"registry manifest {name}@{entry['digest']} returned HTTP {status}")
    except (OSError, http.client.HTTPException) as exc:
        fail(f"registry readiness failed at {base}: {exc}")
    _write_line(f"ready: registry serves {len(doc['images'])} recorded immutable manifests")


def parser() -> argparse.ArgumentParser:
    """Build the image foundation command-line parser."""
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    command = commands.add_parser("validate")
    command.set_defaults(func=cmd_validate)
    command = commands.add_parser("mirror-config")
    command.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    command.set_defaults(func=cmd_mirror_config)
    command = commands.add_parser("mirror-preflight")
    command.add_argument("--config", required=True)
    command.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    command.set_defaults(func=cmd_mirror_preflight)
    command = commands.add_parser("build")
    command.add_argument("--runtime", default="docker")
    command.add_argument("--all", action="store_true")
    command.set_defaults(func=cmd_build)
    command = commands.add_parser("publish")
    command.add_argument("--runtime", default="docker")
    command.add_argument("--digests", required=True)
    command.set_defaults(func=cmd_publish)
    command = commands.add_parser("render-values")
    command.add_argument("--digests", required=True)
    command.set_defaults(func=cmd_render_values)
    command = commands.add_parser("prove-pulls")
    command.add_argument("--digests", required=True)
    command.add_argument("--nodes-json")
    command.set_defaults(func=cmd_prove_pulls)
    command = commands.add_parser("status")
    command.add_argument("--digests", required=True)
    command.add_argument("--registry", default=DEFAULT_ENDPOINT)
    command.set_defaults(func=cmd_status)
    return result


def main() -> None:
    """Run the selected image foundation command."""
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
