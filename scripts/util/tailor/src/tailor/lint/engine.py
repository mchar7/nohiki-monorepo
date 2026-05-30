"""Lint engine — dispatches flat-schema rule entries to registered rule instances.

The engine walks the rules list in declaration order and, per rule, executes
the following gate-resolve-substitute-check pipeline:

1. **Disabled check** — skip if ``rule_id`` is in ``runtime.disabled_rule_ids``.
2. **Tag gates** — skip if ``requires_tags`` is not a subset of
   ``runtime.active_tags`` or ``excludes_tags`` intersects it.
3. **Predicate gate** — if ``applies_when`` is present, evaluate the
   compiled CEL-subset predicate against ``(data, runtime)`` and skip on False.
4. **Scope resolution** — resolve ``scope_paths`` / ``scope_excludes`` through
   the path resolver, which handles ``$``, ``[*]`` wildcards, and the
   ``sibling.<name>`` prefix.
5. **Variable substitution** — expand ``{{ var }}`` references in any params
   listed in the rule's ``SUBSTITUTABLE_PARAMS`` using ``runtime.variables``.
6. **Params validation** — instantiate the rule's ``PARAMS_MODEL`` on the
   expanded dict. Failures surface as ``LintConfigError`` with rule_id context.
7. **Rule check** — invoke ``rule.check(...)`` and collect issues.

The engine is stateless aside from the injected registry; compiled predicates
are cached on ``_predicate_cache`` keyed by source text to amortise parse cost
across all calls sharing the engine instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from tailor.exceptions import LintConfigError
from tailor.lint.cel import CompiledPredicate, compile_predicate
from tailor.lint.content.rules.path_resolver import resolve_scope
from tailor.lint.meta import META_KEY
from tailor.lint.models import LintConfig, LintIssue, RuleConfig
from tailor.lint.registry import RULE_REGISTRY, RuleRegistry
from tailor.lint.runtime import LintRuntimeContext
from tailor.lint.substitute import substitute_params

if TYPE_CHECKING:
    from tailor.lint.content.rules.protocol import Rule


class LintResult(BaseModel, frozen=True):
    """Return value from ``LintEngine.evaluate()``.

    Attributes:
        issues: All emitted lint issues in declaration order.
    """

    issues: tuple[LintIssue, ...]


class LintEngine:
    """Dispatches YAML rule entries to registered rule implementations.

    A single instance may serve many evaluations; ``_predicate_cache`` caches
    compiled ``applies_when`` expressions by source text for the instance's
    lifetime. Callers that want a fresh cache should construct a new engine.
    """

    def __init__(self, registry: RuleRegistry | None = None) -> None:
        """Bind a rule registry for dispatch.

        Args:
            registry: Registry mapping TYPE_ID → Rule instance. When ``None``
                (the default), the module-level ``RULE_REGISTRY`` is used —
                resolved at construction time, not at function-definition
                time, so the registry is guaranteed to be populated.
        """
        self._registry = registry if registry is not None else RULE_REGISTRY
        self._predicate_cache: dict[str, CompiledPredicate] = {}

    def evaluate(
        self,
        data: dict[str, object],
        config: LintConfig,
        runtime: LintRuntimeContext | None = None,
    ) -> LintResult:
        """Run all configured rules against ``data``.

        Args:
            data: Parsed document data to lint (without the ``_tailor_meta`` key).
            config: Loaded lint configuration (flat rules list).
            runtime: Optional per-run context. Defaults to an empty context.

        Returns:
            Aggregated ``LintResult`` with issues from every rule that fired.

        Raises:
            LintConfigError: ``data`` still contains the ``_tailor_meta`` key
                (the meta block must be stripped before evaluation via
                ``extract_tailor_meta``). Rules could otherwise surface spurious
                hits against the meta block itself.
        """
        if META_KEY in data:
            msg = (
                f"LintEngine.evaluate received data containing the {META_KEY!r} key. "
                "Callers must strip it via extract_tailor_meta before evaluation."
            )
            raise LintConfigError(msg)
        ctx = runtime or LintRuntimeContext()
        issues: list[LintIssue] = []
        for rule_cfg in config.rules:
            issues.extend(self._evaluate_one(rule_cfg, data, ctx))
        return LintResult(issues=tuple(issues))

    def _evaluate_one(
        self,
        rule_cfg: RuleConfig,
        data: dict[str, object],
        runtime: LintRuntimeContext,
    ) -> list[LintIssue]:
        """Dispatch a single rule entry through the full gate-resolve-check pipeline."""
        if rule_cfg.rule_id in runtime.disabled_rule_ids:
            return []
        if not _tags_match(rule_cfg, runtime):
            return []
        if not self._applies_when_match(rule_cfg, data, runtime):
            return []

        rule = self._registry.get(rule_cfg.type)
        resolved = resolve_scope(data, rule_cfg.scope_paths, rule_cfg.scope_excludes, runtime)
        params = self._build_params(rule, rule_cfg, runtime)
        # ``rule.check`` returns ``list[LintIssue]`` already; returning it
        # directly avoids a redundant O(n) copy per rule invocation.
        return rule.check(
            rule_id=rule_cfg.rule_id,
            severity=rule_cfg.severity,
            resolved=resolved,
            params=params,
            data=data,
            runtime=runtime,
        )

    def _applies_when_match(
        self,
        rule_cfg: RuleConfig,
        data: dict[str, object],
        runtime: LintRuntimeContext,
    ) -> bool:
        """Evaluate the optional ``applies_when`` predicate; True when absent."""
        if rule_cfg.applies_when is None:
            return True
        predicate = self._predicate_cache.get(rule_cfg.applies_when)
        if predicate is None:
            predicate = compile_predicate(rule_cfg.applies_when)
            self._predicate_cache[rule_cfg.applies_when] = predicate
        # Evaluator closures are pure functions of ``(data, runtime)``. Any
        # exception raised here is a bug in the CEL module, not user input,
        # so we let it propagate. The orchestrator's broad catch in
        # ``_run_lint`` keeps it from killing the generation pipeline.
        return predicate.evaluate(data, runtime)

    @staticmethod
    def _build_params(
        rule: Rule,
        rule_cfg: RuleConfig,
        runtime: LintRuntimeContext,
    ) -> BaseModel:
        """Substitute ``{{ var }}`` in substitutable fields, then validate via ``PARAMS_MODEL``.

        Validation failures (both missing vars and Pydantic errors) surface as
        ``LintConfigError`` keyed by ``rule_id`` so users see actionable messages.
        """
        expanded = substitute_params(
            rule_cfg.params,
            rule.SUBSTITUTABLE_PARAMS,
            runtime.variables,
            rule_id=rule_cfg.rule_id,
        )
        try:
            return rule.PARAMS_MODEL(**expanded)
        except ValidationError as err:
            details = "; ".join(f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in err.errors())
            msg = f"Invalid params for rule_id={rule_cfg.rule_id!r} (type={rule_cfg.type!r}): {details}"
            raise LintConfigError(msg) from err


def _tags_match(rule_cfg: RuleConfig, runtime: LintRuntimeContext) -> bool:
    """Return True when ``requires_tags`` are satisfied and ``excludes_tags`` are absent."""
    requires_ok = not rule_cfg.requires_tags or all(tag in runtime.active_tags for tag in rule_cfg.requires_tags)
    excludes_ok = not rule_cfg.excludes_tags or not any(tag in runtime.active_tags for tag in rule_cfg.excludes_tags)
    return requires_ok and excludes_ok


_DEFAULT_ENGINE: LintEngine | None = None
"""Process-wide default engine. Lazily instantiated on first ``run_lint``
call so that import-order hazards cannot bind the engine to a partially
populated registry. Reusing a single instance preserves the compiled-predicate
cache across orchestrator invocations."""


def run_lint(
    data: dict[str, object],
    config: LintConfig,
    runtime: LintRuntimeContext | None = None,
) -> list[LintIssue]:
    """Module-level convenience shim that binds the singleton ``RULE_REGISTRY``.

    Preserves the plain ``list[LintIssue]`` return contract used by the tailor
    orchestrator to minimize downstream churn during the schema migration.
    Reuses the module-level default engine so the compiled-predicate cache
    persists across calls (applies_when expressions compile exactly once per
    process).
    """
    global _DEFAULT_ENGINE  # noqa: PLW0603 — deliberate lazy singleton
    if _DEFAULT_ENGINE is None:
        _DEFAULT_ENGINE = LintEngine()
    return list(_DEFAULT_ENGINE.evaluate(data, config, runtime).issues)
