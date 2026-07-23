"""Unit tests for embedding vector event structures.

Tests the proto structures used in the embedding request/callback pattern
for ML embeddings, verifying correct oneof arm usage, cross-domain embedding
composition (ListingSnapshot, SearchPrefSnapshot), and event correlation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from nohiki.common.v1 import EventMetadata
from nohiki.ml.v1 import (
    DenseData,
    EmbeddingType,
    EmbeddingVector,
    MultiVectorData,
    SparseData,
)


def _build_test_metadata(correlation_id: str | None = None) -> EventMetadata:
    """Build test event metadata with correct field names."""
    return EventMetadata(
        event_id=str(uuid4()),
        timestamp=datetime.now(UTC),
        source_service="test-service",
        correlation_id=correlation_id,
        version="v1",
    )


def _build_dense_embedding(
    dim: int = 1024,
    *,
    model_id: str = "TechWolf/JobBERT-v2",
    collection_version: str = "v1",
) -> EmbeddingVector:
    """Build a dense EmbeddingVector for tests."""
    return EmbeddingVector(
        embedding_type=EmbeddingType.DENSE,
        dense=DenseData(values=[0.1] * dim),
        content_hash="a" * 64,
        model_id=model_id,
        collection_version=collection_version,
    )


def _build_muvera_embedding(
    dim: int = 8192,
    *,
    collection_version: str = "v1",
) -> EmbeddingVector:
    """Build a MUVERA FDE EmbeddingVector for tests."""
    return EmbeddingVector(
        embedding_type=EmbeddingType.MUVERA,
        dense=DenseData(values=[0.05] * dim),
        content_hash="b" * 64,
        model_id="mixedbread-ai/mxbai-edge-colbert-v0-17m",
        collection_version=collection_version,
    )


def _build_sparse_embedding(
    *,
    collection_version: str = "v1",
) -> EmbeddingVector:
    """Build a sparse EmbeddingVector for tests."""
    return EmbeddingVector(
        embedding_type=EmbeddingType.SPARSE,
        sparse=SparseData(
            indices=[1, 5, 10, 50, 100],
            values=[0.8, 0.6, 0.5, 0.3, 0.2],
        ),
        content_hash="c" * 64,
        model_id="Qdrant/minicoil-v1",
        collection_version=collection_version,
    )


# EmbeddingVector oneof geometry tests


class TestEmbeddingVectorOneofGeometry:
    """Test the EmbeddingVector oneof 'data' arm for each embedding type."""

    def test_dense_embedding_structure(self) -> None:
        """Dense embedding carries values in DenseData.values."""
        ev = _build_dense_embedding(dim=1024)

        assert ev.embedding_type == EmbeddingType.DENSE
        assert ev.dense is not None
        assert len(ev.dense.values) == 1024
        assert ev.sparse is None
        assert ev.multi_vector is None

    def test_muvera_embedding_structure(self) -> None:
        """MUVERA FDE uses DenseData with 8192 dims, disambiguated by embedding_type."""
        ev = _build_muvera_embedding()

        assert ev.embedding_type == EmbeddingType.MUVERA
        assert ev.dense is not None
        assert len(ev.dense.values) == 8192
        assert ev.sparse is None

    def test_sparse_embedding_structure(self) -> None:
        """Sparse embedding carries indices and values in SparseData."""
        ev = _build_sparse_embedding()

        assert ev.embedding_type == EmbeddingType.SPARSE
        assert ev.sparse is not None
        assert len(ev.sparse.indices) == 5
        assert len(ev.sparse.values) == 5
        assert ev.dense is None

    def test_colbert_multivector_structure(self) -> None:
        """ColBERT uses MultiVectorData with flattened token embeddings."""
        num_tokens = 12
        token_dim = 48
        ev = EmbeddingVector(
            embedding_type=EmbeddingType.COLBERT,
            multi_vector=MultiVectorData(
                values=[0.01] * (num_tokens * token_dim),
                num_tokens=num_tokens,
                token_dim=token_dim,
            ),
            content_hash="d" * 64,
            model_id="mixedbread-ai/mxbai-edge-colbert-v0-17m",
            collection_version="v1",
        )

        assert ev.embedding_type == EmbeddingType.COLBERT
        assert ev.multi_vector is not None
        assert ev.multi_vector.num_tokens == num_tokens
        assert ev.multi_vector.token_dim == token_dim
        assert len(ev.multi_vector.values) == num_tokens * token_dim
        assert ev.dense is None
        assert ev.sparse is None

    def test_embedding_vector_metadata_fields(self) -> None:
        """content_hash, model_id, and collection_version are carried on every vector."""
        ev = _build_dense_embedding(model_id="custom-model", collection_version="v2")

        assert ev.content_hash == "a" * 64
        assert ev.model_id == "custom-model"
        assert ev.collection_version == "v2"


# Staleness detection via collection_version + model_id


class TestStalenessDetection:
    """Staleness is detected by comparing collection_version or model_id."""

    def test_same_version_not_stale(self) -> None:
        """Two embeddings with identical version + model are compatible."""
        a = _build_dense_embedding(model_id="model-v1", collection_version="v1")
        b = _build_dense_embedding(model_id="model-v1", collection_version="v1")

        assert a.collection_version == b.collection_version
        assert a.model_id == b.model_id

    def test_mismatched_collection_version_detected(self) -> None:
        """Different collection versions indicate stale vectors."""
        old = _build_dense_embedding(collection_version="v1")
        new = _build_dense_embedding(collection_version="v2")

        assert old.collection_version != new.collection_version

    def test_mismatched_model_id_detected(self) -> None:
        """Different model IDs indicate incompatible vectors."""
        a = _build_dense_embedding(model_id="model-v1")
        b = _build_dense_embedding(model_id="model-v2")

        assert a.model_id != b.model_id


# Cross-domain: ListingSnapshot with embeddings


class TestListingSnapshotEmbeddings:
    """Test embeddings composed within ListingSnapshot."""

    def test_listing_snapshot_with_embeddings(self) -> None:
        """ListingSnapshot carries title_embedding + skills_embedding as EmbeddingVector."""
        from nohiki.common.v1 import JobBoardSource, WorkArrangement
        from nohiki.job.listing.v1 import ListingSnapshot

        title_ev = _build_dense_embedding(dim=1024, model_id="title-model")
        skills_ev = _build_dense_embedding(dim=1024, model_id="skills-model")

        snapshot = ListingSnapshot(
            id=str(uuid4()),
            listing_url="https://example.com/job/1",
            source=JobBoardSource.INDEED,
            title="Python Developer",
            company_name="TechCorp",
            description="Building APIs",
            work_arrangement=WorkArrangement.REMOTE,
            title_embedding=title_ev,
            skills_embedding=skills_ev,
            collection_version="v1",
        )

        assert snapshot.title_embedding.embedding_type == EmbeddingType.DENSE
        assert snapshot.title_embedding.model_id == "title-model"
        assert snapshot.skills_embedding.model_id == "skills-model"
        assert snapshot.collection_version == "v1"

    def test_listing_snapshot_with_retrieval_embeddings(self) -> None:
        """ListingSnapshot carries MUVERA + sparse + ColBERT in retrieval_embeddings."""
        from nohiki.common.v1 import JobBoardSource
        from nohiki.job.listing.v1 import ListingSnapshot

        retrieval = [
            _build_muvera_embedding(),
            _build_sparse_embedding(),
            EmbeddingVector(
                embedding_type=EmbeddingType.COLBERT,
                multi_vector=MultiVectorData(
                    values=[0.01] * (10 * 48),
                    num_tokens=10,
                    token_dim=48,
                ),
                content_hash="e" * 64,
                model_id="mixedbread-ai/mxbai-edge-colbert-v0-17m",
                collection_version="v1",
            ),
        ]

        snapshot = ListingSnapshot(
            id=str(uuid4()),
            listing_url="https://example.com/job/2",
            source=JobBoardSource.LINKEDIN,
            title="Backend Engineer",
            company_name="StartupCo",
            description="Building microservices",
            retrieval_embeddings=retrieval,
            collection_version="v1",
        )

        types = {ev.embedding_type for ev in snapshot.retrieval_embeddings}
        assert types == {EmbeddingType.MUVERA, EmbeddingType.SPARSE, EmbeddingType.COLBERT}

    def test_listing_snapshot_without_embeddings(self) -> None:
        """ListingSnapshot before embedding processing has empty/default vectors."""
        from nohiki.common.v1 import JobBoardSource
        from nohiki.job.listing.v1 import ListingSnapshot

        snapshot = ListingSnapshot(
            id=str(uuid4()),
            listing_url="https://example.com/job/3",
            source=JobBoardSource.LINKEDIN,
            title="Backend Engineer",
            company_name="StartupCo",
            description="Building microservices",
        )

        assert len(snapshot.retrieval_embeddings) == 0


# Cross-domain: SearchPrefSnapshot with embeddings


class TestSearchPrefSnapshotEmbeddings:
    """Test embeddings composed within SearchPrefSnapshot."""

    def test_search_pref_with_query_embedding(self) -> None:
        """SearchPrefSnapshot carries an optional query_embedding."""
        from nohiki.user.pref.v1 import SearchPrefSnapshot

        query_ev = _build_dense_embedding(dim=1024, model_id="query-model")

        pref = SearchPrefSnapshot(
            id=str(uuid4()),
            search_keywords=["Python", "Backend", "API"],
            query_embedding=query_ev,
        )

        assert pref.query_embedding is not None
        assert pref.query_embedding.embedding_type == EmbeddingType.DENSE
        assert pref.query_embedding.model_id == "query-model"
        assert pref.search_keywords == ["Python", "Backend", "API"]

    def test_search_pref_with_user_skills_embedding(self) -> None:
        """SearchPrefSnapshot carries a user_skills_embedding."""
        from nohiki.user.pref.v1 import SearchPrefSnapshot

        skills_ev = _build_dense_embedding(dim=1024, model_id="skills-model")

        pref = SearchPrefSnapshot(
            id=str(uuid4()),
            search_keywords=["Software Engineer"],
            user_skills_embedding=skills_ev,
        )

        assert pref.user_skills_embedding.embedding_type == EmbeddingType.DENSE
        assert len(pref.user_skills_embedding.dense.values) == 1024

    def test_search_pref_with_retrieval_embeddings(self) -> None:
        """SearchPrefSnapshot carries query_retrieval_embeddings for multi-stage search."""
        from nohiki.user.pref.v1 import SearchPrefSnapshot

        retrieval = [_build_muvera_embedding(), _build_sparse_embedding()]

        pref = SearchPrefSnapshot(
            id=str(uuid4()),
            search_keywords=["ML Engineer"],
            query_retrieval_embeddings=retrieval,
        )

        assert len(pref.query_retrieval_embeddings) == 2
        types = {ev.embedding_type for ev in pref.query_retrieval_embeddings}
        assert types == {EmbeddingType.MUVERA, EmbeddingType.SPARSE}


# Correlation ID propagation


class TestCorrelationIdPropagation:
    """Test correlation ID and causation chain through events."""

    def test_correlation_id_in_metadata(self) -> None:
        """Correlation ID is propagated in event metadata."""
        correlation_id = str(uuid4())
        metadata = _build_test_metadata(correlation_id)
        assert metadata.correlation_id == correlation_id

    def test_causation_chain(self) -> None:
        """Causation ID links events in a causal chain."""
        correlation_id = str(uuid4())
        first_event_id = str(uuid4())

        first_metadata = EventMetadata(
            event_id=first_event_id,
            timestamp=datetime.now(UTC),
            source_service="service-a",
            correlation_id=correlation_id,
            version="v1",
        )

        second_metadata = EventMetadata(
            event_id=str(uuid4()),
            timestamp=datetime.now(UTC),
            source_service="service-b",
            correlation_id=correlation_id,
            causation_id=first_event_id,
            version="v1",
        )

        assert first_metadata.correlation_id == second_metadata.correlation_id
        assert second_metadata.causation_id == first_metadata.event_id


# Embedding saga request/callback pattern


class TestEmbeddingSagaPattern:
    """Test the embedding saga request/callback pattern structures."""

    def test_saga_context_tracked_via_correlation_id(self) -> None:
        """Correlation ID links request and callback across services."""
        saga_id = str(uuid4())

        request_metadata = EventMetadata(
            event_id=str(uuid4()),
            timestamp=datetime.now(UTC),
            source_service="enrichment-service",
            correlation_id=saga_id,
            version="v1",
        )

        callback_metadata = EventMetadata(
            event_id=str(uuid4()),
            timestamp=datetime.now(UTC),
            source_service="ml-compute-service",
            correlation_id=saga_id,
            causation_id=request_metadata.event_id,
            version="v1",
        )

        assert request_metadata.correlation_id == callback_metadata.correlation_id
        assert callback_metadata.causation_id == request_metadata.event_id

    def test_embedding_batch_tracking_by_collection_version(self) -> None:
        """Multiple EmbeddingVectors in a batch share collection_version."""
        embeddings: dict[str, EmbeddingVector] = {}

        for entity_type in ("title", "skills", "description"):
            embeddings[entity_type] = _build_dense_embedding(
                model_id=f"model-{entity_type}",
                collection_version="v1",
            )

        assert len(embeddings) == 3
        versions = {ev.collection_version for ev in embeddings.values()}
        assert versions == {"v1"}
