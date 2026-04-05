"""Tests for the provider-level shared concurrency limiter registry."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from nohiki_llm_client.client.concurrency import (
    _SHARED_LIMITERS,
    apply_concurrency_limit,
    get_or_create_provider_limiter,
    reset_provider_limiters,
)
from pydantic_ai.models.concurrency import ConcurrencyLimitedModel, ConcurrencyLimiter


@pytest.fixture(autouse=True)
def _clear_registry() -> Generator[None]:
    """Reset the shared limiter registry before and after every test."""
    reset_provider_limiters()
    yield
    reset_provider_limiters()


class TestGetOrCreateProviderLimiter:
    """Tests for get_or_create_provider_limiter."""

    def test_returns_concurrency_limiter(self) -> None:
        limiter = get_or_create_provider_limiter("http://localhost:11434/v1", 1)
        assert isinstance(limiter, ConcurrencyLimiter)

    def test_same_key_returns_same_instance(self) -> None:
        key = "http://localhost:11434/v1"
        limiter_a = get_or_create_provider_limiter(key, 1)
        limiter_b = get_or_create_provider_limiter(key, 1)
        assert limiter_a is limiter_b

    def test_different_keys_return_different_instances(self) -> None:
        limiter_a = get_or_create_provider_limiter("http://host-a:11434/v1", 1)
        limiter_b = get_or_create_provider_limiter("http://host-b:11434/v1", 1)
        assert limiter_a is not limiter_b

    def test_limiter_registered_in_shared_dict(self) -> None:
        key = "http://localhost:11434/v1"
        limiter = get_or_create_provider_limiter(key, 1)
        assert _SHARED_LIMITERS[key] is limiter

    def test_limiter_name_matches_provider_key(self) -> None:
        key = "http://localhost:11434/v1"
        limiter = get_or_create_provider_limiter(key, 1)
        assert limiter.name == key

    def test_limit_reflected_in_max_running(self) -> None:
        limiter = get_or_create_provider_limiter("http://unique-host:11434/v1", 3)
        assert limiter.max_running == 3


class TestResetProviderLimiters:
    """Tests for reset_provider_limiters."""

    def test_clears_registry(self) -> None:
        get_or_create_provider_limiter("http://host-a:11434/v1", 1)
        get_or_create_provider_limiter("http://host-b:11434/v1", 1)
        assert len(_SHARED_LIMITERS) == 2
        reset_provider_limiters()
        assert len(_SHARED_LIMITERS) == 0

    def test_new_instance_created_after_reset(self) -> None:
        key = "http://localhost:11434/v1"
        limiter_before = get_or_create_provider_limiter(key, 1)
        reset_provider_limiters()
        limiter_after = get_or_create_provider_limiter(key, 1)
        assert limiter_before is not limiter_after


class TestApplyConcurrencyLimit:
    """Tests for apply_concurrency_limit."""

    def test_no_limit_returns_original_model(self) -> None:
        from pydantic_ai.models.test import TestModel

        model = TestModel()
        result = apply_concurrency_limit(model, None)
        assert result is model

    def test_int_limit_wraps_with_concurrency_limited_model(self) -> None:
        from pydantic_ai.models.test import TestModel

        model = TestModel()
        result = apply_concurrency_limit(model, 4)
        assert isinstance(result, ConcurrencyLimitedModel)

    def test_int_limit_without_key_creates_per_instance_wrapper(self) -> None:
        from pydantic_ai.models.test import TestModel

        model_a = TestModel()
        model_b = TestModel()
        wrapped_a = apply_concurrency_limit(model_a, 2)
        wrapped_b = apply_concurrency_limit(model_b, 2)
        assert isinstance(wrapped_a, ConcurrencyLimitedModel)
        assert isinstance(wrapped_b, ConcurrencyLimitedModel)

    def test_provider_key_uses_shared_limiter(self) -> None:
        from pydantic_ai.models.test import TestModel

        key = "http://shared-host:11434/v1"
        model_a = TestModel()
        model_b = TestModel()
        apply_concurrency_limit(model_a, 1, provider_key=key)
        apply_concurrency_limit(model_b, 1, provider_key=key)
        assert len(_SHARED_LIMITERS) == 1
        assert _SHARED_LIMITERS[key].max_running == 1

    def test_shared_limiter_is_in_registry(self) -> None:
        from pydantic_ai.models.test import TestModel

        key = "http://registry-check:11434/v1"
        model = TestModel()
        apply_concurrency_limit(model, 1, provider_key=key)
        assert key in _SHARED_LIMITERS

    def test_no_provider_key_does_not_pollute_registry(self) -> None:
        from pydantic_ai.models.test import TestModel

        model = TestModel()
        apply_concurrency_limit(model, 2)
        assert len(_SHARED_LIMITERS) == 0
