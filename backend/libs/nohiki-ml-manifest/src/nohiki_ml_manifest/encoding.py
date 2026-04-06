"""ML encoder model configuration schemas.

Defines inference backends and per-encoder configuration for ColBERT late
interaction, MUVERA fixed-dimensional encoding, sparse (MiniCOIL), and dense
(sentence-transformer) models.  Each config carries its own normalization
constants derived from empirical model calibration.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cached_property
from typing import Self

from pydantic import BaseModel, Field, computed_field, model_validator

from nohiki_ml_manifest.calibration import DenseCalibrationConfig, MaxSimCalibrationConfig


class InferenceBackend(StrEnum):
    """Controls where embeddings are computed.

    DIRECT: In-process via sentence-transformers/PyLate (requires heavy deps).
    TEI   : Remote Text Embeddings Inference server via gRPC.
    ONNX  : In-process ONNX Runtime with optional int8 quantization.
    """

    DIRECT = "direct"
    TEI = "tei"
    ONNX = "onnx"


class MaxSimNormalizationConfig(BaseModel):
    """Model-intrinsic normalization constants for ColBERT MaxSim scores.

    Derived from empirical analysis of per-token cosine similarity
    distributions, which are stable across query lengths (CLT).
    Defaults match the production-calibrated values in the manifest JSON.
    """

    per_token_sim_p5: float = Field(default=0.8634, ge=0.0, le=1.0)
    per_token_sim_p95: float = Field(default=0.9999, ge=0.0, le=1.0)
    per_token_sim_mean: float = Field(default=0.9355, ge=0.0, le=1.0)
    per_token_sim_std: float = Field(default=0.0396, ge=0.0, le=1.0)
    averaged_score_min: float = Field(default=0.92, ge=0.0, le=1.0)
    averaged_score_max: float = Field(default=0.95, ge=0.0, le=1.0)
    calibration: MaxSimCalibrationConfig | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_ranges(self) -> Self:
        if self.per_token_sim_p95 <= self.per_token_sim_p5:
            msg = "per_token_sim_p95 must be greater than per_token_sim_p5"
            raise ValueError(msg)
        if self.averaged_score_max <= self.averaged_score_min:
            msg = "averaged_score_max must be greater than averaged_score_min"
            raise ValueError(msg)
        return self

    @computed_field
    @cached_property
    def averaged_score_range(self) -> float:
        """Normalization range for quality-based scaling."""
        return self.averaged_score_max - self.averaged_score_min


class LateInteractionConfig(BaseModel):
    """ColBERT late-interaction model configuration."""

    model_id: str = Field(default="mixedbread-ai/mxbai-edge-colbert-v0-17m")
    token_dim: int = Field(default=48, ge=1)
    max_length: int = Field(default=32000, ge=1)
    normalization: MaxSimNormalizationConfig = Field(default_factory=MaxSimNormalizationConfig)
    inference_backend: InferenceBackend = Field(default=InferenceBackend.DIRECT)
    tei_endpoint: str | None = Field(default=None)
    tei_timeout_seconds: float = Field(default=30.0, gt=0.0)


class MuveraConfig(BaseModel):
    """MUVERA Fixed-Dimensional Encoding configuration.

    Output dimension: ``2^k_sim * dim_proj * r_reps``  (default: 8192).
    """

    dim: int = Field(default=48, ge=1)
    k_sim: int = Field(default=6, ge=1)
    dim_proj: int = Field(default=16, ge=1)
    r_reps: int = Field(default=8, ge=1)
    random_seed: int = Field(default=42)


class SparseNormalizationConfig(BaseModel):
    """Model-intrinsic normalization constants for sparse dot-product scores.

    Percentiles define the expected score range for linear normalization
    of MiniCOIL-style learned sparse embeddings.
    """

    score_p10: float = Field(default=1.5, ge=0.0)
    score_p90: float = Field(default=5.5, ge=0.0)

    @model_validator(mode="after")
    def _validate_range(self) -> Self:
        if self.score_p90 <= self.score_p10:
            msg = "score_p90 must be greater than score_p10"
            raise ValueError(msg)
        return self

    @computed_field
    @cached_property
    def score_range(self) -> float:
        """Normalization range (P90 - P10)."""
        return self.score_p90 - self.score_p10


class SparseConfig(BaseModel):
    """Sparse vector configuration for MiniCOIL-style learned sparse embeddings."""

    enabled: bool = Field(default=True)
    model_id: str = Field(default="Qdrant/minicoil-v1")
    normalization: SparseNormalizationConfig = Field(default_factory=SparseNormalizationConfig)


class DenseNormalizationConfig(BaseModel):
    """Model-intrinsic normalization constants for dense sentence embeddings.

    Operational thresholds calibrated from skill-to-skill similarity pairs.
    ``auto_match_threshold`` is chosen where precision = 100% (zero false positives).
    Calibration provenance is tracked separately in the ``calibration`` field.
    """

    auto_match_threshold: float = Field(default=0.83, ge=0.0, le=1.0)
    uncertain_min_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    calibration: DenseCalibrationConfig | None = Field(default=None)


class DenseConfig(BaseModel):
    """Dense sentence embedding configuration.

    Supports DIRECT (sentence-transformers), ONNX (quantized), and TEI
    (remote server) inference backends.
    """

    enabled: bool = Field(default=True)
    model_id: str = Field(default="TechWolf/JobBERT-v2")
    embedding_dim: int = Field(default=1024, ge=1)
    max_length: int = Field(default=64, ge=1)
    trust_remote_code: bool = Field(default=False)
    device: str = Field(
        default="cpu",
        description="Device for model inference. Explicitly set to avoid meta tensor issues.",
    )
    normalization: DenseNormalizationConfig = Field(default_factory=DenseNormalizationConfig)
    inference_backend: InferenceBackend = Field(default=InferenceBackend.DIRECT)
    onnx_file_name: str | None = Field(default=None)
    tei_endpoint: str | None = Field(default=None)
    tei_timeout_seconds: float = Field(default=30.0, gt=0.0)
