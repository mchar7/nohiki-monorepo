"""MUVERA Fixed-Dimensional Encoding."""

from typing import Protocol, cast

import numpy as np
from nohiki_ml_manifest import SemanticRepresentationManifest
from nohiki_observability import get_logger

from nohiki_ml_core import _deps

logger = get_logger(__name__)
_FASTEMBED_MUVERA_MODULE = "fastembed.postprocess.muvera"


class MuveraProtocol(Protocol):
    """Protocol for fastembed Muvera encoder."""

    def process_query(self, tokens: np.ndarray) -> np.ndarray:
        """Process query tokens into FDE."""

    def process_document(self, tokens: np.ndarray) -> np.ndarray:
        """Process document tokens into FDE."""


def _load_muvera_class(module: object, attr_name: str) -> type[MuveraProtocol]:
    return cast(type[MuveraProtocol], getattr(module, attr_name))


class MUVERAEncoder:
    """MUVERA FDE encoder for converting multi-vector to single-vector.

    Uses fastembed's MUVERA implementation for asymmetric encoding.

    CRITICAL:
    - Use encode() with is_query=False for documents (AVG aggregation)
    - Use encode() with is_query=True for queries (SUM aggregation)
    - Distance metric in Qdrant MUST be DOT (not Cosine)
    - Output dimension computed from manifest config (2^k_sim * dim_proj * r_reps)

    Note:
        Requires [inference] extra: uv pip install nohiki-ml-core[inference]
        This encoder always runs locally - no remote backend option.

    """

    def __init__(self, manifest: SemanticRepresentationManifest) -> None:
        """Initialize encoder with manifest.

        Args:
            manifest: Semantic representation configuration

        Raises:
            MissingLocalDependencyError: If fastembed is not installed

        """
        self.manifest = manifest
        self.config = manifest.muvera
        self._encoder: MuveraProtocol | None = None

        # Validate fastembed is available upfront
        _deps.require_fastembed("MUVERA encoder", module_name=_FASTEMBED_MUVERA_MODULE)

        # Compute expected output dimension from config
        self._expected_dim: int = int((2**self.config.k_sim) * self.config.dim_proj * self.config.r_reps)

        logger.info(
            "MUVERA encoder initialized",
            expected_dimension=self._expected_dim,
            k_sim=self.config.k_sim,
            dim_proj=self.config.dim_proj,
            r_reps=self.config.r_reps,
        )

    def _ensure_encoder(self) -> MuveraProtocol:
        """Lazy-load encoder on first use.

        Returns:
            fastembed MUVERA encoder instance

        Raises:
            RuntimeError: If encoder fails to initialize

        """
        if self._encoder is None:
            module = _deps.import_optional_module(
                _FASTEMBED_MUVERA_MODULE,
                _deps.LocalDependency.FASTEMBED,
                "MUVERA encoder",
            )
            try:
                encoder_class = _load_muvera_class(module, "Muvera")
                self._encoder = encoder_class(
                    dim=self.config.dim,
                    k_sim=self.config.k_sim,
                    dim_proj=self.config.dim_proj,
                    r_reps=self.config.r_reps,
                    random_seed=self.config.random_seed,
                )
                logger.info("Muvera model loaded")
            except Exception as e:
                logger.exception("Failed to load Muvera model")
                error_msg = f"Failed to initialize MUVERA encoder: {e}"
                raise RuntimeError(error_msg) from e
        return self._encoder

    def encode(self, tokens: np.ndarray, *, is_query: bool = False) -> np.ndarray:
        """Convert ColBERT tokens to MUVERA FDE.

        Args:
            tokens: ColBERT tokens of shape (num_tokens, token_dim)
            is_query: If True, use SUM aggregation; else AVG aggregation

        Returns:
            np.ndarray of shape (embedding_size,)

        Raises:
            ValueError: If token shape is invalid

        """
        encoder = self._ensure_encoder()

        # Validate token dimensions
        # Tokens should be (num_tokens, token_dim)
        required_ndim = 2
        if tokens.ndim != required_ndim:
            msg = f"Muvera requires {required_ndim}D tokens, got {tokens.ndim}D"
            raise ValueError(msg)

        if tokens.shape[1] != self.config.dim:
            msg = f"Expected token_dim={self.config.dim}, got {tokens.shape[1]}"
            raise ValueError(msg)

        try:
            # Query uses SUM aggregation, Document uses AVG aggregation
            fde = encoder.process_query(tokens) if is_query else encoder.process_document(tokens)

            result = np.array(fde, dtype=np.float32)

            logger.debug(
                "MUVERA encoding completed",
                num_tokens=tokens.shape[0],
                output_dim=result.shape[0],
                is_query=is_query,
            )
        except Exception:
            logger.exception(
                "MUVERA encoding failed",
                token_shape=tokens.shape,
                is_query=is_query,
            )
            raise
        else:
            return result

    @property
    def output_dimension(self) -> int:
        """Get output FDE dimension."""
        return self._expected_dim
