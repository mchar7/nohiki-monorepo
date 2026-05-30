"""S3 feature configuration."""

from __future__ import annotations

from dataclasses import dataclass

from nohiki_scaffold.core.exceptions import ValidationError

from ._validation import validate_bucket_name, validate_key_prefix


@dataclass(frozen=True, slots=True)
class S3Options:
    """S3-related feature flags and parameters.

    When ``enabled=True``, ``bucket_name`` must be provided. ``key_prefix`` is
    optional and namespaces all object keys written by the service.
    """

    enabled: bool = False
    bucket_name: str | None = None
    key_prefix: str | None = None

    def __post_init__(self) -> None:
        """Enforce bucket_name presence/format when enabled; forbid params when disabled."""
        if self.enabled:
            if not self.bucket_name:
                msg = "s3.bucket_name is required when s3.enabled=True"
                raise ValidationError(msg)
            validate_bucket_name(self.bucket_name)
            if self.key_prefix is not None:
                validate_key_prefix(self.key_prefix)
        elif self.bucket_name is not None or self.key_prefix is not None:
            msg = "s3 parameters require s3.enabled=True"
            raise ValidationError(msg)


__all__ = ["S3Options"]
