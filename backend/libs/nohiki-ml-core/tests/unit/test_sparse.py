"""Unit tests for SparseEncoder."""

from collections.abc import Generator
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from nohiki_ml_core.encoders.sparse import SparseEncoder, SparseVector
from nohiki_ml_manifest import SemanticRepresentationManifest


@pytest.fixture
def mock_require_fastembed() -> Generator[None]:
    """Mock require_fastembed to allow encoder construction without fastembed installed."""
    with patch("nohiki_ml_core.encoders.sparse.require_fastembed"):
        yield


@dataclass
class MockSparseEmbedding:
    """Mock fastembed SparseEmbedding result."""

    indices: np.ndarray
    values: np.ndarray


@pytest.fixture
def mock_sparse_model() -> MagicMock:
    """Create mock sparse model."""
    mock_model = MagicMock()
    rng = np.random.default_rng(42)

    def mock_embed(texts: list[str]) -> list[MockSparseEmbedding]:
        results = []
        for text in texts:
            num_terms = max(1, min(len(text.split()) * 3, 100))
            indices = rng.integers(0, 30522, size=num_terms)
            values = rng.random(size=num_terms).astype(np.float32)
            results.append(MockSparseEmbedding(indices=indices, values=values))
        return results

    mock_model.embed = mock_embed
    return mock_model


def test_sparse_vector_creation() -> None:
    """Test SparseVector dataclass creation."""
    vec = SparseVector(indices=[1, 2, 3], values=[0.5, 0.3, 0.2])

    assert vec.indices == [1, 2, 3]
    assert vec.values == [0.5, 0.3, 0.2]


def test_sparse_vector_is_frozen_dataclass() -> None:
    """Test SparseVector is a frozen dataclass."""
    import dataclasses

    assert dataclasses.is_dataclass(SparseVector)
    params = getattr(SparseVector, "__dataclass_params__", None)
    assert params is not None
    assert params.frozen is True


@pytest.mark.parametrize(
    ("indices", "values", "error"),
    [
        ([1, 2], [0.5], "equal lengths"),
        ([-1], [0.5], "non-negative integers"),
        ([True], [0.5], "non-negative integers"),
        ([1, 1], [0.5, 0.3], "unique"),
        ([1], [float("nan")], "finite"),
        ([1], [float("inf")], "finite"),
    ],
    ids=["length-mismatch", "negative-index", "boolean-index", "duplicate-index", "nan", "infinity"],
)
def test_sparse_vector_rejects_malformed_geometry(
    indices: list[int],
    values: list[float],
    error: str,
) -> None:
    """Sparse geometry must remain aligned, unique, nonnegative, and finite."""
    with pytest.raises(ValueError, match=error):
        SparseVector(indices=indices, values=values)


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_encoder_initialization_with_manifest(
    sample_manifest_data: dict,
) -> None:
    """Test sparse encoder initialization with manifest."""
    manifest = SemanticRepresentationManifest(**sample_manifest_data)
    encoder = SparseEncoder(manifest)

    assert encoder.enabled is True
    assert encoder.model_id == "Qdrant/minicoil-v1"
    assert encoder._model is None


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_encoder_initialization_without_manifest() -> None:
    """Test sparse encoder initialization without manifest."""
    encoder = SparseEncoder()

    assert encoder.enabled is True
    assert encoder.model_id == "Qdrant/minicoil-v1"


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_encoder_custom_model_id(sample_manifest_data: dict[str, object]) -> None:
    """Test sparse encoder with custom model ID."""
    manifest_data = sample_manifest_data.copy()
    manifest_data["sparse"] = {"enabled": True, "model_id": "custom/splade-model"}
    manifest = SemanticRepresentationManifest.model_validate(manifest_data)
    encoder = SparseEncoder(manifest)

    assert encoder.model_id == "custom/splade-model"


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_encode_with_mock(
    mock_sparse_model: MagicMock,
) -> None:
    """Test encoding text with mocked sparse model."""
    encoder = SparseEncoder()
    encoder._model = mock_sparse_model

    result = encoder.encode("Software Engineer with Python experience")

    assert isinstance(result, SparseVector)
    assert len(result.indices) > 0
    assert len(result.values) > 0
    assert len(result.indices) == len(result.values)
    assert all(isinstance(i, (int, np.integer)) for i in result.indices)
    assert all(isinstance(v, (float, np.floating)) for v in result.values)


def test_sparse_encode_disabled(sample_manifest_data: dict[str, object]) -> None:
    """Test encoding when sparse encoding is disabled."""
    manifest_data = sample_manifest_data.copy()
    manifest_data["sparse"] = {"enabled": False}
    manifest = SemanticRepresentationManifest.model_validate(manifest_data)
    encoder = SparseEncoder(manifest)

    result = encoder.encode("Some text")

    assert result.indices == []
    assert result.values == []


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_encode_empty_text(
    mock_sparse_model: MagicMock,
) -> None:
    """Test encoding empty text."""
    encoder = SparseEncoder()
    encoder._model = mock_sparse_model

    result = encoder.encode("")

    assert isinstance(result, SparseVector)


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_encode_batch_with_mock(
    mock_sparse_model: MagicMock,
) -> None:
    """Test batch encoding with mocked sparse model."""
    encoder = SparseEncoder()
    encoder._model = mock_sparse_model

    texts = ["text one", "text two", "text three"]
    results = encoder.encode_batch(texts)

    assert len(results) == 3
    for result in results:
        assert isinstance(result, SparseVector)
        assert len(result.indices) > 0
        assert len(result.values) > 0


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_encode_batch_rejects_missing_result() -> None:
    """Every input text must have exactly one sparse model result."""
    encoder = SparseEncoder()
    encoder._model = MagicMock()
    encoder._model.embed.return_value = [
        MockSparseEmbedding(indices=np.array([1]), values=np.array([0.5])),
    ]

    with pytest.raises(ValueError, match="returned 1 rows for 2 texts"):
        encoder.encode_batch(["one", "two"])


def test_sparse_encode_batch_disabled(sample_manifest_data: dict[str, object]) -> None:
    """Test batch encoding when disabled."""
    manifest_data = sample_manifest_data.copy()
    manifest_data["sparse"] = {"enabled": False}
    manifest = SemanticRepresentationManifest.model_validate(manifest_data)
    encoder = SparseEncoder(manifest)

    results = encoder.encode_batch(["text one", "text two"])

    assert len(results) == 2
    assert all(r.indices == [] for r in results)
    assert all(r.values == [] for r in results)


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_encode_batch_empty_list() -> None:
    """Test batch encoding with empty list."""
    encoder = SparseEncoder()

    results = encoder.encode_batch([])

    assert results == []


def test_sparse_missing_fastembed_raises_early() -> None:
    """Test MissingLocalDependencyError is raised early when fastembed not installed."""
    from nohiki_ml_core._deps import MissingLocalDependencyError

    with (
        patch("nohiki_ml_core._deps.check_fastembed_available", return_value=False),
        pytest.raises(MissingLocalDependencyError, match="Sparse encoder"),
    ):
        SparseEncoder()


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_lazy_loading_import_error() -> None:
    """Test RuntimeError is raised when fastembed import fails at model load time."""
    encoder = SparseEncoder()

    with (
        patch.dict("sys.modules", {"fastembed": None}),
        patch(
            "builtins.__import__",
            side_effect=ImportError("No module named 'fastembed'"),
        ),
        pytest.raises(ImportError),
    ):
        encoder._ensure_model()


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_encode_model_error() -> None:
    """Test encoding handles model errors gracefully."""
    encoder = SparseEncoder()
    mock_model = MagicMock()
    mock_model.embed.side_effect = RuntimeError("Model error")
    encoder._model = mock_model

    with pytest.raises(RuntimeError, match="Model error"):
        encoder.encode("test text")


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_encode_returns_empty_on_no_embeddings() -> None:
    """Test encoding returns empty vector when model returns no embeddings."""
    encoder = SparseEncoder()
    mock_model = MagicMock()
    mock_model.embed.return_value = []
    encoder._model = mock_model

    result = encoder.encode("test text")

    assert result.indices == []
    assert result.values == []


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_indices_are_bert_vocab_ids(
    mock_sparse_model: MagicMock,
) -> None:
    """Test that sparse indices are within BERT vocabulary range."""
    encoder = SparseEncoder()
    encoder._model = mock_sparse_model

    result = encoder.encode("Software Engineer Python")

    for idx in result.indices:
        assert 0 <= idx < 30522


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_ensure_model_runtime_error() -> None:
    """Test RuntimeError during model loading is wrapped properly."""
    encoder = SparseEncoder()

    mock_ste = MagicMock(side_effect=ValueError("Invalid model"))
    with patch.dict("sys.modules", {"fastembed": MagicMock(SparseTextEmbedding=mock_ste)}):
        # Force re-import by clearing cached model
        encoder._model = None
        with pytest.raises(RuntimeError, match="Failed to load sparse model"):
            encoder._ensure_model()


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_encode_batch_model_error() -> None:
    """Test batch encoding handles model errors gracefully."""
    encoder = SparseEncoder()
    mock_model = MagicMock()
    mock_model.embed.side_effect = RuntimeError("Batch error")
    encoder._model = mock_model

    with pytest.raises(RuntimeError, match="Batch error"):
        encoder.encode_batch(["text1", "text2"])


def test_sparse_vector_dot_product_empty_vectors() -> None:
    """Test dot product calculation with empty vectors returns 0."""
    vec1 = SparseVector(indices=[], values=[])
    vec2 = SparseVector(indices=[1, 2], values=[0.5, 0.3])

    assert vec1.dot_product(vec2) == pytest.approx(0.0)
    assert vec2.dot_product(vec1) == pytest.approx(0.0)


def test_sparse_vector_dot_product_no_overlap() -> None:
    """Test dot product calculation with non-overlapping indices returns 0."""
    vec1 = SparseVector(indices=[1, 2], values=[0.5, 0.3])
    vec2 = SparseVector(indices=[3, 4], values=[0.4, 0.6])

    assert vec1.dot_product(vec2) == pytest.approx(0.0)


def test_sparse_vector_dot_product_partial_overlap() -> None:
    """Test dot product calculation with partial index overlap."""
    vec1 = SparseVector(indices=[1, 2, 3], values=[0.5, 0.3, 0.2])
    vec2 = SparseVector(indices=[2, 3, 4], values=[0.4, 0.1, 0.6])

    expected = 0.3 * 0.4 + 0.2 * 0.1
    assert vec1.dot_product(vec2) == pytest.approx(expected)


def test_sparse_vector_dot_product_full_overlap() -> None:
    """Test dot product calculation with full index overlap."""
    vec1 = SparseVector(indices=[1, 2], values=[0.5, 0.3])
    vec2 = SparseVector(indices=[1, 2], values=[0.4, 0.6])

    expected = 0.5 * 0.4 + 0.3 * 0.6
    assert vec1.dot_product(vec2) == pytest.approx(expected)


def test_sparse_vector_dot_product_asymmetric() -> None:
    """Test dot product calculation is commutative."""
    vec1 = SparseVector(indices=[1, 2, 3], values=[0.5, 0.3, 0.2])
    vec2 = SparseVector(indices=[2, 4], values=[0.4, 0.6])

    assert vec1.dot_product(vec2) == pytest.approx(vec2.dot_product(vec1))


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_encoder_warm_up() -> None:
    """Test warm_up method pre-loads the model."""
    encoder = SparseEncoder()
    mock_model = MagicMock()
    encoder._model = mock_model

    encoder.warm_up()

    assert encoder._model is mock_model


@pytest.mark.usefixtures("mock_require_fastembed")
def test_sparse_encoder_warm_up_disabled(
    sample_manifest_data: dict[str, object],
) -> None:
    """Test warm_up does nothing when sparse encoder is disabled."""
    manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
    manifest.sparse.enabled = False
    encoder = SparseEncoder(manifest)

    encoder.warm_up()

    assert encoder._model is None
