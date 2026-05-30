"""``_tailor_meta`` — the sole runtime-context input for the lint engine.

The meta block lives under the ``_tailor_meta`` key inside manual-mode JSON
data. It is stripped before the document passes to schema validation, template
rendering, and the lint engine, which keeps it invisible to both the template
author and the LLM.

Design decisions:
- Underscore-prefix ``_tailor_meta`` keeps the key out of schema JSON Schema
  definitions (which cannot easily reserve keywords).
- All fields are optional; a missing meta block yields an empty runtime context.
- Sibling documents are resolved **once** at meta-load time, not lazily — this
  surfaces missing-sibling errors early and keeps the engine pure.

Contract:
- ``extract_tailor_meta(data)`` returns ``(stripped_data, meta | None)``.
- ``build_runtime(meta, base_dir)`` returns a populated ``LintRuntimeContext``.
- Neither helper mutates inputs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError, field_validator

from tailor.exceptions import LintConfigError
from tailor.lint.runtime import LintRuntimeContext

if TYPE_CHECKING:
    from collections.abc import Mapping

META_KEY = "_tailor_meta"

# lint_tags entries must be snake-case lowercase identifiers
# and lint_vars keys must be valid identifiers (so ``{{ var_name }}`` substitution
# cannot reference syntactically-invalid placeholders).
_TAG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VAR_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class TailorMetaConfig(BaseModel, frozen=True, extra="forbid"):
    """Runtime-context configuration parsed from ``_tailor_meta`` in input data.

    Attributes:
        lint_tags: Tags to activate; consulted by ``requires_tags`` /
            ``excludes_tags`` gates and the ``has_tag('x')`` CEL predicate.
            Each tag must match ``^[a-z][a-z0-9_]*$``. Stored as a frozenset
            to deduplicate and match the ``LintRuntimeContext.active_tags`` type.
        lint_vars: Variable map used by ``{{ var }}`` substitution in
            substitutable rule params. Keys must be valid identifiers so they
            can appear inside ``{{ ... }}`` placeholders.
        sibling_documents: Logical name → relative path map for companion
            documents consulted via ``sibling.<name>.<path>`` references
            (e.g. ``{"companion": "companion.json"}``). Paths are resolved
            relative to the primary data file's directory.
        lint_disable_rule_ids: Rule IDs to skip entirely during evaluation —
            used by authors to silence a specific rule for a given draft.
            Stored as a frozenset to deduplicate and match the
            ``LintRuntimeContext.disabled_rule_ids`` type.
    """

    lint_tags: frozenset[str] = frozenset()
    lint_vars: dict[str, str] = Field(default_factory=dict)
    sibling_documents: dict[str, str] = Field(default_factory=dict)
    lint_disable_rule_ids: frozenset[str] = frozenset()

    @field_validator("lint_tags")
    @classmethod
    def _validate_tag_names(cls, v: frozenset[str]) -> frozenset[str]:
        """Every tag must match ``^[a-z][a-z0-9_]*$``."""
        for tag in v:
            if not _TAG_RE.match(tag):
                msg = f"Invalid lint_tag {tag!r}: must match {_TAG_RE.pattern}"
                raise ValueError(msg)
        return v

    @field_validator("lint_vars")
    @classmethod
    def _validate_var_names(cls, v: dict[str, str]) -> dict[str, str]:
        """Variable names must match ``^[a-zA-Z_][a-zA-Z0-9_]*$``."""
        for name in v:
            if not _VAR_NAME_RE.match(name):
                msg = f"Invalid lint_vars key {name!r}: must match {_VAR_NAME_RE.pattern}"
                raise ValueError(msg)
        return v


def extract_tailor_meta(
    data: Mapping[str, object],
) -> tuple[dict[str, object], TailorMetaConfig | None]:
    """Split ``_tailor_meta`` off of input data.

    The returned ``stripped_data`` is a shallow copy of ``data`` with the meta
    key removed — callers pass it through schema validation, rendering, and
    linting. The returned meta (if present) is consumed by ``build_runtime``.

    Args:
        data: Raw document data, typically from ``load_data_file``.

    Returns:
        ``(stripped_data, meta)``. ``meta`` is ``None`` when ``_tailor_meta`` is
        absent.

    Raises:
        LintConfigError: ``_tailor_meta`` exists but is not a mapping, or its
            contents fail ``TailorMetaConfig`` validation.
    """
    stripped = {k: v for k, v in data.items() if k != META_KEY}
    meta_raw = data.get(META_KEY)
    if meta_raw is None:
        return stripped, None

    if not isinstance(meta_raw, dict):
        msg = f"_tailor_meta must be a mapping, got {type(meta_raw).__name__}"
        raise LintConfigError(msg)

    try:
        meta = TailorMetaConfig.model_validate(meta_raw)
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors())
        msg = f"Invalid _tailor_meta ({exc.error_count()} error(s)): {details}"
        raise LintConfigError(msg) from exc

    return stripped, meta


def build_runtime(meta: TailorMetaConfig | None, base_dir: Path | None = None) -> LintRuntimeContext:
    """Build a ``LintRuntimeContext`` from parsed meta and an optional base dir.

    Sibling documents are resolved against ``base_dir`` and loaded eagerly as
    JSON objects. Any missing sibling file or non-object payload raises
    ``LintConfigError`` so that ``has_sibling('x')`` never silently returns
    False due to a filesystem typo.

    Args:
        meta: Parsed ``TailorMetaConfig`` or ``None`` for an empty runtime.
        base_dir: Directory used to resolve relative sibling paths. Ignored
            when ``meta.sibling_documents`` is empty.

    Returns:
        Fully populated ``LintRuntimeContext``.

    Raises:
        LintConfigError: Sibling file missing, unreadable, or non-object JSON.
    """
    if meta is None:
        return LintRuntimeContext()

    siblings = _load_siblings(meta.sibling_documents, base_dir)
    return LintRuntimeContext(
        active_tags=frozenset(meta.lint_tags),
        variables=dict(meta.lint_vars),
        sibling_documents=siblings,
        disabled_rule_ids=frozenset(meta.lint_disable_rule_ids),
    )


def _load_siblings(
    mapping: Mapping[str, str],
    base_dir: Path | None,
) -> dict[str, dict[str, object]]:
    """Resolve every sibling document path and load its JSON object.

    Each sibling path is resolved against ``base_dir`` (or the current working
    directory when ``base_dir`` is None). Loaded payloads must be JSON objects
    (``dict[str, object]``) — arrays / scalars are rejected so path navigation
    (``sibling.<name>.key``) can assume a mapping root.
    """
    if not mapping:
        return {}

    root = base_dir if base_dir is not None else Path.cwd()
    loaded: dict[str, dict[str, object]] = {}
    for name, rel_path in mapping.items():
        resolved = (root / rel_path).resolve() if not Path(rel_path).is_absolute() else Path(rel_path)
        loaded[name] = _load_sibling_json(name, resolved)
    return loaded


def _load_sibling_json(name: str, path: Path) -> dict[str, object]:
    """Read a sibling document from ``path`` and validate it is a JSON object."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        msg = f"Sibling document {name!r} not found at {path}"
        raise LintConfigError(msg, path=str(path)) from exc
    except OSError as exc:
        msg = f"Failed to read sibling document {name!r} at {path}: {exc}"
        raise LintConfigError(msg, path=str(path)) from exc

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"Sibling document {name!r} at {path} is not valid JSON: {exc}"
        raise LintConfigError(msg, path=str(path)) from exc

    if not isinstance(payload, dict):
        msg = f"Sibling document {name!r} at {path} must be a JSON object, got {type(payload).__name__}"
        raise LintConfigError(msg, path=str(path))
    return payload
