"""Database feature configuration."""

from __future__ import annotations

from dataclasses import dataclass

from nohiki_scaffold.core.exceptions import ValidationError

from ._validation import validate_schema_name


@dataclass(frozen=True, slots=True)
class DatabaseOptions:
    """Postgres-related feature flags."""

    enabled: bool = False
    schema_name: str = ""
    outbox: bool = False
    alembic: bool = False
    saga: bool = False
    freshness_tracking: bool = False
    state_machine: bool = False

    def __post_init__(self) -> None:
        """Validate schema_name when DB is enabled; forbid sub-features when disabled."""
        if self.enabled:
            if not self.schema_name:
                msg = "database.schema_name is required when database.enabled=True"
                raise ValidationError(msg)
            validate_schema_name(self.schema_name)
        elif any((self.outbox, self.alembic, self.saga, self.freshness_tracking, self.state_machine)):
            msg = "Database sub-features require database.enabled=True"
            raise ValidationError(msg)


__all__ = ["DatabaseOptions"]
