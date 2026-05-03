"""Benchmarks for ML manifest and embedding validation (nohiki-ml-core).

Measures manifest construction, collection name resolution, MUVERA dimension
computation, and embedding validation -- operations that run on every scoring
pipeline invocation and embedding callback.
"""

from __future__ import annotations

import pytest
from nohiki_ml_manifest import (
    CollectionConfig,
    CollectionsConfig,
    DenseConfig,
    EmbeddingValidator,
    LateInteractionConfig,
    MaxSimNormalizationConfig,
    MuveraConfig,
    PipelineStageConfig,
    QdrantCollectionSchema,
    QdrantVectorDefinition,
    ScoringConfig,
    SemanticRepresentationManifest,
    SparseConfig,
)

# Manifest fixtures

_QDRANT_SCHEMA = QdrantCollectionSchema(
    vectors={
        "muvera": QdrantVectorDefinition(size=8192, distance="Cosine"),
        "colbert": QdrantVectorDefinition(
            size=48,
            distance="Cosine",
            multivector_config={"comparator": "max_sim"},
        ),
    },
    primary_dense_name="muvera",
    colbert_name="colbert",
)

_COLLECTIONS = CollectionsConfig(
    jobs=CollectionConfig(version="v1", qdrant=_QDRANT_SCHEMA),
    profiles=CollectionConfig(version="v1", qdrant=_QDRANT_SCHEMA),
    skills=CollectionConfig(
        version="v1",
        qdrant=QdrantCollectionSchema(
            vectors={"default": QdrantVectorDefinition(size=1024, distance="Cosine")},
            primary_dense_name="default",
        ),
    ),
)


def _build_manifest() -> SemanticRepresentationManifest:
    return SemanticRepresentationManifest(collections=_COLLECTIONS)


# Manifest construction (once at service startup)


def test_bench_manifest_construction(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full manifest construction with all sub-configs."""
    benchmark(_build_manifest)


def test_bench_maxsim_normalization_config(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark MaxSimNormalizationConfig construction."""
    benchmark(MaxSimNormalizationConfig)


def test_bench_late_interaction_config(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark LateInteractionConfig construction."""
    benchmark(LateInteractionConfig)


def test_bench_muvera_config(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark MuveraConfig construction."""
    benchmark(MuveraConfig)


def test_bench_dense_config(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark DenseConfig construction."""
    benchmark(DenseConfig)


def test_bench_sparse_config(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark SparseConfig construction."""
    benchmark(SparseConfig)


def test_bench_pipeline_stage_config(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark PipelineStageConfig construction."""
    benchmark(PipelineStageConfig)


def test_bench_scoring_config(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark ScoringConfig construction."""
    benchmark(ScoringConfig)


# Collection name resolution (every vector search)


def test_bench_get_collection_name_job(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark collection name lookup for jobs."""
    manifest = _build_manifest()
    benchmark(manifest.get_collection_name, "job")


def test_bench_get_collection_name_profile(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark collection name lookup for profiles."""
    manifest = _build_manifest()
    benchmark(manifest.get_collection_name, "profile")


def test_bench_get_collection_name_skill(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark collection name lookup for skills."""
    manifest = _build_manifest()
    benchmark(manifest.get_collection_name, "skill")


def test_bench_muvera_output_dimension(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark MUVERA output dimension computation (cached_property)."""
    manifest = _build_manifest()
    # First access computes, subsequent are cached
    _ = manifest.muvera_output_dimension
    benchmark(lambda: manifest.muvera_output_dimension)


# Embedding validation (every embedding callback)


def test_bench_validate_collection_version_match(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark version validation when versions match (happy path)."""
    manifest = _build_manifest()
    validator = EmbeddingValidator(manifest)
    benchmark(validator.validate_collection_version, "job", "v1")


def test_bench_validate_muvera_dimension(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark MUVERA dimension validation (happy path)."""
    manifest = _build_manifest()
    validator = EmbeddingValidator(manifest)
    benchmark(validator.validate_muvera_dimension, 8192)


def test_bench_validate_dense_dimension(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark dense dimension validation (happy path)."""
    manifest = _build_manifest()
    validator = EmbeddingValidator(manifest)
    benchmark(validator.validate_dense_dimension, 1024)


def test_bench_validate_colbert_token_dim(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark ColBERT token dimension validation (happy path)."""
    manifest = _build_manifest()
    validator = EmbeddingValidator(manifest)
    benchmark(validator.validate_colbert_token_dimension, 48)


_MUVERA_VALUES = [0.1] * 8192


def test_bench_validate_full_muvera_embedding(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark full MUVERA embedding validation (version + dimension)."""
    manifest = _build_manifest()
    validator = EmbeddingValidator(manifest)
    benchmark(
        validator.validate_embedding,
        _MUVERA_VALUES,
        "job",
        "v1",
        "muvera",
        raise_on_error=False,
    )


def test_bench_validate_full_dense_embedding(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark full dense embedding validation."""
    manifest = _build_manifest()
    validator = EmbeddingValidator(manifest)
    dense_values = [0.1] * 1024
    benchmark(
        validator.validate_embedding,
        dense_values,
        "skill",
        "v1",
        "dense",
        raise_on_error=False,
    )
