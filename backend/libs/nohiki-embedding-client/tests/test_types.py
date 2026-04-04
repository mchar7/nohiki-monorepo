"""Tests for nohiki_embedding_client.types module."""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

import pytest
from nohiki.common.v1 import CallbackHeader, ErrorInfo
from nohiki.ml.v1 import (
    BatchEmbeddingResultItem,
    DenseData,
    EmbeddingCallback,
    EmbeddingType,
    EmbeddingVector,
    EncodingMode,
    EntityType,
    MultiVectorData,
    SparseData,
)
from nohiki.ml.v1 import (
    EmbeddingResult as ProtoEmbeddingResult,
)
from nohiki_embedding_client.types import BatchEmbeddingItemResult, EmbeddingResult, EmbeddingSpec


def _make_dense_vector(
    values: list[float] | None = None,
    content_hash: str = "a" * 64,
) -> EmbeddingVector:
    """Create a DENSE EmbeddingVector for testing."""
    return EmbeddingVector(
        embedding_type=EmbeddingType.DENSE,
        dense=DenseData(values=values or [0.1, 0.2, 0.3]),
        content_hash=content_hash,
        collection_version="v1",
    )


def _make_muvera_vector(
    values: list[float] | None = None,
    content_hash: str = "a" * 64,
) -> EmbeddingVector:
    """Create a MUVERA EmbeddingVector for testing."""
    return EmbeddingVector(
        embedding_type=EmbeddingType.MUVERA,
        dense=DenseData(values=values or [0.1] * 100),
        content_hash=content_hash,
        collection_version="v1",
    )


def _make_sparse_vector(
    content_hash: str = "a" * 64,
) -> EmbeddingVector:
    """Create a SPARSE EmbeddingVector for testing."""
    return EmbeddingVector(
        embedding_type=EmbeddingType.SPARSE,
        sparse=SparseData(indices=[1, 5, 10], values=[0.5, 0.3, 0.2]),
        content_hash=content_hash,
        collection_version="v1",
    )


def _make_colbert_vector(
    content_hash: str = "a" * 64,
) -> EmbeddingVector:
    """Create a COLBERT EmbeddingVector for testing."""
    return EmbeddingVector(
        embedding_type=EmbeddingType.COLBERT,
        multi_vector=MultiVectorData(values=[0.1] * 96, num_tokens=2, token_dim=48),
        content_hash=content_hash,
        collection_version="v1",
    )


def _make_callback_header(
    operation_id: str = "550e8400-e29b-41d4-a716-446655440000",
) -> CallbackHeader:
    """Create a CallbackHeader for testing."""
    return CallbackHeader(operation_id=operation_id)


def _make_embedding_callback(
    *,
    entity_id: str = "skill-123",
    entity_type: EntityType = EntityType.SKILL,
    embeddings: list[EmbeddingVector] | None = None,
    content_hash: str = "a" * 64,
    collection_version: str = "v1",
    encoding_mode: EncodingMode = EncodingMode.DOCUMENT,
    requested_types: list[EmbeddingType] | None = None,
) -> EmbeddingCallback:
    """Create an EmbeddingCallback with success payload for testing."""
    if embeddings is None:
        embeddings = [_make_dense_vector()]
    return EmbeddingCallback(
        metadata=MagicMock(),
        callback=_make_callback_header(),
        entity_id=entity_id,
        entity_type=entity_type,
        success=ProtoEmbeddingResult(
            collection_version=collection_version,
            content_hash=content_hash,
            requested_types=(
                requested_types
                if requested_types is not None
                else [embedding.embedding_type for embedding in embeddings]
            ),
            encoding_mode=encoding_mode,
            embeddings=embeddings,
        ),
    )


class TestEmbeddingSpec:
    """Tests for EmbeddingSpec dataclass."""

    def test_custom_values(self) -> None:
        """EmbeddingSpec preserves custom values."""
        spec = EmbeddingSpec(
            requested_types=[EmbeddingType.MUVERA, EmbeddingType.SPARSE],
            encoding_mode=EncodingMode.QUERY,
            publish_to_index=True,
        )

        assert spec.requested_types == [EmbeddingType.MUVERA, EmbeddingType.SPARSE]
        assert spec.encoding_mode == EncodingMode.QUERY
        assert spec.publish_to_index is True

    def test_frozen(self) -> None:
        """EmbeddingSpec is immutable."""
        assert dataclasses.is_dataclass(EmbeddingSpec)
        params = getattr(EmbeddingSpec, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestEmbeddingResult:
    """Tests for EmbeddingResult dataclass."""

    def test_basic_creation_with_dense(self) -> None:
        """Basic EmbeddingResult creation with a single DENSE vector."""
        dense_vec = _make_dense_vector()
        result = EmbeddingResult(
            embeddings=[dense_vec],
            entity_id="entity-456",
            entity_type=EntityType.JOB,
            collection_version="v1",
            content_hash="a" * 64,
            encoding_mode=EncodingMode.DOCUMENT,
        )

        assert result.entity_id == "entity-456"
        assert result.entity_type == EntityType.JOB
        assert result.collection_version == "v1"
        assert len(result.embeddings) == 1

    def test_get_dense(self) -> None:
        """get_dense retrieves the DENSE embedding vector."""
        dense_vec = _make_dense_vector(values=[0.1, 0.2, 0.3])
        result = EmbeddingResult(
            embeddings=[dense_vec],
            entity_id="skill-789",
            entity_type=EntityType.SKILL,
            collection_version="v1",
            content_hash="a" * 64,
            encoding_mode=EncodingMode.DOCUMENT,
        )

        found = result.get_dense()
        assert found is not None
        assert found.dense is not None
        assert len(found.dense.values) == 3

    def test_get_muvera(self) -> None:
        """get_muvera retrieves the MUVERA embedding vector."""
        muvera_vec = _make_muvera_vector()
        result = EmbeddingResult(
            embeddings=[muvera_vec],
            entity_id="job-456",
            entity_type=EntityType.JOB,
            collection_version="v1",
            content_hash="a" * 64,
            encoding_mode=EncodingMode.DOCUMENT,
        )

        found = result.get_muvera()
        assert found is not None
        assert found.embedding_type == EmbeddingType.MUVERA

    def test_get_sparse(self) -> None:
        """get_sparse retrieves the SPARSE embedding vector."""
        sparse_vec = _make_sparse_vector()
        result = EmbeddingResult(
            embeddings=[sparse_vec],
            entity_id="job-456",
            entity_type=EntityType.JOB,
            collection_version="v1",
            content_hash="a" * 64,
            encoding_mode=EncodingMode.DOCUMENT,
        )

        found = result.get_sparse()
        assert found is not None
        assert found.sparse is not None
        assert list(found.sparse.indices) == [1, 5, 10]

    def test_get_colbert(self) -> None:
        """get_colbert retrieves the COLBERT embedding vector."""
        colbert_vec = _make_colbert_vector()
        result = EmbeddingResult(
            embeddings=[colbert_vec],
            entity_id="job-456",
            entity_type=EntityType.JOB,
            collection_version="v1",
            content_hash="a" * 64,
            encoding_mode=EncodingMode.DOCUMENT,
        )

        found = result.get_colbert()
        assert found is not None
        assert found.multi_vector is not None
        assert found.multi_vector.num_tokens == 2
        assert found.multi_vector.token_dim == 48

    def test_get_by_type_returns_none_when_missing(self) -> None:
        """get_by_type returns None when type not present."""
        dense_vec = _make_dense_vector()
        result = EmbeddingResult(
            embeddings=[dense_vec],
            entity_id="entity-456",
            entity_type=EntityType.JOB,
            collection_version="v1",
            content_hash="a" * 64,
            encoding_mode=EncodingMode.DOCUMENT,
        )

        assert result.get_muvera() is None
        assert result.get_sparse() is None
        assert result.get_colbert() is None

    def test_multiple_embeddings(self) -> None:
        """EmbeddingResult with multiple embedding types."""
        result = EmbeddingResult(
            embeddings=[
                _make_muvera_vector(),
                _make_sparse_vector(),
                _make_colbert_vector(),
            ],
            entity_id="job-456",
            entity_type=EntityType.JOB,
            collection_version="v1",
            content_hash="a" * 64,
            encoding_mode=EncodingMode.DOCUMENT,
        )

        assert len(result.embeddings) == 3
        assert result.get_muvera() is not None
        assert result.get_sparse() is not None
        assert result.get_colbert() is not None
        assert result.get_dense() is None

    def test_from_callback_success(self) -> None:
        """from_callback creates EmbeddingResult from success callback."""
        dense_vec = _make_dense_vector()
        callback = _make_embedding_callback(
            entity_id="skill-123",
            entity_type=EntityType.SKILL,
            embeddings=[dense_vec],
            content_hash="a" * 64,
        )

        result = EmbeddingResult.from_callback(callback)

        assert result.entity_id == "skill-123"
        assert result.entity_type == EntityType.SKILL
        assert result.content_hash == "a" * 64
        assert result.collection_version == "v1"
        assert result.encoding_mode == EncodingMode.DOCUMENT
        assert len(result.embeddings) == 1
        assert result.get_dense() is not None

    def test_from_callback_with_multiple_embeddings(self) -> None:
        """from_callback with multiple embedding types."""
        callback = _make_embedding_callback(
            entity_id="job-456",
            entity_type=EntityType.JOB,
            embeddings=[
                _make_muvera_vector(content_hash="b" * 64),
                _make_sparse_vector(content_hash="b" * 64),
                _make_colbert_vector(content_hash="b" * 64),
            ],
            content_hash="b" * 64,
        )

        result = EmbeddingResult.from_callback(callback)

        assert len(result.embeddings) == 3
        assert result.get_muvera() is not None
        assert result.get_sparse() is not None
        assert result.get_colbert() is not None

    @pytest.mark.parametrize(
        ("embeddings", "requested_types", "error"),
        [
            ([], [EmbeddingType.DENSE], "at least one embedding"),
            ([_make_dense_vector()], [EmbeddingType.DENSE, EmbeddingType.SPARSE], "do not match"),
            ([_make_dense_vector(), _make_sparse_vector()], [EmbeddingType.DENSE], "do not match"),
            ([_make_dense_vector()], [EmbeddingType.DENSE, EmbeddingType.DENSE], "must be unique"),
            ([_make_dense_vector(), _make_dense_vector()], [EmbeddingType.DENSE], "Duplicate embedding type"),
        ],
        ids=["empty", "missing", "extra", "duplicate-request", "duplicate-result"],
    )
    def test_from_callback_rejects_inconsistent_outputs(
        self,
        embeddings: list[EmbeddingVector],
        requested_types: list[EmbeddingType],
        error: str,
    ) -> None:
        """Every requested geometry must appear exactly once in a successful callback."""
        callback = _make_embedding_callback(embeddings=embeddings, requested_types=requested_types)

        with pytest.raises(ValueError, match=error):
            EmbeddingResult.from_callback(callback)

    @pytest.mark.parametrize(
        "embedding",
        [
            EmbeddingVector(
                embedding_type=EmbeddingType.DENSE,
                dense=DenseData(values=[]),
                content_hash="a" * 64,
                collection_version="v1",
            ),
            _make_dense_vector(values=[float("nan")]),
            _make_muvera_vector(values=[float("inf")]),
            EmbeddingVector(
                embedding_type=EmbeddingType.SPARSE,
                sparse=SparseData(indices=[1, 2], values=[0.5]),
                content_hash="a" * 64,
                collection_version="v1",
            ),
            EmbeddingVector(
                embedding_type=EmbeddingType.SPARSE,
                sparse=SparseData(indices=[1, 1], values=[0.5, 0.3]),
                content_hash="a" * 64,
                collection_version="v1",
            ),
            EmbeddingVector(
                embedding_type=EmbeddingType.SPARSE,
                sparse=SparseData(indices=[1], values=[float("-inf")]),
                content_hash="a" * 64,
                collection_version="v1",
            ),
            EmbeddingVector(
                embedding_type=EmbeddingType.COLBERT,
                multi_vector=MultiVectorData(values=[0.1] * 95, num_tokens=2, token_dim=48),
                content_hash="a" * 64,
                collection_version="v1",
            ),
            EmbeddingVector(
                embedding_type=EmbeddingType.COLBERT,
                multi_vector=MultiVectorData(values=[float("nan")], num_tokens=1, token_dim=1),
                content_hash="a" * 64,
                collection_version="v1",
            ),
        ],
        ids=[
            "empty-dense",
            "nonfinite-dense",
            "nonfinite-muvera",
            "sparse-length-mismatch",
            "duplicate-sparse-index",
            "nonfinite-sparse",
            "colbert-shape",
            "nonfinite-colbert",
        ],
    )
    def test_from_callback_rejects_malformed_vectors(self, embedding: EmbeddingVector) -> None:
        """Malformed geometry never crosses the callback decoding boundary."""
        callback = _make_embedding_callback(embeddings=[embedding])

        with pytest.raises(ValueError, match="Malformed"):
            EmbeddingResult.from_callback(callback)

    @pytest.mark.parametrize("content_hash", ["a" * 63, "A" * 64, "g" * 64], ids=["short", "uppercase", "nonhex"])
    @pytest.mark.parametrize("hash_target", ["result", "vector"])
    def test_from_callback_rejects_noncanonical_hashes(self, content_hash: str, hash_target: str) -> None:
        """Callback and vector hashes must use canonical lowercase SHA-256 text."""
        vector = _make_dense_vector(content_hash=content_hash if hash_target == "vector" else "a" * 64)
        callback = _make_embedding_callback(
            embeddings=[vector],
            content_hash=content_hash if hash_target == "result" else "a" * 64,
        )

        with pytest.raises(ValueError, match="lowercase SHA-256"):
            EmbeddingResult.from_callback(callback)

    def test_from_callback_error_raises_value_error(self) -> None:
        """from_callback raises ValueError when callback has error, not success."""
        callback = EmbeddingCallback(
            metadata=MagicMock(),
            callback=_make_callback_header(),
            entity_id="skill-123",
            entity_type=EntityType.SKILL,
            error=ErrorInfo(
                error_code="PIPELINE_ERROR",
                error_message="test failure",
                retryable=False,
            ),
        )

        with pytest.raises(ValueError, match="is not a success"):
            EmbeddingResult.from_callback(callback)

    def test_is_frozen_dataclass(self) -> None:
        """EmbeddingResult is a frozen dataclass."""
        assert dataclasses.is_dataclass(EmbeddingResult)
        params = getattr(EmbeddingResult, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestBatchEmbeddingItemResult:
    """Tests for BatchEmbeddingItemResult dataclass."""

    def test_from_result_item(self) -> None:
        """from_result_item creates BatchEmbeddingItemResult from proto."""
        dense_vec = _make_dense_vector()
        proto_item = BatchEmbeddingResultItem(
            point_id="skill-1_label",
            entity_id="skill-1",
            embeddings=[dense_vec],
            content_hash="c" * 64,
            item_attributes={"variant": "label"},
        )

        result = BatchEmbeddingItemResult.from_result_item(proto_item)

        assert result.point_id == "skill-1_label"
        assert result.entity_id == "skill-1"
        assert len(result.embeddings) == 1
        assert result.content_hash == "c" * 64
        assert result.item_attributes == {"variant": "label"}

    def test_from_result_item_empty_attributes(self) -> None:
        """from_result_item with empty item_attributes."""
        proto_item = BatchEmbeddingResultItem(
            point_id="p1",
            entity_id="e1",
            embeddings=[_make_dense_vector()],
            content_hash="d" * 64,
        )

        result = BatchEmbeddingItemResult.from_result_item(proto_item)

        assert result.item_attributes == {}

    @pytest.mark.parametrize(
        ("content_hash", "embeddings", "error"),
        [
            ("A" * 64, [_make_dense_vector()], "lowercase SHA-256"),
            ("a" * 64, [_make_dense_vector(values=[float("inf")])], "Malformed"),
        ],
        ids=["item-hash", "item-vector"],
    )
    def test_from_result_item_rejects_malformed_payload(
        self,
        content_hash: str,
        embeddings: list[EmbeddingVector],
        error: str,
    ) -> None:
        """Batch item decoding enforces the same hash and geometry boundary."""
        item = BatchEmbeddingResultItem(
            point_id="point-1",
            entity_id="entity-1",
            embeddings=embeddings,
            content_hash=content_hash,
        )

        with pytest.raises(ValueError, match=error):
            BatchEmbeddingItemResult.from_result_item(item)

    def test_get_dense(self) -> None:
        """get_dense on BatchEmbeddingItemResult."""
        result = BatchEmbeddingItemResult(
            point_id="p1",
            entity_id="e1",
            embeddings=[_make_dense_vector()],
            content_hash="a" * 64,
        )

        assert result.get_dense() is not None

    def test_is_frozen_dataclass(self) -> None:
        """BatchEmbeddingItemResult is a frozen dataclass."""
        assert dataclasses.is_dataclass(BatchEmbeddingItemResult)
        params = getattr(BatchEmbeddingItemResult, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True
