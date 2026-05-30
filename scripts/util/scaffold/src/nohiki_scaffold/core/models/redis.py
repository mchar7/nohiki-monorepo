"""Redis feature configuration."""

from __future__ import annotations

from dataclasses import dataclass

from nohiki_scaffold.core.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class RedisOptions:
    """Redis-related feature flags."""

    enabled: bool = False
    bootstrap_distributed_lock: bool = False
    circuit_breaker_for_ext_http: bool = False

    def __post_init__(self) -> None:
        """Forbid Redis sub-features when Redis itself is disabled."""
        if not self.enabled and (self.bootstrap_distributed_lock or self.circuit_breaker_for_ext_http):
            msg = "Redis sub-features require redis.enabled=True"
            raise ValidationError(msg)


__all__ = ["RedisOptions"]
