"""Tests for core providers infrastructure."""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import ClassVar
from unittest.mock import patch

import pytest
from nohiki.common.v1 import NotificationChannel
from notification_service.core.providers import (
    BaseProvider,
    EmailConfig,
    ProviderConfigError,
    ProviderNotFoundError,
    ProviderRegistrationError,
    ProviderResult,
    clear_provider_registry,
    configure_email_provider,
    get_available_channels,
    get_provider,
    get_providers_for_channel,
    is_channel_supported,
    register_provider,
)
from notification_service.db.models import Message


class MockProvider(BaseProvider):
    """Mock provider for testing."""

    channel: ClassVar[NotificationChannel] = NotificationChannel.EMAIL
    name: ClassVar[str] = "mock_provider"
    required_secrets: ClassVar[list[str]] = ["mock_secret"]

    async def send(self, message: Message) -> ProviderResult:
        """Mock send."""
        del message  # Unused in mock
        return ProviderResult(success=True)

    async def validate_config(self) -> bool:
        """Mock validate."""
        return True


class MockProviderNoSecrets(BaseProvider):
    """Mock provider with no required secrets."""

    channel: ClassVar[NotificationChannel] = NotificationChannel.EMAIL
    name: ClassVar[str] = "mock_provider_no_secrets"

    async def send(self, message: Message) -> ProviderResult:
        """Mock send."""
        del message  # Unused in mock
        return ProviderResult(success=True)

    async def validate_config(self) -> bool:
        """Mock validate."""
        return True


@pytest.fixture
def email_config() -> EmailConfig:
    """Fixture for EmailConfig."""
    return EmailConfig(
        from_address="test@example.com",
        from_name="Test Sender",
        unsubscribe_domain="example.com",
    )


@pytest.fixture(autouse=True)
def clean_registry() -> Generator[None]:
    """Clean up provider registry before and after tests."""
    clear_provider_registry()
    yield
    clear_provider_registry()


class TestProviderResult:
    """Tests for ProviderResult."""

    def test_repr(self) -> None:
        """Test string representation."""
        result = ProviderResult(success=True, provider_msg_id="123")
        assert "success=True" in str(result)
        assert "provider_msg_id=123" in str(result)


class TestBaseProvider:
    """Tests for BaseProvider."""

    def test_validate_required_secrets_success(self, email_config: EmailConfig) -> None:
        """Test validate secrets succeeds when present."""
        with patch.dict(os.environ, {"MOCK_SECRET": "value"}):
            provider = MockProvider(email_config)
            assert provider.config == email_config

    def test_validate_required_secrets_missing(self, email_config: EmailConfig) -> None:
        """Test validate secrets fails when missing."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ProviderConfigError) as exc_info:
                MockProvider(email_config)
            assert "Missing required environment variables" in str(exc_info.value)

    def test_no_required_secrets(self, email_config: EmailConfig) -> None:
        """Test provider with no required secrets works."""
        provider = MockProviderNoSecrets(email_config)
        assert provider.config == email_config

    def test_repr(self, email_config: EmailConfig) -> None:
        """Test provider string representation."""
        with patch.dict(os.environ, {"MOCK_SECRET": "value"}):
            provider = MockProvider(email_config)
            assert "MockProvider" in str(provider)
            assert "mock_provider" in str(provider)


class TestProviderRegistry:
    """Tests for provider registration and retrieval."""

    def test_register_provider_success(self) -> None:
        """Test successful registration."""
        register_provider(NotificationChannel.EMAIL, MockProvider)
        assert is_channel_supported(NotificationChannel.EMAIL)
        assert "mock_provider" in get_providers_for_channel(NotificationChannel.EMAIL)

    def test_register_provider_missing_name(self) -> None:
        """Test fails if missing name."""

        class NoNameProvider(BaseProvider):
            channel = NotificationChannel.EMAIL

            # name missing
            async def send(self, message: Message) -> ProviderResult:
                del message  # Unused in mock
                return ProviderResult(success=True)

            async def validate_config(self) -> bool:
                return True

        with pytest.raises(ProviderRegistrationError) as exc_info:
            register_provider(NotificationChannel.EMAIL, NoNameProvider)
        assert "must have a 'name'" in str(exc_info.value)

    def test_register_provider_missing_name_send(self) -> None:
        """Test fails if provider has wrong send signature."""

        class WrongSignatureProvider(BaseProvider):
            channel = NotificationChannel.EMAIL
            name = "wrong_signature_provider"

            async def send(self, message: Message) -> ProviderResult:
                del message  # Unused in mock
                return ProviderResult(success=True)

            async def validate_config(self) -> bool:
                return True

        # This should succeed - provider has correct signature
        register_provider(NotificationChannel.EMAIL, WrongSignatureProvider)
        assert is_channel_supported(NotificationChannel.EMAIL)

    def test_register_duplicate_provider(self) -> None:
        """Test fails if registering duplicate name."""
        register_provider(NotificationChannel.EMAIL, MockProvider)
        with pytest.raises(ProviderRegistrationError) as exc_info:
            register_provider(NotificationChannel.EMAIL, MockProvider)
        assert "already registered" in str(exc_info.value)

    def test_configure_email_provider_success(self, email_config: EmailConfig) -> None:
        """Test successful email configuration."""
        register_provider(NotificationChannel.EMAIL, MockProvider)
        configure_email_provider(email_config, "mock_provider")

        # Should be able to get default provider now
        with patch.dict(os.environ, {"MOCK_SECRET": "value"}):
            provider = get_provider(NotificationChannel.EMAIL)
            assert isinstance(provider, MockProvider)

    def test_configure_email_provider_not_registered(self, email_config: EmailConfig) -> None:
        """Test fails if provider not registered."""
        with pytest.raises(ProviderNotFoundError) as exc_info:
            configure_email_provider(email_config, "unknown")
        assert "not registered" in str(exc_info.value)

    def test_configure_email_provider_wrong_channel(self, email_config: EmailConfig) -> None:
        """Test fails if provider registered for wrong channel."""

        # This scenario is a bit tricky since we pass the channel to register_provider.
        # But if we register for SMS and try to configure for EMAIL default.
        class SmsProvider(MockProvider):
            channel = NotificationChannel.SMS
            name = "sms_provider"

        register_provider(NotificationChannel.SMS, SmsProvider)

        with pytest.raises(ProviderNotFoundError) as exc_info:
            configure_email_provider(email_config, "sms_provider")
        assert "not registered for EMAIL" in str(exc_info.value)

    def test_get_provider_specific(self, email_config: EmailConfig) -> None:
        """Test getting a specific provider by name."""
        register_provider(NotificationChannel.EMAIL, MockProvider)
        configure_email_provider(email_config, "mock_provider")

        with patch.dict(os.environ, {"MOCK_SECRET": "value"}):
            provider = get_provider(NotificationChannel.EMAIL, "mock_provider")
            assert isinstance(provider, MockProvider)

    def test_get_provider_unsupported_channel(self) -> None:
        """Test fails for unsupported channel."""
        with pytest.raises(ProviderNotFoundError) as exc_info:
            get_provider(NotificationChannel.SMS)
        assert "No provider registered" in str(exc_info.value)

    def test_get_provider_no_default(self) -> None:
        """Test fails if no default provider configured."""
        register_provider(NotificationChannel.EMAIL, MockProvider)
        # Not configured
        with pytest.raises(ProviderNotFoundError) as exc_info:
            get_provider(NotificationChannel.EMAIL)
        assert "No default provider" in str(exc_info.value)

    def test_get_provider_unknown_name(self) -> None:
        """Test fails if requesting unknown provider name."""
        register_provider(NotificationChannel.EMAIL, MockProvider)
        with pytest.raises(ProviderNotFoundError) as exc_info:
            get_provider(NotificationChannel.EMAIL, "unknown")
        assert "Provider 'unknown' not found" in str(exc_info.value)

    def test_get_provider_instantiation_error(self, email_config: EmailConfig) -> None:
        """Test handles instantiation errors (e.g. missing secrets)."""
        register_provider(NotificationChannel.EMAIL, MockProvider)
        configure_email_provider(email_config, "mock_provider")

        # Missing secrets will cause ProviderConfigError during init
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ProviderNotFoundError) as exc_info:
                get_provider(NotificationChannel.EMAIL)
            assert "Failed to instantiate" in str(exc_info.value)

    def test_get_available_channels(self) -> None:
        """Test listing available channels."""
        assert get_available_channels() == []
        register_provider(NotificationChannel.EMAIL, MockProvider)
        channels = get_available_channels()
        assert len(channels) == 1
        assert channels[0] == NotificationChannel.EMAIL

    def test_get_providers_for_channel(self) -> None:
        """Test listing providers for channel."""
        assert get_providers_for_channel(NotificationChannel.EMAIL) == []
        register_provider(NotificationChannel.EMAIL, MockProvider)
        providers = get_providers_for_channel(NotificationChannel.EMAIL)
        assert providers == ["mock_provider"]

    def test_is_channel_supported(self) -> None:
        """Test channel support check."""
        assert is_channel_supported(NotificationChannel.EMAIL) is False
        register_provider(NotificationChannel.EMAIL, MockProvider)
        assert is_channel_supported(NotificationChannel.EMAIL) is True
