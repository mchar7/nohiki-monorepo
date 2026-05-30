"""Exception hierarchy for nohiki-scaffold.

All exceptions raised by scaffold internals derive from :class:`ScaffoldError`.
This lets CLI command wrappers catch the base class to map to exit code 2
while letting narrower subclasses produce specific user-facing messages.
"""

from __future__ import annotations


class ScaffoldError(Exception):
    """Base class for all scaffold-level errors."""


class ValidationError(ScaffoldError):
    """A spec failed validation (regex, consistency, reserved-name collision)."""


class TemplateError(ScaffoldError):
    """A template failed to render (missing variable, syntax error, etc.)."""


class WorkspaceEditError(ScaffoldError):
    """Root ``pyproject.toml`` edit could not be applied."""


class VerifyError(ScaffoldError):
    """Post-scaffold verification failed."""


__all__ = [
    "ScaffoldError",
    "TemplateError",
    "ValidationError",
    "VerifyError",
    "WorkspaceEditError",
]
