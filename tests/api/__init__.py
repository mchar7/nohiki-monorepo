"""End-to-end testing package for Nohiki platform.

Tests hit real deployed services. Requires Docker Compose stack running.
"""

from .client import NohikiClient
from .config import E2EConfig

__all__ = [
    "E2EConfig",
    "NohikiClient",
]
