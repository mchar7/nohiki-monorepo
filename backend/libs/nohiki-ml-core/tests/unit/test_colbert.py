"""Unit tests for ColBERTEncoder."""

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from time import sleep
from typing import cast
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from nohiki_ml_core._deps import LocalDependency, MissingLocalDependencyError
from nohiki_ml_core.encoders.colbert import ColBERTEncoder
from nohiki_ml_manifest import (
    InferenceBackend,
    SemanticRepresentationManifest,
)


@pytest.fixture
def mock_require_pylate() -> Generator[None]:
    """Allow encoder construction through the owned availability seam."""
    with patch("nohiki_ml_core._deps.optional_dependency_available", return_value=True):
        yield


@pytest.fixture
def manifest(sample_manifest_data: dict) -> SemanticRepresentationManifest:
    """Create manifest from sample data."""
    return SemanticRepresentationManifest(**sample_manifest_data)


@pytest.fixture
def mock_colbert_model() -> MagicMock:
    """Create mock ColBERT model."""
    mock_model = MagicMock()
    rng = np.random.default_rng(42)

    # Mock encode method to return realistic token arrays
    def mock_encode(
        texts: list[str],
        *,
        _is_query: object = None,
        _batch_size: object = None,
        **_kwargs: object,
    ) -> list:
        # Return list of 2D arrays (num_tokens, token_dim=48)
        results = []
        for text in texts:
            # Simulate variable token count based on text length
            num_tokens = max(1, min(len(text.split()) * 2, 512))
            tokens = rng.standard_normal((num_tokens, 48)).astype(np.float32)
            results.append(tokens.tolist())
        return results

    mock_model.encode = mock_encode
    return mock_model


@pytest.mark.usefixtures("mock_require_pylate")
def test_colbert_encoder_initialization(
    manifest: SemanticRepresentationManifest,
) -> None:
    """Test ColBERT encoder initialization from manifest."""
    encoder = ColBERTEncoder(manifest)

    assert encoder.model_id == "mixedbread-ai/mxbai-edge-colbert-v0-17m"
    assert encoder.token_dim == 48
    assert encoder.max_length == 32000
    assert encoder._model is None  # Lazy loading


@pytest.mark.parametrize("backend", [InferenceBackend.TEI, InferenceBackend.ONNX])
def test_colbert_rejects_non_direct_backend_at_initialization(
    sample_manifest_data: dict[str, object],
    backend: InferenceBackend,
) -> None:
    """ColBERT fails before inference when its backend cannot preserve PyLate semantics."""
    late_interaction = cast("dict[str, object]", sample_manifest_data["late_interaction"])
    late_interaction["inference_backend"] = backend
    if backend is InferenceBackend.TEI:
        late_interaction["tei_endpoint"] = "localhost:8090"
    manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)

    with pytest.raises(
        ValueError,
        match=rf"ColBERT supports only inference_backend='direct'; got '{backend.value}'",
    ):
        ColBERTEncoder(manifest)


@pytest.mark.usefixtures("mock_require_pylate")
def test_colbert_encode_document_shape(
    manifest: SemanticRepresentationManifest,
    mock_colbert_model: MagicMock,
) -> None:
    """Test document encoding returns correct shape."""
    encoder = ColBERTEncoder(manifest)
    encoder._model = mock_colbert_model

    result = encoder.encode_document("Software Engineer with Python experience")

    assert isinstance(result, np.ndarray)
    assert result.ndim == 2
    assert result.shape[1] == 48  # Token dimension
    assert result.dtype == np.float32


@pytest.mark.usefixtures("mock_require_pylate")
def test_colbert_encode_query_shape(
    manifest: SemanticRepresentationManifest,
    mock_colbert_model: MagicMock,
) -> None:
    """Test query encoding returns correct shape."""
    encoder = ColBERTEncoder(manifest)
    encoder._model = mock_colbert_model

    result = encoder.encode_query("python developer")

    assert isinstance(result, np.ndarray)
    assert result.ndim == 2
    assert result.shape[1] == 48
    assert result.dtype == np.float32


@pytest.mark.usefixtures("mock_require_pylate")
def test_colbert_encode_batch(
    manifest: SemanticRepresentationManifest,
    mock_colbert_model: MagicMock,
) -> None:
    """Test batch encoding returns list of arrays."""
    encoder = ColBERTEncoder(manifest)
    encoder._model = mock_colbert_model

    texts = ["text one", "text two", "text three"]
    results = encoder.encode_batch(texts, is_query=False)

    assert isinstance(results, list)
    assert len(results) == 3
    for arr in results:
        assert isinstance(arr, np.ndarray)
        assert arr.ndim == 2
        assert arr.shape[1] == 48


@pytest.mark.usefixtures("mock_require_pylate")
@pytest.mark.parametrize(
    "invalid_tokens",
    [
        np.zeros(48, dtype=np.float32),
        np.zeros((2, 47), dtype=np.float32),
        np.full((2, 48), float("nan"), dtype=np.float32),
        np.full((2, 48), float("inf"), dtype=np.float32),
    ],
    ids=["wrong-rank", "wrong-token-dimension", "nan", "infinity"],
)
def test_colbert_encode_document_rejects_malformed_tokens(
    manifest: SemanticRepresentationManifest,
    invalid_tokens: np.ndarray,
) -> None:
    """Document encoding rejects malformed token tensors at the backend boundary."""
    encoder = ColBERTEncoder(manifest)
    encoder._model = MagicMock()
    encoder._model.encode.return_value = [invalid_tokens]

    with pytest.raises(ValueError, match="ColBERT encoder returned"):
        encoder.encode_document("Software Engineer")


@pytest.mark.usefixtures("mock_require_pylate")
def test_colbert_encode_batch_rejects_missing_result(
    manifest: SemanticRepresentationManifest,
) -> None:
    """Every input text must have exactly one ColBERT result tensor."""
    encoder = ColBERTEncoder(manifest)
    encoder._model = MagicMock()
    encoder._model.encode.return_value = [np.zeros((2, 48), dtype=np.float32)]

    with pytest.raises(ValueError, match="returned 1 rows for 2 texts"):
        encoder.encode_batch(["one", "two"])


def test_colbert_missing_pylate_raises_early(
    manifest: SemanticRepresentationManifest,
) -> None:
    """Test MissingLocalDependencyError is raised early when pylate not installed."""
    with (
        patch("nohiki_ml_core._deps.optional_dependency_available", return_value=False),
        pytest.raises(MissingLocalDependencyError, match="ColBERT DIRECT backend"),
    ):
        ColBERTEncoder(manifest)


@pytest.mark.usefixtures("mock_require_pylate")
def test_colbert_lazy_loading_import_error(
    manifest: SemanticRepresentationManifest,
) -> None:
    """A missing PyLate backend raises the typed import error."""
    encoder = ColBERTEncoder(manifest)

    with (
        patch(
            "nohiki_ml_core._deps.import_optional_module",
            side_effect=MissingLocalDependencyError(LocalDependency.PYLATE, "ColBERT DIRECT backend"),
        ),
        pytest.raises(MissingLocalDependencyError, match="ColBERT DIRECT backend"),
    ):
        encoder._ensure_model()


@pytest.mark.usefixtures("mock_require_pylate")
def test_colbert_direct_single_encode_preserves_is_query(
    manifest: SemanticRepresentationManifest,
) -> None:
    """DIRECT single encoding passes document/query mode to PyLate unchanged."""
    encoder = ColBERTEncoder(manifest)
    model = MagicMock()
    model.encode.return_value = [np.zeros((2, 48), dtype=np.float32)]
    encoder._model = model

    encoder.encode_document("doc text")
    model.encode.assert_called_once_with(["doc text"], is_query=False, batch_size=1)

    model.reset_mock()
    encoder.encode_query("query text")
    model.encode.assert_called_once_with(["query text"], is_query=True, batch_size=1)


@pytest.mark.usefixtures("mock_require_pylate")
def test_colbert_direct_batch_encode_preserves_is_query(
    manifest: SemanticRepresentationManifest,
) -> None:
    """DIRECT batch encoding passes document/query mode and batch size to PyLate unchanged."""
    encoder = ColBERTEncoder(manifest)
    model = MagicMock()
    model.encode.return_value = [np.zeros((2, 48), dtype=np.float32)]
    encoder._model = model

    encoder.encode_batch(["doc text"], is_query=False, batch_size=3)
    model.encode.assert_called_once_with(["doc text"], is_query=False, batch_size=3)

    model.reset_mock()
    encoder.encode_batch(["query text"], is_query=True, batch_size=5)
    model.encode.assert_called_once_with(["query text"], is_query=True, batch_size=5)


@pytest.mark.usefixtures("mock_require_pylate")
def test_colbert_serializes_shared_tokenizer_access(
    manifest: SemanticRepresentationManifest,
) -> None:
    """Concurrent requests must not borrow the mutable tokenizer at the same time."""
    encoder = ColBERTEncoder(manifest)
    borrowed = Lock()

    def encode(
        texts: list[str],
        *,
        is_query: bool,
        batch_size: int,
    ) -> list[np.ndarray]:
        del is_query, batch_size
        if not borrowed.acquire(blocking=False):
            message = "Already borrowed"
            raise RuntimeError(message)
        try:
            sleep(0.02)
            return [np.zeros((2, 48), dtype=np.float32) for _ in texts]
        finally:
            borrowed.release()

    model = MagicMock()
    model.encode.side_effect = encode
    encoder._model = model
    start = Barrier(8)

    def encode_query(index: int) -> np.ndarray:
        start.wait()
        return encoder.encode_query(str(index))

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(encode_query, range(8)))

    assert len(results) == 8


@pytest.mark.usefixtures("mock_require_pylate")
def test_colbert_encode_empty_text(
    manifest: SemanticRepresentationManifest,
    mock_colbert_model: MagicMock,
) -> None:
    """Test encoding empty text."""
    encoder = ColBERTEncoder(manifest)
    encoder._model = mock_colbert_model

    result = encoder.encode_document("")

    assert isinstance(result, np.ndarray)
    assert result.ndim == 2


@pytest.mark.usefixtures("mock_require_pylate")
def test_colbert_encode_long_text(
    manifest: SemanticRepresentationManifest,
    mock_colbert_model: MagicMock,
) -> None:
    """Test encoding long text."""
    encoder = ColBERTEncoder(manifest)
    encoder._model = mock_colbert_model

    # Generate text with many words
    long_text = " ".join(["word"] * 1000)
    result = encoder.encode_document(long_text)

    assert isinstance(result, np.ndarray)
    assert result.ndim == 2
    assert result.shape[1] == 48


@pytest.mark.usefixtures("mock_require_pylate")
def test_colbert_model_load_error(
    manifest: SemanticRepresentationManifest,
) -> None:
    """Test RuntimeError when model fails to load."""
    encoder = ColBERTEncoder(manifest)

    mock_pylate = MagicMock()
    mock_pylate.models.ColBERT.side_effect = ValueError("Model load failed")

    with (
        patch.dict(
            "sys.modules",
            {"pylate": mock_pylate, "pylate.models": mock_pylate.models},
        ),
        pytest.raises(RuntimeError, match="Failed to load ColBERT model"),
    ):
        encoder._ensure_model()
