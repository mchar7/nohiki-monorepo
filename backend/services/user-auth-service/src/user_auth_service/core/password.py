"""Password hashing utilities using Argon2.

All hash/verify calls are offloaded to a thread to avoid blocking the
async event loop: Argon2 is deliberately CPU-intensive (100-300 ms).
"""

import asyncio

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Secure Argon2 configuration
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)


def _hash_password_sync(password: str) -> str:
    """Hash a password using Argon2 (synchronous, CPU-bound)."""
    result: str = _hasher.hash(password)
    return result


def _verify_password_sync(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash (synchronous, CPU-bound)."""
    try:
        _hasher.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False
    else:
        return True


async def hash_password(password: str) -> str:
    """Hash a password using Argon2, offloaded to a thread."""
    return await asyncio.to_thread(_hash_password_sync, password)


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash, offloaded to a thread."""
    return await asyncio.to_thread(_verify_password_sync, plain_password, hashed_password)
