"""Module-level constants for scaffold validation and rendering."""

from __future__ import annotations

from typing import Final

MIN_NAME_LEN: Final[int] = 3
MAX_NAME_LEN: Final[int] = 40
MAX_DESCRIPTION_LEN: Final[int] = 200
MAX_OWNER_LEN: Final[int] = 40
SERVICE_NAME_PATTERN: Final[str] = r"^[a-z][a-z0-9-]{2,40}$"
LIB_NAME_PATTERN: Final[str] = r"^nohiki-[a-z][a-z0-9-]{1,40}$"
OWNER_PATTERN: Final[str] = r"^[A-Za-z0-9_-]{1,40}$"
SCHEMA_NAME_PATTERN: Final[str] = r"^[a-z][a-z0-9_]{2,40}$"
ENV_PREFIX_PATTERN: Final[str] = r"^[A-Z][A-Z0-9_]{1,40}_$"

DEFAULT_VERIFY_TIMEOUT_S: Final[int] = 120
"""Per-step timeout for verification subprocesses."""
