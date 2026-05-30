"""Backend service specification."""

from __future__ import annotations

from dataclasses import dataclass

from nohiki_scaffold.core.exceptions import ValidationError
from nohiki_scaffold.core.features import KafkaRole, ServiceShape

from ._validation import (
    validate_description,
    validate_env_prefix,
    validate_name,
    validate_owner,
)
from .database import DatabaseOptions
from .kafka import KafkaOptions
from .ml import MLOptions
from .redis import RedisOptions
from .s3 import S3Options


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """Complete specification for a backend service."""

    name: str
    friendly_name: str
    description: str
    owner: str
    shape: ServiceShape
    env_prefix: str
    module_name: str
    database: DatabaseOptions
    redis: RedisOptions
    kafka: KafkaOptions
    s3: S3Options
    ml: MLOptions

    def __post_init__(self) -> None:
        """Validate names, owner, env_prefix, description; enforce shape/role consistency."""
        self._validate_strings()
        self._validate_shape_kafka_consistency()

    def _validate_strings(self) -> None:
        """Regex-validate atomic string fields."""
        validate_name(self.name)
        validate_owner(self.owner)
        validate_env_prefix(self.env_prefix)
        if not self.friendly_name.strip():
            msg = "friendly_name must not be empty"
            raise ValidationError(msg)
        validate_description(self.description)

    def _validate_shape_kafka_consistency(self) -> None:
        """Enforce shape x kafka-role consistency rules."""
        if self.shape is ServiceShape.HTTP_ONLY and self.kafka.role in {
            KafkaRole.CONSUMER_ONLY,
            KafkaRole.BOTH,
        }:
            msg = "HTTP_ONLY shape cannot have a consumer kafka role"
            raise ValidationError(msg)
        if self.shape is ServiceShape.KAFKA_ONLY and self.kafka.role is KafkaRole.NONE:
            msg = "KAFKA_ONLY shape requires a non-NONE kafka.role"
            raise ValidationError(msg)


__all__ = ["ServiceSpec"]
