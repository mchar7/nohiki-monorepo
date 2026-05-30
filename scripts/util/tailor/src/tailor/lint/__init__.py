"""Document linting system for tailor CLI — flat-schema lint with registry dispatch."""

from __future__ import annotations

from tailor.lint.config import load_lint_config
from tailor.lint.engine import LintEngine, LintResult, run_lint
from tailor.lint.meta import META_KEY, TailorMetaConfig, build_runtime, extract_tailor_meta
from tailor.lint.models import (
    ROOT_PATH,
    BannedPattern,
    LayoutConfig,
    LintConfig,
    LintIssue,
    RuleConfig,
    Severity,
)
from tailor.lint.registry import RULE_REGISTRY, RuleRegistry, register_builtin_rules
from tailor.lint.runtime import LintRuntimeContext

# Registry is populated at import time by ``tailor.lint.registry`` itself so
# we don't need to invoke ``register_builtin_rules`` here. The symbol is
# re-exported for callers that want to populate a custom registry.

__all__ = [
    "META_KEY",
    "ROOT_PATH",
    "RULE_REGISTRY",
    "BannedPattern",
    "LayoutConfig",
    "LintConfig",
    "LintEngine",
    "LintIssue",
    "LintResult",
    "LintRuntimeContext",
    "RuleConfig",
    "RuleRegistry",
    "Severity",
    "TailorMetaConfig",
    "build_runtime",
    "extract_tailor_meta",
    "load_lint_config",
    "register_builtin_rules",
    "run_lint",
]
