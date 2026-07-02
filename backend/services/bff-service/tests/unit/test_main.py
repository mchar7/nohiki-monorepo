"""Behavioral tests for BFF application-level request policy."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from pytest_mock import MockerFixture


@asynccontextmanager
async def _consumer_supervision(
    events: list[str],
    *,
    failure: Exception | None = None,
    trigger: asyncio.Event | None = None,
) -> AsyncIterator[None]:
    """Model the client's TaskGroup supervision, including owner-task interruption."""
    if (failure is None) != (trigger is None):
        message = "failure and trigger must be provided together"
        raise ValueError(message)

    async def fail_after_trigger() -> None:
        assert failure is not None
        assert trigger is not None
        await trigger.wait()
        events.append("consumer-fatal")
        raise failure

    async with asyncio.TaskGroup() as tasks:
        monitor = tasks.create_task(fail_after_trigger()) if failure is not None else None
        events.append("supervision-enter")
        try:
            yield
        finally:
            events.append("supervision-exit")
            if monitor is not None and not monitor.done():
                monitor.cancel()


def _request(path: str, secret: str | None) -> Request:
    headers = [] if secret is None else [(b"x-auth-listings-secret", secret.encode())]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("203.0.113.7", 12345),
            "server": ("api.test", 443),
            "root_path": "",
        }
    )


@pytest.mark.parametrize(
    ("path_suffix", "supplied_secret"),
    [
        pytest.param("/auth-listings/", None, id="missing-secret"),
        pytest.param("/auth-listings/", "wrong-secret", id="invalid-secret"),
        pytest.param("/listings/", "worker-secret", id="valid-secret-wrong-route"),
    ],
)
def test_auth_listings_worker_bucket_requires_valid_route_secret(
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
    path_suffix: str,
    supplied_secret: str | None,
) -> None:
    """Unauthenticated traffic must stay in its client bucket, never the Worker's shared bucket."""
    from bff_service import main

    monkeypatch.setattr(main.settings.auth_listings, "secret", "worker-secret")
    fallback = mocker.patch.object(main, "get_client_id", return_value="client:203.0.113.7")

    key = main._bff_rate_limit_key(_request(f"{main.settings.api_prefix}{path_suffix}", supplied_secret))

    assert key == "client:203.0.113.7"
    fallback.assert_called_once()


def test_valid_auth_listings_worker_request_uses_service_bucket(
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    """Only a correctly authenticated Worker request receives the service-tier rate bucket."""
    from bff_service import main

    monkeypatch.setattr(main.settings.auth_listings, "secret", "worker-secret")
    fallback = mocker.patch.object(main, "get_client_id", return_value="client:203.0.113.7")

    key = main._bff_rate_limit_key(_request(f"{main.settings.api_prefix}/auth-listings/", "worker-secret"))

    assert key == "service:auth-listings-worker"
    fallback.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_orders_startup_before_graceful_resource_shutdown(
    mocker: MockerFixture,
) -> None:
    """The app becomes ready only after dependencies start and releases resources in dependency order."""
    from bff_service import main

    events: list[str] = []

    def sync_event(name: str) -> None:
        events.append(name)

    def async_recorder(name: str) -> Callable[..., object]:
        async def record(*_args: object, **_kwargs: object) -> None:
            events.append(name)

        return record

    mocker.patch.object(main, "init_jwks_verifier", side_effect=lambda _config: sync_event("jwks"))
    mocker.patch.object(main, "initialize_database", side_effect=async_recorder("database"))
    mocker.patch.object(main, "_cleanup_expired_revocations", side_effect=async_recorder("cleanup"))
    mocker.patch.object(main, "ensure_kafka_ready", side_effect=async_recorder("broker"))
    mocker.patch.object(
        main.kafka_client,
        "ensure_producer_ready",
        side_effect=async_recorder("producer"),
    )
    mocker.patch.object(main, "get_async_sessionmaker", return_value=object())
    mocker.patch.object(
        main.kafka_client,
        "set_db_session_factory",
        side_effect=lambda _factory: sync_event("session-factory"),
    )
    mocker.patch.object(main, "init_sse_bridge", side_effect=async_recorder("sse"))
    mocker.patch.object(main, "start_event_consumer", side_effect=lambda: sync_event("consumers"))
    mocker.patch.object(
        main.kafka_client,
        "wait_for_consumer_catchup",
        side_effect=async_recorder("catchup"),
    )
    mocker.patch.object(
        main.kafka_client,
        "supervise_consumer_failures",
        side_effect=lambda: _consumer_supervision(events),
    )
    mocker.patch.object(
        main.kafka_client,
        "stop_consumers",
        side_effect=async_recorder("stop-consumers"),
    )
    mocker.patch.object(main, "close_sse_bridge", side_effect=async_recorder("close-sse"))
    mocker.patch.object(main.kafka_client, "close", side_effect=async_recorder("close-kafka"))
    mocker.patch.object(main.CacheFactory, "close_all", side_effect=async_recorder("close-redis"))
    mocker.patch.object(main, "close_all_engines", side_effect=async_recorder("close-database"))
    mocker.patch.object(main.obs, "shutdown", side_effect=lambda: sync_event("observability"))

    async with main.lifespan(main.app):
        events.append("serving")

    assert events == [
        "jwks",
        "database",
        "cleanup",
        "broker",
        "producer",
        "session-factory",
        "sse",
        "consumers",
        "supervision-enter",
        "catchup",
        "serving",
        "supervision-exit",
        "stop-consumers",
        "close-sse",
        "close-kafka",
        "close-redis",
        "close-database",
        "observability",
    ]


@pytest.mark.asyncio
async def test_lifespan_catchup_timeout_fails_closed_and_cleans_started_resources(
    mocker: MockerFixture,
) -> None:
    """A startup barrier failure never yields readiness and closes resources already opened."""
    from bff_service import main
    from nohiki_kafka_client.exceptions import KafkaClientError

    failure = KafkaClientError("catch-up timed out")

    mocker.patch.object(main, "init_jwks_verifier")
    mocker.patch.object(main, "initialize_database", new_callable=AsyncMock)
    mocker.patch.object(main, "_cleanup_expired_revocations", new_callable=AsyncMock)
    mocker.patch.object(main, "ensure_kafka_ready", new_callable=AsyncMock)
    mocker.patch.object(main.kafka_client, "ensure_producer_ready", new_callable=AsyncMock)
    mocker.patch.object(main, "get_async_sessionmaker", return_value=object())
    mocker.patch.object(main.kafka_client, "set_db_session_factory")
    mocker.patch.object(main, "init_sse_bridge", new_callable=AsyncMock)
    mocker.patch.object(main, "start_event_consumer")
    mocker.patch.object(
        main.kafka_client,
        "supervise_consumer_failures",
        side_effect=lambda: _consumer_supervision([]),
    )
    mocker.patch.object(
        main.kafka_client,
        "wait_for_consumer_catchup",
        new_callable=AsyncMock,
        side_effect=failure,
    )
    stop_consumers = mocker.patch.object(main.kafka_client, "stop_consumers", new_callable=AsyncMock)
    close_sse = mocker.patch.object(main, "close_sse_bridge", new_callable=AsyncMock)
    close_kafka = mocker.patch.object(main.kafka_client, "close", new_callable=AsyncMock)
    close_redis = mocker.patch.object(main.CacheFactory, "close_all", new_callable=AsyncMock)
    close_database = mocker.patch.object(main, "close_all_engines", new_callable=AsyncMock)
    shutdown = mocker.patch.object(main.obs, "shutdown")

    with pytest.raises(ExceptionGroup) as raised:
        async with main.lifespan(main.app):
            pytest.fail("lifespan yielded readiness after catch-up failure")

    assert raised.value.exceptions == (failure,)

    stop_consumers.assert_awaited_once()
    close_sse.assert_awaited_once()
    close_kafka.assert_awaited_once()
    close_redis.assert_awaited_once()
    close_database.assert_awaited_once()
    shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_fatal_consumer_during_catchup_propagates_and_cleans_in_order(
    mocker: MockerFixture,
) -> None:
    """A fatal owner failure interrupts the catch-up barrier and still releases every resource."""
    from bff_service import main

    events: list[str] = []
    trigger = asyncio.Event()
    failure = RuntimeError("consumer owner failed")

    async def catchup_until_interrupted(*_args: object, **_kwargs: object) -> None:
        events.append("catchup")
        trigger.set()
        await asyncio.Event().wait()

    mocker.patch.object(main, "init_jwks_verifier")
    mocker.patch.object(main, "initialize_database", new_callable=AsyncMock)
    mocker.patch.object(main, "_cleanup_expired_revocations", new_callable=AsyncMock)
    mocker.patch.object(main, "ensure_kafka_ready", new_callable=AsyncMock)
    mocker.patch.object(main.kafka_client, "ensure_producer_ready", new_callable=AsyncMock)
    mocker.patch.object(main, "get_async_sessionmaker", return_value=object())
    mocker.patch.object(main.kafka_client, "set_db_session_factory")
    mocker.patch.object(main, "init_sse_bridge", new_callable=AsyncMock)
    mocker.patch.object(main, "start_event_consumer")
    mocker.patch.object(
        main.kafka_client,
        "supervise_consumer_failures",
        side_effect=lambda: _consumer_supervision(events, failure=failure, trigger=trigger),
    )
    mocker.patch.object(
        main.kafka_client,
        "wait_for_consumer_catchup",
        side_effect=catchup_until_interrupted,
    )
    mocker.patch.object(
        main.kafka_client,
        "stop_consumers",
        side_effect=lambda: events.append("stop-consumers"),
    )
    mocker.patch.object(main, "close_sse_bridge", side_effect=lambda: events.append("close-sse"))
    mocker.patch.object(main.kafka_client, "close", side_effect=lambda: events.append("close-kafka"))
    mocker.patch.object(main.CacheFactory, "close_all", side_effect=lambda: events.append("close-redis"))
    mocker.patch.object(main, "close_all_engines", side_effect=lambda: events.append("close-database"))
    mocker.patch.object(main.obs, "shutdown", side_effect=lambda: events.append("observability"))

    with pytest.raises(ExceptionGroup) as raised:
        async with main.lifespan(main.app):
            pytest.fail("lifespan yielded readiness after fatal consumer failure")

    assert raised.value.exceptions == (failure,)
    assert events == [
        "supervision-enter",
        "catchup",
        "consumer-fatal",
        "supervision-exit",
        "stop-consumers",
        "close-sse",
        "close-kafka",
        "close-redis",
        "close-database",
        "observability",
    ]


@pytest.mark.asyncio
async def test_cleanup_expired_revocations_commits_once(mocker: MockerFixture) -> None:
    """Initial cleanup deletes and commits in one short-lived database session."""
    from bff_service import main

    session = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = session
    session_factory = MagicMock(return_value=context)
    mocker.patch.object(main, "get_async_sessionmaker", return_value=session_factory)
    delete = mocker.patch.object(main, "delete_expired_revocations", new=AsyncMock(return_value=3))

    await main._cleanup_expired_revocations()

    delete.assert_awaited_once_with(session)
    session.commit.assert_awaited_once_with()
    context.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_periodic_cleanup_waits_between_runs_and_is_cancellable(
    mocker: MockerFixture,
) -> None:
    """Periodic cleanup runs after each interval and propagates cancellation cleanly."""
    from bff_service import main

    sleep = mocker.patch.object(
        main.asyncio,
        "sleep",
        new=AsyncMock(side_effect=[None, asyncio.CancelledError]),
    )
    cleanup = mocker.patch.object(main, "_cleanup_expired_revocations", new=AsyncMock())

    with pytest.raises(asyncio.CancelledError):
        await main._run_revocation_cleanup()

    sleep.assert_awaited_with(main._REVOCATION_CLEANUP_INTERVAL_SECONDS)
    cleanup.assert_awaited_once_with()
