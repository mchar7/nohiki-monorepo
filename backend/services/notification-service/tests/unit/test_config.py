"""Unit tests for the config.py module."""

import pytest
from notification_service.core.config import Settings
from pydantic import ValidationError


def test_settings_defaults() -> None:
    """Test Settings has correct default values."""
    settings = Settings()
    assert settings.service_name == "notification-service"
    assert settings.service_version == "0.1.0"
    assert settings.rate_limit.requests_per_window == 10
    assert settings.rate_limit.window_seconds == 60
    assert settings.outbox.batch_size == 10


def test_redis_settings_defaults() -> None:
    """Test Redis settings have correct default values from test env."""
    settings = Settings()
    # Conftest sets NOTIFICATION_REDIS__DSN to localhost for testing
    assert str(settings.redis.dsn) == "redis://localhost:6379/0"
    assert settings.redis.socket_timeout == pytest.approx(5.0)
    assert settings.redis.max_connections == 10


def test_redis_url_computed_with_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test redis DSN with password and SSL."""
    monkeypatch.setenv("NOTIFICATION_REDIS__DSN", "rediss://:secret@myredis.example.com:6380/5")
    settings = Settings()
    assert "myredis.example.com" in str(settings.redis.dsn)
    assert "6380" in str(settings.redis.dsn)


def test_redis_url_computed_no_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test redis DSN without password."""
    monkeypatch.setenv("NOTIFICATION_REDIS__DSN", "redis://localhost:6379/0")
    settings = Settings()
    assert "localhost" in str(settings.redis.dsn)
    assert "6379" in str(settings.redis.dsn)


def test_rate_limit_requests_must_be_positive() -> None:
    """Test validation fails with non-positive rate limit requests."""
    from notification_service.core.config import RateLimitSettings

    with pytest.raises(ValidationError, match="Input should be greater than 0"):
        RateLimitSettings(requests_per_window=0)


def test_rate_limit_window_must_be_positive() -> None:
    """Test validation fails with non-positive rate limit window."""
    from notification_service.core.config import RateLimitSettings

    with pytest.raises(ValidationError, match="Input should be greater than 0"):
        RateLimitSettings(window_seconds=0)


def test_outbox_batch_size_must_be_positive() -> None:
    """Test validation fails with non-positive outbox batch size."""
    from notification_service.core.config import OutboxSettings

    with pytest.raises(ValidationError, match="Input should be greater than 0"):
        OutboxSettings(batch_size=0)


def test_outbox_error_backoff_default() -> None:
    """Loop-level backoff defaults to 5 seconds."""
    from notification_service.core.config import OutboxSettings

    assert OutboxSettings().error_backoff_seconds == 5


def test_outbox_error_backoff_must_be_positive() -> None:
    """Negative or zero backoff is rejected."""
    from notification_service.core.config import OutboxSettings

    with pytest.raises(ValidationError, match="Input should be greater than 0"):
        OutboxSettings(error_backoff_seconds=0)


def test_circuit_breaker_defaults() -> None:
    """Default breaker config matches the documented values."""
    settings = Settings()
    cb = settings.circuit_breaker
    assert cb.failure_threshold == 5
    assert cb.success_threshold == 2
    assert cb.timeout_seconds == pytest.approx(30.0)
    assert cb.half_open_max_calls == 1


def test_circuit_breaker_thresholds_must_be_positive() -> None:
    """All circuit-breaker fields reject non-positive values."""
    from notification_service.core.config import CircuitBreakerSettings

    with pytest.raises(ValidationError, match="Input should be greater than 0"):
        CircuitBreakerSettings(failure_threshold=0)
    with pytest.raises(ValidationError, match="Input should be greater than 0"):
        CircuitBreakerSettings(success_threshold=0)
    with pytest.raises(ValidationError, match="Input should be greater than 0"):
        CircuitBreakerSettings(timeout_seconds=0.0)
    with pytest.raises(ValidationError, match="Input should be greater than 0"):
        CircuitBreakerSettings(half_open_max_calls=0)


def test_outbox_jitter_factor_default() -> None:
    """Default jitter factor matches the documented ±20% band."""
    from notification_service.core.config import OutboxSettings

    assert OutboxSettings().jitter_factor == pytest.approx(0.2)


def test_outbox_jitter_factor_accepts_zero() -> None:
    """jitter_factor=0 is valid and disables jitter."""
    from notification_service.core.config import OutboxSettings

    assert OutboxSettings(jitter_factor=0.0).jitter_factor == 0.0


def test_outbox_jitter_factor_rejects_negative() -> None:
    """Negative jitter factors are nonsensical and rejected."""
    from notification_service.core.config import OutboxSettings

    with pytest.raises(ValidationError, match="Input should be greater than or equal to 0"):
        OutboxSettings(jitter_factor=-0.1)


def test_outbox_jitter_factor_rejects_above_one() -> None:
    """Factor >1 would let jitter dominate the base delay; rejected."""
    from notification_service.core.config import OutboxSettings

    with pytest.raises(ValidationError, match="Input should be less than or equal to 1"):
        OutboxSettings(jitter_factor=1.1)
