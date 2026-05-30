"""Runtime context for lint evaluation.

The runtime context carries per-run state that rules, predicates, and path
resolvers consult during a single ``LintEngine.evaluate`` call: active tags,
variable substitutions, loaded sibling documents, and disabled rule IDs.

Populated by ``tailor.lint.meta.build_runtime`` from the ``_tailor_meta`` block
in input data. The dataclass itself is passive — it is just a frozen bag of
state threaded through the engine so that rules remain pure functions of
their inputs.

Even though the dataclass is ``frozen=True``, its mapping fields are typed as
``Mapping[...]`` (read-only protocol) so downstream code cannot mutate them
through the attribute. This makes the context effectively immutable from a
consumer's perspective — the only supported way to change runtime state is
to construct a new ``LintRuntimeContext``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LintRuntimeContext:
    """Per-run state consulted by rules during evaluation.

    Attributes:
        active_tags: Tags declared in ``_tailor_meta.lint_tags``. Controls
            ``requires_tags`` / ``excludes_tags`` gating on rules and the
            ``has_tag('x')`` CEL predicate.
        variables: ``lint_vars`` map. Used by ``{{ var }}`` substitution in
            substitutable rule params. Typed as ``Mapping[str, str]`` so
            consumers cannot mutate it through the frozen dataclass attribute.
        sibling_documents: Loaded sibling documents keyed by logical name,
            accessible via ``sibling.<name>.<path>`` in scope paths and the
            ``has_sibling('name')`` CEL predicate. Typed as ``Mapping[...]``
            for the same immutability reason as ``variables``.
        disabled_rule_ids: Rule IDs to skip entirely during evaluation.
    """

    active_tags: frozenset[str] = frozenset()
    variables: Mapping[str, str] = field(default_factory=dict)
    sibling_documents: Mapping[str, dict[str, object]] = field(default_factory=dict)
    disabled_rule_ids: frozenset[str] = frozenset()
