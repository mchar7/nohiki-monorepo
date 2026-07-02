"""Re-export ``redis_container`` so pytest discovers it under ``tests/api/``.

Mirrors the pattern in ``tests/integration/conftest.py`` for Postgres.
"""

from __future__ import annotations

from nohiki_redis_utils.testing import redis_container

__all__ = ["redis_container"]
