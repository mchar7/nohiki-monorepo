"""Tests for package initialization and lazy imports."""

from __future__ import annotations

import importlib
import sys

_ISOLATED_MODULE_PREFIXES = ("fastapi", "nohiki_observability", "nohiki_redis_utils")


def test_cache_only_import_keeps_optional_features_lazy() -> None:
    """Cache-only imports must not load HTTP or optional Redis features."""
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in _ISOLATED_MODULE_PREFIXES)
    }
    try:
        for name in saved_modules:
            sys.modules.pop(name, None)

        redis_utils = importlib.import_module("nohiki_redis_utils")
        lazy_modules = {
            "nohiki_redis_utils.auth_rate_limiter",
            "nohiki_redis_utils.delayed_queue",
            "nohiki_redis_utils.distributed_lock",
            "nohiki_redis_utils.metrics",
            "nohiki_redis_utils.multi_tier_rate_limiter",
            "nohiki_redis_utils.rate_limiter",
        }
        assert lazy_modules.isdisjoint(sys.modules)
        assert "fastapi" not in sys.modules

        auth_limiter = redis_utils.AuthRateLimiter
        assert auth_limiter.__module__ == "nohiki_redis_utils.auth_rate_limiter"
        assert "nohiki_redis_utils.auth_rate_limiter" in sys.modules
        assert "nohiki_redis_utils.multi_tier_rate_limiter" in sys.modules
        assert "nohiki_redis_utils.rate_limiter" in sys.modules
    finally:
        stale_modules = [
            name
            for name in sys.modules
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in _ISOLATED_MODULE_PREFIXES)
        ]
        for name in stale_modules:
            del sys.modules[name]
        sys.modules.update(saved_modules)
