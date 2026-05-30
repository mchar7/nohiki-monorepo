"""Rule registry for dispatching YAML rule entries to concrete rule implementations.

Rules are stateless singletons mapped by ``TYPE_ID``. Registration is
centralized via ``register_builtin_rules`` to avoid import-time side effects
in rule modules -- importing ``tailor.lint.registry`` alone populates the
default registry idempotently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tailor.lint.content.rules.protocol import Rule


class RuleRegistry:
    """Mutable mapping of ``TYPE_ID`` → concrete rule instance.

    Rule instances are stateless and shared across all dispatches. Registration
    raises ``ValueError`` on duplicate ``TYPE_ID`` to catch accidental
    double-registration.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._rules: dict[str, Rule] = {}

    def register(self, rule: Rule) -> None:
        """Register a rule instance under its ``TYPE_ID``.

        Args:
            rule: Rule instance with a ``TYPE_ID`` class variable.

        Raises:
            ValueError: If the type id is already registered.
        """
        type_id = rule.TYPE_ID
        if type_id in self._rules:
            msg = f"Rule type id {type_id!r} is already registered"
            raise ValueError(msg)
        self._rules[type_id] = rule

    def get(self, type_id: str) -> Rule:
        """Return the rule registered under ``type_id``.

        Args:
            type_id: Rule type identifier.

        Returns:
            The registered rule instance.

        Raises:
            KeyError: If no rule is registered under ``type_id``.
        """
        try:
            return self._rules[type_id]
        except KeyError as err:
            msg = f"Unknown rule type id: {type_id!r}"
            raise KeyError(msg) from err

    def contains(self, type_id: str) -> bool:
        """Return True iff ``type_id`` is registered."""
        return type_id in self._rules

    def known_types(self) -> tuple[str, ...]:
        """Return sorted tuple of all registered type ids."""
        return tuple(sorted(self._rules))


def register_builtin_rules(registry: RuleRegistry) -> None:
    """Register every built-in rule class on ``registry``.

    Imports the rule modules inside the function so that importing
    ``tailor.lint.registry`` by itself does not pull the rule modules
    transitively -- callers opt in by invoking this function.

    Idempotent: re-invocation is a no-op for already-registered rules.

    Args:
        registry: Target registry to populate.
    """
    from tailor.lint.content.rules.cross_path_rules import (
        RepeatedLiteralAcrossPathsRule,
        RepeatedPhraseAcrossPathsRule,
    )
    from tailor.lint.content.rules.orphan_rules import OrphanFinalWordHeuristicRule
    from tailor.lint.content.rules.ratio_rules import RatioRule
    from tailor.lint.content.rules.rhythm_rules import RhythmCheckRule
    from tailor.lint.content.rules.section_rules import (
        BannedChildNamesRule,
        FirstItemCapitalizationRule,
        MaxChildItemsRule,
        MaxItemsRule,
        MaxWordsPerItemRule,
        MinItemsRule,
        MinWordsPerItemRule,
        UniqueOpeningWordsRule,
        VerbTenseRule,
    )
    from tailor.lint.content.rules.structure_rules import (
        RequiredSectionsRule,
        SectionOrderRule,
    )
    from tailor.lint.content.rules.text_rules import (
        BannedOpenersRule,
        BannedPatternsRule,
        MaxConsecutiveOpenerRule,
        MaxStructuralPunctuationPerSentenceRule,
        MentionCountRule,
    )
    from tailor.lint.content.rules.word_budget_rules import (
        MaxTotalWordsRule,
        MinTotalWordsRule,
    )

    # Each concrete class satisfies the ``Rule`` Protocol structurally; we
    # iterate without an intermediate tuple[Rule, ...] annotation because ty
    # cannot widen a heterogeneous tuple literal to a Protocol alias.
    builtins: list[Rule] = []
    builtins.append(MinItemsRule())
    builtins.append(MaxItemsRule())
    builtins.append(MinWordsPerItemRule())
    builtins.append(MaxWordsPerItemRule())
    builtins.append(UniqueOpeningWordsRule())
    builtins.append(VerbTenseRule())
    builtins.append(MaxChildItemsRule())
    builtins.append(BannedChildNamesRule())
    builtins.append(FirstItemCapitalizationRule())
    # Text family
    builtins.append(BannedPatternsRule())
    builtins.append(BannedOpenersRule())
    builtins.append(MaxStructuralPunctuationPerSentenceRule())
    builtins.append(MaxConsecutiveOpenerRule())
    builtins.append(MentionCountRule())
    # Word-budget family
    builtins.append(MinTotalWordsRule())
    builtins.append(MaxTotalWordsRule())
    # Structure family
    builtins.append(RequiredSectionsRule())
    builtins.append(SectionOrderRule())
    # Cross-path family
    builtins.append(RepeatedLiteralAcrossPathsRule())
    builtins.append(RepeatedPhraseAcrossPathsRule())
    # Ratio family
    builtins.append(RatioRule())
    # Rhythm family
    builtins.append(RhythmCheckRule())
    # Orphan content-heuristic family
    builtins.append(OrphanFinalWordHeuristicRule())

    for rule in builtins:
        if not registry.contains(rule.TYPE_ID):
            registry.register(rule)


# Module-level singleton. Populated unconditionally at module import so that
# any direct importer (e.g. ``from tailor.lint.engine import run_lint``) sees
# a fully populated registry without relying on ``tailor.lint.__init__``
# having been imported first.
RULE_REGISTRY = RuleRegistry()
register_builtin_rules(RULE_REGISTRY)
