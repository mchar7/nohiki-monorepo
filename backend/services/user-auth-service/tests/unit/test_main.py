"""Unit tests for identity_service.main module lifespan."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class TestInitializeJWTHandler:
    """Tests for _initialize_jwt_handler function."""

    def test_initialize_jwt_handler_loads_key_and_creates_handler(self) -> None:
        """Test that _initialize_jwt_handler loads the private key and initializes handler."""
        mock_settings = MagicMock()
        mock_settings.jwt.issuer = "test-issuer"
        mock_settings.jwt.audience = "test-audience"
        mock_settings.jwt.key_id = "test-key-id"
        mock_settings.jwt.access_token_expire_minutes = 15
        mock_settings.jwt.refresh_token_expire_days = 30
        mock_settings.jwt.private_key_path = "/path/to/key.pem"

        mock_private_key = "-----BEGIN PRIVATE KEY-----\nMOCK_KEY\n-----END PRIVATE KEY-----"

        with (
            patch("user_auth_service.main.settings", mock_settings),
            patch("user_auth_service.main.load_private_key_from_file", return_value=mock_private_key) as mock_load,
            patch("user_auth_service.main.init_jwt_handler") as mock_init,
        ):
            from user_auth_service.main import _initialize_jwt_handler

            _initialize_jwt_handler()

            # Verify load_private_key_from_file was called with Path object
            mock_load.assert_called_once()
            call_args = mock_load.call_args[0][0]
            assert isinstance(call_args, Path)
            assert str(call_args) == "/path/to/key.pem"

            # Verify init_jwt_handler was called with correct arguments
            mock_init.assert_called_once()
            args = mock_init.call_args
            assert args[0][0] == mock_private_key
            assert args[0][1].issuer == "test-issuer"
            assert args[0][1].audience == "test-audience"
            assert args[0][1].key_id == "test-key-id"


class TestLifespan:
    """Tests for lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_initializes_database(self) -> None:
        """Lifespan calls initialize_database with config settings."""
        with (
            patch("user_auth_service.main._initialize_jwt_handler"),
            patch("user_auth_service.main.initialize_database", new_callable=AsyncMock) as mock_init_db,
            patch("user_auth_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch("user_auth_service.main.kafka_client") as mock_kafka,
        ):
            mock_kafka.ensure_producer_ready = AsyncMock()
            mock_kafka.close = AsyncMock()
            from user_auth_service.main import lifespan, settings

            mock_app = MagicMock()

            async with lifespan(mock_app):
                mock_init_db.assert_awaited()

            # initialize_database now takes the full Settings object
            mock_init_db.assert_awaited_once_with(settings)

    @pytest.mark.asyncio
    async def test_lifespan_handles_db_init_failure(self) -> None:
        """Lifespan raises exception on database initialization failure."""
        mock_init_db = AsyncMock(side_effect=RuntimeError("DB init failed"))
        with (
            patch("user_auth_service.main._initialize_jwt_handler"),
            patch("user_auth_service.main.initialize_database", mock_init_db),
            patch("user_auth_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch("user_auth_service.main.kafka_client") as mock_kafka,
        ):
            mock_kafka.ensure_producer_ready = AsyncMock()
            mock_kafka.close = AsyncMock()
            from user_auth_service.main import lifespan

            mock_app = MagicMock()

            with pytest.raises(RuntimeError, match="DB init failed"):
                async with lifespan(mock_app):
                    mock_init_db.assert_awaited()

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_calls_cleanup_methods(self) -> None:
        """Test that lifespan shutdown calls all cleanup methods in correct order."""
        call_order: list[str] = []

        def track_kafka_close() -> None:
            call_order.append("kafka_close")

        def track_cache_close() -> None:
            call_order.append("cache_close")

        def track_engine_close() -> None:
            call_order.append("engine_close")

        def track_obs_shutdown() -> None:
            call_order.append("obs_shutdown")

        mock_kafka = MagicMock()
        mock_kafka.close = AsyncMock(side_effect=track_kafka_close)

        mock_cache_factory = MagicMock()
        mock_cache_factory.close_all = AsyncMock(side_effect=track_cache_close)

        mock_obs = MagicMock()
        mock_obs.shutdown = MagicMock(side_effect=track_obs_shutdown)

        mock_kafka.ensure_producer_ready = AsyncMock()

        with (
            patch("user_auth_service.main._initialize_jwt_handler"),
            patch("user_auth_service.main.initialize_database", new_callable=AsyncMock),
            patch("user_auth_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch("user_auth_service.main.kafka_client", mock_kafka),
            patch("user_auth_service.main.CacheFactory", mock_cache_factory),
            patch(
                "user_auth_service.main.close_all_engines",
                new_callable=AsyncMock,
                side_effect=track_engine_close,
            ),
            patch("user_auth_service.main.obs", mock_obs),
        ):
            from user_auth_service.main import lifespan

            mock_app = MagicMock()

            async with lifespan(mock_app):
                pass  # Startup and shutdown

        # Verify cleanup was called in correct order (producer-only, no stop_consumers)
        mock_kafka.close.assert_awaited_once()
        mock_cache_factory.close_all.assert_awaited_once()
        mock_obs.shutdown.assert_called_once()

        assert call_order == [
            "kafka_close",
            "cache_close",
            "engine_close",
            "obs_shutdown",
        ]


class TestAppInitialization:
    """Tests for FastAPI app initialization."""

    def test_auth_routes_enforce_public_http_contracts(self) -> None:
        """The assembled app exposes auth routers with their real rejection behavior."""
        from user_auth_service.main import app, settings

        client = TestClient(app)
        origin = settings.security.get_csrf_origins()[0]

        refresh_response = client.post(
            f"{settings.api_prefix}/auth/refresh",
            headers={"Origin": origin},
        )
        account_response = client.get(f"{settings.api_prefix}/account")
        providers_response = client.get(f"{settings.api_prefix}/auth/oauth/providers")

        assert refresh_response.status_code == 401
        assert refresh_response.json()["message"] == "Refresh token required"
        assert refresh_response.json()["path"] == f"{settings.api_prefix}/auth/refresh"
        assert account_response.status_code == 401
        assert account_response.json()["message"] == "Authentication required"
        assert account_response.json()["path"] == f"{settings.api_prefix}/account"
        assert providers_response.status_code == 200
        assert [provider["id"] for provider in providers_response.json()["providers"]] == [
            "github",
            "google",
        ]

    def test_registration_openapi_requires_only_canonical_name(self) -> None:
        """Generated API schema exposes the canonical registration name contract."""
        from user_auth_service.main import app

        create_user = app.openapi()["components"]["schemas"]["CreateUserRequest"]

        assert "display_name" in create_user["required"]
        assert create_user["properties"]["display_name"]["maxLength"] == 255
        assert "first_name" not in create_user["properties"]
        assert "last_name" not in create_user["properties"]


class TestJWKSEndpoint:
    """Tests for JWKS endpoint."""

    def test_jwks_endpoint_returns_keys(self) -> None:
        """Test that JWKS endpoint returns public keys."""
        mock_jwt_handler = MagicMock()
        mock_jwt_handler.get_jwks.return_value = {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": "test-key-id",
                    "n": "test-modulus",
                    "e": "AQAB",
                }
            ]
        }

        with (
            patch("user_auth_service.main._initialize_jwt_handler"),
            patch("user_auth_service.main.get_jwt_handler", return_value=mock_jwt_handler),
            patch("user_auth_service.main.initialize_database", new_callable=AsyncMock),
            patch("user_auth_service.main.kafka_client.close", new_callable=AsyncMock),
            patch("user_auth_service.main.CacheFactory.close_all", new_callable=AsyncMock),
            patch("user_auth_service.main.close_all_engines", new_callable=AsyncMock),
        ):
            from user_auth_service.main import app

            client = TestClient(app)
            response = client.get("/.well-known/jwks.json")

            assert response.status_code == 200
            assert response.json() == {
                "keys": [
                    {
                        "kty": "RSA",
                        "use": "sig",
                        "alg": "RS256",
                        "kid": "test-key-id",
                        "n": "test-modulus",
                        "e": "AQAB",
                    }
                ]
            }
            # Verify Cache-Control header
            assert "Cache-Control" in response.headers
            assert "max-age=3600" in response.headers["Cache-Control"]

    def test_jwks_endpoint_sets_cache_headers(self) -> None:
        """Test that JWKS endpoint sets correct cache headers."""
        mock_jwt_handler = MagicMock()
        mock_jwt_handler.get_jwks.return_value = {"keys": []}

        with (
            patch("user_auth_service.main._initialize_jwt_handler"),
            patch("user_auth_service.main.get_jwt_handler", return_value=mock_jwt_handler),
            patch("user_auth_service.main.initialize_database", new_callable=AsyncMock),
            patch("user_auth_service.main.kafka_client.close", new_callable=AsyncMock),
            patch("user_auth_service.main.CacheFactory.close_all", new_callable=AsyncMock),
            patch("user_auth_service.main.close_all_engines", new_callable=AsyncMock),
        ):
            from user_auth_service.main import app

            client = TestClient(app)
            response = client.get("/.well-known/jwks.json")

            assert response.headers["Cache-Control"] == "public, max-age=3600"
