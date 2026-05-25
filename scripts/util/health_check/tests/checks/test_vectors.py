"""Tests for vector health checks."""

from __future__ import annotations

import json
from unittest.mock import patch

from health_check.checks.vectors.qdrant_dimensions import (
    QdrantDimensionsCheck,
    _check_vector_dim,
    _fetch_existing_collections,
)
from health_check.config.thresholds import QDRANT_PORT
from health_check.core.models import CheckStatus

from tests.conftest import MockPlatform


def _collections_response(names: list[str]) -> str:
    return json.dumps({"result": {"collections": [{"name": n} for n in names]}})


def _collection_info(vector_name: str, size: int) -> str:
    return json.dumps(
        {"result": {"config": {"params": {"vectors": {vector_name: {"size": size, "distance": "Cosine"}}}}}}
    )


_FAKE_EXPECTED: dict[str, dict[str, int]] = {
    "jobs_v1": {"muvera": 8192, "colbert": 48},
    "skills_v1": {"sparse": 30522},
}


class TestFetchExistingCollections:
    async def test_returns_collection_names(self) -> None:
        payload = _collections_response(["jobs_v1", "skills_v1"])
        platform = MockPlatform(_curl_result=(0, payload, ""))
        result = await _fetch_existing_collections(platform)
        assert result == frozenset({"jobs_v1", "skills_v1"})

    async def test_returns_none_on_curl_failure(self) -> None:
        platform = MockPlatform(_curl_result=(1, "", "connection refused"))
        result = await _fetch_existing_collections(platform)
        assert result is None

    async def test_returns_none_on_invalid_json(self) -> None:
        platform = MockPlatform(_curl_result=(0, "not-json", ""))
        result = await _fetch_existing_collections(platform)
        assert result is None

    async def test_returns_none_on_missing_result_key(self) -> None:
        platform = MockPlatform(_curl_result=(0, json.dumps({}), ""))
        result = await _fetch_existing_collections(platform)
        assert result == frozenset()

    async def test_uses_qdrant_port(self) -> None:
        calls: list[str] = []

        class _CapturePlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                calls.append(url)
                return (0, _collections_response([]), "")

        await _fetch_existing_collections(_CapturePlatform())
        assert any(str(QDRANT_PORT) in url for url in calls)


class TestCheckVectorDim:
    async def test_returns_none_when_dimensions_match(self) -> None:
        platform = MockPlatform(_curl_result=(0, _collection_info("muvera", 8192), ""))
        result = await _check_vector_dim(platform, "jobs_v1", "muvera", 8192)
        assert result is None

    async def test_returns_failure_on_mismatch(self) -> None:
        platform = MockPlatform(_curl_result=(0, _collection_info("muvera", 4096), ""))
        result = await _check_vector_dim(platform, "jobs_v1", "muvera", 8192)
        assert result is not None
        assert "jobs_v1.muvera" in result
        assert "4096" in result
        assert "8192" in result

    async def test_returns_error_on_curl_failure(self) -> None:
        platform = MockPlatform(_curl_result=(1, "", "error"))
        result = await _check_vector_dim(platform, "jobs_v1", "muvera", 8192)
        assert result is not None
        assert "cannot query" in result

    async def test_returns_failure_when_required_vector_missing_or_dimension_absent(self) -> None:
        missing = json.dumps({"result": {"config": {"params": {"vectors": {}}}}})
        result = await _check_vector_dim(MockPlatform(_curl_result=(0, missing, "")), "jobs_v1", "muvera", 8192)
        assert result == "jobs_v1.muvera: required vector missing"

        absent_size = json.dumps({"result": {"config": {"params": {"vectors": {"muvera": {"distance": "Cosine"}}}}}})
        result = await _check_vector_dim(MockPlatform(_curl_result=(0, absent_size, "")), "jobs_v1", "muvera", 8192)
        assert result is not None
        assert "dim=None" in result

    async def test_returns_error_on_invalid_json(self) -> None:
        platform = MockPlatform(_curl_result=(0, "bad-json", ""))
        result = await _check_vector_dim(platform, "jobs_v1", "muvera", 8192)
        assert result is not None
        assert "cannot parse" in result

    async def test_invalid_named_vector_schema_is_failure(self) -> None:
        info = json.dumps({"result": {"config": {"params": {"vectors": "single-unnamed"}}}})
        result = await _check_vector_dim(MockPlatform(_curl_result=(0, info, "")), "jobs_v1", "muvera", 8192)
        assert result == "jobs_v1: invalid named-vector schema"


class TestQdrantDimensionsCheck:
    def test_metadata_check_id(self) -> None:
        assert QdrantDimensionsCheck().metadata.check_id == "qdrant_dimensions"

    def test_metadata_depends_on_core_services(self) -> None:
        assert "core_services" in QdrantDimensionsCheck().metadata.depends_on

    async def test_error_when_qdrant_unreachable(self) -> None:
        platform = MockPlatform(_curl_result=(1, "", "connection refused"))
        result = await QdrantDimensionsCheck().execute(platform)
        assert result.status == CheckStatus.ERROR
        assert str(QDRANT_PORT) in result.summary

    async def test_fails_when_required_collections_are_missing(self) -> None:
        collections = _collections_response([])
        platform = MockPlatform(_curl_result=(0, collections, ""))
        with patch(
            "health_check.checks.vectors.qdrant_dimensions.load_expected_dimensions",
            return_value=_FAKE_EXPECTED,
        ):
            result = await QdrantDimensionsCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert all(f"{collection}: missing" in result.details for collection in _FAKE_EXPECTED)

    async def test_passes_when_all_dimensions_correct(self) -> None:
        present = list(_FAKE_EXPECTED.keys())

        class _CorrectDimPlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                if url.endswith("/collections"):
                    return (0, _collections_response(present), "")
                for col, vectors in _FAKE_EXPECTED.items():
                    if col in url:
                        body = {
                            "result": {
                                "config": {
                                    "params": {
                                        "vectors": {
                                            name: {"size": dim, "distance": "Cosine"} for name, dim in vectors.items()
                                        }
                                    }
                                }
                            }
                        }
                        return (0, json.dumps(body), "")
                return (0, json.dumps({"result": {"config": {"params": {"vectors": {}}}}}), "")

        with patch(
            "health_check.checks.vectors.qdrant_dimensions.load_expected_dimensions",
            return_value=_FAKE_EXPECTED,
        ):
            result = await QdrantDimensionsCheck().execute(_CorrectDimPlatform())
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_dimension_mismatch(self) -> None:
        present = ["jobs_v1"]
        wrong_dim = 4096

        class _WrongDimPlatform(MockPlatform):
            def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
                if url.endswith("/collections"):
                    return (0, _collections_response(present), "")
                return (0, _collection_info("muvera", wrong_dim), "")

        with patch(
            "health_check.checks.vectors.qdrant_dimensions.load_expected_dimensions",
            return_value={"jobs_v1": {"muvera": 8192}},
        ):
            result = await QdrantDimensionsCheck().execute(_WrongDimPlatform())
        assert result.status == CheckStatus.FAILED
        assert len(result.details) > 0
