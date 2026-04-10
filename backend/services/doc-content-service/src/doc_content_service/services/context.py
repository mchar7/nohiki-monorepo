"""Context dataclass for PydanticAI content generation agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DocumentContentContext:
    """All context needed for content generation via PydanticAI.

    This dataclass is injected into the PydanticAI agent and available
    in system prompt builders via RunContext.deps.
    """

    job_data: dict[str, Any]
    schema_definition: dict[str, Any]
    schema_name: str
    schema_version: str
    attachments: list[dict[str, str]]
    user_preferences: dict[str, Any]
