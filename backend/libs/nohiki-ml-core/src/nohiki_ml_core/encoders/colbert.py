"""Direct PyLate ColBERT encoder."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from threading import Lock
from typing import Protocol, cast

import numpy as np
from nohiki_ml_manifest import InferenceBackend, SemanticRepresentationManifest
from nohiki_observability import get_logger

from nohiki_ml_core._deps import require_pylate

logger = get_logger(__name__)
TOKEN_EMBEDDING_NDIM = 2


class ColBERTModel(Protocol):
    """Protocol for PyLate ColBERT models."""

    def encode(
        self,
        texts: list[str],
        *,
        is_query: bool,
        batch_size: int,
    ) -> list[Sequence[Sequence[float]]]:
        """Encode texts into ColBERT token arrays."""


def _load_colbert_model_class(module: object, attr_name: str) -> type[ColBERTModel]:
    return cast(type[ColBERTModel], getattr(module, attr_name))


class ColBERTEncoder:
    """ColBERT token encoder using direct PyLate inference.

    Query and document encoding remain distinct so PyLate applies the
    aggregation semantics required for late-interaction retrieval.
    """

    def __init__(self, manifest: SemanticRepresentationManifest) -> None:
        """Initialize the encoder from a semantic representation manifest.

        Raises:
            ValueError: If the configured backend is not DIRECT.
            MissingLocalDependencyError: If PyLate is not installed.
        """
        self.manifest = manifest
        self.model_id = manifest.late_interaction.model_id
        self.token_dim = manifest.late_interaction.token_dim
        self.max_length = manifest.late_interaction.max_length
        self._backend = manifest.late_interaction.inference_backend
        self._model: ColBERTModel | None = None
        self._inference_lock = Lock()

        if self._backend != InferenceBackend.DIRECT:
            msg = f"ColBERT supports only inference_backend='direct'; got {self._backend.value!r}"
            raise ValueError(msg)
        require_pylate("ColBERT DIRECT backend")

        logger.info(
            "ColBERT encoder initialized",
            model_id=self.model_id,
            token_dim=self.token_dim,
            max_length=self.max_length,
            backend=self._backend.value,
        )

    def _ensure_model(self) -> ColBERTModel:
        """Lazy-load the PyLate model on first use."""
        if self._model is None:
            models_module = importlib.import_module("pylate.models")
            model_class = _load_colbert_model_class(models_module, "ColBERT")
            try:
                self._model = model_class(model_name_or_path=self.model_id)
                logger.info("ColBERT model loaded", model_id=self.model_id)
            except Exception as exc:
                msg = f"Failed to load ColBERT model {self.model_id}: {exc}"
                raise RuntimeError(msg) from exc
        return self._model

    def _validate_tokens(self, value: object) -> np.ndarray:
        """Normalize and validate token embeddings at the backend boundary."""
        result = np.asarray(value, dtype=np.float32)
        if result.ndim != TOKEN_EMBEDDING_NDIM or result.shape[1] != self.token_dim:
            msg = f"ColBERT encoder returned shape {result.shape}; expected (tokens, {self.token_dim})"
            raise ValueError(msg)
        if not np.isfinite(result).all():
            msg = "ColBERT encoder returned non-finite values"
            raise ValueError(msg)
        return result

    def _encode_via_pylate(self, text: str, *, is_query: bool) -> np.ndarray:
        """Encode one text using the matching PyLate encoding mode."""
        try:
            with self._inference_lock:
                model = self._ensure_model()
                tokens = model.encode([text], is_query=is_query, batch_size=1)[0]
            result = self._validate_tokens(tokens)
            logger.debug(
                "Encoded via PyLate",
                num_tokens=result.shape[0],
                token_dim=result.shape[1],
                is_query=is_query,
            )
        except Exception:
            logger.exception("PyLate encoding failed", text_length=len(text))
            raise
        else:
            return result

    def encode_document(self, text: str) -> np.ndarray:
        """Encode a document with PyLate document semantics."""
        return self._encode_via_pylate(text, is_query=False)

    def encode_query(self, text: str) -> np.ndarray:
        """Encode a query with PyLate query semantics."""
        return self._encode_via_pylate(text, is_query=True)

    def encode_batch(
        self,
        texts: list[str],
        *,
        is_query: bool = False,
        batch_size: int = 8,
    ) -> list[np.ndarray]:
        """Encode texts in one PyLate batch with the requested encoding mode."""
        try:
            with self._inference_lock:
                model = self._ensure_model()
                results = model.encode(texts, is_query=is_query, batch_size=batch_size)
        except Exception:
            logger.exception(
                "PyLate batch encoding failed",
                num_texts=len(texts),
                is_query=is_query,
            )
            raise
        if len(results) != len(texts):
            msg = f"ColBERT encoder returned {len(results)} rows for {len(texts)} texts"
            raise ValueError(msg)
        return [self._validate_tokens(result) for result in results]

    def warm_up(self) -> None:
        """Pre-load the PyLate model to avoid first-request cold-start latency."""
        with self._inference_lock:
            self._ensure_model()
        logger.info("ColBERT model warmed up", model_id=self.model_id)
