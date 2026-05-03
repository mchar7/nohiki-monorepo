"""Benchmarks for FastAPI utility operations (nohiki-fastapi-utils).

Measures JWT verification, CSRF validation, error response construction,
and middleware overhead that runs on every HTTP request.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from nohiki_fastapi_utils.errors import (
    ConflictError,
    ErrorCode,
    NotFoundError,
    ValidationError,
)

# Error response construction (every error path in HTTP handlers)


def test_bench_create_not_found_error(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark NotFoundError construction (common in BFF)."""
    benchmark(
        NotFoundError,
        resource="Listing",
        identifier="550e8400-e29b-41d4-a716-446655440000",
    )


def test_bench_create_validation_error(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark ValidationError construction."""
    benchmark(ValidationError, message="Invalid email format")


def test_bench_create_conflict_error(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark ConflictError construction."""
    benchmark(ConflictError, resource="Account", reason="Email already registered")


def test_bench_error_code_comparison(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark ErrorCode enum comparison (used in error handlers)."""
    code = ErrorCode.NOT_FOUND

    def compare() -> bool:
        return code == ErrorCode.NOT_FOUND

    benchmark(compare)


# CSRF validation logic (inlined to avoid ASGI app dependency)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_SAFE_FETCH_SITES = frozenset({"same-origin", "same-site"})
_ALLOWED_ORIGINS = frozenset(
    {
        "https://app.nohiki.io",
        "https://staging.nohiki.io",
        "http://localhost:5173",
    }
)


def _validate_csrf(
    method: str,
    origin: str | None,
    fetch_site: str | None,
    *,
    has_cookies: bool,
) -> bool:
    """Inline CSRF validation logic mirroring CSRFMiddleware.dispatch."""
    if method in _SAFE_METHODS:
        return True
    if not has_cookies:
        return True
    if fetch_site and fetch_site in _SAFE_FETCH_SITES:
        return True
    return bool(origin and origin in _ALLOWED_ORIGINS)


def test_bench_csrf_safe_method(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark CSRF check for safe method (GET -- fast path)."""
    benchmark(_validate_csrf, "GET", None, None, has_cookies=True)


def test_bench_csrf_same_origin(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark CSRF check with Sec-Fetch-Site: same-origin."""
    benchmark(_validate_csrf, "POST", None, "same-origin", has_cookies=True)


def test_bench_csrf_origin_check(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark CSRF check with Origin header validation."""
    benchmark(_validate_csrf, "POST", "https://app.nohiki.io", None, has_cookies=True)


def test_bench_csrf_no_cookies(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark CSRF check without cookies (unauthenticated -- skip)."""
    benchmark(_validate_csrf, "POST", None, None, has_cookies=False)


def test_bench_csrf_reject(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark CSRF check that rejects (cross-origin POST with cookies)."""
    benchmark(
        _validate_csrf,
        "POST",
        "https://evil.example.com",
        "cross-site",
        has_cookies=True,
    )


# JWT claims parsing (inlined to avoid JWKS dependency)


@dataclass(frozen=True, slots=True)
class _JWTClaims:
    """Lightweight JWT claims structure matching JWTClaims dataclass."""

    sub: str
    email: str
    name: str
    iat: int
    exp: int


_SAMPLE_DECODED = {
    "sub": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "name": "Test User",
    "iat": 1700000000,
    "exp": 1700003600,
}


def test_bench_jwt_claims_construction(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark constructing JWTClaims from decoded token dict."""

    def construct() -> _JWTClaims:
        return _JWTClaims(
            sub=_SAMPLE_DECODED["sub"],
            email=_SAMPLE_DECODED["email"],
            name=_SAMPLE_DECODED["name"],
            iat=_SAMPLE_DECODED["iat"],
            exp=_SAMPLE_DECODED["exp"],
        )

    benchmark(construct)


def test_bench_jwt_claims_field_access(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark accessing JWT claims fields (every authenticated request)."""
    claims = _JWTClaims(**_SAMPLE_DECODED)

    def access() -> tuple[str, str, str]:
        return claims.sub, claims.email, claims.name

    benchmark(access)


# Request path matching (URL routing overhead)

_API_PREFIXES = ("/api/v1/", "/api/v2/", "/health", "/.well-known/")


def test_bench_path_prefix_check(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark checking if a request path matches known API prefixes."""
    path = "/api/v1/listings/550e8400-e29b-41d4-a716-446655440000"

    def check() -> bool:
        return any(path.startswith(prefix) for prefix in _API_PREFIXES)

    benchmark(check)


def test_bench_health_check_path(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark health check path matching (middleware fast-path)."""
    path = "/health"
    benchmark(lambda: path in {"/health", "/health/ready"})
