"""Unit tests for the batch embedding service."""

from __future__ import annotations

import uuid

import pytest
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector
from nohiki_embedding_client import BatchEmbeddingItemResult
from skill_graph_service.services.embedding_service import (
    EmbeddingVariant,
    build_skill_batch_items,
    build_skill_vector_points,
    skill_variant_point_id,
)


class TestBuildSkillBatchItems:
    """Tests for build_skill_batch_items."""

    def test_returns_exactly_three_items(self) -> None:
        """Always returns label, description, alt_labels items."""
        skill_id = uuid.uuid4()
        items = build_skill_batch_items(
            skill_id=skill_id,
            preferred_label="Python",
            description="A language",
            alt_labels=["py", "python3"],
        )
        assert len(items) == 3

    def test_point_id_format(self) -> None:
        """Point IDs are deterministic UUID5s from skill_id + variant."""
        skill_id = uuid.uuid4()
        items = build_skill_batch_items(
            skill_id=skill_id,
            preferred_label="Python",
            description=None,
            alt_labels=[],
        )
        assert items[0].point_id == skill_variant_point_id(skill_id, EmbeddingVariant.LABEL)
        assert items[1].point_id == skill_variant_point_id(skill_id, EmbeddingVariant.DESCRIPTION)
        assert items[2].point_id == skill_variant_point_id(skill_id, EmbeddingVariant.ALT_LABELS)

    def test_entity_id_is_skill_uuid(self) -> None:
        """All items carry the same skill UUID as entity_id."""
        skill_id = uuid.uuid4()
        items = build_skill_batch_items(
            skill_id=skill_id,
            preferred_label="Python",
            description=None,
            alt_labels=[],
        )
        for item in items:
            assert item.entity_id == str(skill_id)

    def test_label_variant_uses_preferred_label(self) -> None:
        """LABEL variant text matches preferred_label exactly."""
        skill_id = uuid.uuid4()
        items = build_skill_batch_items(
            skill_id=skill_id,
            preferred_label="Python",
            description="A language",
            alt_labels=["py"],
        )
        assert items[0].text == "Python"

    def test_description_variant_uses_description(self) -> None:
        """DESCRIPTION variant text uses description when provided."""
        skill_id = uuid.uuid4()
        items = build_skill_batch_items(
            skill_id=skill_id,
            preferred_label="Python",
            description="A high-level language",
            alt_labels=[],
        )
        assert items[1].text == "A high-level language"

    def test_description_fallback_on_none(self) -> None:
        """DESCRIPTION variant falls back to preferred_label when description is None."""
        skill_id = uuid.uuid4()
        items = build_skill_batch_items(
            skill_id=skill_id,
            preferred_label="Python",
            description=None,
            alt_labels=[],
        )
        assert items[1].text == "Python"

    def test_alt_labels_variant_joins_labels(self) -> None:
        """ALT_LABELS variant joins provided alt_labels with comma-space."""
        skill_id = uuid.uuid4()
        items = build_skill_batch_items(
            skill_id=skill_id,
            preferred_label="Python",
            description=None,
            alt_labels=["py", "python3", "cpython"],
        )
        assert items[2].text == "py, python3, cpython"

    def test_alt_labels_fallback_on_empty(self) -> None:
        """ALT_LABELS variant falls back to preferred_label when alt_labels is empty."""
        skill_id = uuid.uuid4()
        items = build_skill_batch_items(
            skill_id=skill_id,
            preferred_label="Python",
            description=None,
            alt_labels=[],
        )
        assert items[2].text == "Python"

    def test_alt_labels_truncated_at_max(self) -> None:
        """ALT_LABELS variant truncates at _BATCH_ITEM_MAX_ALT_LABELS (10)."""
        skill_id = uuid.uuid4()
        many = [f"alias{i}" for i in range(15)]
        items = build_skill_batch_items(
            skill_id=skill_id,
            preferred_label="Python",
            description=None,
            alt_labels=many,
        )
        joined = items[2].text
        assert joined.count(", ") == 9  # exactly 10 items → 9 separators

    def test_item_attributes_contains_variant_and_skill_id(self) -> None:
        """Each batch item carries variant and skill_id in item_attributes."""
        skill_id = uuid.uuid4()
        items = build_skill_batch_items(
            skill_id=skill_id,
            preferred_label="Python",
            description=None,
            alt_labels=[],
        )
        for item in items:
            assert "variant" in item.item_attributes
            assert "skill_id" in item.item_attributes
            assert item.item_attributes["skill_id"] == str(skill_id)


class TestBuildSkillVectorPoints:
    """Tests for build_skill_vector_points."""

    @pytest.fixture
    def dense_embedding(self) -> EmbeddingVector:
        """Dense embedding vector for testing."""
        return EmbeddingVector(
            embedding_type=EmbeddingType.DENSE,
            dense=DenseData(values=[0.1] * 1024),
            content_hash="a" * 64,
            model_id="test-model",
            collection_version="v1",
        )

    def _make_result(
        self,
        point_id: str,
        entity_id: str,
        embedding: EmbeddingVector,
        variant: str = "label",
    ) -> BatchEmbeddingItemResult:
        return BatchEmbeddingItemResult(
            point_id=point_id,
            entity_id=entity_id,
            embeddings=[embedding],
            content_hash="a" * 64,
            item_attributes={"variant": variant, "skill_id": entity_id, "name": "TestSkill"},
        )

    def test_empty_results_returns_empty_list(self) -> None:
        """Empty input produces empty output."""
        assert build_skill_vector_points([]) == []

    def test_one_result_produces_one_point(self, dense_embedding: EmbeddingVector) -> None:
        """Single result maps to single VectorPoint."""
        skill_id = str(uuid.uuid4())
        point_id = skill_variant_point_id(uuid.UUID(skill_id), EmbeddingVariant.LABEL)
        result = self._make_result(point_id, skill_id, dense_embedding)
        points = build_skill_vector_points([result])
        assert len(points) == 1

    def test_point_id_preserved(self, dense_embedding: EmbeddingVector) -> None:
        """VectorPoint.point_id matches BatchEmbeddingItemResult.point_id (UUID-formatted)."""
        skill_id = str(uuid.uuid4())
        point_id = skill_variant_point_id(uuid.UUID(skill_id), EmbeddingVariant.LABEL)
        result = self._make_result(point_id, skill_id, dense_embedding)
        points = build_skill_vector_points([result])
        assert points[0].point_id == point_id
        # Regression guard: ensure point_id is a parseable UUID (Qdrant gRPC requirement).
        uuid.UUID(points[0].point_id)

    def test_payload_entity_id(self, dense_embedding: EmbeddingVector) -> None:
        """Payload entity_id matches result.entity_id."""
        skill_id = str(uuid.uuid4())
        point_id = skill_variant_point_id(uuid.UUID(skill_id), EmbeddingVariant.LABEL)
        result = self._make_result(point_id, skill_id, dense_embedding)
        points = build_skill_vector_points([result])
        assert points[0].payload.entity_id == skill_id

    def test_payload_entity_type_is_skill(self, dense_embedding: EmbeddingVector) -> None:
        """Payload entity_type is always 'skill'."""
        skill_id = str(uuid.uuid4())
        point_id = skill_variant_point_id(uuid.UUID(skill_id), EmbeddingVariant.LABEL)
        result = self._make_result(point_id, skill_id, dense_embedding)
        points = build_skill_vector_points([result])
        assert points[0].payload.entity_type == "skill"

    def test_payload_collection_version_from_embedding(self, dense_embedding: EmbeddingVector) -> None:
        """Payload collection_version is taken from the first embedding."""
        skill_id = str(uuid.uuid4())
        point_id = skill_variant_point_id(uuid.UUID(skill_id), EmbeddingVariant.LABEL)
        result = self._make_result(point_id, skill_id, dense_embedding)
        points = build_skill_vector_points([result])
        assert points[0].payload.collection_version == "v1"

    @pytest.mark.parametrize(
        "versions",
        [[], [""], ["v1", "v2"]],
        ids=["missing-embedding", "empty-version", "inconsistent-versions"],
    )
    def test_rejects_missing_or_inconsistent_collection_versions(self, versions: list[str]) -> None:
        """Invalid collection versions are rejected before constructing a Qdrant write."""
        from nohiki_common_exceptions import DataIntegrityError

        skill_id = str(uuid.uuid4())
        point_id = skill_variant_point_id(uuid.UUID(skill_id), EmbeddingVariant.LABEL)
        embeddings = [
            EmbeddingVector(
                embedding_type=EmbeddingType.DENSE,
                dense=DenseData(values=[0.1] * 1024),
                content_hash="a" * 64,
                model_id="test-model",
                collection_version=version,
            )
            for version in versions
        ]
        result = BatchEmbeddingItemResult(
            point_id=point_id,
            entity_id=skill_id,
            embeddings=embeddings,
            content_hash="a" * 64,
            item_attributes={"variant": "label", "skill_id": skill_id, "name": "TestSkill"},
        )

        with pytest.raises(DataIntegrityError, match="missing or inconsistent collection versions"):
            build_skill_vector_points([result])

    def test_payload_embedding_source_from_context(self, dense_embedding: EmbeddingVector) -> None:
        """Payload extra.embedding_source matches the variant from context."""
        skill_id = str(uuid.uuid4())
        point_id = skill_variant_point_id(uuid.UUID(skill_id), EmbeddingVariant.DESCRIPTION)
        result = self._make_result(point_id, skill_id, dense_embedding, variant="description")
        points = build_skill_vector_points([result])
        assert points[0].payload.extra is not None
        assert points[0].payload.extra["embedding_source"] == "description"

    def test_payload_includes_skill_id_and_name(self, dense_embedding: EmbeddingVector) -> None:
        """Payload extra carries canonical skill_id and human-readable name (regression guard).

        semantic.py:build_candidate_list reads payload['skill_id'] for the canonical UUID
        and payload['name'] for the display string. Both MUST be populated by build_skill_vector_points.
        """
        skill_id = str(uuid.uuid4())
        point_id = skill_variant_point_id(uuid.UUID(skill_id), EmbeddingVariant.LABEL)
        result = self._make_result(point_id, skill_id, dense_embedding)
        points = build_skill_vector_points([result])
        extra = points[0].payload.extra
        assert extra is not None
        assert extra["skill_id"] == skill_id
        assert extra["name"] == "TestSkill"

    def test_three_results_produce_three_points(self, dense_embedding: EmbeddingVector) -> None:
        """One result per variant → 3 VectorPoints total."""
        skill_uuid = uuid.uuid4()
        skill_id = str(skill_uuid)
        label_id = skill_variant_point_id(skill_uuid, EmbeddingVariant.LABEL)
        desc_id = skill_variant_point_id(skill_uuid, EmbeddingVariant.DESCRIPTION)
        alt_id = skill_variant_point_id(skill_uuid, EmbeddingVariant.ALT_LABELS)
        results = [
            self._make_result(label_id, skill_id, dense_embedding, "label"),
            self._make_result(desc_id, skill_id, dense_embedding, "description"),
            self._make_result(alt_id, skill_id, dense_embedding, "alt_labels"),
        ]
        points = build_skill_vector_points(results)
        assert len(points) == 3
        point_ids = {p.point_id for p in points}
        assert point_ids == {label_id, desc_id, alt_id}
