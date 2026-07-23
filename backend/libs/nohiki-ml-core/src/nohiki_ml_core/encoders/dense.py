"""Dense sentence encoder with pluggable inference backends."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import httpx
import numpy as np
from nohiki_ml_manifest import InferenceBackend, SemanticRepresentationManifest
from nohiki_observability import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = get_logger(__name__)

NORM_EPSILON: float = 1e-9
DENSE_VECTOR_NDIM = 1
DENSE_BATCH_NDIM = 2


def _create_sentence_transformer(
    model_id: str,
    *,
    backend: Literal["torch", "onnx", "openvino"],
    trust_remote_code: bool,
    model_kwargs: dict[str, str | bool | None] | None,
    device: str,
) -> SentenceTransformer:
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415 -- Keep inference off the import-only path.

    return SentenceTransformer(
        model_id,
        backend=backend,
        trust_remote_code=trust_remote_code,
        model_kwargs=model_kwargs,
        device=device,
    )


class DenseEncoder:
    """Dense sentence encoder with pluggable inference backends.

    Model-agnostic: model_id and parameters from SemanticRepresentationManifest.
    Backend-agnostic: supports DIRECT (sentence-transformers), ONNX, or TEI.

    Architecture:
    - DIRECT backend: Loads sentence-transformers model in-process
    - ONNX backend: Loads quantized ONNX model via sentence-transformers
    - TEI backend: Calls TEI server via HTTP (for dense embeddings)

    For JobBERT models, the Asym layer routes automatically via standard .encode().
    Both V2 (English) and V3 (multilingual) are supported without code changes.

    Usage:
        encoder = DenseEncoder(manifest)
        embedding = encoder.encode("Software Engineer")
        similarity = encoder.compute_similarity("query", "document")

    """

    def __init__(self, manifest: SemanticRepresentationManifest) -> None:
        """Initialize encoder with manifest configuration.

        Args:
            manifest: Semantic representation configuration

        Raises:
            ValueError: If TEI/ONNX backend configured but required fields missing

        """
        self.manifest = manifest
        self._config = manifest.dense
        self.model_id = self._config.model_id
        self.embedding_dim = self._config.embedding_dim
        self.max_length = self._config.max_length
        self._backend = self._config.inference_backend

        self._model: SentenceTransformer | None = None
        self._tei_endpoint = self._config.tei_endpoint
        self._tei_timeout = self._config.tei_timeout_seconds

        if self._backend == InferenceBackend.TEI and not self._tei_endpoint:
            msg = "TEI endpoint required when inference_backend='tei'"
            raise ValueError(msg)

        if self._backend == InferenceBackend.ONNX and not self._config.onnx_file_name:
            msg = "onnx_file_name required when inference_backend='onnx'"
            raise ValueError(msg)

        logger.info(
            "Dense encoder initialized",
            model_id=self.model_id,
            embedding_dim=self.embedding_dim,
            max_length=self.max_length,
            backend=self._backend.value,
        )

    def _ensure_model(self) -> SentenceTransformer:
        """Lazy-load sentence-transformers model on first use.

        Returns:
            SentenceTransformer model instance

        """
        if self._model is None:
            model_kwargs: dict[str, str | bool | None] = {}

            if self._backend == InferenceBackend.ONNX:
                backend = "onnx"
                if self._config.onnx_file_name:
                    model_kwargs["file_name"] = self._config.onnx_file_name
            else:
                backend = "torch"
                # PyTorch 2.6+ forbids .to() on meta tensors, which accelerate
                # creates when low_cpu_mem_usage=True (the default since
                # transformers 4.50). Disabling it avoids the meta tensor
                # dispatch entirely. Negligible impact for CPU inference.
                model_kwargs["low_cpu_mem_usage"] = False

            try:
                self._model = _create_sentence_transformer(
                    self.model_id,
                    backend=backend,
                    trust_remote_code=self._config.trust_remote_code,
                    model_kwargs=model_kwargs or None,
                    device=self._config.device,
                )
                logger.info(
                    "Dense model loaded",
                    model_id=self.model_id,
                    backend=backend,
                    device=self._config.device,
                )
            except Exception as e:
                logger.exception("Failed to load dense model", model_id=self.model_id)
                msg = f"Failed to load dense model '{self.model_id}': {e}"
                raise RuntimeError(msg) from e

        return self._model

    def encode(self, text: str) -> np.ndarray:
        """Encode text into dense embedding vector.

        Args:
            text: Text to encode

        Returns:
            np.ndarray of shape (embedding_dim,)

        """
        if self._backend == InferenceBackend.TEI:
            return self._encode_via_tei(text)
        return self._encode_via_model(text)

    def _validate_embedding(self, value: object, *, batch_rows: int | None = None) -> np.ndarray:
        """Normalize and validate a model/provider tensor before it leaves the encoder."""
        result = np.asarray(value, dtype=np.float32)
        expected_ndim = DENSE_VECTOR_NDIM if batch_rows is None else DENSE_BATCH_NDIM
        rows_valid = batch_rows is None or (result.ndim == DENSE_BATCH_NDIM and result.shape[0] == batch_rows)
        if result.ndim != expected_ndim or not rows_valid:
            msg = f"Dense encoder returned invalid shape {result.shape} for batch_rows={batch_rows}"
            raise ValueError(msg)
        if not np.isfinite(result).all():
            msg = "Dense encoder returned non-finite values"
            raise ValueError(msg)
        return result

    def _encode_via_model(self, text: str) -> np.ndarray:
        """Encode using sentence-transformers (DIRECT or ONNX backend)."""
        model = self._ensure_model()
        embedding = model.encode(text, convert_to_numpy=True)
        return self._validate_embedding(embedding)

    def _encode_via_tei(self, text: str) -> np.ndarray:
        """Encode using TEI server via HTTP."""
        response = httpx.post(
            f"{self._tei_endpoint}/embed",
            json={"inputs": text},
            timeout=self._tei_timeout,
        )
        response.raise_for_status()
        data = response.json()

        # Handle different TEI response formats (list of embeddings or single embedding)
        embedding = data[0] if isinstance(data, list) and data else data

        return self._validate_embedding(embedding)

    def encode_batch(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """Encode batch of texts.

        Args:
            texts: List of texts to encode
            batch_size: Batch size for encoding

        Returns:
            np.ndarray of shape (len(texts), embedding_dim)

        """
        if self._backend == InferenceBackend.TEI:
            return self._encode_batch_via_tei(texts)
        return self._encode_batch_via_model(texts, batch_size)

    def _encode_batch_via_model(self, texts: list[str], batch_size: int) -> np.ndarray:
        """Batch encode using sentence-transformers."""
        model = self._ensure_model()
        embeddings = model.encode(texts, batch_size=batch_size, convert_to_numpy=True)
        return self._validate_embedding(embeddings, batch_rows=len(texts))

    def _encode_batch_via_tei(self, texts: list[str]) -> np.ndarray:
        """Batch encode using TEI server."""
        response = httpx.post(
            f"{self._tei_endpoint}/embed",
            json={"inputs": texts},
            timeout=self._tei_timeout,
        )
        response.raise_for_status()
        return self._validate_embedding(response.json(), batch_rows=len(texts))

    def compute_similarity(self, text_a: str, text_b: str) -> float:
        """Compute cosine similarity between two texts.

        Args:
            text_a: First text
            text_b: Second text

        Returns:
            Cosine similarity in range [0, 1]

        """
        if not text_a.strip() or not text_b.strip():
            return 0.0

        emb_a = self.encode(text_a)
        emb_b = self.encode(text_b)

        norm_a = np.linalg.norm(emb_a)
        norm_b = np.linalg.norm(emb_b)

        if norm_a < NORM_EPSILON or norm_b < NORM_EPSILON:
            return 0.0

        similarity = float(np.dot(emb_a, emb_b) / (norm_a * norm_b))
        return max(0.0, similarity)

    def warm_up(self) -> None:
        """Pre-load the model to avoid cold-start latency."""
        if self._backend != InferenceBackend.TEI:
            self._ensure_model()
            logger.info("Dense model warmed up", model_id=self.model_id)
