"""Machine learning dependency composition."""

from __future__ import annotations

from dataclasses import dataclass, field

from nohiki_scaffold.core.exceptions import ValidationError

from .llm import LLMOptions
from .qdrant import QdrantOptions


@dataclass(frozen=True, slots=True)
class MLOptions:
    """Machine-learning dependency composition for a service."""

    llm: LLMOptions = field(default_factory=LLMOptions)
    qdrant: QdrantOptions = field(default_factory=QdrantOptions)
    manifest: bool = False
    service_holder_pattern: bool = False
    fail_fast_validation: bool = False

    @property
    def any_enabled(self) -> bool:
        """Return True if any ML dependency is enabled."""
        return self.llm.enabled or self.qdrant.enabled or self.manifest

    def __post_init__(self) -> None:
        """Forbid ML auto-features without a concrete ML dep enabled."""
        if self.fail_fast_validation and not self.manifest:
            msg = "ml.fail_fast_validation requires ml.manifest=True"
            raise ValidationError(msg)
        if self.service_holder_pattern and not self.any_enabled:
            msg = "ml.service_holder_pattern requires at least one ML dep (llm/qdrant/manifest)"
            raise ValidationError(msg)


__all__ = ["MLOptions"]
