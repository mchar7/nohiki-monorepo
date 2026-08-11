"""Tests for user_pref_service.core.embedding module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from nohiki.ml.v1 import EmbeddingType, EncodingMode
from nohiki_common_exceptions import ValidationError
from nohiki_embedding_client import EmbeddingPublisher, EmbeddingSpec
from user_pref_service.core.embedding import (
    PREF_EMBEDDING_SPEC,
    PrefEnrichmentSagaContext,
    build_profile_embedding_text,
    get_embedding_publisher,
    profile_embedding_content_hash,
)


class TestPrefEnrichmentSagaContext:
    """Tests for the minimal durable saga callback carrier."""

    def test_round_trip(self) -> None:
        state = PrefEnrichmentSagaContext(saga_id="f47ac10b-58cc-4372-a567-0e02b2c3d479")
        assert PrefEnrichmentSagaContext.from_bytes(state.to_bytes()) == state

    def test_from_bytes_ignores_unknown_fields(self) -> None:
        data = json.dumps({"saga_id": "abc", "legacy_field": "ignored"}).encode()
        assert PrefEnrichmentSagaContext.from_bytes(data).saga_id == "abc"

    def test_payload_contains_only_saga_identity(self) -> None:
        state = PrefEnrichmentSagaContext(saga_id="f47ac10b-58cc-4372-a567-0e02b2c3d479")
        assert json.loads(state.to_bytes()) == {"saga_id": state.saga_id}


class TestPrefEmbeddingSpec:
    """Tests for canonical PREF_EMBEDDING_SPEC constant."""

    def test_is_embedding_spec_instance(self) -> None:
        """PREF_EMBEDDING_SPEC is an EmbeddingSpec."""
        assert isinstance(PREF_EMBEDDING_SPEC, EmbeddingSpec)

    def test_uses_query_encoding_mode(self) -> None:
        """Profiles query DOCUMENT-encoded job points."""
        assert PREF_EMBEDDING_SPEC.encoding_mode == EncodingMode.QUERY

    def test_publish_to_index_is_false(self) -> None:
        """Legacy Kafka sink must not own profile index publication."""
        assert PREF_EMBEDDING_SPEC.publish_to_index is False

    def test_requested_types_are_retrieval_vectors(self) -> None:
        """MUVERA, SPARSE, and COLBERT are requested: no DENSE (retrieval-only)."""
        requested = set(PREF_EMBEDDING_SPEC.requested_types)
        assert EmbeddingType.MUVERA in requested
        assert EmbeddingType.SPARSE in requested
        assert EmbeddingType.COLBERT in requested
        assert EmbeddingType.DENSE not in requested


class TestBuildProfileEmbeddingText:
    """Tests for the single canonical profile query representation."""

    def test_includes_name_then_deduplicated_keywords_then_skills(self) -> None:
        assert (
            build_profile_embedding_text(
                "  Platform   Engineer  ",
                [" Python ", "distributed   systems", "python", ""],
                ["Kubernetes", " PYTHON ", "kubernetes"],
            )
            == "Platform Engineer Python distributed systems Kubernetes"
        )

    def test_is_deterministic_for_identical_inputs(self) -> None:
        args = ("Data roles", ["Python", "SQL", "Python"], ["Spark", "SQL"])
        assert build_profile_embedding_text(*args) == build_profile_embedding_text(*args)

    @pytest.mark.parametrize(
        ("pref_name", "keywords", "skills"),
        [("", [], []), ("   ", ["\t", "\n"], ["  "])],
    )
    def test_rejects_empty_semantic_content(self, pref_name: str, keywords: list[str], skills: list[str]) -> None:
        with pytest.raises(ValidationError):
            build_profile_embedding_text(pref_name, keywords, skills)


class TestProfileEmbeddingContentHash:
    """Tests for the cross-service embedding content identity."""

    def test_matches_embedding_pipeline_normalization(self) -> None:
        assert profile_embedding_content_hash("  Python Developer  ") == profile_embedding_content_hash(
            "python developer"
        )


class TestGetEmbeddingPublisher:
    """Tests for get_embedding_publisher factory."""

    def teardown_method(self) -> None:
        """Clear the cached publisher after each test."""
        get_embedding_publisher.cache_clear()

    def test_returns_embedding_publisher(self) -> None:
        """get_embedding_publisher returns a configured EmbeddingPublisher."""
        mock_manifest = MagicMock()
        mock_manifest.get_entity_version.return_value = "v1"
        mock_settings = MagicMock()
        mock_settings.service_name = "user-pref-service"

        with (
            patch(
                "user_pref_service.core.embedding.get_manifest",
                return_value=mock_manifest,
            ),
            patch(
                "user_pref_service.core.embedding.get_settings",
                return_value=mock_settings,
            ),
        ):
            get_embedding_publisher.cache_clear()
            publisher = get_embedding_publisher()
            assert isinstance(publisher, EmbeddingPublisher)

    def test_caches_publisher(self) -> None:
        """get_embedding_publisher returns same instance on repeated calls."""
        mock_manifest = MagicMock()
        mock_manifest.get_entity_version.return_value = "v1"
        mock_settings = MagicMock()
        mock_settings.service_name = "user-pref-service"

        with (
            patch(
                "user_pref_service.core.embedding.get_manifest",
                return_value=mock_manifest,
            ),
            patch(
                "user_pref_service.core.embedding.get_settings",
                return_value=mock_settings,
            ),
        ):
            get_embedding_publisher.cache_clear()
            p1 = get_embedding_publisher()
            p2 = get_embedding_publisher()
            assert p1 is p2

    def test_publisher_configured_with_correct_callback_topic(self) -> None:
        """Publisher is configured with USER_PREF_EMBEDDING_CALLBACK topic."""
        from nohiki_kafka_client import Topics

        mock_manifest = MagicMock()
        mock_manifest.get_entity_version.return_value = "v1"
        mock_settings = MagicMock()
        mock_settings.service_name = "user-pref-service"

        with (
            patch(
                "user_pref_service.core.embedding.get_manifest",
                return_value=mock_manifest,
            ),
            patch(
                "user_pref_service.core.embedding.get_settings",
                return_value=mock_settings,
            ),
        ):
            get_embedding_publisher.cache_clear()
            publisher = get_embedding_publisher()
            assert publisher.callback_topic == Topics.USER_PREF_EMBEDDING_CALLBACK
