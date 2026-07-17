"""Shared test fixtures for qdrant-init tests."""

import pytest
from nohiki_ml_manifest import CollectionConfig, QdrantCollectionSchema, QdrantSparseConfig, QdrantVectorDefinition


def _make_vector(size: int, distance: str = "Cosine", *, on_disk: bool | None = None) -> QdrantVectorDefinition:
    """Build a QdrantVectorDefinition for testing."""
    return QdrantVectorDefinition(size=size, distance=distance, on_disk=on_disk)


def _make_multivector(size: int) -> QdrantVectorDefinition:
    """Build a multivector QdrantVectorDefinition (ColBERT-style) for testing."""
    return QdrantVectorDefinition(
        size=size,
        distance="Cosine",
        multivector_config={"comparator": "max_sim"},
    )


@pytest.fixture
def sparse_collection_config() -> CollectionConfig:
    """CollectionConfig with dense + multivec + sparse vectors (jobs_v1 style).

    Mirrors the real jobs/profiles collections to test the full payload path,
    including sparse_vectors construction.
    """
    schema = QdrantCollectionSchema(
        vectors={
            "muvera": _make_vector(8192, "Dot"),
            "colbert": _make_multivector(48),
        },
        sparse=QdrantSparseConfig(name="sparse", full_scan_threshold=100_000),
        primary_dense_name="muvera",
        colbert_name="colbert",
    )
    return CollectionConfig(version="v1", qdrant=schema)


@pytest.fixture
def dense_only_collection_config() -> CollectionConfig:
    """CollectionConfig with a single dense vector and no sparse (skills_v1 style).

    Used to verify that sparse_vectors is absent from the payload when
    QdrantCollectionSchema.sparse is None.
    """
    schema = QdrantCollectionSchema(
        vectors={"skill_dense": _make_vector(1024, "Cosine")},
        sparse=None,
        primary_dense_name="skill_dense",
    )
    return CollectionConfig(version="v1", qdrant=schema)


@pytest.fixture
def on_disk_collection_config() -> CollectionConfig:
    """CollectionConfig where a vector has on_disk=True.

    Verifies that on_disk propagates into the Qdrant payload via
    model_dump(exclude_none=True).
    """
    schema = QdrantCollectionSchema(
        vectors={"dense": _make_vector(1024, "Cosine", on_disk=True)},
        sparse=None,
        primary_dense_name="dense",
    )
    return CollectionConfig(version="v1", qdrant=schema)


@pytest.fixture
def on_disk_none_collection_config() -> CollectionConfig:
    """CollectionConfig where on_disk is explicitly None (the default).

    Verifies that on_disk is excluded from the Qdrant payload when None,
    deferring to the Qdrant collection-level default.
    """
    schema = QdrantCollectionSchema(
        vectors={"dense": _make_vector(1024, "Cosine", on_disk=None)},
        sparse=None,
        primary_dense_name="dense",
    )
    return CollectionConfig(version="v1", qdrant=schema)
