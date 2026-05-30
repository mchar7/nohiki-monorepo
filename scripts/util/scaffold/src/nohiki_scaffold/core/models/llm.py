"""LLM integration feature configuration."""

from __future__ import annotations

from dataclasses import dataclass

from nohiki_scaffold.core.exceptions import ValidationError

from ._validation import validate_env_var_name, validate_llm_model, validate_llm_provider


@dataclass(frozen=True, slots=True)
class LLMOptions:
    """LLM integration feature flags and parameters.

    When ``enabled=True``, ``provider`` and ``model`` must be supplied.
    ``api_key_env`` names the environment variable that carries the secret; if
    omitted the scaffold emits a ``CHANGE_ME`` placeholder in ``.env.example``.
    """

    enabled: bool = False
    provider: str | None = None
    model: str | None = None
    api_key_env: str | None = None

    def __post_init__(self) -> None:
        """Require provider/model when enabled; forbid all params when disabled."""
        if self.enabled:
            if not self.provider:
                msg = "llm.provider is required when llm.enabled=True"
                raise ValidationError(msg)
            validate_llm_provider(self.provider)
            if not self.model:
                msg = "llm.model is required when llm.enabled=True"
                raise ValidationError(msg)
            validate_llm_model(self.model)
            if self.api_key_env is not None:
                validate_env_var_name(self.api_key_env)
        elif any((self.provider, self.model, self.api_key_env)):
            msg = "llm parameters require llm.enabled=True"
            raise ValidationError(msg)


__all__ = ["LLMOptions"]
