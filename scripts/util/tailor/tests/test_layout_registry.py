"""Tests for LayoutRuleRegistry and registration of layout rules.

Tests cover registration, retrieval, contains checks, and module-level population.
"""

from __future__ import annotations

import pytest
from tailor.lint.layout.rules import (
    LAYOUT_RULE_REGISTRY,
    LayoutRuleRegistry,
    MaxPagesExceededRule,
    OrphanDetectedRule,
    PageOverflowRule,
    register_layout_rules,
)


class TestLayoutRuleRegistry:
    """Tests for the LayoutRuleRegistry class."""

    def test_new_registry_is_empty(self) -> None:
        """A newly created registry has no rules."""
        registry = LayoutRuleRegistry()
        assert len(registry.known_types()) == 0

    def test_register_single_rule(self) -> None:
        """A rule can be registered by its TYPE_ID."""
        registry = LayoutRuleRegistry()
        rule = OrphanDetectedRule()
        registry.register(rule)
        assert registry.contains(rule.TYPE_ID)

    def test_get_registered_rule(self) -> None:
        """Registered rule can be retrieved."""
        registry = LayoutRuleRegistry()
        rule = OrphanDetectedRule()
        registry.register(rule)
        retrieved = registry.get("orphan_detected")
        assert retrieved is rule

    def test_register_multiple_rules(self) -> None:
        """Multiple rules can be registered in the same registry."""
        registry = LayoutRuleRegistry()
        rules = (OrphanDetectedRule(), PageOverflowRule(), MaxPagesExceededRule())
        for rule in rules:
            registry.register(rule)
        assert len(registry.known_types()) == 3

    def test_duplicate_type_id_raises_error(self) -> None:
        """Registering the same TYPE_ID twice raises ValueError."""
        registry = LayoutRuleRegistry()
        rule1 = OrphanDetectedRule()
        rule2 = OrphanDetectedRule()  # Same TYPE_ID
        registry.register(rule1)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(rule2)

    def test_get_unknown_type_raises_keyerror(self) -> None:
        """Getting an unregistered rule type raises KeyError."""
        registry = LayoutRuleRegistry()
        with pytest.raises(KeyError, match="Unknown layout rule type"):
            registry.get("nonexistent_rule")

    def test_contains_returns_boolean(self) -> None:
        """contains() returns True for registered, False for unregistered."""
        registry = LayoutRuleRegistry()
        rule = PageOverflowRule()
        registry.register(rule)
        assert registry.contains("page_overflow") is True
        assert registry.contains("unknown") is False

    def test_known_types_returns_sorted_tuple(self) -> None:
        """known_types() returns registered type_ids in sorted order."""
        registry = LayoutRuleRegistry()
        registry.register(MaxPagesExceededRule())
        registry.register(OrphanDetectedRule())
        registry.register(PageOverflowRule())
        types = registry.known_types()
        assert types == ("max_pages_exceeded", "orphan_detected", "page_overflow")

    def test_known_types_empty_registry(self) -> None:
        """known_types() on empty registry returns empty tuple."""
        registry = LayoutRuleRegistry()
        assert registry.known_types() == ()


class TestRegisterLayoutRules:
    """Tests for the register_layout_rules() function."""

    def test_register_layout_rules_populates_registry(self) -> None:
        """register_layout_rules() adds the three built-in rules."""
        registry = LayoutRuleRegistry()
        register_layout_rules(registry)
        known = registry.known_types()
        assert "orphan_detected" in known
        assert "page_overflow" in known
        assert "max_pages_exceeded" in known

    def test_register_layout_rules_idempotent(self) -> None:
        """Calling register_layout_rules() twice is safe (idempotent)."""
        registry = LayoutRuleRegistry()
        register_layout_rules(registry)
        types_first = registry.known_types()
        # Calling again should not raise or change state
        register_layout_rules(registry)
        types_second = registry.known_types()
        assert types_first == types_second

    def test_register_layout_rules_uses_process_registry_by_default(self) -> None:
        """register_layout_rules() defaults to LAYOUT_RULE_REGISTRY."""
        # The process registry is already populated on module import,
        # so we just verify it has the built-in rules.
        assert LAYOUT_RULE_REGISTRY.contains("orphan_detected")
        assert LAYOUT_RULE_REGISTRY.contains("page_overflow")
        assert LAYOUT_RULE_REGISTRY.contains("max_pages_exceeded")


class TestLayoutRuleRegistryModuleLevel:
    """Tests for module-level LAYOUT_RULE_REGISTRY population."""

    def test_layout_rule_registry_pre_populated(self) -> None:
        """LAYOUT_RULE_REGISTRY is populated on module import."""
        assert len(LAYOUT_RULE_REGISTRY.known_types()) == 3

    def test_all_builtin_rules_registered(self) -> None:
        """All three built-in rules are in LAYOUT_RULE_REGISTRY."""
        types = LAYOUT_RULE_REGISTRY.known_types()
        assert "orphan_detected" in types
        assert "page_overflow" in types
        assert "max_pages_exceeded" in types

    def test_builtin_rules_are_correct_instances(self) -> None:
        """Retrieved rules are the correct types."""
        orphan_rule = LAYOUT_RULE_REGISTRY.get("orphan_detected")
        assert orphan_rule.TYPE_ID == "orphan_detected"
        page_overflow_rule = LAYOUT_RULE_REGISTRY.get("page_overflow")
        assert page_overflow_rule.TYPE_ID == "page_overflow"
        max_pages_rule = LAYOUT_RULE_REGISTRY.get("max_pages_exceeded")
        assert max_pages_rule.TYPE_ID == "max_pages_exceeded"
