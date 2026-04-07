"""Tests for EmbeddingValidator class."""

from typing import cast

import pytest
from nohiki_common_exceptions import StaleDataError, ValidationError
from nohiki_ml_manifest import EmbeddingValidationResult, EmbeddingValidator, SemanticRepresentationManifest


@pytest.fixture
def manifest(sample_manifest_data: dict[str, object]) -> SemanticRepresentationManifest:
    """Create a test manifest."""
    return SemanticRepresentationManifest.model_validate(sample_manifest_data)


@pytest.fixture
def validator(manifest: SemanticRepresentationManifest) -> EmbeddingValidator:
    """Create a validator with test manifest."""
    return EmbeddingValidator(manifest)


class TestEmbeddingValidator:
    """Test suite for EmbeddingValidator."""

    def test_manifest_property(
        self,
        validator: EmbeddingValidator,
        manifest: SemanticRepresentationManifest,
    ) -> None:
        """Test manifest property returns correct manifest."""
        assert validator.manifest == manifest

    def test_expected_muvera_dimension(self, validator: EmbeddingValidator) -> None:
        """Test MUVERA dimension calculation: 2^k_sim * dim_proj * r_reps."""
        assert validator.expected_muvera_dimension == 8192

    def test_expected_dense_dimension(self, validator: EmbeddingValidator) -> None:
        """Test dense dimension from manifest."""
        assert validator.expected_dense_dimension == 1024

    def test_expected_colbert_token_dim(self, validator: EmbeddingValidator) -> None:
        """Test ColBERT token dimension from manifest."""
        assert validator.expected_colbert_token_dim == 48


class TestValidateCollectionVersion:
    """Test collection_version validation."""

    def test_matching_version_returns_true(self, validator: EmbeddingValidator) -> None:
        """Test valid version returns True."""
        result = validator.validate_collection_version("job", "v1")
        assert result is True

    def test_mismatched_version_raises_stale_data_error(self, validator: EmbeddingValidator) -> None:
        """Test mismatched version raises StaleDataError."""
        with pytest.raises(StaleDataError) as exc_info:
            validator.validate_collection_version("job", "v99")

        assert "mismatch" in exc_info.value.message.lower()

    def test_mismatched_version_returns_false_when_not_raising(self, validator: EmbeddingValidator) -> None:
        """Test mismatched version returns False when raise_on_mismatch=False."""
        result = validator.validate_collection_version(
            "job",
            "v99",
            raise_on_mismatch=False,
        )
        assert result is False


class TestValidateMuveraDimension:
    """Test MUVERA dimension validation."""

    def test_valid_dimension_returns_true(self, validator: EmbeddingValidator) -> None:
        """Test valid dimension returns True."""
        result = validator.validate_muvera_dimension(8192)
        assert result is True

    def test_invalid_dimension_raises_validation_error(self, validator: EmbeddingValidator) -> None:
        """Test invalid dimension raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_muvera_dimension(1024)

        assert exc_info.value.field_name == "embedding_dimension"
        assert exc_info.value.invalid_value == 1024

    def test_invalid_dimension_returns_false_when_not_raising(self, validator: EmbeddingValidator) -> None:
        """Test invalid dimension returns False when not raising."""
        result = validator.validate_muvera_dimension(
            1024,
            raise_on_mismatch=False,
        )
        assert result is False


class TestValidateDenseDimension:
    """Test dense dimension validation."""

    def test_valid_dimension_returns_true(self, validator: EmbeddingValidator) -> None:
        """Test valid dimension returns True."""
        result = validator.validate_dense_dimension(1024)
        assert result is True

    def test_invalid_dimension_raises_validation_error(self, validator: EmbeddingValidator) -> None:
        """Test invalid dimension raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_dense_dimension(768)

        assert exc_info.value.field_name == "embedding_dimension"
        assert exc_info.value.invalid_value == 768

    def test_invalid_dimension_returns_false_when_not_raising(self, validator: EmbeddingValidator) -> None:
        """Test invalid dimension returns False when not raising."""
        result = validator.validate_dense_dimension(
            768,
            raise_on_mismatch=False,
        )
        assert result is False


class TestValidateColbertTokenDimension:
    """Test ColBERT token dimension validation."""

    def test_valid_dimension_returns_true(self, validator: EmbeddingValidator) -> None:
        """Test valid ColBERT token dimension returns True."""
        result = validator.validate_colbert_token_dimension(48)
        assert result is True

    def test_invalid_dimension_raises_validation_error(self, validator: EmbeddingValidator) -> None:
        """Test invalid ColBERT token dimension raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_colbert_token_dimension(64)

        assert exc_info.value.field_name == "token_dimension"
        assert exc_info.value.invalid_value == 64

    def test_invalid_dimension_returns_false_when_not_raising(self, validator: EmbeddingValidator) -> None:
        """Test invalid dimension returns False when not raising."""
        result = validator.validate_colbert_token_dimension(64, raise_on_mismatch=False)
        assert result is False


class TestValidateEmbedding:
    """Test complete embedding validation."""

    def test_valid_muvera_embedding(self, validator: EmbeddingValidator) -> None:
        """Test valid MUVERA embedding passes validation."""
        values = [0.1] * 8192
        result = validator.validate_embedding(
            values=values,
            entity_type="job",
            collection_version="v1",
            embedding_type="muvera",
        )

        assert result.is_valid is True
        assert result.actual_dimension == 8192

    def test_valid_dense_embedding(self, validator: EmbeddingValidator) -> None:
        """Test valid dense embedding passes validation."""
        values = [0.1] * 1024
        result = validator.validate_embedding(
            values=values,
            entity_type="job",
            collection_version="v1",
            embedding_type="dense",
        )

        assert result.is_valid is True
        assert result.actual_dimension == 1024

    def test_valid_colbert_embedding(self, validator: EmbeddingValidator) -> None:
        """Test valid ColBERT token embedding passes validation."""
        values = [0.1] * 48
        result = validator.validate_embedding(
            values=values,
            entity_type="job",
            collection_version="v1",
            embedding_type="colbert",
        )

        assert result.is_valid is True
        assert result.actual_dimension == 48

    def test_case_insensitive_embedding_type(self, validator: EmbeddingValidator) -> None:
        """Test embedding type is case insensitive."""
        values = [0.1] * 1024
        result = validator.validate_embedding(
            values=values,
            entity_type="job",
            collection_version="v1",
            embedding_type="DENSE",
        )

        assert result.is_valid is True

    def test_stale_collection_version_raises_error(self, validator: EmbeddingValidator) -> None:
        """Test stale collection_version raises StaleDataError."""
        values = [0.1] * 1024
        with pytest.raises(StaleDataError):
            validator.validate_embedding(
                values=values,
                entity_type="job",
                collection_version="v99",
                embedding_type="dense",
            )

    def test_invalid_dimension_raises_error(self, validator: EmbeddingValidator) -> None:
        """Test invalid dimension raises ValidationError."""
        values = [0.1] * 512
        with pytest.raises(ValidationError):
            validator.validate_embedding(
                values=values,
                entity_type="job",
                collection_version="v1",
                embedding_type="dense",
            )

    def test_unknown_embedding_type_raises_error(self, validator: EmbeddingValidator) -> None:
        """Test unknown embedding type raises ValidationError."""
        values = [0.1] * 1024
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_embedding(
                values=values,
                entity_type="job",
                collection_version="v1",
                embedding_type="unknown",
            )

        assert exc_info.value.field_name == "embedding_type"
        assert exc_info.value.invalid_value == "unknown"

    def test_validation_without_raising(self, validator: EmbeddingValidator) -> None:
        """Test validation returns result without raising."""
        values = [0.1] * 512
        result = validator.validate_embedding(
            values=values,
            entity_type="job",
            collection_version="v1",
            embedding_type="dense",
            raise_on_error=False,
        )

        assert result.is_valid is False

    @pytest.mark.parametrize(
        "values",
        [
            [True] * 1024,
            ["not-a-number"] * 1024,
            [float("nan")] * 1024,
            [float("inf")] * 1024,
        ],
        ids=["boolean", "string", "nan", "infinity"],
    )
    def test_malformed_embedding_values_raise_validation_error(
        self,
        validator: EmbeddingValidator,
        values: list[object],
    ) -> None:
        """Only finite real-valued tensors cross the manifest validation boundary."""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_embedding(
                values=cast("list[float]", values),
                entity_type="job",
                collection_version="v1",
                embedding_type="dense",
            )

        assert exc_info.value.field_name == "embedding_values"

    @pytest.mark.parametrize(
        ("values", "collection_version"),
        [
            (["not-a-number"] * 1024, "v1"),
            ([0.1] * 1024, "v2"),
        ],
        ids=["malformed-values", "stale-version"],
    )
    def test_complete_validation_reports_invalid_without_raising(
        self,
        validator: EmbeddingValidator,
        values: list[object],
        collection_version: str,
    ) -> None:
        """Non-raising validation preserves malformed-value and stale-version failures."""
        result = validator.validate_embedding(
            values=cast("list[float]", values),
            entity_type="job",
            collection_version=collection_version,
            embedding_type="dense",
            raise_on_error=False,
        )

        assert result.is_valid is False
        assert result.actual_dimension == 1024


class TestEmbeddingValidationResult:
    """Test EmbeddingValidationResult dataclass."""

    def test_result_is_frozen_dataclass(self) -> None:
        """Test result is a frozen dataclass."""
        import dataclasses

        assert dataclasses.is_dataclass(EmbeddingValidationResult)
        params = getattr(EmbeddingValidationResult, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_result_fields(self) -> None:
        """Test result has expected fields."""
        result = EmbeddingValidationResult(
            is_valid=False,
            expected_dimension=1024,
            actual_dimension=768,
            entity_type="job",
            collection_version="v1",
        )

        assert result.is_valid is False
        assert result.expected_dimension == 1024
        assert result.actual_dimension == 768
        assert result.entity_type == "job"
        assert result.collection_version == "v1"
