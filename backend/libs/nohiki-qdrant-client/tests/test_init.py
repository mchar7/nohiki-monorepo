"""Tests for package initialization and lazy imports."""

from __future__ import annotations

import importlib
import sys

from nohiki_ml_manifest import QdrantCollectionSchema, QdrantVectorDefinition


def test_root_and_client_construction_defer_optional_qdrant_features() -> None:
    """Keep helper modules and FastEmbed unloaded until Qdrant is first used."""
    prefixes = ("fastembed", "qdrant_client", "nohiki_qdrant_client")
    saved = {name: module for name, module in sys.modules.items() if name.startswith(prefixes)}
    try:
        for name in saved:
            sys.modules.pop(name, None)

        import nohiki_qdrant_client

        importlib.reload(nohiki_qdrant_client)

        lazy_modules = {
            "nohiki_qdrant_client.collections",
            "nohiki_qdrant_client.filter_builder",
            "nohiki_qdrant_client.multivector",
        }
        assert lazy_modules.isdisjoint(sys.modules)
        assert not any(name == "fastembed" or name.startswith("fastembed.") for name in sys.modules)

        schema = QdrantCollectionSchema(
            vectors={"dense": QdrantVectorDefinition(size=3, distance="Cosine")},
            primary_dense_name="dense",
        )
        client = nohiki_qdrant_client.QdrantVectorClient(nohiki_qdrant_client.QdrantSettings(), schema)

        assert client.primary_dense_name == "dense"
        assert not any(name == "fastembed" or name.startswith("fastembed.") for name in sys.modules)

        assert nohiki_qdrant_client.CollectionConfig is not None
        assert "nohiki_qdrant_client.collections" in sys.modules
    finally:
        stale = [name for name in sys.modules if name.startswith(prefixes)]
        for name in stale:
            del sys.modules[name]
        sys.modules.update(saved)
