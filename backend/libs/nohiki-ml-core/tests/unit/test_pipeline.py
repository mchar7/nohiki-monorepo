"""Unit tests for MLEncodingPipeline."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from nohiki_ml_core.encoders.sparse import SparseVector
from nohiki_ml_core.pipeline import (
    DenseEncodingResult,
    EncodingResult,
    MLEncodingPipeline,
)
from nohiki_ml_manifest import SemanticRepresentationManifest


@pytest.fixture
def manifest(sample_manifest_data: dict) -> SemanticRepresentationManifest:
    """Create manifest from sample data."""
    return SemanticRepresentationManifest(**sample_manifest_data)


@pytest.fixture
def mock_encoders() -> dict[str, MagicMock]:
    """Create mock encoders that return realistic numpy arrays."""
    rng = np.random.default_rng(42)

    colbert = MagicMock()
    colbert.encode_document.return_value = rng.standard_normal((20, 48)).astype(np.float32)
    colbert.encode_query.return_value = rng.standard_normal((10, 48)).astype(np.float32)
    colbert.warm_up = MagicMock()

    muvera = MagicMock()
    muvera.encode.return_value = rng.standard_normal(8192).astype(np.float32)

    sparse = MagicMock()
    sparse.encode.return_value = SparseVector(indices=[1, 5, 42], values=[0.8, 0.3, 0.1])
    sparse.warm_up = MagicMock()

    dense = MagicMock()
    dense.encode.return_value = rng.standard_normal(1024).astype(np.float32)

    return {"colbert": colbert, "muvera": muvera, "sparse": sparse, "dense": dense}


@pytest.fixture
def pipeline(
    manifest: SemanticRepresentationManifest,
    mock_encoders: dict[str, MagicMock],
) -> MLEncodingPipeline:
    """Create pipeline with mocked encoders injected post-construction."""
    with (
        patch("nohiki_ml_core.pipeline.ColBERTEncoder"),
        patch("nohiki_ml_core.pipeline.MUVERAEncoder"),
        patch("nohiki_ml_core.pipeline.SparseEncoder"),
        patch("nohiki_ml_core.pipeline.DenseEncoder"),
    ):
        pipe = MLEncodingPipeline(manifest)
    pipe.colbert = mock_encoders["colbert"]
    pipe.muvera = mock_encoders["muvera"]
    pipe.sparse = mock_encoders["sparse"]
    pipe.dense = mock_encoders["dense"]
    return pipe


class TestMLEncodingPipelineInit:
    """Tests for pipeline initialization."""

    def test_has_all_encoder_attributes(
        self,
        pipeline: MLEncodingPipeline,
    ) -> None:
        """Pipeline exposes colbert, muvera, sparse, and dense encoder attributes."""
        assert hasattr(pipeline, "colbert")
        assert hasattr(pipeline, "muvera")
        assert hasattr(pipeline, "sparse")
        assert hasattr(pipeline, "dense")

    def test_stores_manifest(
        self,
        pipeline: MLEncodingPipeline,
        manifest: SemanticRepresentationManifest,
    ) -> None:
        """Pipeline stores the manifest reference."""
        assert pipeline.manifest is manifest


class TestEncodeDocument:
    """Tests for encode_document method."""

    def test_returns_encoding_result(
        self,
        pipeline: MLEncodingPipeline,
    ) -> None:
        """encode_document returns an EncodingResult dataclass."""
        result = pipeline.encode_document("Test document text", entity_id="doc-1")
        assert isinstance(result, EncodingResult)

    def test_calls_colbert_encode_document(
        self,
        pipeline: MLEncodingPipeline,
        mock_encoders: dict[str, MagicMock],
    ) -> None:
        """encode_document delegates to ColBERT encoder for token generation."""
        pipeline.encode_document("Test document text", entity_id="doc-1")
        mock_encoders["colbert"].encode_document.assert_called_once_with("Test document text")

    def test_calls_muvera_with_colbert_tokens(
        self,
        pipeline: MLEncodingPipeline,
        mock_encoders: dict[str, MagicMock],
    ) -> None:
        """encode_document passes ColBERT tokens to MUVERA with is_query=False."""
        pipeline.encode_document("Test document text", entity_id="doc-1")
        call_args = mock_encoders["muvera"].encode.call_args
        np.testing.assert_array_equal(
            call_args.args[0],
            mock_encoders["colbert"].encode_document.return_value,
        )
        assert call_args.kwargs["is_query"] is False

    def test_calls_sparse_encoder(
        self,
        pipeline: MLEncodingPipeline,
        mock_encoders: dict[str, MagicMock],
    ) -> None:
        """encode_document delegates to sparse encoder for sparse vector."""
        pipeline.encode_document("Test document text", entity_id="doc-1")
        mock_encoders["sparse"].encode.assert_called_once_with("Test document text")

    def test_result_contains_correct_artifacts(
        self,
        pipeline: MLEncodingPipeline,
        mock_encoders: dict[str, MagicMock],
    ) -> None:
        """EncodingResult contains all three embedding types and content hash."""
        result = pipeline.encode_document("Test document text", entity_id="doc-1")

        np.testing.assert_array_equal(
            result.colbert_tokens,
            mock_encoders["colbert"].encode_document.return_value,
        )
        np.testing.assert_array_equal(
            result.muvera_fde,
            mock_encoders["muvera"].encode.return_value,
        )
        assert result.sparse_vector == mock_encoders["sparse"].encode.return_value
        assert isinstance(result.content_hash, str)
        assert len(result.content_hash) == 64  # SHA-256 hex digest

    def test_content_hash_is_deterministic(
        self,
        pipeline: MLEncodingPipeline,
    ) -> None:
        """Same text produces same content hash."""
        r1 = pipeline.encode_document("Same text", entity_id="a")
        r2 = pipeline.encode_document("Same text", entity_id="b")
        assert r1.content_hash == r2.content_hash

    def test_content_hash_normalizes_whitespace_and_case(
        self,
        pipeline: MLEncodingPipeline,
    ) -> None:
        """Content hash normalizes by stripping whitespace and lowercasing."""
        r1 = pipeline.encode_document("  Hello World  ", entity_id="a")
        r2 = pipeline.encode_document("hello world", entity_id="b")
        assert r1.content_hash == r2.content_hash


class TestEncodeQuery:
    """Tests for encode_query method."""

    def test_returns_encoding_result(
        self,
        pipeline: MLEncodingPipeline,
    ) -> None:
        """encode_query returns an EncodingResult dataclass (same type as encode_document)."""
        result = pipeline.encode_query("python developer")
        assert isinstance(result, EncodingResult)

    def test_calls_colbert_encode_query(
        self,
        pipeline: MLEncodingPipeline,
        mock_encoders: dict[str, MagicMock],
    ) -> None:
        """encode_query uses asymmetric query encoding via ColBERT."""
        pipeline.encode_query("python developer")
        mock_encoders["colbert"].encode_query.assert_called_once_with("python developer")

    def test_calls_muvera_with_is_query_true(
        self,
        pipeline: MLEncodingPipeline,
        mock_encoders: dict[str, MagicMock],
    ) -> None:
        """encode_query passes ColBERT tokens to MUVERA with is_query=True (SUM aggregation)."""
        pipeline.encode_query("python developer")
        call_args = mock_encoders["muvera"].encode.call_args
        np.testing.assert_array_equal(
            call_args.args[0],
            mock_encoders["colbert"].encode_query.return_value,
        )
        assert call_args.kwargs["is_query"] is True

    def test_result_contains_all_artifacts(
        self,
        pipeline: MLEncodingPipeline,
        mock_encoders: dict[str, MagicMock],
    ) -> None:
        """EncodingResult contains ColBERT tokens, MUVERA FDE, sparse vector, and hash."""
        result = pipeline.encode_query("python developer")

        np.testing.assert_array_equal(
            result.colbert_tokens,
            mock_encoders["colbert"].encode_query.return_value,
        )
        np.testing.assert_array_equal(
            result.muvera_fde,
            mock_encoders["muvera"].encode.return_value,
        )
        assert result.sparse_vector == mock_encoders["sparse"].encode.return_value
        assert len(result.content_hash) == 64


class TestEncodeDense:
    """Tests for encode_dense method."""

    def test_returns_dense_encoding_result(
        self,
        pipeline: MLEncodingPipeline,
    ) -> None:
        """encode_dense returns a DenseEncodingResult dataclass."""
        result = pipeline.encode_dense("Software Engineer", entity_id="skill-1")
        assert isinstance(result, DenseEncodingResult)

    def test_calls_dense_encoder(
        self,
        pipeline: MLEncodingPipeline,
        mock_encoders: dict[str, MagicMock],
    ) -> None:
        """encode_dense delegates to the dense encoder."""
        pipeline.encode_dense("Software Engineer", entity_id="skill-1")
        mock_encoders["dense"].encode.assert_called_once_with("Software Engineer")

    def test_result_contains_embedding_and_hash(
        self,
        pipeline: MLEncodingPipeline,
        mock_encoders: dict[str, MagicMock],
    ) -> None:
        """DenseEncodingResult contains the dense embedding and content hash."""
        result = pipeline.encode_dense("Software Engineer", entity_id="skill-1")

        np.testing.assert_array_equal(
            result.dense_embedding,
            mock_encoders["dense"].encode.return_value,
        )
        assert len(result.content_hash) == 64

    def test_does_not_call_colbert_or_muvera(
        self,
        pipeline: MLEncodingPipeline,
        mock_encoders: dict[str, MagicMock],
    ) -> None:
        """encode_dense only uses the dense encoder, not ColBERT/MUVERA/sparse."""
        pipeline.encode_dense("Software Engineer", entity_id="skill-1")
        mock_encoders["colbert"].encode_document.assert_not_called()
        mock_encoders["colbert"].encode_query.assert_not_called()
        mock_encoders["muvera"].encode.assert_not_called()
        mock_encoders["sparse"].encode.assert_not_called()


class TestComputeContentHash:
    """Tests for _compute_content_hash method."""

    def test_produces_sha256_hex(
        self,
        pipeline: MLEncodingPipeline,
    ) -> None:
        """Hash is a valid SHA-256 hex digest."""
        result = pipeline._compute_content_hash("test")
        expected = hashlib.sha256(b"test").hexdigest()
        assert result == expected

    def test_strips_and_lowercases(
        self,
        pipeline: MLEncodingPipeline,
    ) -> None:
        """Hash normalizes by stripping whitespace and lowercasing."""
        assert pipeline._compute_content_hash("  HELLO  ") == pipeline._compute_content_hash("hello")

    def test_different_text_different_hash(
        self,
        pipeline: MLEncodingPipeline,
    ) -> None:
        """Different normalized text produces different hashes."""
        assert pipeline._compute_content_hash("foo") != pipeline._compute_content_hash("bar")


class TestDataclasses:
    """Tests for result dataclass construction and immutability."""

    def test_encoding_result_is_frozen(self) -> None:
        """EncodingResult is immutable."""
        import dataclasses

        assert dataclasses.is_dataclass(EncodingResult)
        params = getattr(EncodingResult, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_dense_encoding_result_is_frozen(self) -> None:
        """DenseEncodingResult is immutable."""
        import dataclasses

        assert dataclasses.is_dataclass(DenseEncodingResult)
        params = getattr(DenseEncodingResult, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True
