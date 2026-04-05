"""Tests for rate limiting utilities."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from nohiki_fastapi_utils.rate_limiter import (
    CacheUtilsStorage,
    RateLimitedEndpoint,
    RateLimitExceededHTTP,
    extract_client_ip,
    get_client_id,
    rate_limit,
    rate_limit_exceeded_handler,
    setup_rate_limiting,
)
from nohiki_redis_utils import RedisCache
from redis.asyncio import RedisError


@pytest.fixture
def mock_cache() -> AsyncMock:
    """Create a mock cache."""
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.delete = AsyncMock()
    cache.exists = AsyncMock(return_value=False)
    return cache


class TestRateLimitExceededHTTP:
    """Tests for RateLimitExceededHTTP exception."""

    def test_init(self) -> None:
        """Test RateLimitExceededHTTP initialization."""
        exc = RateLimitExceededHTTP("10/minute", retry_after=30)
        assert exc.status_code == 429
        assert "10/minute" in exc.detail
        assert exc.retry_after == 30
        assert exc.headers is not None
        assert exc.headers["Retry-After"] == "30"


class TestGetClientId:
    """Tests for get_client_id function."""

    def test_returns_user_id_when_present(self) -> None:
        """Test returns user ID from header."""
        request = MagicMock(spec=Request)
        request.headers = {"X-Account-ID": "user-123"}
        request.client = None

        result = get_client_id(request)
        assert result == "user:user-123"

    def test_forwarded_for_without_peer_is_untrusted(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"X-Forwarded-For": "192.168.1.1, 10.0.0.1"}
        request.client = None

        assert get_client_id(request) == "ip:unknown"

    @pytest.mark.parametrize("forwarded", ["not-an-ip", ""])
    def test_malformed_forwarding_without_peer_is_unknown(self, forwarded: str) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"X-Forwarded-For": forwarded}
        request.client = None

        assert get_client_id(request) == "ip:unknown"

    def test_real_ip_without_peer_is_untrusted(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"X-Real-IP": "192.168.1.100"}
        request.client = None

        assert get_client_id(request) == "ip:unknown"

    def test_returns_client_host(self) -> None:
        """Test returns client host as fallback."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        result = get_client_id(request)
        assert result == "ip:127.0.0.1"

    @pytest.mark.parametrize("peer", ["192.0.2.20", "2001:db8::20"])
    def test_peer_ipv4_and_ipv6_ignore_forwarding_headers(self, peer: str) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"X-Forwarded-For": "198.51.100.9", "X-Real-IP": "203.0.113.9"}
        request.client = MagicMock(host=peer)

        assert get_client_id(request) == f"ip:{peer}"

    def test_real_peer_ignores_forged_identity_headers(self) -> None:
        """A network peer cannot choose another rate-limit bucket with headers."""
        app = FastAPI()

        @app.get("/client-id")
        async def client_id(request: Request) -> dict[str, str]:
            return {"client_id": get_client_id(request)}

        response = TestClient(app).get(
            "/client-id",
            headers={
                "X-Account-ID": "victim-account",
                "X-Forwarded-For": "198.51.100.25",
                "X-Real-IP": "203.0.113.9",
            },
        )

        assert response.json() == {"client_id": "ip:testclient"}

    def test_verified_jwt_subject_precedes_network_peer(self) -> None:
        """A verified JWT subject, not the peer address, identifies an account."""

        class Claims:
            sub = "verified-account"

        class Verifier:
            def verify_request(self, _request: Request) -> Claims:
                return Claims()

        app = FastAPI()

        @app.get("/client-id")
        async def client_id(request: Request) -> dict[str, str]:
            return {"client_id": get_client_id(request)}

        with (
            patch("nohiki_fastapi_utils.rate_limiter._JWT_AVAILABLE", new=True),
            patch("nohiki_fastapi_utils.rate_limiter._jwks_verifier_func", return_value=Verifier()),
        ):
            response = TestClient(app).get("/client-id")

        assert response.json() == {"client_id": "user:verified-account"}

    @staticmethod
    def _request(peer: str, forwarded: str | None = None) -> MagicMock:
        request = MagicMock(spec=Request)
        request.client = MagicMock(host=peer)
        request.headers = {} if forwarded is None else {"X-Forwarded-For": forwarded}
        return request

    def test_trusted_proxy_ignores_spoofed_leftmost_forwarded_hop(self) -> None:
        request = self._request("10.0.0.2", "203.0.113.99, 198.51.100.7")

        assert extract_client_ip(request, "10.0.0.0/8") == "198.51.100.7"

    def test_complete_trusted_proxy_chain_returns_original_client(self) -> None:
        request = self._request("10.0.0.3", "198.51.100.7, 10.0.0.2")

        assert extract_client_ip(request, "10.0.0.0/8") == "198.51.100.7"

    def test_untrusted_intermediate_terminates_proxy_chain(self) -> None:
        request = self._request("10.0.0.3", "203.0.113.99, 192.0.2.44")

        assert extract_client_ip(request, "10.0.0.0/8") == "192.0.2.44"

    @pytest.mark.parametrize("forwarded", ["198.51.100.7, not-an-ip", "not-an-ip, 10.0.0.2"])
    def test_malformed_forwarded_hop_falls_back_to_direct_peer(self, forwarded: str) -> None:
        request = self._request("10.0.0.3", forwarded)

        assert extract_client_ip(request, "10.0.0.0/8") == "10.0.0.3"

    def test_direct_client_without_forwarding_is_returned(self) -> None:
        request = self._request("198.51.100.7")

        assert extract_client_ip(request, "10.0.0.0/8") == "198.51.100.7"

    def test_ipv6_proxy_chain_is_canonicalized(self) -> None:
        request = self._request("2001:db8:ffff::2", "2001:0db8:0001::7, 2001:db8:ffff::1")

        assert extract_client_ip(request, "2001:db8:ffff::/48") == "2001:db8:1::7"

    def test_returns_unknown_when_no_client(self) -> None:
        """Test returns unknown when no client info."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = None

        result = get_client_id(request)
        assert result == "ip:unknown"

    def test_no_forwarding_header_and_no_peer_is_unknown(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = None

        assert get_client_id(request) == "ip:unknown"


class TestCacheUtilsStorage:
    """Tests for CacheUtilsStorage class."""

    async def test_incr(self, mock_cache: AsyncMock) -> None:
        """Test incr method."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            storage = CacheUtilsStorage("test-service", redis_url="redis://localhost")
            mock_cache.get.return_value = 5

            result = await storage.incr("test-key", 60, 1)

            assert result == 6
            mock_cache.set.assert_called_once_with("test-key", 6, ttl=60)

    async def test_redis_backend_failure_is_propagated(self) -> None:
        """Rate-limit counters must fail closed when the Redis backend is unavailable."""
        cache = RedisCache(redis_url="redis://localhost", service_name="test")
        try:
            with (
                patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=cache),
                patch.object(cache, "incr_with_ttl_strict", side_effect=RedisError("Connection lost")),
            ):
                storage = CacheUtilsStorage("test-service", redis_url="redis://localhost")
                with pytest.raises(RedisError, match="Connection lost"):
                    await storage.incr("test-key", 60)
        finally:
            await cache.close()

    async def test_get(self, mock_cache: AsyncMock) -> None:
        """Test get method."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            storage = CacheUtilsStorage("test-service", redis_url="redis://localhost")
            mock_cache.get.return_value = 10

            result = await storage.get("test-key")

            assert result == 10

    async def test_get_returns_zero_for_none(self, mock_cache: AsyncMock) -> None:
        """Test get returns 0 when key doesn't exist."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            storage = CacheUtilsStorage("test-service", redis_url="redis://localhost")
            mock_cache.get.return_value = None

            result = await storage.get("test-key")

            assert result == 0

    async def test_get_expiry_when_exists(self, mock_cache: AsyncMock) -> None:
        """Test get_expiry when key exists."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            storage = CacheUtilsStorage("test-service", redis_url="redis://localhost")
            mock_cache.exists.return_value = True

            result = await storage.get_expiry("test-key")

            assert result > 0

    async def test_get_expiry_when_not_exists(self, mock_cache: AsyncMock) -> None:
        """Test get_expiry when key doesn't exist."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            storage = CacheUtilsStorage("test-service", redis_url="redis://localhost")
            mock_cache.exists.return_value = False

            result = await storage.get_expiry("test-key")

            assert result == 0

    async def test_check_healthy(self, mock_cache: AsyncMock) -> None:
        """Test check returns True when healthy."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            storage = CacheUtilsStorage("test-service", redis_url="redis://localhost")
            mock_cache.get.return_value = "ok"

            result = await storage.check()

            assert result is True

    async def test_check_unhealthy(self, mock_cache: AsyncMock) -> None:
        """Test check returns False when unhealthy."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            storage = CacheUtilsStorage("test-service", redis_url="redis://localhost")
            mock_cache.set.side_effect = OSError("Connection failed")

            result = await storage.check()

            assert result is False

    async def test_reset(self, mock_cache: AsyncMock) -> None:
        """Test reset returns None."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            storage = CacheUtilsStorage("test-service", redis_url="redis://localhost")

            result = await storage.reset()

            assert result is None

    async def test_clear(self, mock_cache: AsyncMock) -> None:
        """Test clear deletes key."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            storage = CacheUtilsStorage("test-service", redis_url="redis://localhost")

            await storage.clear("test-key")

            mock_cache.delete.assert_called_once_with("test-key")

    def test_base_exceptions(self, mock_cache: AsyncMock) -> None:
        """Test base_exceptions property."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            storage = CacheUtilsStorage("test-service", redis_url="redis://localhost")

            assert storage.base_exceptions is Exception


class TestRateLimitExceededHandler:
    """Tests for rate_limit_exceeded_handler function."""

    def test_handles_rate_limit_exceeded_http(self) -> None:
        """Test handling RateLimitExceededHTTP exception."""
        request = MagicMock(spec=Request)
        exc = RateLimitExceededHTTP("10/minute", retry_after=30)

        response = rate_limit_exceeded_handler(request, exc)

        assert response.status_code == 429
        assert response.headers["Retry-After"] == "30"

    def test_handles_generic_exception(self) -> None:
        """Test handling generic exception."""
        request = MagicMock(spec=Request)
        exc = Exception("Some error")

        response = rate_limit_exceeded_handler(request, exc)

        assert response.status_code == 429


class TestRateLimitedEndpoint:
    """Tests for RateLimitedEndpoint class."""

    async def test_call_wrapped_function(self) -> None:
        """Test calling wrapped function."""

        async def my_func(x: int) -> int:
            return await asyncio.to_thread(lambda: x * 2)

        from limits import parse

        limits = [parse("10/minute")]
        endpoint = RateLimitedEndpoint(my_func, limits)

        result = await endpoint(5)

        assert result == 10

    def test_rate_limits_property(self) -> None:
        """Test rate_limits property."""
        from limits import parse

        async def my_func() -> str:
            return await asyncio.to_thread(lambda: "ok")

        limits = [parse("10/minute"), parse("100/hour")]
        endpoint = RateLimitedEndpoint(my_func, limits)

        assert endpoint.rate_limits == limits


class TestRateLimitDecorator:
    """Tests for rate_limit decorator."""

    def test_creates_rate_limited_endpoint(self) -> None:
        """Test decorator creates RateLimitedEndpoint."""

        @rate_limit("10/minute", "100/hour")
        async def my_endpoint() -> str:
            return "ok"

        assert isinstance(my_endpoint, RateLimitedEndpoint)
        assert len(my_endpoint.rate_limits) == 2


class TestSetupRateLimiting:
    """Tests for setup_rate_limiting function."""

    def test_adds_middleware_and_handler(self, mock_cache: AsyncMock) -> None:
        """Test setup adds middleware and exception handler."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            app = FastAPI()

            storage = setup_rate_limiting(app, "test-service", redis_url="redis://localhost")

            assert isinstance(storage, CacheUtilsStorage)

    def test_uses_custom_key_func(self, mock_cache: AsyncMock) -> None:
        """Test setup uses custom key function."""

        def custom_key_func(_request: Request) -> str:
            return "custom-key"

        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            app = FastAPI()

            setup_rate_limiting(
                app,
                "test-service",
                redis_url="redis://localhost",
                key_func=custom_key_func,
            )

    def test_uses_custom_limits(self, mock_cache: AsyncMock) -> None:
        """Test setup uses custom default limits."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            app = FastAPI()

            setup_rate_limiting(
                app,
                "test-service",
                redis_url="redis://localhost",
                default_limits=["50/minute"],
            )


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    def test_allows_request_under_limit(self, mock_cache: AsyncMock) -> None:
        """Test middleware allows requests under limit."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            app = FastAPI()
            setup_rate_limiting(
                app,
                "test-service",
                redis_url="redis://localhost",
                default_limits=["100/minute"],
            )

            @app.get("/test")
            async def test_endpoint() -> dict[str, str]:
                return {"status": "ok"}

            mock_cache.get.return_value = 0

            client = TestClient(app)
            response = client.get("/test")

            assert response.status_code == 200

    def test_blocks_request_over_limit(self, mock_cache: AsyncMock) -> None:
        """Test middleware blocks requests over limit."""
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
            app = FastAPI()
            setup_rate_limiting(
                app,
                "test-service",
                redis_url="redis://localhost",
                default_limits=["10/minute"],
            )

            @app.get("/test")
            async def test_endpoint() -> dict[str, str]:
                return {"status": "ok"}

            mock_cache.get.return_value = 100

            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/test")

                assert response.status_code == 429

    async def test_concurrent_requests_atomically_cross_limit(self) -> None:
        """Two simultaneous requests consume distinct counts and only one passes a limit of one."""

        class AtomicCache:
            def __init__(self) -> None:
                self.value = 0
                self._lock = asyncio.Lock()

            async def incr(self, _key: str) -> int:
                async with self._lock:
                    await asyncio.sleep(0)
                    self.value += 1
                    return self.value

            async def expire(self, _key: str, _expiry: int) -> bool:
                return True

            async def ttl(self, _key: str) -> int:
                return 60

            async def get(self, _key: str) -> int:
                msg = "rate limiting must use the backend's atomic increment"
                raise AssertionError(msg)

        cache = AtomicCache()
        with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=cache):
            app = FastAPI()
            setup_rate_limiting(
                app,
                "test-service",
                redis_url="redis://localhost",
                key_func=lambda _request: "shared-client",
                default_limits=["1/minute"],
            )

            @app.get("/test")
            async def test_endpoint() -> dict[str, str]:
                return {"status": "ok"}

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                responses = await asyncio.gather(client.get("/test"), client.get("/test"))

        assert sorted(response.status_code for response in responses) == [200, 429]
        assert cache.value == 2
        limited_response = next(response for response in responses if response.status_code == 429)
        assert limited_response.json()["error"] == "Rate limit exceeded"
        assert int(limited_response.headers["Retry-After"]) >= 1


class TestGetClientIdFallbacks:
    """Tests for get_client_id header fallback paths."""

    def test_uses_x_account_id_header(self) -> None:
        """get_client_id falls back to X-Account-ID header when JWT unavailable."""
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"X-Account-ID": "user-abc"}

        with patch("nohiki_fastapi_utils.rate_limiter._extract_verified_user_id", return_value=None):
            result = get_client_id(mock_request)

        assert result == "user:user-abc"

    def test_uses_verified_jwt_user_id(self) -> None:
        """get_client_id uses verified JWT user ID when available."""
        mock_request = MagicMock(spec=Request)

        with patch("nohiki_fastapi_utils.rate_limiter._extract_verified_user_id", return_value="jwt-user-123"):
            result = get_client_id(mock_request)

        assert result == "user:jwt-user-123"


class TestExtractVerifiedUserId:
    """Tests for _extract_verified_user_id function."""

    def test_returns_none_when_jwt_not_available(self) -> None:
        """Returns None when JWT libraries are not installed."""
        from nohiki_fastapi_utils.rate_limiter import _extract_verified_user_id

        mock_request = MagicMock(spec=Request)
        with patch("nohiki_fastapi_utils.rate_limiter._JWT_AVAILABLE", new=False):
            result = _extract_verified_user_id(mock_request)

        assert result is None

    def test_returns_sub_from_verified_claims(self) -> None:
        """Returns claims.sub when JWT verification succeeds."""
        from nohiki_fastapi_utils.rate_limiter import _extract_verified_user_id

        mock_request = MagicMock(spec=Request)
        mock_verifier = MagicMock()
        mock_claims = MagicMock()
        mock_claims.sub = "verified-user-456"
        mock_verifier.verify_request.return_value = mock_claims

        with (
            patch("nohiki_fastapi_utils.rate_limiter._JWT_AVAILABLE", new=True),
            patch("nohiki_fastapi_utils.rate_limiter._jwks_verifier_func", return_value=mock_verifier),
        ):
            result = _extract_verified_user_id(mock_request)

        assert result == "verified-user-456"
