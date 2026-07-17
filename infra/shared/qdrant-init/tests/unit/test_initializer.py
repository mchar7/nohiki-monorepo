"""Unit tests for CollectionInitializer and _build_payload."""

from unittest.mock import MagicMock

from nohiki_ml_manifest import CollectionConfig
from qdrant_init.client import QdrantAPIError, QdrantInitClient
from qdrant_init.initializer import CollectionInitializer, InitializationResult, _build_payload


def _make_mock_client(*, exists: bool = False) -> MagicMock:
    """Build a MagicMock QdrantInitClient where collection_exists returns a fixed value."""
    mock = MagicMock(spec=QdrantInitClient)
    mock.collection_exists.return_value = exists
    return mock


def _make_mock_manifest(
    collections: dict[str, CollectionConfig],
) -> MagicMock:
    """Build a mock SemanticRepresentationManifest with controllable collections.

    get_collection_name returns '{entity_type}_v1' and get_collection_config
    returns the matching CollectionConfig from the provided dict.
    """
    manifest = MagicMock()
    manifest.collections.items.return_value = collections.items()
    manifest.get_collection_name.side_effect = lambda entity_type: f"{entity_type}_v1"
    manifest.get_collection_config.side_effect = lambda entity_type: collections[entity_type]
    return manifest


class TestBuildPayload:
    """Tests for the _build_payload module-level helper."""

    def test_with_sparse(self, sparse_collection_config: CollectionConfig) -> None:
        """sparse_vectors key is present with the correct index structure."""
        payload = _build_payload(sparse_collection_config)

        assert "sparse_vectors" in payload
        sparse = payload["sparse_vectors"]
        assert "sparse" in sparse
        assert sparse["sparse"]["index"]["full_scan_threshold"] == 100_000

    def test_without_sparse(self, dense_only_collection_config: CollectionConfig) -> None:
        """sparse_vectors key is absent when no sparse config is defined."""
        payload = _build_payload(dense_only_collection_config)

        assert "sparse_vectors" not in payload

    def test_on_disk_true_in_payload(self, on_disk_collection_config: CollectionConfig) -> None:
        """on_disk=True is included in the vector definition payload."""
        payload = _build_payload(on_disk_collection_config)

        assert payload["vectors"]["dense"]["on_disk"] is True

    def test_on_disk_none_excluded_from_payload(self, on_disk_none_collection_config: CollectionConfig) -> None:
        """on_disk=None is excluded from the payload via model_dump(exclude_none=True).

        Qdrant uses the collection-level default when the field is absent, so
        sending null would be incorrect: it must be omitted entirely.
        """
        payload = _build_payload(on_disk_none_collection_config)

        assert "on_disk" not in payload["vectors"]["dense"]

    def test_multivector_config_in_payload(self, sparse_collection_config: CollectionConfig) -> None:
        """multivector_config is present for ColBERT-style vectors."""
        payload = _build_payload(sparse_collection_config)

        colbert = payload["vectors"]["colbert"]
        assert "multivector_config" in colbert
        assert colbert["multivector_config"] == {"comparator": "max_sim"}

    def test_default_distance_is_cosine(self, dense_only_collection_config: CollectionConfig) -> None:
        """Distance defaults to 'Cosine' when not explicitly set."""
        payload = _build_payload(dense_only_collection_config)

        assert payload["vectors"]["skill_dense"]["distance"] == "Cosine"

    def test_dot_distance_preserved(self, sparse_collection_config: CollectionConfig) -> None:
        """Dot product distance set on muvera is preserved in the payload."""
        payload = _build_payload(sparse_collection_config)

        assert payload["vectors"]["muvera"]["distance"] == "Dot"

    def test_vectors_key_always_present(self, dense_only_collection_config: CollectionConfig) -> None:
        """Top-level 'vectors' key is always present in the payload."""
        payload = _build_payload(dense_only_collection_config)

        assert "vectors" in payload


class TestInitializationResult:
    """Tests for the InitializationResult dataclass."""

    def test_success_when_no_failures(self) -> None:
        """Success is True when the failed list is empty."""
        result = InitializationResult(created=["a", "b"], skipped=["c"])
        assert result.success is True

    def test_not_success_when_failures_exist(self) -> None:
        """Success is False when any collection failed to initialize."""
        result = InitializationResult(failed=["jobs_v1"])
        assert result.success is False

    def test_total_sums_all_lists(self) -> None:
        """Total equals the sum of created + skipped + failed."""
        result = InitializationResult(created=["a"], skipped=["b", "c"], failed=["d"])
        assert result.total == 4

    def test_total_empty(self) -> None:
        """Total is 0 when no collections were processed."""
        assert InitializationResult().total == 0


class TestInitializeAll:
    """Tests for CollectionInitializer.initialize_all."""

    def test_creates_all_four_collections(
        self,
        sparse_collection_config: CollectionConfig,
        dense_only_collection_config: CollectionConfig,
    ) -> None:
        """All collections from the manifest are created when none exist."""
        configs = {
            "jobs": sparse_collection_config,
            "profiles": sparse_collection_config,
            "skills": dense_only_collection_config,
            "occupations": dense_only_collection_config,
        }
        mock_client = _make_mock_client(exists=False)
        manifest = _make_mock_manifest(configs)

        result = CollectionInitializer(mock_client, manifest).initialize_all()

        assert len(result.created) == 4
        assert len(result.skipped) == 0
        assert len(result.failed) == 0
        assert mock_client.create_collection.call_count == 4

    def test_skips_existing_collections(
        self,
        dense_only_collection_config: CollectionConfig,
    ) -> None:
        """Existing collections are skipped when skip_existing=True."""
        configs = {
            "skills": dense_only_collection_config,
            "occupations": dense_only_collection_config,
        }
        mock_client = _make_mock_client(exists=True)
        manifest = _make_mock_manifest(configs)

        result = CollectionInitializer(mock_client, manifest).initialize_all(skip_existing=True)

        assert len(result.skipped) == 2
        assert len(result.created) == 0
        mock_client.create_collection.assert_not_called()

    def test_recreates_existing_when_skip_false(
        self,
        dense_only_collection_config: CollectionConfig,
    ) -> None:
        """Existing collections are recreated when skip_existing=False."""
        configs = {"skills": dense_only_collection_config}
        mock_client = _make_mock_client(exists=True)
        manifest = _make_mock_manifest(configs)

        result = CollectionInitializer(mock_client, manifest).initialize_all(skip_existing=False)

        assert len(result.created) == 1
        mock_client.create_collection.assert_called_once()

    def test_records_failed_collections(
        self,
        dense_only_collection_config: CollectionConfig,
    ) -> None:
        """Collections where create_collection raises are recorded in result.failed."""
        configs = {
            "skills": dense_only_collection_config,
            "occupations": dense_only_collection_config,
        }
        mock_client = _make_mock_client(exists=False)
        mock_client.create_collection.side_effect = QdrantAPIError(500, "internal error")
        manifest = _make_mock_manifest(configs)

        result = CollectionInitializer(mock_client, manifest).initialize_all()

        assert len(result.failed) == 2
        assert result.success is False

    def test_partial_failure(
        self,
        dense_only_collection_config: CollectionConfig,
    ) -> None:
        """A mix of created and failed collections is accurately tracked."""
        configs = {
            "skills": dense_only_collection_config,
            "occupations": dense_only_collection_config,
        }
        mock_client = _make_mock_client(exists=False)
        # First call succeeds, second fails
        mock_client.create_collection.side_effect = [None, QdrantAPIError(500, "error")]
        manifest = _make_mock_manifest(configs)

        result = CollectionInitializer(mock_client, manifest).initialize_all()

        assert len(result.created) == 1
        assert len(result.failed) == 1


class TestInitializeOne:
    """Tests for CollectionInitializer.initialize_one."""

    def test_creates_single_collection(
        self,
        dense_only_collection_config: CollectionConfig,
    ) -> None:
        """Creates exactly one collection and returns True on success."""
        mock_client = _make_mock_client(exists=False)
        manifest = _make_mock_manifest({"skills": dense_only_collection_config})

        result = CollectionInitializer(mock_client, manifest).initialize_one("skills")

        assert result is True
        mock_client.create_collection.assert_called_once_with(
            "skills_v1",
            _build_payload(dense_only_collection_config),
        )

    def test_skips_existing_returns_true(
        self,
        dense_only_collection_config: CollectionConfig,
    ) -> None:
        """Returns True without creating when collection already exists and skip_existing=True."""
        mock_client = _make_mock_client(exists=True)
        manifest = _make_mock_manifest({"skills": dense_only_collection_config})

        result = CollectionInitializer(mock_client, manifest).initialize_one("skills", skip_existing=True)

        assert result is True
        mock_client.create_collection.assert_not_called()

    def test_failure_returns_false(
        self,
        dense_only_collection_config: CollectionConfig,
    ) -> None:
        """Returns False when collection creation raises."""
        mock_client = _make_mock_client(exists=False)
        mock_client.create_collection.side_effect = QdrantAPIError(500, "error")
        manifest = _make_mock_manifest({"skills": dense_only_collection_config})

        result = CollectionInitializer(mock_client, manifest).initialize_one("skills")

        assert result is False
