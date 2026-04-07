"""Tests for Qdrant collection management."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki_qdrant_client import CollectionConfig
from nohiki_qdrant_client.collections import (
    _create_or_update_alias_async,
    collection_exists,
    create_collection_from_manifest,
    delete_collection,
    get_collection_name,
    update_alias,
)


class TestCollectionConfig:
    """Tests for CollectionConfig dataclass."""

    def test_init_minimal(self) -> None:
        """Test CollectionConfig with minimal args."""
        config = CollectionConfig(
            collection_version="v1",
            entity_type="jobs",
            muvera_dim=2048,
        )
        assert config.collection_version == "v1"
        assert config.entity_type == "jobs"
        assert config.muvera_dim == 2048
        assert config.distance_metric == "Dot"
        assert config.alias_name is None
        assert config.on_disk is True

    def test_init_full(self) -> None:
        """Test CollectionConfig with all args."""
        config = CollectionConfig(
            collection_version="v1",
            entity_type="jobs",
            muvera_dim=2048,
            distance_metric="Cosine",
            alias_name="jobs_active",
            on_disk=False,
            hnsw_m=32,
            hnsw_ef_construct=200,
        )
        assert config.distance_metric == "Cosine"
        assert config.alias_name == "jobs_active"
        assert config.on_disk is False
        assert config.hnsw_m == 32
        assert config.hnsw_ef_construct == 200


class TestGetCollectionName:
    """Tests for get_collection_name function."""

    def test_sanitizes_dots(self) -> None:
        """Test dots are replaced with underscores."""
        result = get_collection_name("jobs", "v1")
        assert result == "jobs_v1"

    def test_sanitizes_dashes(self) -> None:
        """Test dashes are replaced with underscores."""
        result = get_collection_name("profiles", "v2")
        assert result == "profiles_v2"


class TestCreateCollectionFromManifest:
    """Tests for create_collection_from_manifest function."""

    def test_creates_collection(self) -> None:
        """Test collection creation."""
        mock_client = MagicMock()
        config = CollectionConfig(
            collection_version="v1",
            entity_type="jobs",
            muvera_dim=2048,
        )

        result = create_collection_from_manifest(mock_client, config)

        assert result == "jobs_v1"
        mock_client.recreate_collection.assert_called_once()
        # Verify payload indexes were created
        assert mock_client.create_payload_index.call_count == 8

    def test_creates_collection_with_alias(self) -> None:
        """Test collection creation with alias."""
        mock_client = MagicMock()
        config = CollectionConfig(
            collection_version="v1",
            entity_type="jobs",
            muvera_dim=2048,
            alias_name="jobs_active",
        )

        create_collection_from_manifest(mock_client, config)

        mock_client.recreate_collection.assert_called_once()
        # Verify alias was created
        assert mock_client.update_collection_aliases.call_count >= 1

    def test_uses_cosine_distance(self) -> None:
        """Test collection creation with Cosine distance."""
        mock_client = MagicMock()
        config = CollectionConfig(
            collection_version="v1",
            entity_type="jobs",
            muvera_dim=2048,
            distance_metric="Cosine",
        )

        create_collection_from_manifest(mock_client, config)

        mock_client.recreate_collection.assert_called_once()


class TestUpdateAlias:
    """Tests for update_alias function."""

    def test_updates_alias(self) -> None:
        """Test alias update."""
        mock_client = MagicMock()

        update_alias(mock_client, "jobs_active", "jobs_v2")

        mock_client.update_collection_aliases.assert_called_once()


class TestDeleteCollection:
    """Tests for delete_collection function."""

    def test_deletes_collection(self) -> None:
        """Test collection deletion."""
        mock_client = MagicMock()

        delete_collection(mock_client, "old_collection")

        mock_client.delete_collection.assert_called_once_with(collection_name="old_collection")


class TestCollectionExists:
    """Tests for collection_exists function."""

    def test_returns_true_when_exists(self) -> None:
        """Test returns True when collection exists."""
        mock_client = MagicMock()
        mock_client.collection_exists.return_value = True

        result = collection_exists(mock_client, "my_collection")

        assert result is True
        mock_client.collection_exists.assert_called_once_with(collection_name="my_collection")

    def test_returns_false_when_not_exists(self) -> None:
        """Test returns False when collection doesn't exist."""
        mock_client = MagicMock()
        mock_client.collection_exists.return_value = False

        result = collection_exists(mock_client, "nonexistent")

        assert result is False


class TestCreateOrUpdateAliasAsync:
    """Tests for _create_or_update_alias_async internal helper."""

    @pytest.mark.asyncio
    async def test_creates_alias_successfully(self) -> None:
        """Test alias is created after attempting to delete any existing alias."""
        mock_client = AsyncMock()

        await _create_or_update_alias_async(mock_client, "jobs_active", "jobs_v2")

        assert mock_client.update_collection_aliases.call_count == 2

    @pytest.mark.asyncio
    async def test_delete_failure_is_suppressed(self) -> None:
        """Test that exception during alias deletion is suppressed and creation proceeds."""
        mock_client = AsyncMock()
        mock_client.update_collection_aliases.side_effect = [
            Exception("alias not found"),
            None,
        ]

        await _create_or_update_alias_async(mock_client, "jobs_active", "jobs_v2")

        assert mock_client.update_collection_aliases.call_count == 2

    @pytest.mark.asyncio
    async def test_passes_correct_alias_and_collection_names(self) -> None:
        """Test the create alias call uses the given alias_name and collection_name."""
        from qdrant_client import models

        mock_client = AsyncMock()

        await _create_or_update_alias_async(mock_client, "my_alias", "my_collection_v3")

        create_call_args = mock_client.update_collection_aliases.call_args_list[1]
        ops = create_call_args.kwargs["change_aliases_operations"]
        assert len(ops) == 1
        create_op = ops[0]
        assert isinstance(create_op, models.CreateAliasOperation)
        assert create_op.create_alias.alias_name == "my_alias"
        assert create_op.create_alias.collection_name == "my_collection_v3"
