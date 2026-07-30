"""Unit tests for DenseEncoder."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from nohiki_ml_core._deps import LocalDependency, MissingLocalDependencyError
from nohiki_ml_core.encoders.dense import DenseEncoder
from nohiki_ml_manifest import (
    DenseConfig,
    InferenceBackend,
    SemanticRepresentationManifest,
)


class TestDenseEncoderInitialization:
    """Tests for DenseEncoder initialization."""

    def test_initialization_with_direct_backend(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test initialization with DIRECT backend."""
        manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
        encoder = DenseEncoder(manifest)

        assert encoder.model_id == "TechWolf/JobBERT-v2"
        assert encoder.embedding_dim == 1024
        assert encoder.max_length == 64
        assert encoder._backend == InferenceBackend.DIRECT

    def test_initialization_with_tei_backend(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test initialization with TEI backend."""
        manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
        manifest.dense = DenseConfig(
            enabled=True,
            model_id="TechWolf/JobBERT-v2",
            embedding_dim=1024,
            max_length=64,
            inference_backend=InferenceBackend.TEI,
            tei_endpoint="http://localhost:8080",
            tei_timeout_seconds=30,
        )
        encoder = DenseEncoder(manifest)

        assert encoder._tei_endpoint == "http://localhost:8080"
        assert encoder._tei_timeout == 30

    def test_initialization_with_onnx_backend(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test initialization with ONNX backend."""
        with patch("nohiki_ml_core.encoders.dense._create_sentence_transformer") as mock_st:
            manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
            manifest.dense = DenseConfig(
                enabled=True,
                model_id="TechWolf/JobBERT-v2",
                embedding_dim=1024,
                max_length=64,
                inference_backend=InferenceBackend.ONNX,
                onnx_file_name="model.onnx",
            )
            encoder = DenseEncoder(manifest)
            encoder._ensure_model()

            assert encoder._backend == InferenceBackend.ONNX
            mock_st.assert_called_once_with(
                "TechWolf/JobBERT-v2",
                backend="onnx",
                trust_remote_code=False,
                model_kwargs={"file_name": "model.onnx"},
                device="cpu",
            )

    def test_tei_backend_requires_endpoint(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test TEI backend requires endpoint."""
        manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
        manifest.dense = DenseConfig(
            enabled=True,
            model_id="TechWolf/JobBERT-v2",
            embedding_dim=1024,
            max_length=64,
            inference_backend=InferenceBackend.TEI,
        )

        with pytest.raises(ValueError, match="TEI endpoint required"):
            DenseEncoder(manifest)

    def test_onnx_backend_requires_file_name(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test ONNX backend requires onnx_file_name."""
        manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
        manifest.dense = DenseConfig(
            enabled=True,
            model_id="TechWolf/JobBERT-v2",
            embedding_dim=1024,
            max_length=64,
            inference_backend=InferenceBackend.ONNX,
        )

        with pytest.raises(ValueError, match="onnx_file_name required"):
            DenseEncoder(manifest)


class TestDenseEncoderEncode:
    """Tests for DenseEncoder encoding methods."""

    def test_encode_with_direct_backend(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test encoding with DIRECT backend."""
        with patch("nohiki_ml_core.encoders.dense._create_sentence_transformer") as mock_st:
            manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
            encoder = DenseEncoder(manifest)

            mock_model = MagicMock()
            rng = np.random.default_rng(42)
            mock_model.encode.return_value = rng.random(1024).astype(np.float32)
            mock_st.return_value = mock_model

            result = encoder.encode("Software Engineer")

            assert isinstance(result, np.ndarray)
            assert result.shape == (1024,)
            assert result.dtype == np.float32
            mock_st.assert_called_once()

    def test_encode_batch_with_direct_backend(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test batch encoding with DIRECT backend."""
        with patch("nohiki_ml_core.encoders.dense._create_sentence_transformer") as mock_st:
            manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
            encoder = DenseEncoder(manifest)

            mock_model = MagicMock()
            rng = np.random.default_rng(42)
            mock_model.encode.return_value = rng.random((3, 1024)).astype(np.float32)
            mock_st.return_value = mock_model

            texts = ["text1", "text2", "text3"]
            result = encoder.encode_batch(texts, batch_size=32)

            assert isinstance(result, np.ndarray)
            assert result.shape == (3, 1024)
            assert result.dtype == np.float32

    @pytest.mark.parametrize(
        "invalid_embedding",
        [
            np.zeros((1, 1024), dtype=np.float32),
            np.array([0.1, float("nan")], dtype=np.float32),
            np.array([0.1, float("inf")], dtype=np.float32),
        ],
        ids=["wrong-rank", "nan", "infinity"],
    )
    def test_encode_rejects_malformed_model_vector(
        self,
        sample_manifest_data: dict[str, object],
        invalid_embedding: np.ndarray,
    ) -> None:
        """Single-vector encoding rejects wrong-rank and non-finite model output."""
        manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
        encoder = DenseEncoder(manifest)
        encoder._model = MagicMock()
        encoder._model.encode.return_value = invalid_embedding

        with pytest.raises(ValueError, match="Dense encoder returned"):
            encoder.encode("Software Engineer")

    @pytest.mark.parametrize(
        "invalid_batch",
        [
            np.zeros(1024, dtype=np.float32),
            np.zeros((2, 1024), dtype=np.float32),
            np.full((3, 1024), float("nan"), dtype=np.float32),
        ],
        ids=["wrong-rank", "wrong-row-count", "nonfinite"],
    )
    def test_encode_batch_rejects_malformed_model_tensor(
        self,
        sample_manifest_data: dict[str, object],
        invalid_batch: np.ndarray,
    ) -> None:
        """Batch encoding preserves rank, row-count, and finiteness invariants."""
        manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
        encoder = DenseEncoder(manifest)
        encoder._model = MagicMock()
        encoder._model.encode.return_value = invalid_batch

        with pytest.raises(ValueError, match="Dense encoder returned"):
            encoder.encode_batch(["one", "two", "three"])

    def test_encode_with_tei_backend(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test encoding with TEI backend."""
        with patch("nohiki_ml_core.encoders.dense.httpx.post") as mock_post:
            manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
            manifest.dense = DenseConfig(
                enabled=True,
                model_id="TechWolf/JobBERT-v2",
                embedding_dim=1024,
                max_length=64,
                inference_backend=InferenceBackend.TEI,
                tei_endpoint="http://localhost:8080",
                tei_timeout_seconds=30,
            )
            encoder = DenseEncoder(manifest)

            mock_response = MagicMock()
            mock_response.json.return_value = [[0.1, 0.2, 0.3]]
            mock_post.return_value = mock_response

            result = encoder.encode("Software Engineer")

            assert isinstance(result, np.ndarray)
            assert result.shape == (3,)
            assert result.dtype == np.float32

    def test_encode_batch_with_tei_backend(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test batch encoding with TEI backend."""
        with patch("nohiki_ml_core.encoders.dense.httpx.post") as mock_post:
            manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
            manifest.dense = DenseConfig(
                enabled=True,
                model_id="TechWolf/JobBERT-v2",
                embedding_dim=1024,
                max_length=64,
                inference_backend=InferenceBackend.TEI,
                tei_endpoint="http://localhost:8080",
                tei_timeout_seconds=30,
            )
            encoder = DenseEncoder(manifest)

            mock_response = MagicMock()
            mock_response.json.return_value = [
                [0.1, 0.2],
                [0.3, 0.4],
                [0.5, 0.6],
            ]
            mock_post.return_value = mock_response

            texts = ["text1", "text2", "text3"]
            result = encoder.encode_batch(texts)

            assert isinstance(result, np.ndarray)
            assert result.shape == (3, 2)
            assert result.dtype == np.float32

    def test_encode_model_failure(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test proper error handling on model load failure."""
        with patch("nohiki_ml_core.encoders.dense._create_sentence_transformer") as mock_st:
            manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
            encoder = DenseEncoder(manifest)

            mock_st.side_effect = RuntimeError("Model load failed")

            with pytest.raises(RuntimeError, match="Model load failed"):
                encoder.encode("test")

    def test_missing_sentence_transformers_raises_typed_error(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """A missing local backend remains an import error at the encoder boundary."""
        manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
        encoder = DenseEncoder(manifest)

        with (
            patch(
                "nohiki_ml_core.encoders.dense._create_sentence_transformer",
                side_effect=MissingLocalDependencyError(
                    LocalDependency.SENTENCE_TRANSFORMERS,
                    "Dense encoder",
                ),
            ) as mock_create,
            pytest.raises(MissingLocalDependencyError) as error,
        ):
            encoder.encode("test")

        assert error.value.dependency is LocalDependency.SENTENCE_TRANSFORMERS
        mock_create.assert_called_once()

    def test_encode_tei_http_failure(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test proper error handling on TEI HTTP failure."""
        with patch("nohiki_ml_core.encoders.dense.httpx.post") as mock_post:
            import httpx

            manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
            manifest.dense = DenseConfig(
                enabled=True,
                model_id="TechWolf/JobBERT-v2",
                embedding_dim=1024,
                max_length=64,
                inference_backend=InferenceBackend.TEI,
                tei_endpoint="http://localhost:8080",
            )
            encoder = DenseEncoder(manifest)

            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Error", request=MagicMock(), response=MagicMock()
            )
            mock_post.return_value = mock_response

            with pytest.raises(httpx.HTTPStatusError):
                encoder.encode("test")


class TestDenseEncoderSimilarity:
    """Tests for DenseEncoder similarity computation."""

    def test_compute_similarity(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test computing cosine similarity between texts."""
        with patch("nohiki_ml_core.encoders.dense._create_sentence_transformer") as mock_st:
            manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
            encoder = DenseEncoder(manifest)

            mock_model = MagicMock()
            # Return identical vectors for similarity 1.0
            mock_model.encode.return_value = np.array([1.0, 0.0, 0.0], dtype=np.float32)
            mock_st.return_value = mock_model

            similarity = encoder.compute_similarity("test", "test")

            assert similarity == pytest.approx(1.0)

    def test_compute_similarity_empty_text(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test similarity with empty text returns 0."""
        manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
        encoder = DenseEncoder(manifest)

        similarity = encoder.compute_similarity("", "test")
        assert similarity == pytest.approx(0.0)

        similarity = encoder.compute_similarity("test", "")
        assert similarity == pytest.approx(0.0)

    def test_compute_similarity_whitespace_only(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test similarity with whitespace-only text returns 0."""
        manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
        encoder = DenseEncoder(manifest)

        similarity = encoder.compute_similarity("   ", "test")
        assert similarity == pytest.approx(0.0)

    def test_compute_similarity_zero_norm(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test similarity with zero norm embedding returns 0."""
        with patch("nohiki_ml_core.encoders.dense._create_sentence_transformer") as mock_st:
            manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
            encoder = DenseEncoder(manifest)

            mock_model = MagicMock()
            mock_model.encode.return_value = np.zeros(1024, dtype=np.float32)
            mock_st.return_value = mock_model

            similarity = encoder.compute_similarity("test", "test")

            assert similarity == pytest.approx(0.0)


class TestDenseEncoderWarmUp:
    """Tests for DenseEncoder warm_up method."""

    def test_warm_up_with_direct_backend(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test warm_up pre-loads model with DIRECT backend."""
        with patch("nohiki_ml_core.encoders.dense._create_sentence_transformer") as mock_st:
            manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
            encoder = DenseEncoder(manifest)

            mock_model = MagicMock()
            mock_st.return_value = mock_model

            encoder.warm_up()

            mock_st.assert_called_once()

    def test_warm_up_with_tei_backend(
        self,
        sample_manifest_data: dict[str, object],
    ) -> None:
        """Test warm_up does nothing with TEI backend."""
        manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
        manifest.dense = DenseConfig(
            enabled=True,
            model_id="TechWolf/JobBERT-v2",
            embedding_dim=1024,
            max_length=64,
            inference_backend=InferenceBackend.TEI,
            tei_endpoint="http://localhost:8080",
        )
        encoder = DenseEncoder(manifest)

        encoder.warm_up()

        assert encoder._model is None
