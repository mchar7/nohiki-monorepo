"""Layout rule implementations + layout-specific registry.

Three rule types are defined here:

    * ``orphan_detected`` — flags paragraphs whose final wrapped line is too
      short, the visual analogue of the content-side ``orphan_final_word``.
    * ``page_overflow`` — soft page budget (allows small tolerance).
    * ``max_pages_exceeded`` — hard page ceiling, no tolerance.

Design notes:
    * Layout rules share the same ``Rule`` Protocol as content rules: they
      accept ``rule_id``, ``severity``, ``resolved``, ``params``, plus the
      layout-specific ``layout`` kwarg.
    * ``resolved`` is unused for document-level layout rules (``scope_paths:
      ["$"]``), but kept in the signature for Protocol substitutability. For
      ``orphan_detected``, resolved paths filter which paragraphs apply.
    * A separate ``LayoutRuleRegistry`` keeps layout rule types isolated from
      content rules so ``LintConfig.layout.rules`` only ever dispatches
      layout-family types — catching YAML bugs early.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, Field, StrictInt

from tailor.lint.cel import CompiledPredicate, compile_predicate
from tailor.lint.content.rules.path_resolver import resolve_scope
from tailor.lint.layout.extractor import LayoutMetadata, ParagraphLayout
from tailor.lint.models import LintIssue, RuleConfig, Severity
from tailor.lint.runtime import LintRuntimeContext
from tailor.lint.substitute import substitute_params


@runtime_checkable
class LayoutRule(Protocol):
    """Protocol shared by all layout rule implementations.

    Mirrors :class:`tailor.lint.content.rules.protocol.Rule` but the engine
    injects a ``layout: LayoutMetadata`` kwarg instead of ``data`` / ``runtime``.
    The ``**_`` catch-all preserves forward compatibility with future kwargs.
    """

    TYPE_ID: ClassVar[str]
    PARAMS_MODEL: ClassVar[type[BaseModel]]
    SUBSTITUTABLE_PARAMS: ClassVar[frozenset[str]]

    def check(
        self,
        *,
        rule_id: str,
        severity: Severity,
        resolved: list[tuple[str, list[object]]],
        params: BaseModel,
        layout: LayoutMetadata,
        **_: object,
    ) -> list[LintIssue]:
        """Evaluate this rule and return any triggered issues.

        Args:
            rule_id: Canonical rule identifier from the YAML config.
            severity: Severity to attach to emitted issues.
            resolved: Path resolver output; document-level rules ignore it.
            params: Validated ``PARAMS_MODEL`` instance for this rule.
            layout: Structured post-render layout metadata.
            **_: Ignored forward-compat kwargs.

        Returns:
            Zero or more :class:`LintIssue` objects, one per finding.
        """
        ...


# --------------------------------------------------------------------------- #
# orphan_detected                                                              #
# --------------------------------------------------------------------------- #


class OrphanDetectedParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``orphan_detected``.

    Attributes:
        width_fill_ratio: Last-wrapped-line width divided by paragraph width.
            Below this ratio the line is considered "short" enough to flag.
            Range ``(0.0, 1.0]``; typical value ``0.15``.
        min_substantive_words: If the final line has fewer than this many
            non-stopword tokens, it is also considered an orphan regardless
            of its width-fill ratio. ``>= 1``.
        exclude_single_line: When ``True``, paragraphs that fit on one line
            are never flagged (they cannot orphan).
    """

    width_fill_ratio: float = Field(0.15, gt=0.0, le=1.0)
    min_substantive_words: StrictInt = Field(3, ge=1)
    exclude_single_line: bool = True


class OrphanDetectedRule:
    """Flag paragraphs whose final wrapped line meets orphan criteria.

    Behavior:
        * If ``exclude_single_line`` and the paragraph has one wrapped line,
          skip it.
        * Compute ``last_line_width / paragraph_bbox_width``. If that ratio
          is below ``width_fill_ratio`` **or** the last line has fewer than
          ``min_substantive_words`` non-stopword tokens, emit an issue.

    The issue ``path`` is the paragraph's scope path, ``value`` carries the
    final line's text for easy diagnosis in CLI output.
    """

    TYPE_ID: ClassVar[str] = "orphan_detected"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = OrphanDetectedParams
    SUBSTITUTABLE_PARAMS: ClassVar[frozenset[str]] = frozenset()

    def check(
        self,
        *,
        rule_id: str,
        severity: Severity,
        resolved: list[tuple[str, list[object]]],
        params: BaseModel,
        layout: LayoutMetadata,
        **_: object,
    ) -> list[LintIssue]:
        """Emit one issue per paragraph matching orphan criteria."""
        if not isinstance(params, OrphanDetectedParams):
            msg = f"OrphanDetectedRule expected OrphanDetectedParams, got {type(params).__name__}"
            raise TypeError(msg)
        matched_paths = {path for path, _ in resolved}
        issues: list[LintIssue] = []
        for paragraph in layout.paragraphs:
            if matched_paths and paragraph.scope_path not in matched_paths:
                continue
            if params.exclude_single_line and len(paragraph.wrapped_lines) <= 1:
                continue
            if not paragraph.wrapped_lines:
                continue
            issue = self._evaluate(paragraph, params, rule_id, severity)
            if issue is not None:
                issues.append(issue)
        return issues

    @staticmethod
    def _evaluate(
        paragraph: ParagraphLayout,
        params: OrphanDetectedParams,
        rule_id: str,
        severity: Severity,
    ) -> LintIssue | None:
        """Return an issue if the paragraph's final line orphans, else ``None``."""
        last = paragraph.wrapped_lines[-1]
        paragraph_width = max(1e-6, paragraph.bbox_pt[2] - paragraph.bbox_pt[0])
        last_width = max(0.0, last.bbox_pt[2] - last.bbox_pt[0])
        fill_ratio = last_width / paragraph_width
        if fill_ratio >= params.width_fill_ratio and last.substantive_word_count >= params.min_substantive_words:
            return None
        message = (
            f"Orphan detected: final wrapped line fills {fill_ratio:.0%} of paragraph width "
            f"({last.substantive_word_count} substantive words)"
        )
        return LintIssue(
            rule=rule_id,
            severity=severity,
            path=paragraph.scope_path,
            message=message,
            value=last.text,
        )


# --------------------------------------------------------------------------- #
# page_overflow                                                                #
# --------------------------------------------------------------------------- #


class PageOverflowParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``page_overflow``.

    Attributes:
        max_pages: Soft page budget (positive integer).
        tolerance_pt: Allow ``total_content_height_pt`` to exceed
            ``max_pages * page_height`` by up to this many points before
            flagging. Useful when a template has a small footer that consumes
            space but is acceptable. ``>= 0``.
    """

    max_pages: StrictInt = Field(..., ge=1)
    tolerance_pt: float = Field(0.0, ge=0.0)


class PageOverflowRule:
    """Soft page-budget check.

    Emits a single issue when ``layout.page_count > params.max_pages`` unless
    the content-height overshoot is within ``params.tolerance_pt``.
    """

    TYPE_ID: ClassVar[str] = "page_overflow"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = PageOverflowParams
    SUBSTITUTABLE_PARAMS: ClassVar[frozenset[str]] = frozenset()

    def check(
        self,
        *,
        rule_id: str,
        severity: Severity,
        resolved: list[tuple[str, list[object]]],
        params: BaseModel,
        layout: LayoutMetadata,
        **_: object,
    ) -> list[LintIssue]:
        """Emit at most one aggregate issue when the soft budget is exceeded."""
        if not isinstance(params, PageOverflowParams):
            msg = f"PageOverflowRule expected PageOverflowParams, got {type(params).__name__}"
            raise TypeError(msg)
        # ``resolved`` is part of the shared Rule Protocol shape but unused
        # here. ``page_overflow`` is a document-level aggregate (scope ``"$"``).
        del resolved
        if layout.page_count <= params.max_pages:
            return []
        page_height = layout.page_size_pt[1]
        allowed_total = params.max_pages * page_height + params.tolerance_pt
        if layout.total_content_height_pt <= allowed_total:
            return []
        overshoot = layout.page_count - params.max_pages
        message = (
            f"Content overflows {params.max_pages}-page soft budget by {overshoot} "
            f"page(s); rendered {layout.page_count}"
        )
        return [LintIssue(rule=rule_id, severity=severity, path="$", message=message, value=None)]


# --------------------------------------------------------------------------- #
# max_pages_exceeded                                                           #
# --------------------------------------------------------------------------- #


class MaxPagesExceededParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``max_pages_exceeded``.

    Attributes:
        max_pages: Hard page ceiling (positive integer). No tolerance is
            permitted — this rule is for the "must not exceed" case.
    """

    max_pages: StrictInt = Field(..., ge=1)


class MaxPagesExceededRule:
    """Hard page-count ceiling.

    Emits a single issue when ``layout.page_count > params.max_pages``. No
    tolerance; this is the rule to use when the template literally cannot
    accept more pages (e.g. a hard single-page ceiling).
    """

    TYPE_ID: ClassVar[str] = "max_pages_exceeded"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = MaxPagesExceededParams
    SUBSTITUTABLE_PARAMS: ClassVar[frozenset[str]] = frozenset()

    def check(
        self,
        *,
        rule_id: str,
        severity: Severity,
        resolved: list[tuple[str, list[object]]],
        params: BaseModel,
        layout: LayoutMetadata,
        **_: object,
    ) -> list[LintIssue]:
        """Emit at most one aggregate issue when the hard ceiling is exceeded."""
        if not isinstance(params, MaxPagesExceededParams):
            msg = f"MaxPagesExceededRule expected MaxPagesExceededParams, got {type(params).__name__}"
            raise TypeError(msg)
        # See PageOverflowRule.check. ``resolved`` is unused here.
        del resolved
        if layout.page_count <= params.max_pages:
            return []
        excess = layout.page_count - params.max_pages
        message = f"Document exceeds hard page ceiling: {layout.page_count} pages (max {params.max_pages})"
        return [
            LintIssue(
                rule=rule_id,
                severity=severity,
                path="$",
                message=message,
                value=f"+{excess} pages",
            )
        ]


# --------------------------------------------------------------------------- #
# Registry + runner                                                            #
# --------------------------------------------------------------------------- #


class LayoutRuleRegistry:
    """Type-id → :class:`LayoutRule` instance map.

    Mirrors :class:`tailor.lint.registry.RuleRegistry` but scoped to layout
    rule types so ``LintConfig.layout.rules`` can be validated against a
    narrower set of allowed types.
    """

    def __init__(self) -> None:
        """Initialise with an empty registry."""
        self._rules: dict[str, LayoutRule] = {}

    def register(self, rule: LayoutRule) -> None:
        """Register a rule instance by its ``TYPE_ID``.

        Raises:
            ValueError: ``TYPE_ID`` already registered.
        """
        if rule.TYPE_ID in self._rules:
            msg = f"Layout rule already registered: {rule.TYPE_ID!r}"
            raise ValueError(msg)
        self._rules[rule.TYPE_ID] = rule

    def get(self, type_id: str) -> LayoutRule:
        """Return the rule registered under ``type_id``.

        Raises:
            KeyError: No rule registered under ``type_id``.
        """
        if type_id not in self._rules:
            msg = f"Unknown layout rule type: {type_id!r}"
            raise KeyError(msg)
        return self._rules[type_id]

    def contains(self, type_id: str) -> bool:
        """Return whether ``type_id`` is registered."""
        return type_id in self._rules

    def known_types(self) -> tuple[str, ...]:
        """Return all registered type ids, sorted for stable output."""
        return tuple(sorted(self._rules))


LAYOUT_RULE_REGISTRY: LayoutRuleRegistry = LayoutRuleRegistry()
"""Process-wide layout rule registry. Populated by :func:`register_layout_rules`."""


def register_layout_rules(registry: LayoutRuleRegistry = LAYOUT_RULE_REGISTRY) -> None:
    """Register built-in layout rules into ``registry`` (idempotent)."""
    builtins: tuple[LayoutRule, ...] = (
        OrphanDetectedRule(),
        PageOverflowRule(),
        MaxPagesExceededRule(),
    )
    for rule in builtins:
        if not registry.contains(rule.TYPE_ID):
            registry.register(rule)


# Populate on module import; safe because register_layout_rules is idempotent.
register_layout_rules()


# Shared predicate cache across run_layout_lint invocations. This mirrors the
# per-engine cache in LintEngine so the same applies_when expression only
# compiles once per process.
_LAYOUT_PREDICATE_CACHE: dict[str, CompiledPredicate] = {}

# Synthetic empty document root. Layout rules are document-level
# (``scope_paths: ["$"]``); resolve_scope emits a single ``("$", [data])`` tuple
# when ``data`` is any non-None value. Kept module-level to avoid allocating a
# fresh dict per call.
_EMPTY_LAYOUT_DATA: dict[str, object] = {}


def run_layout_lint(
    rule_configs: tuple[RuleConfig, ...],
    layout: LayoutMetadata,
    *,
    data: dict[str, object] | None = None,
    runtime: LintRuntimeContext | None = None,
    registry: LayoutRuleRegistry = LAYOUT_RULE_REGISTRY,
) -> list[LintIssue]:
    """Evaluate every layout ``RuleConfig`` against ``layout``.

    Mirrors :meth:`tailor.lint.engine.LintEngine.evaluate` for content rules
    but scoped to the layout domain. All gating kinds are honoured symmetrically:
    ``disabled_rule_ids`` → ``requires_tags`` → ``excludes_tags`` →
    ``applies_when``.

    Args:
        rule_configs: Parsed layout rule entries (from
            ``LintConfig.layout.rules``).
        layout: Extracted layout metadata.
        data: Document data dict. Only consumed by the ``applies_when``
            predicate evaluator (so ``schema_has_path('x.y')`` can resolve
            against the real document). When ``None``, ``schema_has_path``
            predicates always return False.
        runtime: Optional runtime context. Used for tag gating, ``applies_when``
            predicate evaluation (``has_tag`` / ``schema_has_path`` /
            ``has_sibling``), ``{{var}}`` substitution in layout rule params,
            and disabled-rule filtering.
        registry: Layout rule registry. Defaults to the process-wide
            :data:`LAYOUT_RULE_REGISTRY`.

    Returns:
        Flattened list of :class:`LintIssue` in ``rule_configs`` order.

    Raises:
        KeyError: Unknown layout rule type in a ``RuleConfig``.
        TypeError: Invalid params for a layout rule.
        LintConfigError: ``applies_when`` references an undefined variable or
            a required ``{{var}}`` is missing from ``runtime.variables``.
    """
    issues: list[LintIssue] = []
    active_tags = runtime.active_tags if runtime is not None else frozenset()
    disabled = runtime.disabled_rule_ids if runtime is not None else frozenset()
    variables = runtime.variables if runtime is not None else {}
    predicate_data: dict[str, object] = data if data is not None else _EMPTY_LAYOUT_DATA
    for cfg in rule_configs:
        if cfg.rule_id in disabled:
            continue
        if cfg.requires_tags and not all(t in active_tags for t in cfg.requires_tags):
            continue
        if cfg.excludes_tags and any(t in active_tags for t in cfg.excludes_tags):
            continue
        if cfg.applies_when is not None and not _layout_applies_when(cfg.applies_when, predicate_data, runtime):
            continue
        rule = registry.get(cfg.type)
        expanded = substitute_params(
            cfg.params,
            rule.SUBSTITUTABLE_PARAMS,
            variables,
            rule_id=cfg.rule_id,
        )
        params = rule.PARAMS_MODEL(**expanded)
        resolved = resolve_scope(predicate_data, cfg.scope_paths, cfg.scope_excludes)
        issues.extend(
            rule.check(
                rule_id=cfg.rule_id,
                severity=cfg.severity,
                resolved=resolved,
                params=params,
                layout=layout,
            )
        )
    return issues


def _layout_applies_when(
    source: str,
    data: dict[str, object],
    runtime: LintRuntimeContext | None,
) -> bool:
    """Compile-or-fetch ``source`` from the module cache and evaluate it.

    Uses a shared module-level cache so each distinct expression compiles
    exactly once per process. A ``None`` runtime is evaluated against a
    synthetic default context (empty tags, empty siblings, empty vars), which
    means predicates like ``has_tag('x')`` return False rather than raising.
    """
    predicate = _LAYOUT_PREDICATE_CACHE.get(source)
    if predicate is None:
        predicate = compile_predicate(source)
        _LAYOUT_PREDICATE_CACHE[source] = predicate
    ctx = runtime if runtime is not None else LintRuntimeContext()
    return predicate.evaluate(data, ctx)
