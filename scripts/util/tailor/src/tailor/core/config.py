"""Configuration management for tailor CLI."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Final

from nohiki_core_settings import NohikiBaseSettings
from nohiki_llm_client import ApiKeyRegistry
from nohiki_test_utils.paths import get_repo_root
from pydantic import Field
from pydantic_settings import SettingsConfigDict

MONOREPO_ROOT: Final[Path] = get_repo_root()
SECRETS_DIR: Final[Path] = MONOREPO_ROOT / "infra" / "shared" / "secrets"
SEED_TEMPLATES_DIR: Final[Path] = MONOREPO_ROOT / "backend" / "services" / "doc-template-service" / "seed_templates"
SEED_SCHEMAS_DIR: Final[Path] = MONOREPO_ROOT / "backend" / "services" / "doc-template-service" / "seed_schemas"
DEFAULT_OUTPUT_DIR: Final[Path] = Path("./output")

APP_TITLE: Final[str] = "Nohiki Tailoring CLI"
DEFAULT_TEMPLATE_NAME: Final[str] = "resume"
DEFAULT_MODEL: Final[str] = "openrouter:google/gemini-3-flash-preview"

_API_KEYS_DIR: Final[Path] = SECRETS_DIR / "llm" / "provider" / "api_keys"

MAX_CONTEXT_FILES: Final[int] = 10
MAX_JOB_FILES: Final[int] = 10


def load_api_keys() -> ApiKeyRegistry:
    """Load all provider API keys from the canonical per-provider secrets directory.

    Reads individual key files from ``infra/shared/secrets/llm/provider/api_keys/``,
    where each filename is the provider name (e.g., ``openrouter``, ``openai``).

    Returns:
        ``ApiKeyRegistry`` populated with all discovered provider keys.
        Returns an empty registry if the secrets directory does not exist.
    """
    registry: dict[str, str] = {}
    if _API_KEYS_DIR.exists():
        for key_file in _API_KEYS_DIR.iterdir():
            if key_file.is_file():
                registry[key_file.name] = key_file.read_text().strip()
    return ApiKeyRegistry.model_validate(registry)


class TailorSettings(NohikiBaseSettings):
    """Settings for the tailor CLI.

    LLM configuration uses a simple model string that is resolved to full
    ``LLMSettings`` at runtime by ``TailorLLMAdapter``, following the same
    pattern as other scripts in this monorepo (generate_l2r_data).
    Secrets are automatically loaded from infra/shared/secrets/ directory.
    """

    model_config = SettingsConfigDict(
        env_prefix="TAILOR_",
        env_nested_delimiter="__",
        secrets_dir=str(SECRETS_DIR),
        extra="ignore",
    )

    service_name: str = "tailor-cli"
    service_name_friendly: str = "Nohiki Tailoring CLI"
    service_desc_friendly: str = "Manual document tailoring tool"
    service_version: str = "0.1.0"

    llm_model: str = Field(
        default=DEFAULT_MODEL,
        description="Fully-qualified LLM model string in 'provider:model' format",
    )

    gotenberg_url: str = Field(
        default="http://localhost:3000",
        description="Gotenberg service URL for PDF/image conversion",
    )
    gotenberg_timeout_s: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Gotenberg request timeout in seconds",
    )

    templates_dir: Path = Field(
        default=SEED_TEMPLATES_DIR,
        description="Directory containing document templates",
    )
    schemas_dir: Path = Field(
        default=SEED_SCHEMAS_DIR,
        description="Directory containing JSON schemas",
    )
    output_dir: Path = Field(
        default=DEFAULT_OUTPUT_DIR,
        description="Default output directory for generated documents",
    )

    @property
    def resolved_templates_dir(self) -> Path:
        """Get absolute templates directory path."""
        return self.templates_dir if self.templates_dir.is_absolute() else MONOREPO_ROOT / self.templates_dir

    @property
    def resolved_schemas_dir(self) -> Path:
        """Get absolute schemas directory path."""
        return self.schemas_dir if self.schemas_dir.is_absolute() else MONOREPO_ROOT / self.schemas_dir

    @property
    def resolved_output_dir(self) -> Path:
        """Get absolute output directory path."""
        return self.output_dir if self.output_dir.is_absolute() else Path.cwd() / self.output_dir


@lru_cache
def get_settings() -> TailorSettings:
    """Get cached settings instance."""
    os.environ.setdefault("SECRETS_DIR", str(SECRETS_DIR))
    return TailorSettings()
