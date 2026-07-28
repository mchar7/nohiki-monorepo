"""Unit tests for MUVERAEncoder."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from nohiki_ml_core.encoders.muvera import MUVERAEncoder
from nohiki_ml_manifest import SemanticRepresentationManifest


@pytest.fixture
def mock_require_fastembed() -> Generator[None]:
    """Mock require_fastembed to allow encoder construction without fastembed installed."""
    with patch("nohiki_ml_core.encoders.muvera.require_fastembed"):
        yield


@pytest.fixture
def manifest(sample_manifest_data: dict) -> SemanticRepresentationManifest:
    """Create manifest from sample data."""
    return SemanticRepresentationManifest(**sample_manifest_data)


@pytest.fixture
def mock_muvera_encoder() -> MagicMock:
    """Create mock MUVERA encoder."""
    mock_encoder = MagicMock()
    # Output dimension: 2^k_sim * dim_proj * r_reps = 2^6 * 16 * 8 = 8192
    mock_encoder.embedding_size = 8192

    # Mock process methods to return 8192-dim vectors
    rng = np.random.default_rng(42)

    def mock_process_document(_tokens: np.ndarray) -> list[float]:
        return rng.random(8192).tolist()

    def mock_process_query(_tokens: np.ndarray) -> list[float]:
        return rng.random(8192).tolist()

    mock_encoder.process_document = MagicMock(side_effect=mock_process_document)
    mock_encoder.process_query = MagicMock(side_effect=mock_process_query)

    return mock_encoder


@pytest.mark.usefixtures("mock_require_fastembed")
def test_muvera_encoder_initialization(
    manifest: SemanticRepresentationManifest,
) -> None:
    """Test MUVERA encoder initialization from manifest."""
    encoder = MUVERAEncoder(manifest)

    assert encoder.config.dim == 48
    assert encoder.config.k_sim == 6
    assert encoder.config.dim_proj == 16
    assert encoder.config.r_reps == 8
    # Output dimension: 2^6 * 16 * 8 = 8192
    assert encoder.output_dimension == 8192
    assert encoder._encoder is None  # Lazy loading


@pytest.mark.usefixtures("mock_require_fastembed")
def test_muvera_encode_document_shape(
    manifest: SemanticRepresentationManifest,
    mock_muvera_encoder: MagicMock,
) -> None:
    """Test document encoding returns correct shape."""
    encoder = MUVERAEncoder(manifest)
    encoder._encoder = mock_muvera_encoder

    # Create mock ColBERT tokens
    tokens = np.random.default_rng(42).random((100, 48)).astype(np.float32)

    result = encoder.encode(tokens, is_query=False)

    assert isinstance(result, np.ndarray)
    assert result.shape == (8192,)  # 2^6 * 16 * 8
    assert result.dtype == np.float32


@pytest.mark.usefixtures("mock_require_fastembed")
def test_muvera_encode_query_shape(
    manifest: SemanticRepresentationManifest,
    mock_muvera_encoder: MagicMock,
) -> None:
    """Test query encoding returns correct shape."""
    encoder = MUVERAEncoder(manifest)
    encoder._encoder = mock_muvera_encoder

    tokens = np.random.default_rng(42).random((20, 48)).astype(np.float32)

    result = encoder.encode(tokens, is_query=True)

    assert isinstance(result, np.ndarray)
    assert result.shape == (8192,)  # 2^6 * 16 * 8
    assert result.dtype == np.float32


@pytest.mark.usefixtures("mock_require_fastembed")
def test_muvera_encode_uses_correct_method(
    manifest: SemanticRepresentationManifest,
    mock_muvera_encoder: MagicMock,
) -> None:
    """Test document vs query encoding uses different methods."""
    encoder = MUVERAEncoder(manifest)
    encoder._encoder = mock_muvera_encoder

    tokens = np.random.default_rng(42).random((50, 48)).astype(np.float32)

    # Document encoding should use process_document
    encoder.encode(tokens, is_query=False)
    mock_muvera_encoder.process_document.assert_called_once()
    mock_muvera_encoder.process_query.assert_not_called()

    mock_muvera_encoder.reset_mock()

    # Query encoding should use process_query
    encoder.encode(tokens, is_query=True)
    mock_muvera_encoder.process_query.assert_called_once()
    mock_muvera_encoder.process_document.assert_not_called()


@pytest.mark.usefixtures("mock_require_fastembed")
def test_muvera_encode_invalid_shape_1d(
    manifest: SemanticRepresentationManifest,
) -> None:
    """Test encoding with 1D array raises ValueError."""
    encoder = MUVERAEncoder(manifest)
    encoder._encoder = MagicMock()

    tokens_1d = np.array([1.0, 2.0, 3.0])

    with pytest.raises(ValueError, match="Muvera requires 2D tokens"):
        encoder.encode(tokens_1d)


@pytest.mark.usefixtures("mock_require_fastembed")
def test_muvera_encode_invalid_shape_3d(
    manifest: SemanticRepresentationManifest,
) -> None:
    """Test encoding with 3D array raises ValueError."""
    encoder = MUVERAEncoder(manifest)
    encoder._encoder = MagicMock()

    tokens_3d = np.zeros((10, 48, 2))

    with pytest.raises(ValueError, match="Muvera requires 2D tokens"):
        encoder.encode(tokens_3d)


@pytest.mark.usefixtures("mock_require_fastembed")
def test_muvera_encode_wrong_token_dim(
    manifest: SemanticRepresentationManifest,
) -> None:
    """Test encoding with wrong token dimension raises ValueError."""
    encoder = MUVERAEncoder(manifest)
    encoder._encoder = MagicMock()

    # Wrong dimension (64 instead of 48)
    wrong_dim_tokens = np.zeros((10, 64))

    with pytest.raises(ValueError, match="Expected token_dim=48"):
        encoder.encode(wrong_dim_tokens)


@pytest.mark.usefixtures("mock_require_fastembed")
def test_muvera_output_dimension_property(
    manifest: SemanticRepresentationManifest,
) -> None:
    """Test output_dimension property returns correct value."""
    encoder = MUVERAEncoder(manifest)

    # theory: 2^k_sim * dim_proj * r_reps = 2^6 * 16 * 8 = 8192
    assert encoder.output_dimension == 8192


def test_muvera_missing_fastembed_raises_early(
    manifest: SemanticRepresentationManifest,
) -> None:
    """Test MissingLocalDependencyError is raised early when fastembed not installed."""
    from nohiki_ml_core._deps import MissingLocalDependencyError

    with (
        patch("nohiki_ml_core._deps.check_fastembed_available", return_value=False),
        pytest.raises(MissingLocalDependencyError, match="MUVERA encoder"),
    ):
        MUVERAEncoder(manifest)


@pytest.mark.usefixtures("mock_require_fastembed")
def test_muvera_lazy_loading_import_error(
    manifest: SemanticRepresentationManifest,
) -> None:
    """Test RuntimeError is raised when fastembed import fails at encoder load time."""
    encoder = MUVERAEncoder(manifest)

    with (
        patch(
            "nohiki_ml_core.encoders.muvera.importlib.import_module",
            side_effect=ImportError("No module named 'fastembed'"),
        ),
        pytest.raises(RuntimeError, match="Failed to initialize MUVERA encoder") as error,
    ):
        encoder._ensure_encoder()

    assert isinstance(error.value.__cause__, ImportError)


@pytest.mark.usefixtures("mock_require_fastembed")
def test_muvera_encode_variable_token_count(
    manifest: SemanticRepresentationManifest,
    mock_muvera_encoder: MagicMock,
) -> None:
    """Test encoding with variable token counts."""
    encoder = MUVERAEncoder(manifest)
    encoder._encoder = mock_muvera_encoder
    rng = np.random.default_rng(42)

    # Test with different token counts
    for num_tokens in [1, 10, 100, 500]:
        tokens = rng.random((num_tokens, 48)).astype(np.float32)
        result = encoder.encode(tokens)

        assert result.shape == (8192,)
        assert result.dtype == np.float32


@pytest.mark.usefixtures("mock_require_fastembed")
def test_muvera_deterministic_encoding(
    manifest: SemanticRepresentationManifest,
) -> None:
    """Test that repeated calls with same input produce same output."""
    fixed_output = np.ones(8192, dtype=np.float32) * 0.5
    encoder = MUVERAEncoder(manifest)
    mock_enc = MagicMock()
    mock_enc.process_document = MagicMock(return_value=fixed_output.tolist())
    encoder._encoder = mock_enc

    rng = np.random.default_rng(12345)
    tokens = rng.random((50, 48)).astype(np.float32)

    result1 = encoder.encode(tokens, is_query=False)
    result2 = encoder.encode(tokens, is_query=False)

    np.testing.assert_array_equal(result1, result2)


@pytest.mark.usefixtures("mock_require_fastembed")
def test_muvera_asymmetric_encoding(
    manifest: SemanticRepresentationManifest,
    mock_muvera_encoder: MagicMock,
) -> None:
    """Test that document and query paths call different encoder methods."""
    encoder = MUVERAEncoder(manifest)
    encoder._encoder = mock_muvera_encoder

    rng = np.random.default_rng(12345)
    tokens = rng.random((50, 48)).astype(np.float32)

    doc_result = encoder.encode(tokens, is_query=False)
    query_result = encoder.encode(tokens, is_query=True)

    mock_muvera_encoder.process_document.assert_called_once()
    mock_muvera_encoder.process_query.assert_called_once()
    assert doc_result.shape == (8192,)
    assert query_result.shape == (8192,)


@pytest.mark.usefixtures("mock_require_fastembed")
def test_muvera_encode_output_dtype_and_shape(
    manifest: SemanticRepresentationManifest,
    mock_muvera_encoder: MagicMock,
) -> None:
    """Test that encode returns float32 ndarray of expected dimension."""
    encoder = MUVERAEncoder(manifest)
    encoder._encoder = mock_muvera_encoder

    rng = np.random.default_rng(42)
    tokens = rng.random((100, 48)).astype(np.float32)

    result = encoder.encode(tokens, is_query=False)

    assert isinstance(result, np.ndarray)
    assert result.dtype == np.float32
    assert result.shape == (8192,)
