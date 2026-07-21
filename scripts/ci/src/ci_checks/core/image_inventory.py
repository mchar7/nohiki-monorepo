"""Canonical container-image inventory and affected-image derivation."""

import json
import re
from pathlib import Path
from typing import NoReturn

from ci_checks.core.packages import REPO_ROOT

INVENTORY_PATH = REPO_ROOT / "scripts" / "ci" / "image_inventory.json"
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_REQUIRED_FIELDS = {
    "name",
    "context",
    "dockerfile",
    "build_args",
    "timeout",
    "ownership",
}


def fail(message: str) -> NoReturn:
    """Raise an image inventory contract error."""
    raise ValueError(message)


def load_inventory(path: Path = INVENTORY_PATH) -> list[dict[str, object]]:
    """Load and validate the canonical image inventory."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"images"} or not isinstance(document["images"], list):
        fail("image inventory must contain exactly one images list")
    images = document["images"]
    names: set[str] = set()
    for image in images:
        if not isinstance(image, dict) or set(image) != _REQUIRED_FIELDS:
            fail("every image must define the canonical fields and ownership")
        name = image["name"]
        ownership = image["ownership"]
        if not isinstance(name, str) or not name or name in names:
            fail("image names must be non-empty and unique")
        if not all(isinstance(image[field], str) for field in ("context", "dockerfile", "build_args")):
            fail(f"image {name} has invalid build fields")
        if not isinstance(image["timeout"], int) or image["timeout"] <= 0:
            fail(f"image {name} has an invalid timeout")
        if (
            not isinstance(ownership, list)
            or not ownership
            or not all(isinstance(rule, str) and rule for rule in ownership)
        ):
            fail(f"image {name} has no ownership rule")
        names.add(name)
    if not images:
        fail("image inventory must not be empty")
    return images


def image_names(images: list[dict[str, object]]) -> list[str]:
    """Return inventory image names in canonical order."""
    return [str(image["name"]) for image in images]


def matrix(images: list[dict[str, object]], selected: set[str] | None = None) -> dict[str, list[dict[str, object]]]:
    """Render the GitHub Actions matrix for the selected image names."""
    all_names = set(image_names(images))
    selected_names = all_names if selected is None else selected
    if not selected_names <= all_names:
        fail(f"unknown affected images: {sorted(selected_names - all_names)}")
    include = [
        {
            "name": image["name"],
            "context": image["context"],
            "dockerfile": image["dockerfile"],
            "build_args": image["build_args"],
            "timeout_minutes": image["timeout"],
        }
        for image in images
        if image["name"] in selected_names
    ]
    return {"include": include}


def affected_images(changed: set[str], images: list[dict[str, object]]) -> list[str]:
    """Map changed paths to images, returning all images when any path is unowned."""
    affected: set[str] = set()
    unmatched = False
    for path in changed:
        owners = {
            str(image["name"])
            for image in images
            if any(
                path.startswith(rule) if rule.endswith("/") else path == rule
                for rule in image["ownership"]
                if isinstance(rule, str)
            )
        }
        if not owners:
            unmatched = True
        affected.update(owners)
    names = image_names(images)
    return names if unmatched else [name for name in names if name in affected]


def write_affected_record(path: Path, head_sha: str, names: list[str]) -> None:
    """Write the affected-image artifact contract."""
    if _SHA_RE.fullmatch(head_sha) is None:
        fail("head_sha must be exactly 40 lowercase hexadecimal characters")
    path.write_text(
        json.dumps({"head_sha": head_sha, "images": names}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def read_affected_record(path: Path, source_sha: str, images: list[dict[str, object]]) -> set[str]:
    """Validate and return the affected-image artifact selection."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"head_sha", "images"}:
        fail("affected-image artifact has an invalid schema")
    if document["head_sha"] != source_sha or _SHA_RE.fullmatch(source_sha) is None:
        fail("affected-image artifact head_sha does not match source_sha")
    names = document["images"]
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names) or len(names) != len(set(names)):
        fail("affected-image artifact images must be a unique string list")
    selected = set(names)
    canonical = set(image_names(images))
    if not selected <= canonical:
        fail("affected-image artifact names are not canonical")
    return selected
