"""Redis cache implementation with circuit breaker protection."""

from __future__ import annotations

import asyncio
import builtins
import json
import time
from collections.abc import Awaitable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

from nohiki_observability import get_logger
from redis.asyncio import Redis, RedisError

from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .distributed_lock import DistributedLockError
from .metrics import get_redis_metrics

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = get_logger(__name__)

_LOCK_POLL_INTERVAL_SECONDS: float = 1.0


def _decode_redis_strings(result: object) -> list[str]:
    """Narrow Redis collection output to decoded string members."""
    if not isinstance(result, list):
        return []
    decoded: list[str] = []
    for item in result:
        if isinstance(item, bytes):
            decoded.append(item.decode())
        elif isinstance(item, str):
            decoded.append(item)
        else:
            msg = f"Unexpected Redis sorted-set member type: {type(item).__name__}"
            raise TypeError(msg)
    return decoded


_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return {redis.call('DEL', KEYS[1])}
end
return {0}
"""
_INCR_WITH_TTL_SCRIPT = """
local current_ttl = redis.call('TTL', KEYS[1])
local current = redis.call('INCRBY', KEYS[1], ARGV[1])
if current_ttl < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return {current}
"""


class RedisCache:
    """Redis-based cache with service isolation, circuit breaker, and distributed locking."""

    def __init__(
        self,
        redis_url: str,
        service_name: str = "default",
        circuit_breaker_config: CircuitBreakerConfig | None = None,
    ) -> None:
        """Initialize Redis cache with service-specific key prefixing.

        Args:
            redis_url: Redis connection URL.
            service_name: Service name for key prefixing and circuit breaker identification.
            circuit_breaker_config: Optional circuit breaker configuration.

        """
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._redis_binary = Redis.from_url(redis_url, decode_responses=False)
        self._service_name = service_name
        self._circuit_breaker = CircuitBreaker(
            name=f"redis-{service_name}",
            config=circuit_breaker_config,
        )
        self._metrics = get_redis_metrics()

    async def close(self) -> None:
        """Close the Redis connections."""
        await self._redis.aclose()
        await self._redis_binary.aclose()

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Access the circuit breaker for monitoring or manual control."""
        return self._circuit_breaker

    def _make_key(self, key: str) -> str:
        """Create service-prefixed cache key for isolation."""
        return f"{self._service_name}:{key}"

    # ===== Public API methods (wrapped with circuit breaker) =====

    async def get(self, key: str) -> object:
        """Get value from Redis cache."""
        start = time.perf_counter()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._get_internal(key),
                fallback=None,
            )
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("get", latency_ms, str(e))
            return None
        else:
            latency_ms = (time.perf_counter() - start) * 1000
            if result is not None:
                self._metrics.record_hit("get", latency_ms)
            else:
                self._metrics.record_miss("get", latency_ms)
            return result

    async def set(self, key: str, value: object, ttl: int | None = None) -> None:
        """Set value in Redis cache."""
        start = time.perf_counter()
        try:
            await self._circuit_breaker.call(
                lambda: self._set_internal(key, value, ttl),
                fallback=None,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("set", latency_ms)
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("set", latency_ms, str(e))

    async def delete(self, key: str) -> None:
        """Delete key from Redis cache."""
        start = time.perf_counter()
        try:
            await self._circuit_breaker.call(
                lambda: self._delete_internal(key),
                fallback=None,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("delete", latency_ms)
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("delete", latency_ms, str(e))

    async def exists(self, key: str) -> bool:
        """Check if key exists in Redis cache."""
        start = time.perf_counter()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._exists_internal(key),
                fallback=False,
            )
            latency_ms = (time.perf_counter() - start) * 1000

            if result:
                self._metrics.record_hit("exists", latency_ms)
            else:
                self._metrics.record_miss("exists", latency_ms)

            return bool(result)
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("exists", latency_ms, str(e))
            return False

    async def setnx(self, key: str, value: object, ttl: int | None = None) -> bool:
        """Set value only if key doesn't exist. Returns True if set, False if key already exists."""
        start = time.perf_counter()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._setnx_internal(key, value, ttl),
                fallback=False,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("setnx", latency_ms)
            return bool(result)
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("setnx", latency_ms, str(e))
            return False

    async def setnx_strict(self, key: str, value: object, ttl: int | None = None) -> bool:
        """Atomically set a key while propagating Redis availability failures.

        Use this for correctness-critical locks and idempotency decisions where
        a cache outage must not be mistaken for an existing key.
        """
        if not await self._circuit_breaker.can_execute():
            msg = "Redis circuit is open"
            raise RedisError(msg)
        try:
            result = await self._setnx_internal(key, value, ttl)
        except asyncio.CancelledError:
            self._circuit_breaker.release_half_open_slot()
            raise
        except RedisError as error:
            await self._circuit_breaker.record_failure(error)
            raise
        await self._circuit_breaker.record_success()
        return result

    async def incr_with_ttl_strict(self, key: str, expiry: int, amount: int = 1) -> int:
        """Increment a fixed-window counter and set its initial TTL atomically."""
        if amount < 1:
            msg = "amount must be positive"
            raise ValueError(msg)
        if expiry < 1:
            msg = "expiry must be positive"
            raise ValueError(msg)
        if not await self._circuit_breaker.can_execute():
            msg = "Redis circuit is open"
            raise RedisError(msg)
        try:
            result = await self._eval_script_internal(
                _INCR_WITH_TTL_SCRIPT,
                keys=[key],
                args=[str(amount), str(expiry)],
            )
        except asyncio.CancelledError:
            self._circuit_breaker.release_half_open_slot()
            raise
        except RedisError as error:
            await self._circuit_breaker.record_failure(error)
            raise
        try:
            current = int(result[0])
        except (IndexError, TypeError, ValueError) as error:
            await self._circuit_breaker.record_failure(error)
            msg = "Unexpected Redis fixed-window counter result"
            raise TypeError(msg) from error
        await self._circuit_breaker.record_success()
        return current

    async def sadd(self, key: str, *members: str) -> int:
        """Add members to set."""
        start = time.perf_counter()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._sadd_internal(key, *members),
                fallback=0,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("sadd", latency_ms)
            return int(result) if result is not None else 0
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("sadd", latency_ms, str(e))
            return 0

    async def srem(self, key: str, *members: str) -> int:
        """Remove members from set."""
        start = time.perf_counter()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._srem_internal(key, *members),
                fallback=0,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("srem", latency_ms)
            return int(result) if result is not None else 0
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("srem", latency_ms, str(e))
            return 0

    async def smembers(self, key: str) -> builtins.set[str]:
        """Get all members of set."""
        start = time.perf_counter()
        empty_set: builtins.set[str] = builtins.set()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._smembers_internal(key),
                fallback=empty_set,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("smembers", latency_ms)
            return set(result) if result else set()
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("smembers", latency_ms, str(e))
            return set()

    async def sismember(self, key: str, member: str) -> bool:
        """Check if member exists in set."""
        start = time.perf_counter()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._sismember_internal(key, member),
                fallback=False,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("sismember", latency_ms)
            return bool(result)
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("sismember", latency_ms, str(e))
            return False

    async def zadd(self, key: str, member: str, score: float) -> int:
        """Add member to sorted set with score."""
        start = time.perf_counter()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._zadd_internal(key, member, score),
                fallback=0,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("zadd", latency_ms)
            return int(result) if result is not None else 0
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("zadd", latency_ms, str(e))
            return 0

    async def zrem(self, key: str, member: str) -> int:
        """Remove member from sorted set."""
        start = time.perf_counter()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._zrem_internal(key, member),
                fallback=0,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("zrem", latency_ms)
            return int(result) if result is not None else 0
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("zrem", latency_ms, str(e))
            return 0

    async def zrange(self, key: str, start: int, stop: int) -> list[str]:
        """Get range of members by index."""
        start_time = time.perf_counter()
        empty_list: list[str] = []
        try:
            result = await self._circuit_breaker.call(
                lambda: self._zrange_internal(key, start, stop),
                fallback=empty_list,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_operation("zrange", latency_ms)
            return list(result) if result else []
        except RedisError as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_error("zrange", latency_ms, str(e))
            return []

    async def zrangebyscore(
        self,
        key: str,
        min_score: float,
        max_score: float,
        offset: int = 0,
        count: int = -1,
    ) -> list[str]:
        """Get members with scores between min and max."""
        start = time.perf_counter()
        empty_list: list[str] = []
        try:
            result = await self._circuit_breaker.call(
                lambda: self._zrangebyscore_internal(key, min_score, max_score, offset, count),
                fallback=empty_list,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("zrangebyscore", latency_ms)
            return list(result) if result else []
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("zrangebyscore", latency_ms, str(e))
            return []

    async def zcard(self, key: str) -> int:
        """Get cardinality (size) of sorted set."""
        start = time.perf_counter()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._zcard_internal(key),
                fallback=0,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("zcard", latency_ms)
            return int(result) if result is not None else 0
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("zcard", latency_ms, str(e))
            return 0

    async def eval_script(self, script: str, keys: list[str], args: list[str]) -> list[str]:
        """Execute Lua script atomically."""
        start = time.perf_counter()
        empty_list: list[str] = []
        try:
            result = await self._circuit_breaker.call(
                lambda: self._eval_script_internal(script, keys, args),
                fallback=empty_list,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("eval_script", latency_ms)
            return list(result) if result else []
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("eval_script", latency_ms, str(e))
            return []

    async def get_bytes(self, key: str) -> bytes | None:
        """Get raw bytes from Redis cache."""
        start = time.perf_counter()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._get_bytes_internal(key),
                fallback=None,
            )
            latency_ms = (time.perf_counter() - start) * 1000

            if result is not None:
                self._metrics.record_hit("get_bytes", latency_ms)
            else:
                self._metrics.record_miss("get_bytes", latency_ms)
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("get_bytes", latency_ms, str(e))
            return None
        else:
            return result

    async def set_bytes(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set raw bytes in Redis cache."""
        start = time.perf_counter()
        try:
            await self._circuit_breaker.call(
                lambda: self._set_bytes_internal(key, value, ttl),
                fallback=None,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("set_bytes", latency_ms)
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("set_bytes", latency_ms, str(e))

    async def incr(self, key: str) -> int:
        """Increment integer value at key by 1. Returns new value. Creates key with 1 if doesn't exist."""
        start = time.perf_counter()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._incr_internal(key),
                fallback=0,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("incr", latency_ms)
            return int(result) if result is not None else 0
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("incr", latency_ms, str(e))
            return 0

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration time on key. Returns True if key exists and expiration was set."""
        start = time.perf_counter()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._expire_internal(key, seconds),
                fallback=False,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("expire", latency_ms)
            return bool(result)
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("expire", latency_ms, str(e))
            return False

    async def ttl(self, key: str) -> int:
        """Get TTL of key in seconds. Returns -2 if key doesn't exist, -1 if no expiry set."""
        start = time.perf_counter()
        try:
            result = await self._circuit_breaker.call(
                lambda: self._ttl_internal(key),
                fallback=-2,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_operation("ttl", latency_ms)
            return int(result) if result is not None else -2
        except RedisError as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_error("ttl", latency_ms, str(e))
            return -2

    # ===== Internal methods (let exceptions propagate for circuit breaker) =====

    async def _get_internal(self, key: str) -> object:
        """Get value from Redis, letting exceptions propagate."""
        value = await self._redis.get(self._make_key(key))
        if value is None:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError, TypeError:
            return value

    async def _set_internal(self, key: str, value: object, ttl: int | None) -> None:
        """Set value in Redis, letting exceptions propagate."""
        serialized_value = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        if ttl:
            await self._redis.set(self._make_key(key), serialized_value, ex=ttl)
        else:
            await self._redis.set(self._make_key(key), serialized_value)

    async def _delete_internal(self, key: str) -> None:
        """Delete key from Redis, letting exceptions propagate."""
        await self._redis.delete(self._make_key(key))

    async def _exists_internal(self, key: str) -> bool:
        """Check key existence in Redis, letting exceptions propagate."""
        return bool(await self._redis.exists(self._make_key(key)))

    async def _setnx_internal(self, key: str, value: object, ttl: int | None) -> bool:
        """Set if not exists in Redis, letting exceptions propagate."""
        serialized_value = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        if ttl:
            result = await self._redis.set(self._make_key(key), serialized_value, nx=True, ex=ttl)
        else:
            result = await self._redis.setnx(self._make_key(key), serialized_value)
        return bool(result)

    async def _zadd_internal(self, key: str, member: str, score: float) -> int:
        """Add to sorted set in Redis, letting exceptions propagate."""
        result = await self._redis.zadd(self._make_key(key), {member: score})
        return int(result) if result is not None else 0

    async def _zrem_internal(self, key: str, member: str) -> int:
        """Remove from sorted set in Redis, letting exceptions propagate."""
        result = await self._redis.zrem(self._make_key(key), member)
        return int(result) if result is not None else 0

    async def _zrange_internal(self, key: str, start: int, stop: int) -> list[str]:
        """Get range from sorted set in Redis, letting exceptions propagate."""
        result: object = await self._redis.zrange(self._make_key(key), start, stop)
        return _decode_redis_strings(result)

    async def _zrangebyscore_internal(
        self, key: str, min_score: float, max_score: float, offset: int, count: int
    ) -> list[str]:
        """Get range by score from sorted set, letting exceptions propagate."""
        if count > 0:
            result: object = await self._redis.zrangebyscore(
                self._make_key(key),
                min=min_score,
                max=max_score,
                start=offset,
                num=count,
            )
        else:
            result = await self._redis.zrangebyscore(self._make_key(key), min=min_score, max=max_score)
        return _decode_redis_strings(result)

    async def _zcard_internal(self, key: str) -> int:
        """Get cardinality of sorted set in Redis, letting exceptions propagate."""
        result = await self._redis.zcard(self._make_key(key))
        return int(result) if result is not None else 0

    async def _eval_script_internal(self, script: str, keys: list[str], args: list[str]) -> list[str]:
        """Execute Lua script in Redis, letting exceptions propagate."""
        prefixed_keys = [self._make_key(k) for k in keys]
        # Use execute_command instead of eval for proper typing
        result: object = await self._redis.execute_command("EVAL", script, len(prefixed_keys), *prefixed_keys, *args)
        if not isinstance(result, list):
            return []
        return [r.decode() if isinstance(r, bytes) else str(r) for r in result]

    async def _sadd_internal(self, key: str, *members: str) -> int:
        """Add members to set in Redis, letting exceptions propagate."""
        result = await self._redis.sadd(self._make_key(key), *members)
        return int(result) if result is not None else 0

    async def _srem_internal(self, key: str, *members: str) -> int:
        """Remove members from set in Redis, letting exceptions propagate."""
        result = await self._redis.srem(self._make_key(key), *members)
        return int(result) if result is not None else 0

    async def _smembers_internal(self, key: str) -> builtins.set[str]:
        """Get all members of set in Redis, letting exceptions propagate."""
        result = await cast(Awaitable[builtins.set[str]], self._redis.smembers(self._make_key(key)))
        return set(result) if result else set()

    async def _sismember_internal(self, key: str, member: str) -> bool:
        """Check if member exists in set in Redis, letting exceptions propagate."""
        result = await cast(Awaitable[int], self._redis.sismember(self._make_key(key), member))
        return bool(result)

    async def _get_bytes_internal(self, key: str) -> bytes | None:
        """Get raw bytes from Redis, letting exceptions propagate."""
        result = await self._redis_binary.get(self._make_key(key))
        return result if isinstance(result, bytes) else None

    async def _set_bytes_internal(self, key: str, value: bytes, ttl: int | None) -> None:
        """Set raw bytes in Redis, letting exceptions propagate."""
        if ttl:
            await self._redis_binary.set(self._make_key(key), value, ex=ttl)
        else:
            await self._redis_binary.set(self._make_key(key), value)

    async def _incr_internal(self, key: str) -> int:
        """Increment value at key in Redis, letting exceptions propagate."""
        result: object = await self._redis.execute_command("INCR", self._make_key(key))
        if isinstance(result, int | str | bytes):
            return int(result)
        msg = f"Unexpected Redis INCR result type: {type(result).__name__}"
        raise TypeError(msg)

    async def _expire_internal(self, key: str, seconds: int) -> bool:
        """Set expiration on key in Redis, letting exceptions propagate."""
        result = await self._redis.expire(self._make_key(key), seconds)
        return bool(result)

    async def _ttl_internal(self, key: str) -> int:
        """Get TTL of key in Redis, letting exceptions propagate."""
        result = await self._redis.ttl(self._make_key(key))
        return int(result) if result is not None else -2

    # ===== Distributed locking methods =====

    async def acquire_lock(
        self,
        lock_key: str,
        lock_value: str,
        ttl_seconds: int = 300,
        timeout_seconds: float = 30.0,
    ) -> bool:
        """Attempt to acquire a distributed lock.

        Args:
            lock_key: Unique identifier for the lock
            lock_value: Unique value for ownership verification
            ttl_seconds: Lock expiration time to prevent deadlocks
            timeout_seconds: Maximum time to wait for lock acquisition

        Returns:
            True if lock acquired, False if timeout reached

        """
        prefixed_key = f"lock:{lock_key}"
        start_time = time.perf_counter()

        while (time.perf_counter() - start_time) < timeout_seconds:
            acquired = await self.setnx(prefixed_key, lock_value, ttl=ttl_seconds)
            if acquired:
                return True
            await asyncio.sleep(_LOCK_POLL_INTERVAL_SECONDS)

        return False

    async def release_lock(self, lock_key: str, lock_value: str) -> bool:
        """Release a distributed lock if we own it.

        Args:
            lock_key: Unique identifier for the lock
            lock_value: Expected lock value for ownership verification

        Returns:
            True if lock was released, False if we didn't own it

        """
        result = await self.eval_script(
            _RELEASE_LOCK_SCRIPT,
            keys=[f"lock:{lock_key}"],
            args=[lock_value],
        )
        return bool(result and int(result[0]))

    async def is_locked(self, lock_key: str) -> bool:
        """Check if a lock is currently held."""
        return await self.exists(f"lock:{lock_key}")

    @asynccontextmanager
    async def distributed_lock(
        self, operation_name: str, ttl_seconds: int = 300, timeout_seconds: float = 30.0
    ) -> AsyncGenerator[None]:
        """Context manager for distributed locking operations.

        Args:
            operation_name: Descriptive name for the locked operation
            ttl_seconds: Lock expiration time (default: 5 minutes)
            timeout_seconds: Lock acquisition timeout (default: 30 seconds)

        Raises:
            DistributedLockError: If lock cannot be acquired within timeout

        Example:
            async with cache.distributed_lock("seed_templates"):
                await seed_default_templates()

        """
        lock_value = f"{time.time()}:{id(self)}"

        try:
            acquired = await self.acquire_lock(operation_name, lock_value, ttl_seconds, timeout_seconds)

            if not acquired:
                error_msg = f"Could not acquire distributed lock for {operation_name} within {timeout_seconds} seconds"
                raise DistributedLockError(error_msg)

            yield

        finally:
            await self.release_lock(operation_name, lock_value)
