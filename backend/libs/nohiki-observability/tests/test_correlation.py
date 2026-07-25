"""Tests for correlation ID middleware."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from nohiki_observability import (
    CORRELATION_ID_HEADER,
    CorrelationIdMiddleware,
    get_correlation_id,
    set_correlation_id,
)
from nohiki_observability.correlation import _correlation_id_ctx_var


@pytest.fixture(autouse=True)
def reset_correlation_id() -> Iterator[None]:
    """Restore the correlation ID after each test."""
    token = _correlation_id_ctx_var.set(None)
    try:
        yield
    finally:
        _correlation_id_ctx_var.reset(token)


@pytest.fixture
def correlation_app() -> FastAPI:
    """Create an app that exposes the request's active correlation ID."""
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/test")
    async def test_endpoint() -> dict[str, str | None]:
        return {"correlation_id": get_correlation_id()}

    return app


class TestCorrelationIdFunctions:
    """Tests for correlation ID context functions."""

    def test_set_and_get_correlation_id(self) -> None:
        """Test setting and getting correlation ID."""
        test_id = str(uuid.uuid4())
        set_correlation_id(test_id)
        assert get_correlation_id() == test_id

    def test_get_correlation_id_none(self) -> None:
        """Test getting correlation ID when not set returns None."""
        token = _correlation_id_ctx_var.set(None)
        try:
            assert get_correlation_id() is None
        finally:
            _correlation_id_ctx_var.reset(token)

    def test_set_correlation_id_overwrites_existing(self) -> None:
        """Test that setting correlation ID overwrites existing value."""
        test_id1 = str(uuid.uuid4())
        test_id2 = str(uuid.uuid4())
        set_correlation_id(test_id1)
        assert get_correlation_id() == test_id1
        set_correlation_id(test_id2)
        assert get_correlation_id() == test_id2

    def test_correlation_id_header_constant(self) -> None:
        """Test that the header constant is correct."""
        assert CORRELATION_ID_HEADER == "X-Correlation-ID"


class TestCorrelationIdMiddleware:
    """Tests for CorrelationIdMiddleware."""

    def test_middleware_generates_correlation_id(self) -> None:
        """Test middleware generates correlation ID when not provided."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from nohiki_observability.correlation import CorrelationIdMiddleware

        app = FastAPI()
        app.add_middleware(CorrelationIdMiddleware)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert CORRELATION_ID_HEADER in response.headers
        # Verify it's a valid UUID
        correlation_id = response.headers[CORRELATION_ID_HEADER]
        uuid.UUID(correlation_id)

    def test_middleware_uses_provided_correlation_id(self) -> None:
        """Test middleware uses correlation ID from request header."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from nohiki_observability.correlation import CorrelationIdMiddleware

        app = FastAPI()
        app.add_middleware(CorrelationIdMiddleware)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app)
        test_id = "test-correlation-id-123"
        response = client.get("/test", headers={CORRELATION_ID_HEADER: test_id})

        assert response.status_code == 200
        assert response.headers[CORRELATION_ID_HEADER] == test_id

    def test_middleware_sets_context_variable(self) -> None:
        """Test middleware sets correlation ID in context variable."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from nohiki_observability.correlation import CorrelationIdMiddleware

        app = FastAPI()
        app.add_middleware(CorrelationIdMiddleware)

        captured_id: str | None = None

        @app.get("/test")
        async def test_endpoint() -> dict[str, str | None]:
            nonlocal captured_id
            captured_id = get_correlation_id()
            return {"correlation_id": captured_id}

        client = TestClient(app)
        test_id = "context-test-id"
        response = client.get("/test", headers={CORRELATION_ID_HEADER: test_id})

        assert response.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "invalid_id",
        ["x" * 129, "contains\x7fcontrol"],
        ids=["129-characters", "non-printable-ascii"],
    )
    async def test_middleware_replaces_invalid_correlation_ids(
        self,
        correlation_app: FastAPI,
        invalid_id: str,
    ) -> None:
        """Unsafe incoming IDs are replaced by one UUIDv7 used throughout the request."""
        transport = httpx.ASGITransport(app=correlation_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/test", headers={CORRELATION_ID_HEADER: invalid_id})

        generated_id = response.headers[CORRELATION_ID_HEADER]
        assert generated_id != invalid_id
        assert uuid.UUID(generated_id).version == 7
        assert response.json() == {"correlation_id": generated_id}

    @pytest.mark.asyncio
    async def test_middleware_restores_context_after_request(self, correlation_app: FastAPI) -> None:
        """Completing a request restores the correlation context active before it."""
        token = _correlation_id_ctx_var.set("outer-context")
        try:
            transport = httpx.ASGITransport(app=correlation_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/test",
                    headers={CORRELATION_ID_HEADER: "request-context"},
                )

            assert response.json() == {"correlation_id": "request-context"}
            assert get_correlation_id() == "outer-context"
        finally:
            _correlation_id_ctx_var.reset(token)


class TestCorrelationIdEdgeCases:
    """Tests for edge cases and error handling."""

    def test_context_var_direct_access(self) -> None:
        """Test direct access to context variable works correctly."""
        # Set via the module-level context variable directly
        test_id = str(uuid.uuid4())
        token = _correlation_id_ctx_var.set(test_id)
        try:
            # Get via the public function
            assert get_correlation_id() == test_id
            # Get directly from context var
            assert _correlation_id_ctx_var.get() == test_id
        finally:
            _correlation_id_ctx_var.reset(token)


class TestCorrelationIdWithoutFastAPI:
    """Tests for the fallback CorrelationIdMiddleware when FastAPI is not installed."""

    def test_fallback_middleware_raises_import_error(self) -> None:
        """Fallback CorrelationIdMiddleware raises ImportError with helpful message."""
        import importlib
        import importlib.abc
        import importlib.machinery
        import sys

        blocked = {
            "fastapi",
            "starlette",
            "starlette.middleware",
            "starlette.middleware.base",
        }

        class _Blocker(importlib.abc.MetaPathFinder):
            def find_spec(
                self,
                fullname: str,
                _path: object = None,
                _target: object = None,
            ) -> None:
                if fullname in blocked or fullname.startswith(("fastapi.", "starlette.")):
                    raise ModuleNotFoundError(fullname)

        blocker = _Blocker()
        with (
            patch.dict(sys.modules),
            patch.object(sys, "meta_path", [blocker, *sys.meta_path]),
        ):
            for mod_name in tuple(sys.modules):
                if (
                    mod_name in blocked
                    or mod_name == "nohiki_observability"
                    or mod_name.startswith(("fastapi.", "starlette.", "nohiki_observability."))
                ):
                    del sys.modules[mod_name]

            mod = importlib.import_module("nohiki_observability.correlation")
            assert "nohiki_observability._correlation_middleware" not in sys.modules
            middleware_cls = mod.CorrelationIdMiddleware
            middleware_mod = sys.modules["nohiki_observability._correlation_middleware"]
            assert middleware_mod._FASTAPI_AVAILABLE is False
            with pytest.raises(ImportError, match="FastAPI not installed"):
                middleware_cls()
