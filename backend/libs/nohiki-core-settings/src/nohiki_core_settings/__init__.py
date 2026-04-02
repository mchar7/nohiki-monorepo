"""Shared configuration components for Nohiki microservices."""

from __future__ import annotations

from nohiki_core_settings.base import (
    AzureKeyVaultNotInstalledError,
    NohikiBaseSettings,
)
from nohiki_core_settings.env import DEVELOPMENT_ENVIRONMENTS, is_development
from nohiki_core_settings.mixins import SettingsMixin
from nohiki_core_settings.observability import (
    LoggingSettings,
    ObservabilitySettings,
    PrometheusSettings,
    TracingSettings,
)

__all__ = [
    "DEVELOPMENT_ENVIRONMENTS",
    "AzureKeyVaultNotInstalledError",
    "LoggingSettings",
    "NohikiBaseSettings",
    "ObservabilitySettings",
    "PrometheusSettings",
    "SettingsMixin",
    "TracingSettings",
    "is_development",
]
