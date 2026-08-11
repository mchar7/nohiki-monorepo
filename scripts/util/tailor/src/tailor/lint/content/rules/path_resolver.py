"""Path resolution utilities for navigating JSON data with glob patterns.

Grammar:
  $                         - Document root. Resolves to ``[("$", [data])]`` so
                              document-level rules see the whole doc as a single item.
  foo.bar                   - Direct key access.
  foo[*]                    - Wildcard over list items (flattens).
  foo[N]                    - Index access.
  sibling.<name>.<path>     - Root against ``runtime.sibling_documents[<name>]``
                              instead of the primary document. Any of the other
                              operators may follow the ``<name>`` prefix.

Additional features for the flat schema:
  resolve_scope(paths, excludes, runtime=None)
      Resolves each path in ``paths``, then removes any entry whose concrete
      path matches an entry in ``excludes`` (which is itself resolved and
      compared by concrete-path equality). ``runtime`` must be provided when
      any path uses the ``sibling.*`` prefix.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from tailor.lint.models import ROOT_PATH

if TYPE_CHECKING:
    from tailor.lint.runtime import LintRuntimeContext

_SIBLING_PREFIX = "sibling."

# Compiled once at module level -- matches a path segment like "entries" or "entries[2]".
_INDEX_PATTERN = re.compile(r"([^\[]+)(?:\[(\d+)\])?")


def navigate(data: object, path: str) -> object:
    """Navigate a dot-separated path through nested dicts and lists.

    Supports ``key[N]`` index notation for list access (e.g. ``entries[0].title``).
    Returns ``None`` when any segment is missing, the type is wrong, or the index
    is out of range.

    Args:
        data: Starting object -- any JSON-compatible value.
        path: Dot-separated path segments, with optional ``[N]`` index notation.

    Returns:
        The value at the resolved path, or ``None`` if unresolvable.
    """
    if not path:
        return data

    current: object = data
    for segment in path.split("."):
        if current is None:
            return None
        match = _INDEX_PATTERN.fullmatch(segment)
        if match is None:
            return None
        key, index_str = match.group(1), match.group(2)
        if not isinstance(current, dict):
            return None
        current = cast("dict[str, object]", current).get(key)
        if index_str is not None:
            if not isinstance(current, list):
                return None
            idx = int(index_str)
            current = current[idx] if idx < len(current) else None

    return current


def resolve_glob_path(
    data: object,
    path: str,
    runtime: LintRuntimeContext | None = None,
) -> list[tuple[str, list[object]]]:
    """Resolve a path that may contain a single ``[*]`` wildcard or the ``$`` root.

    Expands the wildcard over all indices of the preceding array. The suffix
    after the wildcard is navigated from each expanded element.

    Special cases:
    - ``"$"`` resolves to ``[("$", [data])]`` -- document-level rules receive the
      entire document as a single "item" in a one-element list.
    - ``"sibling.<name>.<rest>"`` rebases resolution on
      ``runtime.sibling_documents[<name>]``. The concrete path returned keeps
      the ``sibling.<name>.`` prefix so callers can tell siblings apart.
    - If the parent item is a dict but the suffix resolves to ``None``, an empty
      list is emitted -- this allows ``min_items`` rules to fire on missing child keys.

    Args:
        data: Full primary document data (any JSON-compatible object).
        path: Dot-separated path; at most one ``[*]`` wildcard is supported.
        runtime: Optional runtime context. Required when ``path`` starts with
            ``sibling.<name>``; ignored otherwise.

    Returns:
        List of ``(concrete_path, items)`` tuples. Empty when the path is
        unresolvable or the resolved value is not a list.

    Raises:
        KeyError: ``sibling.<name>...`` references a name that is not loaded
            in ``runtime.sibling_documents``. Sibling loading is eager (see
            ``meta.build_runtime``) so this indicates a caller bug, not user
            misconfiguration.
    """
    if path == ROOT_PATH:
        return [(ROOT_PATH, [data])]

    if path.startswith(_SIBLING_PREFIX):
        return _resolve_sibling(path, runtime)

    return _resolve_with_root(data, path, ROOT_PATH)


def _resolve_sibling(
    path: str,
    runtime: LintRuntimeContext | None,
) -> list[tuple[str, list[object]]]:
    """Delegate a ``sibling.<name>.<rest>`` path to the named sibling document."""
    remainder = path[len(_SIBLING_PREFIX) :]
    if "." not in remainder:
        # Bare ``sibling.<name>`` with no sub-path: resolves to the sibling root.
        sibling_name = remainder
        sub_path = ""
    else:
        sibling_name, sub_path = remainder.split(".", 1)

    if runtime is None:
        msg = f"Path {path!r} requires a runtime context with sibling_documents"
        raise KeyError(msg)
    if sibling_name not in runtime.sibling_documents:
        available = sorted(runtime.sibling_documents)
        msg = f"Sibling {sibling_name!r} not loaded (available: {available}); path was {path!r}"
        raise KeyError(msg)

    sibling_data = runtime.sibling_documents[sibling_name]
    prefix = f"{_SIBLING_PREFIX}{sibling_name}"
    if sub_path == "":
        return [(prefix, [sibling_data])]
    return _resolve_with_root(sibling_data, sub_path, prefix)


def _resolve_with_root(
    data: object,
    path: str,
    concrete_root: str,
) -> list[tuple[str, list[object]]]:
    """Walk ``path`` against ``data`` and emit paths rooted at ``concrete_root``."""
    if "[*]" not in path:
        value = navigate(data, path)
        if value is None:
            return []
        concrete = f"{concrete_root}.{path}"
        if isinstance(value, list):
            # List → treat each element as an item (classic list-of-items scope).
            return [(concrete, cast("list[object]", value))]
        # Primitive or dict → wrap in a singleton so indexed accesses like
        # ``items[1]`` or bare dot paths to a primitive expose the value as a
        # scope item. Mirrors the ``foo[*]`` wildcard branch.
        return [(concrete, [value])]

    wildcard_idx = path.index("[*]")
    prefix = path[:wildcard_idx]
    suffix = path[wildcard_idx + 3 :].removeprefix(".")

    prefix_value = navigate(data, prefix)
    if not isinstance(prefix_value, list):
        return []

    results: list[tuple[str, list[object]]] = []
    for i, item in enumerate(prefix_value):
        concrete_prefix = f"{concrete_root}.{prefix}[{i}]"
        if not suffix:
            # Empty suffix (``foo[*]``) emits one scope entry per index. When the
            # item is itself a list, use it directly as ``items`` (matrix-style
            # nested arrays). Otherwise, wrap the primitive / dict item in a
            # single-element list so rules can iterate per-paragraph or per-entry
            # without needing an explicit child key.
            if isinstance(item, list):
                results.append((concrete_prefix, cast("list[object]", item)))
            else:
                results.append((concrete_prefix, [item]))
        elif isinstance(item, dict):
            child = navigate(item, suffix)
            if isinstance(child, list):
                results.append((f"{concrete_prefix}.{suffix}", cast("list[object]", child)))
            elif child is None:
                results.append((f"{concrete_prefix}.{suffix}", []))

    return results


def resolve_glob_paths(
    data: object,
    paths: tuple[str, ...] | list[str],
    runtime: LintRuntimeContext | None = None,
) -> list[tuple[str, list[object]]]:
    """Resolve multiple paths and concatenate results.

    Args:
        data: Full primary document data.
        paths: Paths, each optionally containing a ``[*]`` wildcard or
            ``sibling.<name>`` prefix.
        runtime: Runtime context; required when any path uses ``sibling.*``.

    Returns:
        Concatenated list of ``(concrete_path, items)`` tuples from all paths.
    """
    results: list[tuple[str, list[object]]] = []
    for path in paths:
        results.extend(resolve_glob_path(data, path, runtime))
    return results


def resolve_scope(
    data: object,
    scope_paths: tuple[str, ...] | list[str],
    scope_excludes: tuple[str, ...] | list[str] = (),
    runtime: LintRuntimeContext | None = None,
) -> list[tuple[str, list[object]]]:
    """Resolve scope paths minus any concrete paths matching scope_excludes.

    The exclusion semantics match by concrete resolved path: an exclude entry is
    resolved through the same grammar, and any ``(path, items)`` tuple whose
    concrete path equals an excluded concrete path is dropped.

    Paths in excludes that don't resolve are silently ignored (not errors) -- this
    allows excludes to be more permissive without failing on optional paths.

    Args:
        data: Full primary document data.
        scope_paths: Paths to include.
        scope_excludes: Paths to subtract from the inclusions.
        runtime: Runtime context; required when any path uses ``sibling.*``.

    Returns:
        List of ``(concrete_path, items)`` tuples after exclusion filtering.
    """
    included = resolve_glob_paths(data, scope_paths, runtime)
    if not scope_excludes:
        return included

    excluded_paths = {concrete for concrete, _items in resolve_glob_paths(data, scope_excludes, runtime)}
    return [(concrete, items) for concrete, items in included if concrete not in excluded_paths]
