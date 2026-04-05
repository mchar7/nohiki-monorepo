"""Tests for PLAID batch scoring module."""

from __future__ import annotations

import dataclasses
import tempfile
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from nohiki_ml_core.batch.plaid_index import (
    _MIN_DOCS_FOR_CLUSTER_METRICS,
    _MIN_TOKENS_FOR_KMEANS,
    PLAIDIndex,
    PLAIDIndexConfig,
    PLAIDRetriever,
    RetrievalResult,
    _compute_k_from_tokens,
)


@pytest.fixture
def mock_require_pylate() -> Generator[None]:
    """Mock require_pylate to allow PLAIDIndex operations without pylate installed."""
    with patch("nohiki_ml_core.batch.plaid_index.require_pylate"):
        yield


class TestPLAIDIndexConfig:
    """Tests for PLAIDIndexConfig dataclass."""

    def test_required_fields(self) -> None:
        """Test config with required fields only."""
        config = PLAIDIndexConfig(
            index_folder="/data/indexes",
            index_name="test_index",
        )
        assert config.index_folder == "/data/indexes"
        assert config.index_name == "test_index"

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = PLAIDIndexConfig(
            index_folder="/data",
            index_name="test",
        )
        assert config.override is False
        assert config.kmeans_niters == 4
        assert config.nbits == 2
        assert config.n_ivf_probe == 8
        assert config.n_full_scores == 8192
        assert config.max_points_per_centroid == 256

    def test_custom_values(self) -> None:
        """Test config with custom values."""
        config = PLAIDIndexConfig(
            index_folder="/custom/path",
            index_name="custom_index",
            override=True,
            kmeans_niters=8,
            nbits=4,
            n_ivf_probe=16,
            n_full_scores=4096,
            max_points_per_centroid=512,
        )
        assert config.override is True
        assert config.kmeans_niters == 8
        assert config.nbits == 4
        assert config.n_ivf_probe == 16
        assert config.n_full_scores == 4096
        assert config.max_points_per_centroid == 512

    def test_is_frozen_dataclass(self) -> None:
        """Test that config is a frozen dataclass."""
        assert dataclasses.is_dataclass(PLAIDIndexConfig)
        params = getattr(PLAIDIndexConfig, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestRetrievalResult:
    """Tests for RetrievalResult dataclass."""

    def test_fields(self) -> None:
        """Test result fields."""
        result = RetrievalResult(
            document_id="doc-123",
            score=0.95,
        )
        assert result.document_id == "doc-123"
        assert abs(result.score - 0.95) < 1e-9

    def test_is_frozen_dataclass(self) -> None:
        """Test that result is a frozen dataclass."""
        assert dataclasses.is_dataclass(RetrievalResult)
        params = getattr(RetrievalResult, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestPLAIDIndex:
    """Tests for PLAIDIndex class."""

    @pytest.fixture
    def config(self) -> Generator[PLAIDIndexConfig]:
        """Create test config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield PLAIDIndexConfig(
                index_folder=tmpdir,
                index_name="test_index",
                override=True,
            )

    @pytest.fixture
    def mock_plaid_index(self) -> MagicMock:
        """Create mock PLAID index from pylate."""
        mock_index = MagicMock()
        mock_index.add_documents = MagicMock()
        return mock_index

    def test_initialization(self, config: PLAIDIndexConfig) -> None:
        """Test PLAIDIndex initialization."""
        index = PLAIDIndex(config=config)
        assert index.config is config
        assert index._index is None

    def test_index_path_property(self, config: PLAIDIndexConfig) -> None:
        """Test index_path property returns correct path."""
        index = PLAIDIndex(config=config)
        expected = Path(config.index_folder) / config.index_name
        assert index.index_path == expected

    def test_exists_returns_false_for_new_index(self, config: PLAIDIndexConfig) -> None:
        """Test exists() returns False for non-existent index."""
        index = PLAIDIndex(config=config)
        assert index.exists() is False

    def test_ensure_index_lazy_loading(
        self,
        config: PLAIDIndexConfig,
        mock_plaid_index: MagicMock,
        mock_require_pylate: None,
    ) -> None:
        """Test ensure_index() lazily loads the index."""
        index = PLAIDIndex(config=config)

        mock_indexes_module = SimpleNamespace(PLAID=MagicMock(return_value=mock_plaid_index))
        with patch(
            "nohiki_ml_core.batch.plaid_index.importlib.import_module",
            return_value=mock_indexes_module,
        ) as mock_import:
            result = index.ensure_index()

            assert result is mock_plaid_index
            mock_import.assert_called_once_with("pylate.indexes")
            mock_indexes_module.PLAID.assert_called_once_with(
                index_folder=config.index_folder,
                index_name=config.index_name,
                override=config.override,
                kmeans_niters=config.kmeans_niters,
                nbits=config.nbits,
                n_ivf_probe=config.n_ivf_probe,
                n_full_scores=config.n_full_scores,
                max_points_per_centroid=config.max_points_per_centroid,
            )

    def test_ensure_index_caches_result(
        self,
        config: PLAIDIndexConfig,
        mock_plaid_index: MagicMock,
        mock_require_pylate: None,
    ) -> None:
        """Test ensure_index() caches the index instance."""
        index = PLAIDIndex(config=config)

        mock_indexes_module = SimpleNamespace(PLAID=MagicMock(return_value=mock_plaid_index))
        with patch(
            "nohiki_ml_core.batch.plaid_index.importlib.import_module",
            return_value=mock_indexes_module,
        ) as mock_import:
            first_result = index.ensure_index()
            second_result = index.ensure_index()

            assert first_result is second_result
            mock_import.assert_called_once_with("pylate.indexes")
            mock_indexes_module.PLAID.assert_called_once()

    def test_ensure_index_missing_pylate(self, config: PLAIDIndexConfig) -> None:
        """Test ensure_index() raises MissingLocalDependencyError when pylate not installed."""
        from nohiki_ml_core._deps import MissingLocalDependencyError

        index = PLAIDIndex(config=config)

        with (
            patch("nohiki_ml_core._deps.check_pylate_available", return_value=False),
            pytest.raises(MissingLocalDependencyError, match="PLAID index"),
        ):
            index.ensure_index()

    def test_build_success(self, config: PLAIDIndexConfig, mock_plaid_index: MagicMock) -> None:
        """Test build() successfully indexes documents."""
        index = PLAIDIndex(config=config)
        index._index = mock_plaid_index

        document_ids = ["doc-1", "doc-2", "doc-3"]
        embeddings = [np.random.default_rng(42).random((10, 128)).astype(np.float32) for _ in range(3)]

        index.build(document_ids, embeddings)

        mock_plaid_index.add_documents.assert_called_once()
        call_kwargs = mock_plaid_index.add_documents.call_args[1]
        assert call_kwargs["documents_ids"] == document_ids
        assert len(call_kwargs["documents_embeddings"]) == 3

    def test_build_mismatched_lengths(self, config: PLAIDIndexConfig) -> None:
        """Test build() raises ValueError for mismatched lengths."""
        index = PLAIDIndex(config=config)

        document_ids = ["doc-1", "doc-2"]
        embeddings = [np.zeros((10, 128))]

        with pytest.raises(ValueError, match="Mismatched lengths"):
            index.build(document_ids, embeddings)

    def test_build_exception_handling(self, config: PLAIDIndexConfig, mock_plaid_index: MagicMock) -> None:
        """Test build() properly propagates exceptions."""
        index = PLAIDIndex(config=config)
        index._index = mock_plaid_index
        mock_plaid_index.add_documents.side_effect = RuntimeError("Index error")

        document_ids = ["doc-1"]
        embeddings = [np.zeros((10, 128))]

        with pytest.raises(RuntimeError, match="Index error"):
            index.build(document_ids, embeddings)

    def test_add_documents_success(self, config: PLAIDIndexConfig, mock_plaid_index: MagicMock) -> None:
        """Test add_documents() successfully adds to existing index."""
        index = PLAIDIndex(config=config)
        index._index = mock_plaid_index

        document_ids = ["doc-4", "doc-5"]
        embeddings = [np.random.default_rng(42).random((10, 128)).astype(np.float32) for _ in range(2)]

        index.add_documents(document_ids, embeddings)

        mock_plaid_index.add_documents.assert_called_once()

    def test_add_documents_mismatched_lengths(self, config: PLAIDIndexConfig) -> None:
        """Test add_documents() raises ValueError for mismatched lengths."""
        index = PLAIDIndex(config=config)

        document_ids = ["doc-1", "doc-2", "doc-3"]
        embeddings = [np.zeros((10, 128))]

        with pytest.raises(ValueError, match="Mismatched lengths"):
            index.add_documents(document_ids, embeddings)

    def test_add_documents_exception_handling(self, config: PLAIDIndexConfig, mock_plaid_index: MagicMock) -> None:
        """Test add_documents() properly propagates exceptions."""
        index = PLAIDIndex(config=config)
        index._index = mock_plaid_index
        mock_plaid_index.add_documents.side_effect = RuntimeError("Write error")

        document_ids = ["doc-1"]
        embeddings = [np.zeros((10, 128))]

        with pytest.raises(RuntimeError, match="Write error"):
            index.add_documents(document_ids, embeddings)

    def test_load_existing_index(self, mock_require_pylate: None) -> None:
        """Test load() loads existing index from disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = PLAIDIndexConfig(
                index_folder=tmpdir,
                index_name="existing_index",
            )
            index_path = Path(tmpdir) / "existing_index"
            index_path.mkdir(parents=True)

            mock_plaid_instance = MagicMock()
            mock_plaid_class = MagicMock(return_value=mock_plaid_instance)
            mock_indexes_module = SimpleNamespace(PLAID=mock_plaid_class)

            with patch(
                "nohiki_ml_core.batch.plaid_index.importlib.import_module",
                return_value=mock_indexes_module,
            ) as mock_import:
                loaded = PLAIDIndex.load(config)

                assert loaded.config.override is False
                mock_import.assert_called_once_with("pylate.indexes")
                mock_plaid_class.assert_called_once()

    def test_load_nonexistent_index(self) -> None:
        """Test load() raises FileNotFoundError for non-existent index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = PLAIDIndexConfig(
                index_folder=tmpdir,
                index_name="nonexistent",
            )

            with pytest.raises(FileNotFoundError, match="Index not found"):
                PLAIDIndex.load(config)

    def test_load_preserves_all_config_fields(self, mock_require_pylate: None) -> None:
        """Test load() preserves all config fields except override."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = PLAIDIndexConfig(
                index_folder=tmpdir,
                index_name="test_index",
                override=True,
                kmeans_niters=8,
                nbits=4,
                n_ivf_probe=16,
                n_full_scores=4096,
                max_points_per_centroid=512,
            )
            index_path = Path(tmpdir) / "test_index"
            index_path.mkdir(parents=True)

            mock_plaid_instance = MagicMock()
            mock_plaid_class = MagicMock(return_value=mock_plaid_instance)
            mock_indexes_module = SimpleNamespace(PLAID=mock_plaid_class)

            with patch(
                "nohiki_ml_core.batch.plaid_index.importlib.import_module",
                return_value=mock_indexes_module,
            ):
                loaded = PLAIDIndex.load(config)

                assert loaded.config.override is False
                assert loaded.config.kmeans_niters == 8
                assert loaded.config.nbits == 4
                assert loaded.config.n_ivf_probe == 16
                assert loaded.config.n_full_scores == 4096
                assert loaded.config.max_points_per_centroid == 512

    def test_load_forces_override_false(self, mock_require_pylate: None) -> None:
        """Test load() forces override=False regardless of input config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = PLAIDIndexConfig(
                index_folder=tmpdir,
                index_name="test_index",
                override=True,
            )
            index_path = Path(tmpdir) / "test_index"
            index_path.mkdir(parents=True)

            mock_plaid_instance = MagicMock()
            mock_plaid_class = MagicMock(return_value=mock_plaid_instance)
            mock_indexes_module = SimpleNamespace(PLAID=mock_plaid_class)

            with patch(
                "nohiki_ml_core.batch.plaid_index.importlib.import_module",
                return_value=mock_indexes_module,
            ):
                loaded = PLAIDIndex.load(config)

                assert loaded.config.override is False


class TestPLAIDRetriever:
    """Tests for PLAIDRetriever class."""

    @pytest.fixture
    def mock_plaid_index(self) -> MagicMock:
        """Create mock PLAID index."""
        return MagicMock()

    @pytest.fixture
    def mock_index_wrapper(self, mock_plaid_index: MagicMock) -> Generator[PLAIDIndex]:
        """Create PLAIDIndex with mocked internal index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = PLAIDIndexConfig(
                index_folder=tmpdir,
                index_name="test",
            )
            wrapper = PLAIDIndex(config=config)
            wrapper._index = mock_plaid_index
            yield wrapper

    @pytest.fixture
    def mock_retriever(self) -> MagicMock:
        """Create mock ColBERT retriever."""
        mock_ret = MagicMock()
        mock_ret.retrieve.return_value = [
            [
                {"id": "doc-1", "score": 0.95},
                {"id": "doc-2", "score": 0.85},
            ],
        ]
        return mock_ret

    def test_initialization(self, mock_index_wrapper: PLAIDIndex) -> None:
        """Test PLAIDRetriever initialization."""
        retriever = PLAIDRetriever(index=mock_index_wrapper)
        assert retriever.index is mock_index_wrapper
        assert retriever._retriever is None

    def test_ensure_retriever_lazy_loading(
        self,
        mock_index_wrapper: PLAIDIndex,
        mock_retriever: MagicMock,
        mock_require_pylate: None,
    ) -> None:
        """Test _ensure_retriever() lazily loads the retriever."""
        retriever = PLAIDRetriever(index=mock_index_wrapper)

        mock_colbert_class = MagicMock(return_value=mock_retriever)
        with patch(
            "nohiki_ml_core.batch.plaid_index.importlib.import_module",
            return_value=SimpleNamespace(ColBERT=mock_colbert_class),
        ) as mock_import:
            result = retriever._ensure_retriever()

            assert result is mock_retriever
            mock_import.assert_called_once_with("pylate.retrieve")
            mock_colbert_class.assert_called_once()

    def test_ensure_retriever_caches_result(
        self,
        mock_index_wrapper: PLAIDIndex,
        mock_retriever: MagicMock,
        mock_require_pylate: None,
    ) -> None:
        """Test _ensure_retriever() caches the retriever instance."""
        retriever = PLAIDRetriever(index=mock_index_wrapper)

        mock_colbert_class = MagicMock(return_value=mock_retriever)
        with patch(
            "nohiki_ml_core.batch.plaid_index.importlib.import_module",
            return_value=SimpleNamespace(ColBERT=mock_colbert_class),
        ) as mock_import:
            first_result = retriever._ensure_retriever()
            second_result = retriever._ensure_retriever()

            assert first_result is second_result
            mock_import.assert_called_once_with("pylate.retrieve")
            mock_colbert_class.assert_called_once()

    def test_ensure_retriever_missing_pylate(self, mock_index_wrapper: PLAIDIndex) -> None:
        """Test _ensure_retriever() raises MissingLocalDependencyError when pylate not installed."""
        from nohiki_ml_core._deps import MissingLocalDependencyError

        retriever = PLAIDRetriever(index=mock_index_wrapper)

        with (
            patch("nohiki_ml_core._deps.check_pylate_available", return_value=False),
            pytest.raises(MissingLocalDependencyError, match="PLAID retriever"),
        ):
            retriever._ensure_retriever()

    def test_retrieve_single_query(self, mock_index_wrapper: PLAIDIndex, mock_retriever: MagicMock) -> None:
        """Test retrieve() for single query."""
        retriever = PLAIDRetriever(index=mock_index_wrapper)
        retriever._retriever = mock_retriever

        query_emb = np.random.default_rng(42).random((20, 128)).astype(np.float32)
        results = retriever.retrieve(query_emb, k=10)

        assert len(results) == 2
        assert results[0].document_id == "doc-1"
        assert abs(results[0].score - 0.95) < 1e-9
        assert mock_retriever.retrieve.call_args.kwargs["subset"] is None

    def test_retrieve_forwards_subset_to_retrieve_batch(
        self, mock_index_wrapper: PLAIDIndex, mock_retriever: MagicMock
    ) -> None:
        """Test retrieve() forwards subset parameter to retrieve_batch."""
        retriever = PLAIDRetriever(index=mock_index_wrapper)
        retriever._retriever = mock_retriever

        query_emb = np.random.default_rng(42).random((20, 128)).astype(np.float32)
        results = retriever.retrieve(query_emb, k=5, subset=["doc-1", "doc-2"])

        assert len(results) == 2
        assert mock_retriever.retrieve.call_args.kwargs["subset"] == ["doc-1", "doc-2"]

    def test_retrieve_batch_success(self, mock_index_wrapper: PLAIDIndex, mock_retriever: MagicMock) -> None:
        """Test retrieve_batch() for multiple queries."""
        mock_retriever.retrieve.return_value = [
            [{"id": "doc-1", "score": 0.95}],
            [{"id": "doc-2", "score": 0.85}],
        ]
        retriever = PLAIDRetriever(index=mock_index_wrapper)
        retriever._retriever = mock_retriever

        queries = [np.random.default_rng(42).random((20, 128)).astype(np.float32) for _ in range(2)]

        results = retriever.retrieve_batch(queries, k=10)

        assert len(results) == 2
        assert len(results[0]) == 1
        assert len(results[1]) == 1
        assert results[0][0].document_id == "doc-1"
        assert results[1][0].document_id == "doc-2"

    def test_retrieve_batch_passes_subset_to_internal_retriever(
        self, mock_index_wrapper: PLAIDIndex, mock_retriever: MagicMock
    ) -> None:
        """Test retrieve_batch() passes subset parameter to internal retriever."""
        mock_retriever.retrieve.return_value = [
            [{"id": "doc-x", "score": 0.90}],
        ]
        retriever = PLAIDRetriever(index=mock_index_wrapper)
        retriever._retriever = mock_retriever

        queries = [np.random.default_rng(42).random((20, 128)).astype(np.float32)]
        retriever.retrieve_batch(queries, k=5, subset=["doc-x"])

        assert mock_retriever.retrieve.call_args.kwargs["subset"] == ["doc-x"]

    def test_retrieve_batch_subset_none_by_default(
        self, mock_index_wrapper: PLAIDIndex, mock_retriever: MagicMock
    ) -> None:
        """Test retrieve_batch() defaults subset to None."""
        mock_retriever.retrieve.return_value = [
            [{"id": "doc-1", "score": 0.95}],
        ]
        retriever = PLAIDRetriever(index=mock_index_wrapper)
        retriever._retriever = mock_retriever

        queries = [np.random.default_rng(42).random((20, 128)).astype(np.float32)]
        retriever.retrieve_batch(queries, k=5)

        assert mock_retriever.retrieve.call_args.kwargs["subset"] is None

    def test_retrieve_batch_empty_input(self, mock_index_wrapper: PLAIDIndex) -> None:
        """Test retrieve_batch() with empty input returns empty list."""
        retriever = PLAIDRetriever(index=mock_index_wrapper)

        results = retriever.retrieve_batch([], k=10)

        assert results == []

    def test_retrieve_batch_exception_handling(self, mock_index_wrapper: PLAIDIndex, mock_retriever: MagicMock) -> None:
        """Test retrieve_batch() properly propagates exceptions."""
        mock_retriever.retrieve.side_effect = RuntimeError("Search failed")
        retriever = PLAIDRetriever(index=mock_index_wrapper)
        retriever._retriever = mock_retriever

        queries = [np.zeros((20, 128))]

        with pytest.raises(RuntimeError, match="Search failed"):
            retriever.retrieve_batch(queries, k=10)

    def test_score_pairs(self, mock_index_wrapper: PLAIDIndex, mock_retriever: MagicMock) -> None:
        """Test score_pairs() uses subset and correct k value."""
        mock_retriever.retrieve.return_value = [
            [
                {"id": "doc-1", "score": 0.95},
                {"id": "doc-2", "score": 0.85},
                {"id": "doc-3", "score": 0.75},
            ],
        ]
        retriever = PLAIDRetriever(index=mock_index_wrapper)
        retriever._retriever = mock_retriever

        queries = [np.random.default_rng(42).random((20, 128)).astype(np.float32)]
        document_ids = ["doc-1", "doc-3"]

        results = retriever.score_pairs(queries, document_ids)

        assert len(results) == 1
        assert len(results[0]) == 2
        assert results[0][0] == ("doc-1", 0.95)
        assert results[0][1] == ("doc-3", 0.75)
        assert mock_retriever.retrieve.call_args.kwargs["k"] == 2
        assert mock_retriever.retrieve.call_args.kwargs["subset"] == ["doc-1", "doc-3"]

    def test_score_pairs_no_matching_docs(self, mock_index_wrapper: PLAIDIndex, mock_retriever: MagicMock) -> None:
        """Test score_pairs() when no documents match."""
        mock_retriever.retrieve.return_value = [
            [{"id": "doc-1", "score": 0.95}],
        ]
        retriever = PLAIDRetriever(index=mock_index_wrapper)
        retriever._retriever = mock_retriever

        queries = [np.zeros((20, 128))]
        document_ids = ["doc-99"]

        results = retriever.score_pairs(queries, document_ids)

        assert len(results) == 1
        assert len(results[0]) == 0
        assert mock_retriever.retrieve.call_args.kwargs["subset"] == ["doc-99"]

    def test_score_pairs_does_not_overfetch(self, mock_index_wrapper: PLAIDIndex, mock_retriever: MagicMock) -> None:
        """Test score_pairs() uses k=len(document_ids), not k*10 (regression guard)."""
        mock_retriever.retrieve.return_value = [
            [{"id": "doc-1", "score": 0.95}, {"id": "doc-2", "score": 0.85}],
        ]
        retriever = PLAIDRetriever(index=mock_index_wrapper)
        retriever._retriever = mock_retriever

        queries = [np.zeros((20, 128))]
        document_ids = ["doc-1", "doc-2"]

        retriever.score_pairs(queries, document_ids)

        assert mock_retriever.retrieve.call_args.kwargs["k"] == 2
        assert mock_retriever.retrieve.call_args.kwargs["subset"] == ["doc-1", "doc-2"]


class TestComputeK:
    """Tests for _compute_k_from_tokens function."""

    def test_small_corpus(self) -> None:
        """Test K computation for small corpus."""
        # 16 * sqrt(100) = 160, log2(160) ≈ 7.32, floor = 7, 2^7 = 128; clamp: min(128, 99) = 99
        assert _compute_k_from_tokens(100) == 99

    def test_medium_corpus(self) -> None:
        """Test K computation for medium corpus."""
        # 16 * sqrt(10000) = 1600, log2(1600) ≈ 10.64, floor = 10, 2^10 = 1024; clamp: min(1024, 9999) = 1024
        assert _compute_k_from_tokens(10000) == 1024

    def test_clamps_at_1_for_single_token(self) -> None:
        """Test returns 1 for single token."""
        assert _compute_k_from_tokens(1) == 1

    def test_clamps_at_zero_tokens(self) -> None:
        """Test returns 1 for zero tokens (edge case)."""
        assert _compute_k_from_tokens(0) == 1

    def test_clamps_below_total_tokens(self) -> None:
        """Test K is clamped below total_tokens."""
        # For small inputs, K should not exceed total_tokens - 1
        result = _compute_k_from_tokens(5)
        assert result <= 4
        assert result >= 1

    def test_result_is_positive_int(self) -> None:
        """Test result is always a positive integer."""
        for n in [1, 10, 100, 1000, 10000]:
            result = _compute_k_from_tokens(n)
            assert isinstance(result, int)
            assert result >= 1


class TestComputeClusterThreshold:
    """Tests for PLAIDIndex.compute_cluster_threshold static method."""

    def test_returns_float(self) -> None:
        """Test returns a float value with real sklearn."""
        from sklearn.cluster import MiniBatchKMeans

        token_arrays = [np.random.default_rng(42).random((10, 8)).astype(np.float32) for _ in range(3)]
        with patch(
            "nohiki_ml_core.batch.plaid_index.get_minibatch_kmeans",
            return_value=MiniBatchKMeans,
        ):
            result = PLAIDIndex.compute_cluster_threshold(token_arrays)
        assert isinstance(result, float)
        assert result > 0.0

    def test_calls_get_minibatch_kmeans(self) -> None:
        """Test get_minibatch_kmeans is called with correct feature string."""
        mock_km_class = MagicMock()
        mock_km_instance = MagicMock()
        mock_km_instance.cluster_centers_ = np.array([[0.0]])
        mock_km_instance.labels_ = np.array([0, 0, 0])
        mock_km_class.return_value = mock_km_instance

        with patch(
            "nohiki_ml_core.batch.plaid_index.get_minibatch_kmeans",
            return_value=mock_km_class,
        ) as mock_get_kmeans:
            PLAIDIndex.compute_cluster_threshold([np.zeros((3, 1))])
            mock_get_kmeans.assert_called_once_with("PLAID cluster threshold computation")

    def test_degenerate_single_token_returns_zero(self) -> None:
        """Test returns 0.0 for degenerate single-token input."""
        from sklearn.cluster import MiniBatchKMeans

        with patch(
            "nohiki_ml_core.batch.plaid_index.get_minibatch_kmeans",
            return_value=MiniBatchKMeans,
        ):
            result = PLAIDIndex.compute_cluster_threshold([np.zeros((1, 8))])
            assert result == 0.0

    def test_raises_when_sklearn_missing(self) -> None:
        """Test raises MissingLocalDependencyError when sklearn not available."""
        from nohiki_ml_core._deps import MissingLocalDependencyError

        with (
            patch("nohiki_ml_core._deps.check_sklearn_available", return_value=False),
            pytest.raises(MissingLocalDependencyError),
        ):
            PLAIDIndex.compute_cluster_threshold([np.zeros((10, 8))])

    def test_sampling_path_executes_for_large_corpus(self) -> None:
        """Test sampling branch is taken when total_tokens exceeds sample_size."""
        from sklearn.cluster import MiniBatchKMeans

        # 110 tokens per array x 10 arrays = 1100 tokens; sample_size=100 forces sampling
        token_arrays = [np.random.default_rng(i).random((110, 8)).astype(np.float32) for i in range(10)]
        with patch(
            "nohiki_ml_core.batch.plaid_index.get_minibatch_kmeans",
            return_value=MiniBatchKMeans,
        ):
            result = PLAIDIndex.compute_cluster_threshold(token_arrays, sample_size=100)
        assert isinstance(result, float)
        assert result >= 0.0

    def test_k_uses_original_corpus_size_not_sample_size(self) -> None:
        """Test K is derived from full corpus size, not the down-sampled count."""
        captured_k: list[int] = []

        original_compute_k = _compute_k_from_tokens

        def capturing_compute_k(total_tokens: int) -> int:
            captured_k.append(total_tokens)
            return original_compute_k(total_tokens)

        from sklearn.cluster import MiniBatchKMeans

        # 20 tokens x 10 arrays = 200 tokens; sample_size=50 triggers sampling
        token_arrays = [np.random.default_rng(i).random((20, 8)).astype(np.float32) for i in range(10)]
        with (
            patch(
                "nohiki_ml_core.batch.plaid_index.get_minibatch_kmeans",
                return_value=MiniBatchKMeans,
            ),
            patch(
                "nohiki_ml_core.batch.plaid_index._compute_k_from_tokens",
                side_effect=capturing_compute_k,
            ),
        ):
            PLAIDIndex.compute_cluster_threshold(token_arrays, sample_size=50)

        assert len(captured_k) == 1
        # K should be based on the original 200 tokens, not the 50-token sample
        assert captured_k[0] == 200


class TestPLAIDIndexMetrics:
    """Tests for PLAIDIndexMetrics class."""

    @pytest.fixture(autouse=True)
    def clear_metrics_cache(self) -> Generator[None]:
        """Clear metrics singleton cache between tests."""
        from nohiki_ml_core.batch.metrics import get_plaid_metrics

        get_plaid_metrics.cache_clear()
        yield
        get_plaid_metrics.cache_clear()

    def test_singleton_returns_same_instance(self) -> None:
        """Test get_plaid_metrics returns same instance."""
        from nohiki_ml_core.batch.metrics import get_plaid_metrics

        with patch("nohiki_ml_core.batch.metrics.metrics.get_meter") as mock_meter:
            mock_meter.return_value = MagicMock()
            first = get_plaid_metrics()
            second = get_plaid_metrics()
            assert first is second

    def test_has_rebuilds_total_counter(self) -> None:
        """Test PLAIDIndexMetrics has rebuilds_total counter."""
        from nohiki_ml_core.batch.metrics import PLAIDIndexMetrics

        with patch("nohiki_ml_core.batch.metrics.metrics.get_meter") as mock_meter:
            mock_meter.return_value = MagicMock()
            metrics_instance = PLAIDIndexMetrics()
            assert hasattr(metrics_instance, "rebuilds_total")
            assert metrics_instance.rebuilds_total is not None

    def test_creates_observable_gauges(self) -> None:
        """Test observable gauges are created."""
        from nohiki_ml_core.batch.metrics import PLAIDIndexMetrics

        mock_meter = MagicMock()
        with patch("nohiki_ml_core.batch.metrics.metrics.get_meter", return_value=mock_meter):
            PLAIDIndexMetrics()
            gauge_calls = list(mock_meter.create_observable_gauge.call_args_list)
            assert len(gauge_calls) == 2
            gauge_names = [call.args[0] for call in gauge_calls]
            assert "nohiki_plaid_cluster_threshold" in gauge_names
            assert "nohiki_plaid_docs_since_rebuild_total" in gauge_names

    def test_register_index(self) -> None:
        """Test register_index stores the index reference."""
        from nohiki_ml_core.batch.metrics import PLAIDIndexMetrics

        with patch("nohiki_ml_core.batch.metrics.metrics.get_meter") as mock_meter:
            mock_meter.return_value = MagicMock()
            metrics_instance = PLAIDIndexMetrics()
            mock_index = MagicMock(spec=PLAIDIndex)
            metrics_instance.register_index(mock_index)
            assert metrics_instance._index is mock_index

    def test_observe_cluster_threshold_returns_empty_when_no_index(self) -> None:
        """Test callback returns empty list when no index registered."""
        from nohiki_ml_core.batch.metrics import PLAIDIndexMetrics
        from opentelemetry import metrics

        with patch("nohiki_ml_core.batch.metrics.metrics.get_meter") as mock_meter:
            mock_meter.return_value = MagicMock()
            metrics_instance = PLAIDIndexMetrics()
            mock_options = MagicMock(spec=metrics.CallbackOptions)
            result = metrics_instance._observe_cluster_threshold(mock_options)
            assert result == []

    def test_observe_cluster_threshold_returns_empty_when_baseline_none(self) -> None:
        """Test callback returns empty list when cluster_threshold_baseline is None."""
        from nohiki_ml_core.batch.metrics import PLAIDIndexMetrics
        from opentelemetry import metrics

        with patch("nohiki_ml_core.batch.metrics.metrics.get_meter") as mock_meter:
            mock_meter.return_value = MagicMock()
            metrics_instance = PLAIDIndexMetrics()
            mock_index = MagicMock(spec=PLAIDIndex)
            mock_index.cluster_threshold_baseline = None
            metrics_instance.register_index(mock_index)
            mock_options = MagicMock(spec=metrics.CallbackOptions)
            result = metrics_instance._observe_cluster_threshold(mock_options)
            assert result == []

    def test_observe_cluster_threshold_returns_observation_when_valid(self) -> None:
        """Test callback returns observation when index has valid baseline."""
        from nohiki_ml_core.batch.metrics import PLAIDIndexMetrics
        from opentelemetry import metrics

        with patch("nohiki_ml_core.batch.metrics.metrics.get_meter") as mock_meter:
            mock_meter.return_value = MagicMock()
            metrics_instance = PLAIDIndexMetrics()
            mock_index = MagicMock(spec=PLAIDIndex)
            mock_index.cluster_threshold_baseline = 0.42
            mock_index.config.index_name = "test_index"
            metrics_instance.register_index(mock_index)
            mock_options = MagicMock(spec=metrics.CallbackOptions)
            result = metrics_instance._observe_cluster_threshold(mock_options)
            assert len(result) == 1
            assert result[0].value == 0.42

    def test_observe_docs_since_rebuild_returns_empty_when_no_index(self) -> None:
        """Test callback returns empty list when no index registered."""
        from nohiki_ml_core.batch.metrics import PLAIDIndexMetrics
        from opentelemetry import metrics

        with patch("nohiki_ml_core.batch.metrics.metrics.get_meter") as mock_meter:
            mock_meter.return_value = MagicMock()
            metrics_instance = PLAIDIndexMetrics()
            mock_options = MagicMock(spec=metrics.CallbackOptions)
            result = metrics_instance._observe_docs_since_rebuild(mock_options)
            assert result == []

    def test_observe_docs_since_rebuild_returns_observation_when_valid(self) -> None:
        """Test callback returns observation when index is registered."""
        from nohiki_ml_core.batch.metrics import PLAIDIndexMetrics
        from opentelemetry import metrics

        with patch("nohiki_ml_core.batch.metrics.metrics.get_meter") as mock_meter:
            mock_meter.return_value = MagicMock()
            metrics_instance = PLAIDIndexMetrics()
            mock_index = MagicMock(spec=PLAIDIndex)
            mock_index.docs_since_rebuild = 15
            mock_index.config.index_name = "test_index"
            metrics_instance.register_index(mock_index)
            mock_options = MagicMock(spec=metrics.CallbackOptions)
            result = metrics_instance._observe_docs_since_rebuild(mock_options)
            assert len(result) == 1
            assert result[0].value == 15


class TestPLAIDIndexStateTracking:
    """Tests for PLAIDIndex state tracking fields."""

    @pytest.fixture
    def config(self) -> Generator[PLAIDIndexConfig]:
        """Create test config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield PLAIDIndexConfig(
                index_folder=tmpdir,
                index_name="test_index",
                override=True,
            )

    @pytest.fixture
    def mock_plaid_index(self) -> MagicMock:
        """Create mock PLAID index."""
        mock_index = MagicMock()
        mock_index.add_documents = MagicMock()
        return mock_index

    def test_initial_state_fields(self, config: PLAIDIndexConfig) -> None:
        """Test state fields have correct initial values."""
        index = PLAIDIndex(config=config)
        assert index.total_docs == 0
        assert index.docs_since_rebuild == 0
        assert index.cluster_threshold_baseline is None

    def test_build_updates_state_for_small_corpus(self, config: PLAIDIndexConfig, mock_plaid_index: MagicMock) -> None:
        """Test build() updates state fields for small corpus (no metrics)."""
        index = PLAIDIndex(config=config)
        index._index = mock_plaid_index

        document_ids = ["doc-1", "doc-2", "doc-3"]
        embeddings = [np.random.default_rng(42).random((10, 128)).astype(np.float32) for _ in range(3)]

        index.build(document_ids, embeddings)

        assert index.total_docs == 3
        assert index.docs_since_rebuild == 0
        assert index.cluster_threshold_baseline is None

    def test_add_documents_increments_state(self, config: PLAIDIndexConfig, mock_plaid_index: MagicMock) -> None:
        """Test add_documents() increments state counters."""
        index = PLAIDIndex(config=config)
        index._index = mock_plaid_index
        index._total_docs = 10
        index._docs_since_rebuild = 0

        document_ids = ["doc-11", "doc-12", "doc-13"]
        embeddings = [np.random.default_rng(42).random((10, 128)).astype(np.float32) for _ in range(3)]

        index.add_documents(document_ids, embeddings)

        assert index.total_docs == 13
        assert index.docs_since_rebuild == 3

    def test_build_resets_docs_since_rebuild(self, config: PLAIDIndexConfig, mock_plaid_index: MagicMock) -> None:
        """Test build() resets docs_since_rebuild to 0."""
        index = PLAIDIndex(config=config)
        index._index = mock_plaid_index
        index._docs_since_rebuild = 100

        document_ids = ["doc-1", "doc-2"]
        embeddings = [np.random.default_rng(42).random((10, 128)).astype(np.float32) for _ in range(2)]

        index.build(document_ids, embeddings)

        assert index.docs_since_rebuild == 0

    def test_min_docs_for_cluster_metrics_constant(self) -> None:
        """Test _MIN_DOCS_FOR_CLUSTER_METRICS has expected value."""
        assert _MIN_DOCS_FOR_CLUSTER_METRICS == 50

    def test_min_tokens_for_kmeans_constant(self) -> None:
        """Test _MIN_TOKENS_FOR_KMEANS has expected value."""
        assert _MIN_TOKENS_FOR_KMEANS == 2

    def test_add_documents_registers_metrics(self, config: PLAIDIndexConfig, mock_plaid_index: MagicMock) -> None:
        """Test add_documents() registers with metrics (covers load() + add_documents() path)."""
        index = PLAIDIndex(config=config)
        index._index = mock_plaid_index

        document_ids = ["doc-1", "doc-2"]
        embeddings = [np.random.default_rng(42).random((10, 128)).astype(np.float32) for _ in range(2)]

        with patch("nohiki_ml_core.batch.plaid_index.get_plaid_metrics") as mock_get_metrics:
            mock_metrics = MagicMock()
            mock_get_metrics.return_value = mock_metrics

            index.add_documents(document_ids, embeddings)

            mock_metrics.register_index.assert_called_once_with(index)

    def test_build_emits_metrics_for_large_corpus(self, config: PLAIDIndexConfig, mock_plaid_index: MagicMock) -> None:
        """Test build() computes cluster threshold and emits metrics for large corpus."""
        index = PLAIDIndex(config=config)
        index._index = mock_plaid_index

        document_ids = [f"doc-{i}" for i in range(_MIN_DOCS_FOR_CLUSTER_METRICS)]
        embeddings = [np.random.default_rng(42).random((10, 8)).astype(np.float32) for _ in document_ids]

        with (
            patch.object(PLAIDIndex, "compute_cluster_threshold", return_value=0.42),
            patch("nohiki_ml_core.batch.plaid_index.get_plaid_metrics") as mock_get_metrics,
        ):
            mock_metrics = MagicMock()
            mock_get_metrics.return_value = mock_metrics

            index.build(document_ids, embeddings)

            mock_metrics.register_index.assert_called_once_with(index)
            mock_metrics.rebuilds_total.add.assert_called_once()
            assert index.cluster_threshold_baseline == 0.42


class TestPLAIDIntegration:
    """Integration tests for PLAID module (requires pylate)."""

    @pytest.fixture
    def skip_if_no_pylate(self) -> None:
        """Skip test if pylate is not installed."""
        import importlib.util

        if importlib.util.find_spec("pylate") is None:
            pytest.skip("pylate not installed")

    def test_full_pipeline(self, skip_if_no_pylate: None) -> None:
        """Test full index → retrieve pipeline with real pylate."""
        # This test would use real pylate if installed
        # For CI without pylate, it's skipped
