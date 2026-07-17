"""HTTP client for Qdrant REST API operations."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Self
from urllib.parse import quote

import httpx
import structlog

if TYPE_CHECKING:
    from types import TracebackType

logger = structlog.get_logger(__name__)

DEFAULT_TIMEOUT: Final[float] = 30.0
DEFAULT_MAX_RETRIES: Final[int] = 30
DEFAULT_RETRY_INTERVAL: Final[float] = 2.0
MAX_RETRIES: Final[int] = 300
MAX_RETRY_INTERVAL: Final[float] = 60.0


@dataclass(frozen=True, slots=True)
class CollectionInfo:
    """Information about a Qdrant collection."""

    name: str
    points_count: int
    vectors_count: int


class QdrantConnectionError(Exception):
    """Raised when Qdrant is not reachable."""


class QdrantAPIError(Exception):
    """Raised when Qdrant API returns an error."""

    def __init__(self, status_code: int, message: str) -> None:
        """Initialize with status code and message."""
        super().__init__(f"Qdrant API error (HTTP {status_code}): {message}")
        self.status_code = status_code


class QdrantInitClient:
    """HTTP client for Qdrant collection initialization."""

    def __init__(self, base_url: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Initialize the client with a validated base URL and timeout."""
        url = httpx.URL(base_url)
        if url.scheme not in {"http", "https"} or not url.host:
            msg = "Qdrant URL must be an absolute HTTP(S) URL"
            raise ValueError(msg)
        if url.username or url.password or url.query or url.fragment:
            msg = "Qdrant URL must not contain credentials, a query, or a fragment"
            raise ValueError(msg)
        if not math.isfinite(timeout) or timeout <= 0:
            msg = "timeout must be a positive finite number"
            raise ValueError(msg)

        self._base_url = str(url).rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> Self:
        """Enter context manager."""
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        """Exit context manager and close client."""
        self.close()

    def _collection_url(self, name: str) -> str:
        """Build a path-safe URL for a non-empty collection name."""
        if not name:
            msg = "collection name must not be empty"
            raise ValueError(msg)
        return f"{self._base_url}/collections/{quote(name, safe='')}"

    def wait_for_ready(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_interval: float = DEFAULT_RETRY_INTERVAL,
    ) -> None:
        """Wait for Qdrant to become available."""
        if not 1 <= max_retries <= MAX_RETRIES:
            msg = f"max_retries must be between 1 and {MAX_RETRIES}"
            raise ValueError(msg)
        if not math.isfinite(retry_interval) or not 0 <= retry_interval <= MAX_RETRY_INTERVAL:
            msg = f"retry_interval must be between 0 and {MAX_RETRY_INTERVAL} seconds"
            raise ValueError(msg)
        logger.info("waiting_for_qdrant", url=self._base_url)

        for attempt in range(1, max_retries + 1):
            if self._check_health():
                logger.info("qdrant_ready")
                return

            logger.debug(
                "qdrant_not_ready",
                attempt=attempt,
                max_retries=max_retries,
                retry_interval=retry_interval,
            )
            if attempt < max_retries:
                time.sleep(retry_interval)

        msg = f"Qdrant not available after {max_retries} attempts"
        raise QdrantConnectionError(msg)

    def _check_health(self) -> bool:
        """Check if Qdrant is healthy."""
        try:
            response = self._client.get(f"{self._base_url}/collections")
        except httpx.HTTPError:
            return False
        else:
            return response.status_code == HTTPStatus.OK

    def collection_exists(self, name: str) -> bool:
        """Check if a collection exists."""
        try:
            response = self._client.get(self._collection_url(name))
        except httpx.HTTPError as exc:
            msg = f"Failed to check Qdrant collection {name!r}"
            raise QdrantConnectionError(msg) from exc

        if response.status_code == HTTPStatus.NOT_FOUND:
            return False
        if response.status_code != HTTPStatus.OK:
            raise QdrantAPIError(response.status_code, response.text)
        return True

    def get_collection_info(self, name: str) -> CollectionInfo | None:
        """Get information about a collection."""
        try:
            response = self._client.get(self._collection_url(name))
            if response.status_code != HTTPStatus.OK:
                return None

            data = response.json()
            result = data.get("result", {})
            return CollectionInfo(
                name=name,
                points_count=result.get("points_count", 0),
                vectors_count=result.get("vectors_count", 0),
            )
        except httpx.HTTPError:
            return None

    def create_collection(self, name: str, payload: Mapping[str, object]) -> None:
        """Create a Qdrant collection."""
        try:
            response = self._client.put(
                self._collection_url(name),
                json=payload,
            )
        except httpx.HTTPError as exc:
            msg = f"Failed to create Qdrant collection {name!r}"
            raise QdrantConnectionError(msg) from exc

        if response.status_code != HTTPStatus.OK:
            raise QdrantAPIError(response.status_code, response.text)

    def delete_collection(self, name: str) -> bool:
        """Delete a Qdrant collection. Returns True if deleted, False if not found."""
        try:
            response = self._client.delete(self._collection_url(name))
        except httpx.HTTPError as exc:
            msg = f"Failed to delete Qdrant collection {name!r}"
            raise QdrantConnectionError(msg) from exc

        if response.status_code == HTTPStatus.NOT_FOUND:
            return False
        if response.status_code != HTTPStatus.OK:
            raise QdrantAPIError(response.status_code, response.text)
        return True

    def list_collections(self) -> list[str]:
        """List all collection names."""
        response = self._client.get(f"{self._base_url}/collections")
        if response.status_code != HTTPStatus.OK:
            return []

        data = response.json()
        collections = data.get("result", {}).get("collections", [])
        return [c.get("name", "") for c in collections if c.get("name")]
