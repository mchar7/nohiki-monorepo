"""Embedding validation against the semantic representation manifest."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real

from nohiki_common_exceptions import StaleDataError, ValidationError

from nohiki_ml_manifest.manifest import SemanticRepresentationManifest


@dataclass(frozen=True, slots=True)
class EmbeddingValidationResult:
    """Outcome of a single embedding validation check."""

    is_valid: bool
    expected_dimension: int
    actual_dimension: int
    entity_type: str
    collection_version: str


class EmbeddingValidator:
    """Validates embedding dimensions and collection versions against the manifest.

    Attributes:
        manifest: The manifest instance used for validation.

    """

    __slots__ = ("_manifest",)

    def __init__(self, manifest: SemanticRepresentationManifest) -> None:
        """Initialise with a manifest instance.

        Args:
            manifest: Source of truth for expected dimensions and versions.

        """
        self._manifest = manifest

    @property
    def manifest(self) -> SemanticRepresentationManifest:
        """Return the underlying manifest."""
        return self._manifest

    @property
    def expected_muvera_dimension(self) -> int:
        """Expected MUVERA FDE dimension."""
        return self._manifest.muvera_output_dimension

    @property
    def expected_dense_dimension(self) -> int:
        """Expected dense embedding dimension."""
        return self._manifest.dense.embedding_dim

    @property
    def expected_colbert_token_dim(self) -> int:
        """Expected ColBERT per-token dimension."""
        return self._manifest.late_interaction.token_dim

    def validate_collection_version(
        self,
        entity_type: str,
        collection_version: str,
        *,
        raise_on_mismatch: bool = True,
    ) -> bool:
        """Check that *collection_version* matches the manifest for *entity_type*.

        Args:
            entity_type: Entity kind (``"job"``, ``"profile"``, ``"skill"``).
            collection_version: Version string from the embedding payload.
            raise_on_mismatch: Raise ``StaleDataError`` on mismatch.

        Returns:
            ``True`` if the version matches, ``False`` if it does not and
            *raise_on_mismatch* is ``False``.

        Raises:
            StaleDataError: When versions diverge and *raise_on_mismatch* is ``True``.

        """
        expected = self._manifest.get_entity_version(entity_type)
        if collection_version != expected:
            if raise_on_mismatch:
                raise StaleDataError(
                    resource_type="EmbeddingVector",
                    resource_id=f"{entity_type}:{collection_version}",
                    message=(
                        f"Embedding collection_version mismatch for {entity_type}: "
                        f"got '{collection_version}', expected '{expected}'"
                    ),
                )
            return False
        return True

    def validate_muvera_dimension(self, actual_dimension: int, *, raise_on_mismatch: bool = True) -> bool:
        """Validate a MUVERA FDE vector's dimension.

        Args:
            actual_dimension: The actual MUVERA FDE vector length.
            raise_on_mismatch: Raise ``ValidationError`` on mismatch.

        Returns:
            ``True`` if the dimension matches, ``False`` otherwise.

        Raises:
            ValidationError: If dimensions diverge and *raise_on_mismatch* is ``True``.

        """
        expected = self.expected_muvera_dimension
        if actual_dimension != expected and raise_on_mismatch:
            raise ValidationError(
                field_name="embedding_dimension",
                invalid_value=actual_dimension,
                constraint=(
                    f"MUVERA dimension must be {expected} "
                    f"(2^{self._manifest.muvera.k_sim} * "
                    f"{self._manifest.muvera.dim_proj} * "
                    f"{self._manifest.muvera.r_reps})"
                ),
            )
        return actual_dimension == expected

    def validate_dense_dimension(self, actual_dimension: int, *, raise_on_mismatch: bool = True) -> bool:
        """Validate a dense embedding vector's dimension.

        Args:
            actual_dimension: The actual dense embedding vector length.
            raise_on_mismatch: Raise ``ValidationError`` on mismatch.

        Returns:
            ``True`` if the dimension matches, ``False`` otherwise.

        Raises:
            ValidationError: If dimensions diverge and *raise_on_mismatch* is ``True``.

        """
        expected = self.expected_dense_dimension
        if actual_dimension != expected and raise_on_mismatch:
            raise ValidationError(
                field_name="embedding_dimension",
                invalid_value=actual_dimension,
                constraint=f"Dense dimension must be {expected}",
            )
        return actual_dimension == expected

    def validate_colbert_token_dimension(self, actual_dimension: int, *, raise_on_mismatch: bool = True) -> bool:
        """Validate a ColBERT token embedding dimension.

        Args:
            actual_dimension: The actual token dimension.
            raise_on_mismatch: Raise ``ValidationError`` on mismatch.

        Raises:
            ValidationError: If dimensions diverge and *raise_on_mismatch* is ``True``.

        """
        expected = self.expected_colbert_token_dim
        if actual_dimension != expected and raise_on_mismatch:
            raise ValidationError(
                field_name="token_dimension",
                invalid_value=actual_dimension,
                constraint=f"ColBERT token dimension must be {expected}",
            )
        return actual_dimension == expected

    def validate_embedding(
        self,
        values: list[float],
        entity_type: str,
        collection_version: str,
        embedding_type: str,
        *,
        raise_on_error: bool = True,
    ) -> EmbeddingValidationResult:
        """Run all validations for a complete embedding representation.

        Args:
            values: The embedding vector values.
            entity_type: Entity kind.
            collection_version: Version string from the embedding payload.
            embedding_type: One of ``"muvera"``, ``"dense"``, ``"colbert"``.
            raise_on_error: Raise on the first validation failure.

        Raises:
            StaleDataError: On collection version mismatch.
            ValidationError: On dimension mismatch or unknown type.

        """
        collection_valid = self.validate_collection_version(
            entity_type,
            collection_version,
            raise_on_mismatch=raise_on_error,
        )
        values_valid = isinstance(values, list) and all(
            isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value)) for value in values
        )
        if not values_valid and raise_on_error:
            raise ValidationError(
                field_name="embedding_values",
                invalid_value="non-finite or non-numeric values",
                constraint="Must be a list of finite real numbers",
            )

        actual_dim = len(values) if isinstance(values, list) else 0
        expected_dim, dimension_valid = self._validate_dimension_by_type(
            embedding_type,
            actual_dim,
            raise_on_error=raise_on_error,
        )
        return EmbeddingValidationResult(
            is_valid=collection_valid and values_valid and dimension_valid,
            expected_dimension=expected_dim,
            actual_dimension=actual_dim,
            entity_type=entity_type,
            collection_version=collection_version,
        )

    def _validate_dimension_by_type(
        self,
        embedding_type: str,
        actual_dim: int,
        *,
        raise_on_error: bool,
    ) -> tuple[int, bool]:
        """Dispatch dimension validation to the correct method by embedding type."""
        match embedding_type.lower():
            case "muvera":
                return self.expected_muvera_dimension, self.validate_muvera_dimension(
                    actual_dim,
                    raise_on_mismatch=raise_on_error,
                )
            case "dense":
                return self.expected_dense_dimension, self.validate_dense_dimension(
                    actual_dim,
                    raise_on_mismatch=raise_on_error,
                )
            case "colbert":
                return self.expected_colbert_token_dim, self.validate_colbert_token_dimension(
                    actual_dim,
                    raise_on_mismatch=raise_on_error,
                )
            case _:
                raise ValidationError(
                    field_name="embedding_type",
                    invalid_value=embedding_type,
                    constraint="Must be one of: muvera, dense, colbert",
                )
