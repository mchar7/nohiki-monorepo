"""Shared ML inference logic for Nohiki (ColBERT, MUVERA, Sparse).

Manifest schema, caching, and validation are in ``nohiki-ml-manifest``.
Encoders, pipeline, GPU detection, and model caching
that require heavy optional dependencies.

For batch processing with PLAID index (requires [inference] extra)::

    from nohiki_ml_core.batch import PLAIDIndex, PLAIDRetriever
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from nohiki_ml_core._deps import (
    LocalDependency,
    MissingLocalDependencyError,
    check_fastembed_available,
    check_pylate_available,
    require_fastembed,
    require_pylate,
)
from nohiki_ml_core.gpu import (
    ComputeBackend,
    GpuCapabilities,
    GpuNotAvailableError,
    detect_gpu_capabilities,
    get_available_backend,
    require_gpu,
    reset_gpu_detection_cache,
    validate_compute_backend,
)

if TYPE_CHECKING:
    from nohiki_ml_core.encoders.colbert import ColBERTEncoder as ColBERTEncoder
    from nohiki_ml_core.encoders.dense import DenseEncoder as DenseEncoder
    from nohiki_ml_core.encoders.muvera import MUVERAEncoder as MUVERAEncoder
    from nohiki_ml_core.encoders.sparse import SparseEncoder as SparseEncoder
    from nohiki_ml_core.encoders.sparse import SparseVector as SparseVector
    from nohiki_ml_core.model_cache import (
        ModelArchive as ModelArchive,
    )
    from nohiki_ml_core.model_cache import (
        ModelCacheManager as ModelCacheManager,
    )
    from nohiki_ml_core.model_cache import (
        SourceDownloader as SourceDownloader,
    )
    from nohiki_ml_core.pipeline import (
        DenseBatchEncodingResult as DenseBatchEncodingResult,
    )
    from nohiki_ml_core.pipeline import (
        DenseEncodingResult as DenseEncodingResult,
    )
    from nohiki_ml_core.pipeline import (
        EncodingResult as EncodingResult,
    )
    from nohiki_ml_core.pipeline import (
        MLEncodingPipeline as MLEncodingPipeline,
    )

__all__ = [
    "ColBERTEncoder",
    "ComputeBackend",
    "DenseBatchEncodingResult",
    "DenseEncoder",
    "DenseEncodingResult",
    "EncodingResult",
    "GpuCapabilities",
    "GpuNotAvailableError",
    "LocalDependency",
    "MLEncodingPipeline",
    "MUVERAEncoder",
    "MissingLocalDependencyError",
    "ModelArchive",
    "ModelCacheManager",
    "SourceDownloader",
    "SparseEncoder",
    "SparseVector",
    "check_fastembed_available",
    "check_pylate_available",
    "detect_gpu_capabilities",
    "get_available_backend",
    "require_fastembed",
    "require_gpu",
    "require_pylate",
    "reset_gpu_detection_cache",
    "validate_compute_backend",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "ColBERTEncoder": ("nohiki_ml_core.encoders.colbert", "ColBERTEncoder"),
    "DenseEncoder": ("nohiki_ml_core.encoders.dense", "DenseEncoder"),
    "MUVERAEncoder": ("nohiki_ml_core.encoders.muvera", "MUVERAEncoder"),
    "SparseEncoder": ("nohiki_ml_core.encoders.sparse", "SparseEncoder"),
    "SparseVector": ("nohiki_ml_core.encoders.sparse", "SparseVector"),
    "DenseBatchEncodingResult": ("nohiki_ml_core.pipeline", "DenseBatchEncodingResult"),
    "DenseEncodingResult": ("nohiki_ml_core.pipeline", "DenseEncodingResult"),
    "EncodingResult": ("nohiki_ml_core.pipeline", "EncodingResult"),
    "MLEncodingPipeline": ("nohiki_ml_core.pipeline", "MLEncodingPipeline"),
    "ModelCacheManager": ("nohiki_ml_core.model_cache", "ModelCacheManager"),
    "ModelArchive": ("nohiki_ml_core.model_cache", "ModelArchive"),
    "SourceDownloader": ("nohiki_ml_core.model_cache", "SourceDownloader"),
}


def __getattr__(name: str) -> object:
    """Lazy-import components requiring [inference] extra (PEP 562)."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
