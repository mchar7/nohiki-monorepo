"""ManifestMixin: settings mixin for services requiring the manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Self

from nohiki_core_settings.mixins import SettingsMixin
from pydantic import Field, model_validator

from nohiki_ml_manifest.cache import DEFAULT_MANIFEST_PATH


class ManifestMixin(SettingsMixin):
    """Mixin for services that load the semantic representation manifest.

    Validates that the manifest file exists at settings construction time
    (fail-fast).  Actual loading and caching is handled by ``ManifestCache``.

    Env var: ``{PREFIX}MANIFEST_PATH``
    """

    manifest_path: Path = Field(default=DEFAULT_MANIFEST_PATH)

    @model_validator(mode="after")
    def _validate_manifest_path_exists(self) -> Self:
        """Fail fast if the manifest file is missing at startup."""
        if not self.manifest_path.exists():
            msg = f"Manifest file not found: {self.manifest_path}"
            raise ValueError(msg)
        return self
