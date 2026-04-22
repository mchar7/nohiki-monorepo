"""Provider abstraction for messaging channels."""

from __future__ import annotations

import math
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, ClassVar

from nohiki.common.v1 import NotificationChannel

if TYPE_CHECKING:
    from notification_service.db.models import Message

from nohiki_observability import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EmailConfig:
    """Shared email configuration for all email providers."""

    from_address: str
    from_name: str
    unsubscribe_domain: str
    provider_name: str | None = None
    api_key: str = ""


class ProviderError(Exception):
    """Base exception for provider-related errors."""


class ProviderNotFoundError(ProviderError):
    """Exception raised when a provider is not found."""


class ProviderRegistrationError(ProviderError):
    """Exception raised when there's an error registering a provider."""


class ProviderConfigError(ProviderError):
    """Exception raised when there's an error with provider configuration."""


class ProviderResult:
    """Result of a provider send operation."""

    def __init__(
        self,
        *,
        success: bool,
        provider_msg_id: str | None = None,
        error: str | None = None,
        retryable: bool = True,
        retry_after_seconds: int | None = None,
    ) -> None:
        """Initialize provider result."""
        self.success = success
        self.provider_msg_id = provider_msg_id
        self.error = error
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds

    def __repr__(self) -> str:
        """Return string representation of provider result."""
        return (
            f"ProviderResult(success={self.success}, provider_msg_id={self.provider_msg_id}, "
            f"error={self.error}, retryable={self.retryable}, "
            f"retry_after_seconds={self.retry_after_seconds})"
        )


def parse_retry_after(value: str | None) -> int | None:
    """Parse an HTTP Retry-After value into a non-negative delay."""
    if value is None:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except TypeError, ValueError, OverflowError:
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0, math.ceil((retry_at - datetime.now(UTC)).total_seconds()))


class BaseProvider(ABC):
    """Abstract base class for messaging providers."""

    channel: ClassVar[NotificationChannel]
    name: ClassVar[str]
    required_secrets: ClassVar[list[str]]

    def __init__(self, config: EmailConfig) -> None:
        """Initialize the provider.

        Args:
            config: Shared email configuration

        """
        self.config = config
        self._validate_required_secrets()

    def _validate_required_secrets(self) -> None:
        """Validate that all required secrets are available via environment variables.

        Raises:
            ProviderConfigError: If any required secret is missing

        """
        if not hasattr(self, "required_secrets"):
            return

        configured_key_available = self.config.provider_name == self.name and bool(self.config.api_key)
        missing_secrets = []
        for secret_name in self.required_secrets:
            env_var = secret_name.upper().replace("-", "_")
            if not configured_key_available and not os.environ.get(env_var):
                missing_secrets.append(env_var)

        if missing_secrets:
            msg = f"Missing required environment variables for {self.name}: {', '.join(missing_secrets)}"
            logger.error(msg)
            raise ProviderConfigError(msg)

    @abstractmethod
    async def send(self, message: Message) -> ProviderResult:
        """Send a message via this provider.

        Args:
            message: The message model to send

        Returns:
            ProviderResult with success status and optional provider message ID or error

        Raises:
            ProviderException: If there's an error sending the message

        """

    @abstractmethod
    async def validate_config(self) -> bool:
        """Validate provider configuration.

        Returns:
            True if configuration is valid, False otherwise

        Raises:
            ProviderConfigError: If there's an error validating the configuration

        """

    def __repr__(self) -> str:
        """Return string representation of provider."""
        return f"{self.__class__.__name__}(channel={self.channel}, name={self.name})"


@dataclass(slots=True)
class _ProviderRegistry:
    """Registry for notification providers."""

    providers: dict[NotificationChannel, dict[str, type[BaseProvider]]] = field(
        default_factory=lambda: {channel: {} for channel in NotificationChannel}
    )
    instances: dict[NotificationChannel, dict[str, BaseProvider]] = field(
        default_factory=lambda: {channel: {} for channel in NotificationChannel}
    )
    email_config: EmailConfig | None = field(default=None)
    default_provider: dict[NotificationChannel, str] = field(default_factory=dict)

    def clear(self) -> None:
        """Clear the registry (for testing)."""
        self.providers = {channel: {} for channel in NotificationChannel}
        self.instances = {channel: {} for channel in NotificationChannel}
        self.email_config = None
        self.default_provider = {}


_registry = _ProviderRegistry()


def register_provider(channel: NotificationChannel, provider_class: type[BaseProvider]) -> None:
    """Register a provider for a specific notification channel.

    Args:
        channel: The notification channel to register the provider for
        provider_class: The provider class to register

    Raises:
        ProviderRegistrationError: If the provider is already registered or has invalid configuration

    """
    if not issubclass(provider_class, BaseProvider):
        msg = f"Provider class {provider_class.__name__} must be a subclass of BaseProvider"
        logger.error(msg)
        raise ProviderRegistrationError(msg)

    if not hasattr(provider_class, "name") or not provider_class.name:
        msg = f"Provider class {provider_class.__name__} must have a 'name' class attribute"
        logger.error(msg)
        raise ProviderRegistrationError(msg)

    provider_name = provider_class.name

    if provider_name in _registry.providers[channel]:
        msg = f"Provider '{provider_name}' for channel '{channel}' is already registered"
        logger.warning(msg)
        raise ProviderRegistrationError(msg)

    _registry.providers[channel][provider_name] = provider_class
    logger.info("Registered provider", channel=channel, provider=provider_class.__name__, provider_name=provider_name)


def configure_email_provider(
    config: EmailConfig,
    provider_name: str,
) -> None:
    """Configure the email provider system.

    Args:
        config: Shared email configuration
        provider_name: Name of the provider to use as default

    Raises:
        ProviderNotFoundError: If the specified provider is not registered

    """
    if (
        NotificationChannel.EMAIL not in _registry.providers
        or provider_name not in _registry.providers[NotificationChannel.EMAIL]
    ):
        msg = f"Provider '{provider_name}' not registered for EMAIL channel"
        logger.error(msg)
        raise ProviderNotFoundError(msg)

    _registry.email_config = config
    _registry.default_provider[NotificationChannel.EMAIL] = provider_name
    logger.info("Configured email provider", provider=provider_name)


def get_provider(channel: NotificationChannel, provider_name: str | None = None) -> BaseProvider:
    """Get a provider instance for the specified notification channel.

    Args:
        channel: The notification channel to get a provider for
        provider_name: Optional specific provider name to use. If not provided,
                      uses the configured default provider.

    Returns:
        An instance of the requested provider

    Raises:
        ProviderNotFoundError: If no provider is found for the channel or the specific provider name

    """
    if channel not in _registry.providers or not _registry.providers[channel]:
        msg = f"No provider registered for channel: {channel}"
        logger.error(msg)
        raise ProviderNotFoundError(msg)

    if provider_name is None:
        provider_name = _registry.default_provider.get(channel)
        if provider_name is None:
            msg = f"No default provider configured for channel: {channel}"
            logger.error(msg)
            raise ProviderNotFoundError(msg)

    if provider_name not in _registry.providers[channel]:
        msg = f"Provider '{provider_name}' not found for channel: {channel}"
        logger.error(msg)
        raise ProviderNotFoundError(msg)

    if provider_name in _registry.instances[channel]:
        return _registry.instances[channel][provider_name]

    email_config = _registry.email_config
    if email_config is None:
        msg = "Email provider not configured. Call configure_email_provider() first."
        logger.error(msg)
        raise ProviderNotFoundError(msg)

    try:
        provider_class = _registry.providers[channel][provider_name]
        provider = provider_class(email_config)
        _registry.instances[channel][provider_name] = provider
    except (ValueError, TypeError, ProviderError) as e:
        msg = f"Failed to instantiate provider '{provider_name}' for channel '{channel}': {e}"
        logger.exception(msg)
        raise ProviderNotFoundError(msg) from e
    except Exception as e:
        msg = f"Unexpected error instantiating provider '{provider_name}' for channel '{channel}': {e}"
        logger.exception(msg)
        raise ProviderNotFoundError(msg) from e
    else:
        return provider


def get_fallback_providers(
    channel: NotificationChannel,
    *,
    exclude: str,
) -> list[BaseProvider]:
    """List instantiated fallback providers for a channel, minus ``exclude``.

    :class:`~notification_service.services.outbox.provider_router.ProviderRouter`
    calls this when the primary's breaker is open. Providers are returned in
    registration order so failover is deterministic. A fallback that fails to
    instantiate (missing secret etc.) is logged and skipped.

    Args:
        channel: Channel whose fallbacks to enumerate.
        exclude: Primary provider name to leave out.

    Returns:
        Cached provider instances for ``channel`` whose names differ from
        ``exclude``. Empty list if none are healthy.

    """
    registered = _registry.providers.get(channel, {})
    fallbacks: list[BaseProvider] = []

    for provider_name in registered:
        if provider_name == exclude:
            continue
        try:
            fallbacks.append(get_provider(channel, provider_name))
        except ProviderNotFoundError as exc:
            # Surface misconfigured fallbacks in logs instead of swallowing them.
            logger.warning(
                "Fallback provider unavailable; skipping",
                channel=channel,
                provider=provider_name,
                error=str(exc),
            )

    return fallbacks


def get_default_provider_name(channel: NotificationChannel) -> str | None:
    """Return the configured default provider name for a channel."""
    return _registry.default_provider.get(channel)


def get_available_channels() -> list[NotificationChannel]:
    """Get list of available notification channels with registered providers.

    Returns:
        List of channels that have at least one registered provider

    """
    return [channel for channel in NotificationChannel if _registry.providers.get(channel)]


def get_providers_for_channel(channel: NotificationChannel) -> list[str]:
    """Get list of provider names available for a specific channel.

    Args:
        channel: The channel to get providers for

    Returns:
        List of provider names registered for the channel

    """
    if channel not in _registry.providers:
        return []
    return list(_registry.providers[channel].keys())


def is_channel_supported(channel: NotificationChannel) -> bool:
    """Check if a notification channel is supported.

    Args:
        channel: The channel to check

    Returns:
        True if the channel has at least one registered provider, False otherwise

    """
    return channel in _registry.providers and bool(_registry.providers[channel])


def clear_provider_registry() -> None:
    """Clear the provider registry (primarily for testing)."""
    _registry.clear()
    logger.info("Provider registry cleared")
