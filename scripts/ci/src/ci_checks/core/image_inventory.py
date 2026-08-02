"""Canonical release-image inventory: schema, ownership matching, matrix, and affected records.

Standard library only, and nothing imported from outside ``ci-checks``: the hosted Checks router
runs this behind a package-only sync, and ``scripts/ci/image_matrix.py`` plus
``scripts/ci/image_digests.py`` reach it from a bare ``python3`` with no virtual environment.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

SCHEMA_VERSION: Final = 3
IMAGE_TIMEOUT_MINUTES: Final = 16
PRODUCT_CLASS: Final = "product"
VERIFICATION_OPS_CLASS: Final = "verification/ops"
IMAGE_CLASSES: Final = frozenset({PRODUCT_CLASS, VERIFICATION_OPS_CLASS})
TOP_LEVEL_KEYS: Final = frozenset({"schema_version", "no_image_ownership", "images"})
IMAGE_KEYS: Final = frozenset(
    {"name", "context", "dockerfile", "build_args", "lockfile", "timeout", "ownership", "class"}
)
AFFECTED_RECORD_KEYS: Final = frozenset({"head_sha", "images"})

INVENTORY_PATH: Final = Path(__file__).resolve().parents[5] / "scripts" / "ci" / "image_inventory.json"

# A change to one of these alters which rows any diff selects, so none of them can be no-image
# and none of them may narrow the selection.
SELECTION_AUTHORITY_PATHS: Final = frozenset(
    {
        ".github/workflows/build-push.yml",
        ".github/workflows/checks.yml",
        "scripts/ci/image_digests.py",
        "scripts/ci/image_inventory.json",
        "scripts/ci/image_matrix.py",
        "scripts/ci/src/ci_checks/checks/gate.py",
        "scripts/ci/src/ci_checks/core/image_inventory.py",
    }
)

_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_PINNED_IMAGE_RE = re.compile(
    r"^(?:#\s*syntax=|FROM\s+(?:--platform=\S+\s+)?|COPY\s+(?:--\S+\s+)*?--from=)"
    r"(?P<ref>\S+?@sha256:[0-9a-f]{64})",
    re.IGNORECASE | re.MULTILINE,
)
_MIRROR_ROOT_RE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+\Z")


class InventoryError(ValueError):
    """The inventory, an ownership rule, or an affected-image record is invalid."""


@dataclass(frozen=True, slots=True)
class ImageRecord:
    """One canonical release-build record.

    Attributes:
        name: Canonical image name.
        context: Repo-relative Docker build context directory.
        dockerfile: Repo-relative Dockerfile path.
        build_args: Single ``KEY=VALUE`` build argument, empty when unused.
        lockfile: Repo-relative dependency input whose changes select this image.
        timeout: Build-and-scan cap in minutes.
        ownership: Repo-relative rules selecting this image; a trailing ``/`` means prefix.
        image_class: Publication class: ``product`` or ``verification/ops``.
    """

    name: str
    context: str
    dockerfile: str
    build_args: str
    lockfile: str
    timeout: int
    ownership: tuple[str, ...]
    image_class: str

    def matrix_row(self) -> dict[str, object]:
        """Return this record as one ``strategy.matrix.include`` row.

        Returns:
            The build-push row keyed by name, context, dockerfile, build args, lockfile,
            and timeout in minutes.
        """
        return {
            "name": self.name,
            "context": self.context,
            "dockerfile": self.dockerfile,
            "build_args": self.build_args,
            "lockfile": self.lockfile,
            "timeout_minutes": self.timeout,
        }


@dataclass(frozen=True, slots=True)
class ImageInventory:
    """The validated inventory: declaration-ordered images plus the no-image rule set.

    Attributes:
        images: Declaration-ordered release records.
        no_image_ownership: Paths that own no image at all.
    """

    images: tuple[ImageRecord, ...]
    no_image_ownership: tuple[str, ...]

    @property
    def names(self) -> tuple[str, ...]:
        """Return every canonical image name in declaration order."""
        return tuple(record.name for record in self.images)

    @property
    def product_names(self) -> tuple[str, ...]:
        """Return routine-publication image names in declaration order."""
        return tuple(record.name for record in self.images if record.image_class == PRODUCT_CLASS)


@dataclass(frozen=True, slots=True)
class VendoredBaseImage:
    """One digest-pinned OCI build input and its owned mirror identity."""

    source: str
    mirror_repository: str
    digest: str

    @property
    def mirror_tag(self) -> str:
        """Return the deterministic tag used to seed the mirror."""
        return f"{self.mirror_repository}:sha256-{self.digest.removeprefix('sha256:')}"

    @property
    def mirror_reference(self) -> str:
        """Return the digest-preserving reference consumed by BuildKit."""
        return f"{self.mirror_repository}@{self.digest}"


def _check_rule(rule: object, field: str) -> str:
    if not isinstance(rule, str) or not rule:
        msg = f"{field} contains an empty or non-string path rule"
        raise InventoryError(msg)
    if rule.startswith("/") or "\\" in rule:
        msg = f"{field} rule {rule!r} must be a relative posix path"
        raise InventoryError(msg)
    if any(part in {"", ".", ".."} for part in rule.rstrip("/").split("/")):
        msg = f"{field} rule {rule!r} is not a normalized path"
        raise InventoryError(msg)
    return rule


def _build_path(checkout: Path, value: object, field: str, name: str) -> Path:
    if not isinstance(value, str) or not value:
        msg = f"image {name} has an empty or non-string {field}"
        raise InventoryError(msg)
    if value.endswith("/"):
        msg = f"image {name} {field} must not end in a separator"
        raise InventoryError(msg)
    if value != ".":
        _check_rule(value, f"image {name} {field}")
    resolved = (checkout / value).resolve()
    if resolved != checkout and not resolved.is_relative_to(checkout):
        msg = f"image {name} {field} {value!r} resolves outside the checkout"
        raise InventoryError(msg)
    return resolved


def _overlaps(left: str, right: str) -> bool:
    if left.endswith("/") and right.endswith("/"):
        return left.startswith(right) or right.startswith(left)
    if left.endswith("/"):
        return right == left.rstrip("/") or right.startswith(left)
    if right.endswith("/"):
        return left == right.rstrip("/") or left.startswith(right)
    return left == right


def _matches(rule: str, path: str) -> bool:
    return path.startswith(rule) if rule.endswith("/") else path == rule


def _rules(raw: object, field: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(raw, list):
        msg = f"{field} must be a list of path rules"
        raise InventoryError(msg)
    rules: list[str] = []
    for entry in raw:
        rule = _check_rule(entry, field)
        if rule in rules:
            msg = f"{field} repeats the rule {rule!r}"
            raise InventoryError(msg)
        rules.append(rule)
    if not rules and not allow_empty:
        msg = f"{field} must declare at least one path rule"
        raise InventoryError(msg)
    return tuple(rules)


def split_registry_pin(reference: str) -> tuple[str, str, str]:
    """Return the original name, tagless repository, and digest of a registry pin."""
    tagged, separator, digest = reference.rpartition("@")
    if not separator:
        msg = f"base image {reference!r} is not digest pinned"
        raise InventoryError(msg)
    head, tag_separator, candidate = tagged.rpartition(":")
    # A colon only introduces a tag in the final path component; otherwise
    # it is a registry port (registry.example:5000/team/image).
    repository = head if tag_separator and "/" not in candidate else tagged
    return tagged, repository, digest


def _canonical_registry_reference(reference: str) -> tuple[str, str, str]:
    _, repository, digest = split_registry_pin(reference)
    first_component = repository.split("/", maxsplit=1)[0]
    if "/" not in repository:
        repository = f"docker.io/library/{repository}"
    elif "." not in first_component and ":" not in first_component and first_component != "localhost":
        repository = f"docker.io/{repository}"
    return f"{repository}@{digest}", repository, digest


def _base_images(text: str, mirror_root: str) -> tuple[VendoredBaseImage, ...]:
    if not _MIRROR_ROOT_RE.fullmatch(mirror_root):
        msg = f"base-image mirror root {mirror_root!r} is not a canonical registry path"
        raise InventoryError(msg)
    pins: dict[str, VendoredBaseImage] = {}
    for match in _PINNED_IMAGE_RE.finditer(text):
        original = match["ref"]
        source, repository, digest = _canonical_registry_reference(original)
        pins[original] = VendoredBaseImage(
            source=source,
            mirror_repository=f"{mirror_root}/{repository}",
            digest=digest,
        )
    return tuple(pins[reference] for reference in sorted(pins))


def vendored_base_images(
    inventory: ImageInventory,
    checkout: Path,
    mirror_root: str,
) -> tuple[VendoredBaseImage, ...]:
    """Collect every unique digest-pinned OCI input used by the inventory."""
    pins: dict[str, VendoredBaseImage] = {}
    for record in inventory.images:
        dockerfile = checkout / record.dockerfile
        try:
            text = dockerfile.read_text(encoding="utf-8")
        except OSError as exc:
            msg = f"cannot read image {record.name} dockerfile {dockerfile}: {exc}"
            raise InventoryError(msg) from exc
        for pin in _base_images(text, mirror_root):
            pins[pin.source] = pin
    return tuple(pins[source] for source in sorted(pins))


def render_vendored_dockerfile(record: ImageRecord, checkout: Path, mirror_root: str) -> str:
    """Rewrite one Dockerfile to consume owned mirrors at the original digests."""
    dockerfile = checkout / record.dockerfile
    try:
        text = dockerfile.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"cannot read image {record.name} dockerfile {dockerfile}: {exc}"
        raise InventoryError(msg) from exc
    mirrors = {pin.source: pin.mirror_reference for pin in _base_images(text, mirror_root)}

    def replace(match: re.Match[str]) -> str:
        source, _, _ = _canonical_registry_reference(match["ref"])
        return match.group(0).replace(match["ref"], mirrors[source])

    return _PINNED_IMAGE_RE.sub(replace, text)


def _record(raw: object, checkout: Path) -> ImageRecord:
    if not isinstance(raw, dict):
        msg = f"image record keys must be exactly {sorted(IMAGE_KEYS)}"
        raise InventoryError(msg)
    fields = cast(dict[str, object], raw)
    if set(fields) != IMAGE_KEYS:
        msg = f"image record keys must be exactly {sorted(IMAGE_KEYS)}"
        raise InventoryError(msg)
    name = fields["name"]
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        msg = f"image name {name!r} is not a canonical kebab-case name"
        raise InventoryError(msg)
    build_args = fields["build_args"]
    if not isinstance(build_args, str):
        msg = f"image {name} build_args must be a string"
        raise InventoryError(msg)
    image_class = fields["class"]
    if image_class not in IMAGE_CLASSES:
        msg = f"image {name} class must be one of {sorted(IMAGE_CLASSES)}"
        raise InventoryError(msg)
    timeout = fields["timeout"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout != IMAGE_TIMEOUT_MINUTES:
        msg = f"image {name} timeout must be exactly {IMAGE_TIMEOUT_MINUTES}"
        raise InventoryError(msg)
    context, dockerfile, lockfile = (
        _build_path(checkout, fields[field], field, name) for field in ("context", "dockerfile", "lockfile")
    )
    if not context.is_dir():
        msg = f"image {name} context is not a directory"
        raise InventoryError(msg)
    for field, path in (("dockerfile", dockerfile), ("lockfile", lockfile)):
        if not path.is_file():
            msg = f"image {name} {field} is not a file"
            raise InventoryError(msg)
    return ImageRecord(
        name=name,
        context=str(fields["context"]),
        dockerfile=str(fields["dockerfile"]),
        build_args=build_args,
        lockfile=str(fields["lockfile"]),
        timeout=timeout,
        ownership=_rules(fields["ownership"], f"image {name} ownership", allow_empty=False),
        image_class=str(image_class),
    )


def _no_image_rules(raw: object, images: Sequence[ImageRecord]) -> tuple[str, ...]:
    rules = _rules(raw, "no_image_ownership", allow_empty=True)
    for rule in rules:
        if any(_overlaps(rule, authority) for authority in SELECTION_AUTHORITY_PATHS):
            msg = f"no_image_ownership rule {rule!r} covers an image-selection authority"
            raise InventoryError(msg)
        for record in images:
            for owned in record.ownership:
                if _overlaps(rule, owned):
                    msg = f"no_image_ownership rule {rule!r} overlaps image {record.name} rule {owned!r}"
                    raise InventoryError(msg)
    return rules


def _load_document(path: Path, subject: str, keys: frozenset[str], noun: str) -> dict[str, object]:
    """Read one JSON document and confirm it is an object with exactly the expected keys.

    Args:
        path: File to read.
        subject: Phrase naming the document in the unreadable-file message.
        keys: The exact top-level key set the document must carry.
        noun: Phrase naming the key set in the wrong-keys message.

    Returns:
        The parsed document.

    Raises:
        InventoryError: If the file is unreadable, not UTF-8, not JSON, or not an object with
            exactly ``keys``. ``OSError`` covers access failure and ``ValueError`` covers the
            whole decode-and-parse family, whose members include ``UnicodeDecodeError`` and
            ``JSONDecodeError``; a narrower tuple lets the next unanticipated decode error
            escape the caller's fallback, while ``ValueError`` still lets a programming error
            such as ``TypeError`` surface.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = f"cannot read {subject} {path}: {exc}"
        raise InventoryError(msg) from exc
    if not isinstance(data, dict) or set(data) != keys:
        msg = f"{noun} must be exactly {sorted(keys)}"
        raise InventoryError(msg)
    return cast("dict[str, object]", data)


def load_inventory(path: Path | None = None, checkout: Path | None = None) -> ImageInventory:
    """Load and fully validate the canonical image inventory.

    Args:
        path: Inventory JSON path; defaults to the repository's canonical inventory.
        checkout: Checkout root that build paths resolve under; defaults to the inventory's
            grandparent directory.

    Returns:
        The validated declaration-ordered inventory.

    Raises:
        InventoryError: If the file is unreadable or any schema, path, or overlap rule fails.
    """
    source = INVENTORY_PATH if path is None else path
    root = (source.resolve().parents[2] if checkout is None else checkout).resolve()
    data = _load_document(source, "image inventory", TOP_LEVEL_KEYS, "inventory keys")
    version = data["schema_version"]
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        msg = f"inventory schema_version must be {SCHEMA_VERSION}"
        raise InventoryError(msg)
    raw_images = data["images"]
    if not isinstance(raw_images, list) or not raw_images:
        msg = "inventory must declare at least one image"
        raise InventoryError(msg)
    images = tuple(_record(raw, root) for raw in raw_images)
    seen: set[str] = set()
    for record in images:
        if record.name in seen:
            msg = f"duplicate image name {record.name}"
            raise InventoryError(msg)
        seen.add(record.name)
    return ImageInventory(images=images, no_image_ownership=_no_image_rules(data["no_image_ownership"], images))


def affected_images(changed: Iterable[str], inventory: ImageInventory) -> tuple[str, ...]:
    """Select the declaration-ordered images that a changed-path set invalidates.

    Args:
        changed: Repo-relative changed paths, deletions included.
        inventory: The validated inventory.

    Returns:
        The declaration-ordered owner union; empty when every path is no-image; every image
        name when any path is unknown or is an image-selection authority.
    """
    paths = {path for path in changed if path}
    if not paths:
        return ()
    if paths & SELECTION_AUTHORITY_PATHS:
        return inventory.names
    selected = tuple(
        record.name
        for record in inventory.images
        if any(_matches(rule, path) for path in paths for rule in record.ownership)
    )
    for path in paths:
        if any(_matches(rule, path) for record in inventory.images for rule in record.ownership):
            continue
        if any(_matches(rule, path) for rule in inventory.no_image_ownership):
            continue
        # An unmodelled path may be any image's build input; fail closed to the whole set.
        return inventory.names
    return selected


def render_matrix(inventory: ImageInventory, names: Iterable[str] | None = None) -> dict[str, list[dict[str, object]]]:
    """Render a build-push ``strategy.matrix`` object from the inventory.

    Args:
        inventory: The validated inventory.
        names: Optional subset of canonical names; ``None`` renders every record.

    Returns:
        ``{"include": [...]}`` in declaration order.

    Raises:
        InventoryError: If a requested name is not canonical.
    """
    if names is None:
        return {"include": [record.matrix_row() for record in inventory.images]}
    chosen = set(names)
    unknown = sorted(chosen - set(inventory.names))
    if unknown:
        msg = f"unknown image names: {unknown}"
        raise InventoryError(msg)
    return {"include": [record.matrix_row() for record in inventory.images if record.name in chosen]}


def write_affected_record(path: Path, head_sha: str, names: Sequence[str]) -> None:
    """Write the SHA-bound affected-image record.

    Args:
        path: Destination file.
        head_sha: Tested commit the selection binds to.
        names: Selected canonical names in declaration order.

    Raises:
        InventoryError: If the head SHA is not a 40-character hex commit id.
    """
    sha = head_sha.lower()
    if not _SHA_RE.fullmatch(sha):
        msg = f"affected-image record needs a 40-character commit id, got {head_sha!r}"
        raise InventoryError(msg)
    payload = json.dumps({"head_sha": sha, "images": list(names)}, separators=(",", ":"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{payload}\n", encoding="utf-8")


def read_affected_record(path: Path, expected_sha: str, inventory: ImageInventory) -> tuple[str, ...]:
    """Read and validate an affected-image record against the inventory.

    Args:
        path: Record file.
        expected_sha: Source commit the record must be bound to.
        inventory: The validated inventory.

    Returns:
        The selected canonical names in declaration order; an empty tuple is valid.

    Raises:
        InventoryError: If the record is unreadable, malformed, stale, duplicated, unknown,
            or out of declaration order.
    """
    expected = expected_sha.lower()
    if not _SHA_RE.fullmatch(expected):
        msg = f"expected source sha must be a 40-character commit id, got {expected_sha!r}"
        raise InventoryError(msg)
    data = _load_document(path, "affected-image record", AFFECTED_RECORD_KEYS, "affected-image record keys")
    head_sha, raw_names = data["head_sha"], data["images"]
    if not isinstance(head_sha, str) or not _SHA_RE.fullmatch(head_sha):
        msg = f"affected-image record head_sha {head_sha!r} is not 40 lowercase hex characters"
        raise InventoryError(msg)
    if head_sha != expected:
        msg = f"affected-image record binds {head_sha}, not the tested {expected}"
        raise InventoryError(msg)
    return canonical_subset(raw_names, inventory, label="affected-image record")


def canonical_subset(raw_names: object, inventory: ImageInventory, label: str) -> tuple[str, ...]:
    """Validate a selection as a unique, declaration-ordered subset of the inventory.

    Args:
        raw_names: Candidate selection, rejected unless it is a list of strings.
        inventory: The validated inventory.
        label: Subject named in every error message.

    Returns:
        The selection in declaration order; an empty tuple is valid.

    Raises:
        InventoryError: If the selection is not a name list, repeats a name, names an unknown
            image, or is out of declaration order.
    """
    if not isinstance(raw_names, list) or not all(isinstance(name, str) for name in raw_names):
        msg = f"{label} must be a list of image names"
        raise InventoryError(msg)
    selected = [name for name in raw_names if isinstance(name, str)]
    if len(set(selected)) != len(selected):
        msg = f"{label} repeats an image name"
        raise InventoryError(msg)
    unknown = sorted(set(selected) - set(inventory.names))
    if unknown:
        msg = f"{label} names unknown images: {unknown}"
        raise InventoryError(msg)
    chosen = set(selected)
    if selected != [name for name in inventory.names if name in chosen]:
        msg = f"{label} is not in canonical declaration order"
        raise InventoryError(msg)
    return tuple(selected)
