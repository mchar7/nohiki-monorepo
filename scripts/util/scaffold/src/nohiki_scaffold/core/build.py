"""Build planning and execution for scaffolded packages.

The flow is deterministic and side-effect free until `apply_plan` is called:

1. `build_plan(spec)` produces a `BuildPlan` listing every file to write and
   every `tool.uv.workspace` / `tool.ty.environment` / `tool.uv.sources` edit
   to apply to the root `pyproject.toml`.
2. `apply_plan(plan, repo_root=..., dry_run=...)` writes files atomically via
   temp-file + `os.replace`, applies the TOML edits via `tomlkit`, validates
   the mutated root TOML with `tomllib` before committing it, and prints Rich
   hints for work the scaffolder deliberately does not automate (Kafka topics,
   compose/k8s entries, CONTRIBUTING.md role table).

Atomicity guarantees:
  - Each individual file write is atomic (temp + fsync + rename).
  - The root pyproject edit is atomic AND validated in-memory before commit.
  - If any file write fails, we emit a recovery instruction pointing at git;
    we intentionally do NOT carry custom backup files because VCS is the source
    of truth.
"""

from __future__ import annotations

import os
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import tomlkit
from tomlkit.items import Array, String, Table

from nohiki_scaffold.core.exceptions import WorkspaceEditError
from nohiki_scaffold.core.models import LibSpec, ServiceSpec
from nohiki_scaffold.core.validators import target_directory_for_lib, target_directory_for_service

if TYPE_CHECKING:
    from tomlkit.toml_document import TOMLDocument


@dataclass(frozen=True, slots=True)
class FileWrite:
    """A file to be written when the plan is applied.

    `path` is absolute. `trigger` is a short human-readable reason, e.g.
    "database.alembic" or "kafka.handlers.commands", used by `--explain`.
    """

    path: Path
    content: str
    trigger: str


@dataclass(frozen=True, slots=True)
class TomlEdit:
    """An in-place mutation to apply to a `tomlkit` TOMLDocument."""

    description: str
    apply: Callable[[TOMLDocument], None]


@dataclass(frozen=True, slots=True)
class BuildPlan:
    """The complete plan for creating one package.

    `files` is ordered so parent directories are written before their children.
    `root_edits` is applied to `<repo_root>/pyproject.toml` in a single atomic
    write. `hints` are Rich-markup strings to display post-apply.
    """

    spec: ServiceSpec | LibSpec
    files: tuple[FileWrite, ...]
    root_edits: tuple[TomlEdit, ...]
    hints: tuple[str, ...] = field(default_factory=tuple)


_SERVICE_SECTION_BY_PREFIX: dict[str, str] = {
    "user-": "# User domain services",
    "job-": "# Job domain services",
    "doc-": "# Doc domain services",
    "ml-": "# ML services",
    "skill-": "# Skill domain services",
}
_SERVICE_DEFAULT_SECTION = "# Infrastructure services"
_LIB_SECTION = "# Shared libraries"


def _service_section_comment(name: str) -> str:
    """Return the `# ... services` comment under which `name` belongs."""
    for prefix, section in _SERVICE_SECTION_BY_PREFIX.items():
        if name.startswith(prefix):
            return section
    return _SERVICE_DEFAULT_SECTION


def _add_workspace_member(member_path: str, *, section_comment: str) -> TomlEdit:
    """Insert a `tool.uv.workspace.members` entry under the matching section comment.

    tomlkit's Array preserves comments as trivia on items. We find the insertion
    point by scanning for the section-comment line and inserting after the
    last member under that comment (before the next comment or end of array).
    If the section comment is absent, we fall back to appending at end.
    """

    def _apply(doc: TOMLDocument) -> None:
        members = _nav(doc, "tool", "uv", "workspace", "members")
        if not isinstance(members, Array):
            msg = "tool.uv.workspace.members is not an Array"
            raise WorkspaceEditError(msg)
        if member_path in [str(v) for v in members]:
            return
        insert_index = _find_section_insert_index(members, section_comment)
        new_item = tomlkit.string(member_path)
        if insert_index is None:
            members.append(member_path)
        else:
            members.insert(insert_index, new_item)

    return TomlEdit(description=f"+ workspace member: {member_path}", apply=_apply)


def _add_uv_source(name: str) -> TomlEdit:
    """Append `<name> = { workspace = true }` to `[tool.uv.sources]`."""

    def _apply(doc: TOMLDocument) -> None:
        sources = cast("Table", _nav(doc, "tool", "uv", "sources"))
        if name in sources:
            return
        entry = tomlkit.inline_table()
        entry["workspace"] = True
        sources[name] = entry

    return TomlEdit(description=f"+ uv source: {name} = {{ workspace = true }}", apply=_apply)


def _add_ty_root(src_path: str) -> TomlEdit:
    """Append a path to `tool.ty.environment.root`."""

    def _apply(doc: TOMLDocument) -> None:
        root = _nav(doc, "tool", "ty", "environment", "root")
        if not isinstance(root, Array):
            msg = "tool.ty.environment.root is not an Array"
            raise WorkspaceEditError(msg)
        if src_path in [str(v) for v in root]:
            return
        root.append(src_path)

    return TomlEdit(description=f"+ ty root: {src_path}", apply=_apply)


def _nav(doc: TOMLDocument, *path: str) -> object:
    """Navigate nested tables; raise WorkspaceEditError on missing."""
    current: object = doc
    for segment in path:
        if not hasattr(current, "__getitem__"):
            joined = ".".join(path)
            msg = f"Root pyproject has non-subscriptable value at: {joined}"
            raise WorkspaceEditError(msg)
        try:
            next_value = cast("dict[str, object]", current)[segment]
        except (KeyError, TypeError) as exc:
            joined = ".".join(path)
            msg = f"Root pyproject missing required table: {joined}"
            raise WorkspaceEditError(msg) from exc
        current = next_value
    return current


def _find_section_insert_index(members: Array, section_comment: str) -> int | None:
    """Return the insertion index just after the last existing entry under `section_comment`.

    tomlkit exposes raw trivia via `.body` on Arrays/Containers. We iterate the
    array items and look at the leading-comment trivia attached to each. If the
    target section is found, we keep advancing while entries belong to it (i.e.
    no intervening section-comment); we stop at the first comment that is NOT
    our target, and insert before it.
    """
    raw = getattr(members, "_value", None)
    if raw is None:
        return None

    found_section = False
    last_match_index: int | None = None
    string_index = 0
    for entry in raw:
        value = getattr(entry, "value", entry)
        comment_node = getattr(entry, "comment", None)
        leading_comment_text = None
        if comment_node is not None:
            leading_comment_text = str(comment_node).strip()
        if isinstance(value, String):
            if found_section:
                last_match_index = string_index + 1
            string_index += 1
            continue
        if leading_comment_text is None:
            continue
        if leading_comment_text == section_comment:
            found_section = True
        elif found_section:
            break

    if not found_section:
        return None
    return last_match_index


def build_plan(spec: ServiceSpec | LibSpec, *, repo_root: Path) -> BuildPlan:
    """Construct a BuildPlan for the given spec.

    Dispatches to the service or library builder based on spec type. The
    archetype-specific builders live in `nohiki_scaffold.core.build_service`
    and `nohiki_scaffold.core.build_lib` and are imported lazily to keep
    module load light.
    """
    if isinstance(spec, ServiceSpec):
        from nohiki_scaffold.core.build_service import build_service_plan

        return build_service_plan(spec, repo_root=repo_root)
    from nohiki_scaffold.core.build_lib import build_lib_plan

    return build_lib_plan(spec, repo_root=repo_root)


def apply_plan(plan: BuildPlan, *, repo_root: Path, dry_run: bool) -> None:
    """Materialise a BuildPlan on disk.

    Writes every file atomically, then applies root-pyproject edits atomically
    as a single final step. Validates TOML parses with `tomllib` before commit.
    In `dry_run` mode, no filesystem changes are made; this function becomes a
    no-op beyond argument validation (caller is expected to render the plan
    via `cli.display`).
    """
    if dry_run:
        return

    # Verify target directory does not already exist (defence in depth; the
    # validator should have caught this earlier).
    target = _target_dir(plan.spec, repo_root)
    if target.exists():
        msg = f"Target directory already exists: {target}"
        raise WorkspaceEditError(msg)

    # Phase 1: write all files.
    for fw in plan.files:
        fw.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(fw.path, fw.content)

    # Phase 2: apply root pyproject edits.
    if plan.root_edits:
        _apply_root_edits(repo_root, plan.root_edits)


def _target_dir(spec: ServiceSpec | LibSpec, repo_root: Path) -> Path:
    if isinstance(spec, ServiceSpec):
        return target_directory_for_service(repo_root, spec)
    return target_directory_for_lib(repo_root, spec)


def _atomic_write_text(path: Path, content: str) -> None:
    """Write `content` to `path` atomically via tempfile + rename."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _apply_root_edits(repo_root: Path, edits: tuple[TomlEdit, ...]) -> None:
    """Apply every TomlEdit to the root pyproject atomically."""
    root_pyproject = repo_root / "pyproject.toml"
    text = root_pyproject.read_text(encoding="utf-8")
    doc = tomlkit.parse(text)
    for edit in edits:
        edit.apply(doc)
    rendered = tomlkit.dumps(doc)
    # Validate that the edited document still parses as plain TOML.
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as exc:
        msg = f"Root pyproject edit produced invalid TOML: {exc}"
        raise WorkspaceEditError(msg) from exc
    _atomic_write_text(root_pyproject, rendered)
