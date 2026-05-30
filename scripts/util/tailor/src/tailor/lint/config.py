"""YAML lint config loader for the flat-schema template lint configuration.

Loading happens in two passes:
1. **Structural validation** -- Pydantic parses the YAML into a ``LintConfig``.
   The built-in ``model_validator`` enforces non-empty rules and composite key
   uniqueness (``(rule_id, scope_path)``).
2. **Registry-aware validation** -- every rule's ``type`` is looked up in the
   ``RULE_REGISTRY``, and ``params`` is validated against the matching rule's
   ``PARAMS_MODEL``. This cannot happen in Pydantic itself because the
   registry is only populated once rule modules are imported.

The ``RULE_REGISTRY`` is pre-populated with built-in rules when
``tailor.lint`` is first imported via ``register_builtin_rules``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from tailor.exceptions import LintConfigError
from tailor.lint.layout.rules import LAYOUT_RULE_REGISTRY
from tailor.lint.models import LintConfig, RuleConfig
from tailor.lint.registry import RULE_REGISTRY


def load_lint_config(template_path: Path) -> LintConfig | None:
    """Load and validate a flat-schema lint config co-located with a template.

    Derives ``<stem>.lint.yaml`` from the template path. Returns ``None`` if no
    file exists (opt-in per template) or the file is empty / all-comments.

    Args:
        template_path: Path to the template HTML (or any file sharing the stem).

    Returns:
        Validated ``LintConfig`` with every rule's ``params`` pre-checked against
        its registered ``PARAMS_MODEL``. ``None`` when no config file is present.

    Raises:
        LintConfigError: The file exists but YAML is malformed, structure is
            invalid, an unknown ``type`` is referenced, or a rule's ``params``
            fail their rule's Pydantic validation.
    """
    lint_path = template_path.with_suffix(".lint.yaml")
    if not lint_path.exists():
        return None

    try:
        raw = lint_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError) as exc:
        msg = f"Failed to parse lint config {lint_path.name}: {exc}"
        raise LintConfigError(msg, path=str(lint_path)) from exc

    # Empty YAML file (or all-comment file) -- safe_load returns None.
    if data is None:
        return None

    if not isinstance(data, dict):
        msg = f"Lint config {lint_path.name} must be a YAML mapping, got {type(data).__name__}"
        raise LintConfigError(msg, path=str(lint_path))

    try:
        config = LintConfig.model_validate(data)
    except ValidationError as exc:
        raise _to_lint_config_error(exc, lint_path) from exc

    _validate_registry_and_params(config, lint_path)
    return config


def _validate_registry_and_params(config: LintConfig, lint_path: Path) -> None:
    """Fail-fast registry-aware validation for every rule in ``config``.

    Content rules (``config.rules``) are validated against ``RULE_REGISTRY``;
    layout rules (``config.layout.rules``) are validated against
    ``LAYOUT_RULE_REGISTRY``. Each rule's ``params`` dict must instantiate
    cleanly against its rule's ``PARAMS_MODEL``.
    """
    for rule_cfg in config.rules:
        _validate_rule_against_registry(
            rule_cfg,
            lint_path,
            contains=RULE_REGISTRY.contains,
            get_params_model=lambda type_id: RULE_REGISTRY.get(type_id).PARAMS_MODEL,
            known=RULE_REGISTRY.known_types,
            family="content",
        )

    if config.layout is not None:
        for rule_cfg in config.layout.rules:
            _validate_rule_against_registry(
                rule_cfg,
                lint_path,
                contains=LAYOUT_RULE_REGISTRY.contains,
                get_params_model=lambda type_id: LAYOUT_RULE_REGISTRY.get(type_id).PARAMS_MODEL,
                known=LAYOUT_RULE_REGISTRY.known_types,
                family="layout",
            )


def _validate_rule_against_registry(
    rule_cfg: RuleConfig,
    lint_path: Path,
    *,
    contains: Callable[[str], bool],
    get_params_model: Callable[[str], type[BaseModel]],
    known: Callable[[], tuple[str, ...]],
    family: str,
) -> None:
    """Validate one rule's ``type`` and ``params`` against a registry lookup."""
    if not contains(rule_cfg.type):
        msg = (
            f"Unknown {family} rule type {rule_cfg.type!r} in rule_id={rule_cfg.rule_id!r} "
            f"(known {family} types: {', '.join(known())})"
        )
        raise LintConfigError(msg, path=str(lint_path))

    params_model = get_params_model(rule_cfg.type)
    try:
        params_model(**rule_cfg.params)
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors())
        msg = f"Invalid params for rule_id={rule_cfg.rule_id!r} (type={rule_cfg.type!r}): {details}"
        raise LintConfigError(msg, path=str(lint_path)) from exc


def _to_lint_config_error(exc: ValidationError, lint_path: Path) -> LintConfigError:
    """Convert a Pydantic ValidationError into a ``LintConfigError`` with file context."""
    error_count = exc.error_count()
    details = "; ".join(f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors())
    msg = f"Invalid lint config {lint_path.name} ({error_count} error(s)): {details}"
    return LintConfigError(msg, path=str(lint_path))
