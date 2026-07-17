"""Unit tests for QdrantInitClient."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import httpx
import pytest
from qdrant_init.client import (
    CollectionInfo,
    QdrantAPIError,
    QdrantConnectionError,
    QdrantInitClient,
)


def _make_response(status_code: int, json_data: object = None) -> MagicMock:
    """Build a mock httpx.Response with the given status code and optional JSON body."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    if json_data is not None:
        response.json.return_value = json_data
    response.text = f"HTTP {status_code}"
    return response


def _make_client(base_url: str = "http://localhost:6333") -> tuple[QdrantInitClient, MagicMock]:
    """Create a QdrantInitClient with its underlying httpx.Client replaced by a MagicMock.

    Returns both the client and the mock so tests can configure responses and
    assert call patterns.
    """
    client = QdrantInitClient(base_url)
    mock_http = MagicMock(spec=httpx.Client)
    client._client = mock_http
    return client, mock_http


class TestContextManager:
    """Tests for __enter__/__exit__ context manager protocol."""

    def test_enter_returns_self(self) -> None:
        """__enter__ must return the client itself for use in 'with' blocks."""
        client, _ = _make_client()
        result = client.__enter__()
        assert result is client

    def test_close_called_on_exit(self) -> None:
        """__exit__ must close the underlying httpx.Client."""
        client, mock_http = _make_client()
        client.__exit__(None, None, None)
        mock_http.close.assert_called_once()

    def test_context_manager_closes_on_success(self) -> None:
        """Using the client as a context manager calls close after the block."""
        client, mock_http = _make_client()
        with client:
            pass
        mock_http.close.assert_called_once()

    def test_context_manager_closes_on_exception(self) -> None:
        """close() is called even when the context block raises."""
        client, mock_http = _make_client()
        msg = "boom"
        with pytest.raises(ValueError, match=msg), client:
            raise ValueError(msg)
        mock_http.close.assert_called_once()


class TestWaitForReady:
    """Tests for the Qdrant readiness polling loop."""

    def test_success_on_first_try(self) -> None:
        """Returns immediately when Qdrant responds 200 on the first attempt."""
        client, mock_http = _make_client()
        mock_http.get.return_value = _make_response(HTTPStatus.OK)

        with patch("qdrant_init.client.time.sleep") as mock_sleep:
            client.wait_for_ready()

        mock_sleep.assert_not_called()

    def test_retries_then_succeeds(self) -> None:
        """Retries after a failed health check and eventually returns."""
        client, mock_http = _make_client()
        # First two calls fail (non-200), third succeeds
        mock_http.get.side_effect = [
            _make_response(HTTPStatus.SERVICE_UNAVAILABLE),
            _make_response(HTTPStatus.SERVICE_UNAVAILABLE),
            _make_response(HTTPStatus.OK),
        ]

        with patch("qdrant_init.client.time.sleep") as mock_sleep:
            client.wait_for_ready(max_retries=5, retry_interval=0.1)

        assert mock_sleep.call_count == 2

    def test_timeout_raises_connection_error(self) -> None:
        """Raises QdrantConnectionError when all retries are exhausted."""
        client, mock_http = _make_client()
        mock_http.get.return_value = _make_response(HTTPStatus.SERVICE_UNAVAILABLE)

        with patch("qdrant_init.client.time.sleep"), pytest.raises(QdrantConnectionError):
            client.wait_for_ready(max_retries=3, retry_interval=0.0)

        assert mock_http.get.call_count == 3

    def test_http_error_does_not_propagate(self) -> None:
        """httpx.HTTPError during health check is absorbed; retry continues."""
        client, mock_http = _make_client()
        mock_http.get.side_effect = [
            httpx.ConnectError("refused"),
            _make_response(HTTPStatus.OK),
        ]

        with patch("qdrant_init.client.time.sleep") as mock_sleep:
            client.wait_for_ready(max_retries=5, retry_interval=0.0)

        assert mock_sleep.call_count == 1


class TestCollectionExists:
    """Tests for collection existence check."""

    def test_returns_true_for_200(self) -> None:
        """HTTP 200 means the collection exists."""
        client, mock_http = _make_client()
        mock_http.get.return_value = _make_response(HTTPStatus.OK)

        assert client.collection_exists("my_collection") is True
        mock_http.get.assert_called_once_with("http://localhost:6333/collections/my_collection")

    def test_returns_false_for_404(self) -> None:
        """HTTP 404 means the collection does not exist."""
        client, mock_http = _make_client()
        mock_http.get.return_value = _make_response(HTTPStatus.NOT_FOUND)

        assert client.collection_exists("missing") is False

    def test_raises_connection_error_on_http_error(self) -> None:
        """Network errors are propagated so callers do not treat outages as absence."""
        client, mock_http = _make_client()
        mock_http.get.side_effect = httpx.ConnectError("refused")

        with pytest.raises(QdrantConnectionError):
            client.collection_exists("any")


class TestGetCollectionInfo:
    """Tests for collection metadata retrieval."""

    def test_success_parses_response(self) -> None:
        """Returns a CollectionInfo with parsed points and vectors counts."""
        client, mock_http = _make_client()
        mock_http.get.return_value = _make_response(
            HTTPStatus.OK,
            {"result": {"points_count": 42, "vectors_count": 84}},
        )

        info = client.get_collection_info("jobs_v1")

        assert info is not None
        assert info.name == "jobs_v1"
        assert info.points_count == 42
        assert info.vectors_count == 84

    def test_missing_result_fields_default_to_zero(self) -> None:
        """Missing fields in the response default to 0."""
        client, mock_http = _make_client()
        mock_http.get.return_value = _make_response(HTTPStatus.OK, {"result": {}})

        info = client.get_collection_info("jobs_v1")

        assert info is not None
        assert info.points_count == 0
        assert info.vectors_count == 0

    def test_returns_none_for_non_200(self) -> None:
        """HTTP 404 returns None rather than raising."""
        client, mock_http = _make_client()
        mock_http.get.return_value = _make_response(HTTPStatus.NOT_FOUND)

        assert client.get_collection_info("missing") is None

    def test_returns_none_on_http_error(self) -> None:
        """Network errors return None rather than propagating."""
        client, mock_http = _make_client()
        mock_http.get.side_effect = httpx.ConnectError("refused")

        assert client.get_collection_info("any") is None


class TestCreateCollection:
    """Tests for collection creation via PUT."""

    def test_success_calls_put_with_payload(self) -> None:
        """Sends a PUT to the correct URL with the given payload on HTTP 200."""
        client, mock_http = _make_client()
        mock_http.put.return_value = _make_response(HTTPStatus.OK)
        payload = {"vectors": {"dense": {"size": 1024, "distance": "Cosine"}}}

        client.create_collection("skills_v1", payload)

        mock_http.put.assert_called_once_with(
            "http://localhost:6333/collections/skills_v1",
            json=payload,
        )

    def test_non_200_raises_api_error(self) -> None:
        """HTTP error responses raise QdrantAPIError with the status code."""
        client, mock_http = _make_client()
        mock_http.put.return_value = _make_response(HTTPStatus.BAD_REQUEST)

        with pytest.raises(QdrantAPIError) as exc_info:
            client.create_collection("bad", {})

        assert exc_info.value.status_code == HTTPStatus.BAD_REQUEST


class TestDeleteCollection:
    """Tests for collection deletion."""

    def test_success_returns_true(self) -> None:
        """Returns True when Qdrant responds with HTTP 200."""
        client, mock_http = _make_client()
        mock_http.delete.return_value = _make_response(HTTPStatus.OK)

        assert client.delete_collection("jobs_v1") is True
        mock_http.delete.assert_called_once_with("http://localhost:6333/collections/jobs_v1")

    def test_not_found_returns_false(self) -> None:
        """Returns False when the collection does not exist (non-200)."""
        client, mock_http = _make_client()
        mock_http.delete.return_value = _make_response(HTTPStatus.NOT_FOUND)

        assert client.delete_collection("missing") is False


class TestListCollections:
    """Tests for listing all collections."""

    def test_parses_collection_names(self) -> None:
        """Extracts and returns name strings from the Qdrant list response."""
        client, mock_http = _make_client()
        mock_http.get.return_value = _make_response(
            HTTPStatus.OK,
            {"result": {"collections": [{"name": "jobs_v1"}, {"name": "skills_v1"}]}},
        )

        result = client.list_collections()

        assert result == ["jobs_v1", "skills_v1"]

    def test_empty_collections(self) -> None:
        """Returns an empty list when no collections exist."""
        client, mock_http = _make_client()
        mock_http.get.return_value = _make_response(
            HTTPStatus.OK,
            {"result": {"collections": []}},
        )

        assert client.list_collections() == []

    def test_non_200_returns_empty_list(self) -> None:
        """HTTP error responses return an empty list, not an exception."""
        client, mock_http = _make_client()
        mock_http.get.return_value = _make_response(HTTPStatus.INTERNAL_SERVER_ERROR)

        assert client.list_collections() == []

    def test_skips_entries_without_name(self) -> None:
        """Malformed collection entries lacking a 'name' key are silently skipped."""
        client, mock_http = _make_client()
        mock_http.get.return_value = _make_response(
            HTTPStatus.OK,
            {"result": {"collections": [{"name": "valid"}, {}]}},
        )

        result = client.list_collections()

        assert result == ["valid"]


class TestCollectionInfo:
    """Tests for the CollectionInfo dataclass."""

    def test_frozen_slots(self) -> None:
        """CollectionInfo is immutable: attribute assignment must raise."""
        assert CollectionInfo.__dataclass_params__.frozen
