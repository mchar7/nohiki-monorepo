"""Protocol for all lint rules (content + layout).

``Rule`` is a ``typing.Protocol`` with ``runtime_checkable`` so concrete rule
classes can be recognized by both runtime ``isinstance`` checks and static
type checkers without requiring explicit inheritance registration (which
``ty`` does not handle well for ABCs).

Design decisions:

- ``rule_id`` and ``severity`` are passed per-call so one rule class serves
  many YAML entries with different ids/severities.
- ``params`` is a validated Pydantic instance of the rule's ``PARAMS_MODEL``.
  Each impl narrows via ``isinstance`` at the top of ``check()``.
- ``resolved`` is the engine's path-resolved view of ``scope_paths``. Most
  rules operate exclusively on this.
- ``data`` and ``runtime`` are threaded through for the small number of rules
  (cross-path, mention_count with variable targets, etc.) whose behavior
  depends on params-level paths or runtime tags/variables beyond the engine's
  pre-resolution step.
- The Protocol accepts a catch-all ``**_: object`` so rules that don't need
  ``data`` / ``runtime`` can omit them from their own signature (via the same
  catch-all) without falling out of Protocol compliance. This keeps unused-arg
  warnings silent without suppressions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pydantic import BaseModel

    from tailor.lint.models import LintIssue, Severity


@runtime_checkable
class Rule(Protocol):
    """Stateless lint rule dispatched by ``TYPE_ID``.

    Concrete implementations declare ``TYPE_ID``, ``PARAMS_MODEL``,
    ``SUBSTITUTABLE_PARAMS`` class vars and implement ``check()``.

    Attributes:
        TYPE_ID: Unique identifier matched against ``RuleConfig.type`` at dispatch.
        PARAMS_MODEL: Pydantic model class used to validate ``RuleConfig.params``.
        SUBSTITUTABLE_PARAMS: Names of string params that accept ``{{ var }}``
            substitution from the runtime variable map. Empty for most rules.
    """

    TYPE_ID: ClassVar[str]
    PARAMS_MODEL: ClassVar[type[BaseModel]]
    SUBSTITUTABLE_PARAMS: ClassVar[frozenset[str]] = frozenset()

    def check(
        self,
        *,
        rule_id: str,
        severity: Severity,
        resolved: list[tuple[str, list[object]]],
        params: BaseModel,
        **_: object,
    ) -> list[LintIssue]:
        """Run the rule against the resolved scope.

        Impl classes narrow ``params`` via an ``isinstance`` guard; the engine
        guarantees correctness via the registry mapping.

        The engine also passes ``data: dict[str, object]`` (the primary
        document with ``_tailor_meta`` stripped) and
        ``runtime: LintRuntimeContext`` as keyword arguments. Rules that need
        them declare them explicitly in their own signature; rules that don't
        absorb them via the same ``**_`` catch-all this Protocol uses.

        Args:
            rule_id: Composite rule identifier. Emitted as ``LintIssue.rule`` verbatim.
            severity: Severity to assign to any issues this call emits.
            resolved: ``(concrete_path, items)`` tuples from the path resolver.
            params: Validated ``PARAMS_MODEL`` instance for this rule type.

        Returns:
            Zero or more lint issues. An empty list indicates the rule passed.
        """
        ...
