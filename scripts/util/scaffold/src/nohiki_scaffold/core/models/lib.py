"""Shared library specification."""

from __future__ import annotations

from dataclasses import dataclass, field

from nohiki_scaffold.core.exceptions import ValidationError

from ._validation import validate_description, validate_lib_name, validate_owner


@dataclass(frozen=True, slots=True)
class LibSpec:
    """Complete specification for a shared library."""

    name: str
    module_name: str
    description: str
    owner: str
    base_dependencies: frozenset[str] = field(default_factory=frozenset)
    optional_extras: dict[str, frozenset[str]] = field(default_factory=dict)
    ships_testing_module: bool = False
    ships_exceptions_module: bool = False
    ships_console_script: str | None = None
    namespace_package: bool = False

    def __post_init__(self) -> None:
        """Validate name, module_name, owner, description."""
        validate_lib_name(self.name)
        validate_owner(self.owner)
        validate_description(self.description)
        if not self.module_name.isidentifier():
            msg = f"module_name {self.module_name!r} is not a valid Python identifier"
            raise ValidationError(msg)


__all__ = ["LibSpec"]
