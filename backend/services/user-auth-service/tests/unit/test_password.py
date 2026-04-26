"""Unit tests for password hashing."""

import pytest
from user_auth_service.core.password import hash_password, verify_password


class TestPasswordHashing:
    """Tests for password hashing functionality."""

    @pytest.mark.asyncio
    async def test_hash_returns_argon2_format(self) -> None:
        """Hash should return argon2 format string."""
        hashed = await hash_password("test_password")
        assert hashed.startswith("$argon2")

    @pytest.mark.asyncio
    async def test_same_password_different_hashes(self) -> None:
        """Same password should produce different hashes (due to salt)."""
        hash1 = await hash_password("test_password")
        hash2 = await hash_password("test_password")
        assert hash1 != hash2

    @pytest.mark.asyncio
    async def test_verify_correct_password(self) -> None:
        """Correct password should verify successfully."""
        password = "correct_password_123"
        hashed = await hash_password(password)
        assert await verify_password(password, hashed) is True

    @pytest.mark.asyncio
    async def test_verify_incorrect_password(self) -> None:
        """Incorrect password should fail verification."""
        hashed = await hash_password("correct_password")
        assert await verify_password("wrong_password", hashed) is False

    @pytest.mark.asyncio
    async def test_verify_empty_password(self) -> None:
        """Empty password should fail verification."""
        hashed = await hash_password("some_password")
        assert await verify_password("", hashed) is False
