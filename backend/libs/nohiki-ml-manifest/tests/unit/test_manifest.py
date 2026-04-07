"""Unit tests for SemanticRepresentationManifest with per-collection versioning."""

import json
from collections.abc import Generator
from pathlib import Path

import pytest
from nohiki_ml_manifest import (
    CollectionConfig,
    CollectionsConfig,
    DenseConfig,
    ManifestCache,
    QdrantCollectionSchema,
    QdrantSparseConfig,
    QdrantVectorDefinition,
    SemanticRepresentationManifest,
)
from nohiki_ml_manifest.encoding import (
    DenseNormalizationConfig,
    LateInteractionConfig,
    MaxSimNormalizationConfig,
    MuveraConfig,
    SparseConfig,
    SparseNormalizationConfig,
)
from pydantic import ValidationError


def _create_minimal_collections() -> CollectionsConfig:
    """Create minimal valid collections config for testing."""
    qdrant_schema = QdrantCollectionSchema(
        vectors={"muvera": QdrantVectorDefinition(size=8192, distance="Dot")},
        sparse=QdrantSparseConfig(),
        primary_dense_name="muvera",
    )
    dense_schema = QdrantCollectionSchema(
        vectors={"default": QdrantVectorDefinition(size=1024, distance="Cosine")},
        primary_dense_name="default",
    )
    return CollectionsConfig(
        jobs=CollectionConfig(version="v1", qdrant=qdrant_schema),
        profiles=CollectionConfig(version="v1", qdrant=qdrant_schema),
        skills=CollectionConfig(version="v1", qdrant=dense_schema),
        occupations=CollectionConfig(version="v1", qdrant=dense_schema),
    )


class TestManifestInitialization:
    """Tests for manifest construction and field access."""

    def test_manifest_initialization(self, sample_manifest_data: dict) -> None:
        """Test manifest initialization with valid data."""
        manifest = SemanticRepresentationManifest(**sample_manifest_data)

        assert manifest.collections.jobs.version == "v1"
        assert manifest.collections.profiles.version == "v1"
        assert manifest.collections.skills.version == "v1"
        assert manifest.late_interaction.model_id == "mixedbread-ai/mxbai-edge-colbert-v0-17m"
        assert manifest.late_interaction.token_dim == 48
        assert manifest.muvera.k_sim == 6
        assert manifest.muvera.dim_proj == 16
        assert manifest.muvera.r_reps == 8
        assert manifest.sparse.enabled is True

    def test_manifest_muvera_output_dimension_computed(self) -> None:
        """Test muvera_output_dimension is computed from MUVERA parameters."""
        manifest = SemanticRepresentationManifest(collections=_create_minimal_collections())
        assert manifest.muvera_output_dimension == 8192

        manifest2 = SemanticRepresentationManifest(
            collections=_create_minimal_collections(),
            muvera=MuveraConfig(k_sim=5, dim_proj=32, r_reps=4),
        )
        assert manifest2.muvera_output_dimension == 4096

    def test_deployed_manifest_stales_profiles_without_reindexing_jobs(self) -> None:
        manifest = SemanticRepresentationManifest.load_from_path(
            Path(__file__).parents[5] / "data/config/semantic_representation_manifest.json"
        )

        assert manifest.collections.profiles.version == "v2"
        assert manifest.get_collection_name("profile") == "profiles_v2"
        assert manifest.collections.jobs.version == "v1"
        assert manifest.get_collection_name("job") == "jobs_v1"


class TestManifestLoadFromPath:
    """Tests for load_from_path classmethod."""

    def test_load_from_path(self, tmp_path: Path, sample_manifest_data: dict) -> None:
        """Test loading manifest directly from path."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(sample_manifest_data))

        manifest = SemanticRepresentationManifest.load_from_path(manifest_path)

        assert manifest.collections.jobs.version == "v1"

    def test_load_from_path_missing(self, tmp_path: Path) -> None:
        """Test load_from_path with non-existent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Manifest file not found"):
            SemanticRepresentationManifest.load_from_path(tmp_path / "missing.json")

    def test_load_from_path_invalid_json(self, tmp_path: Path) -> None:
        """Test loading invalid JSON raises ValueError."""
        manifest_path = tmp_path / "invalid.json"
        manifest_path.write_text("not valid json")

        with pytest.raises(ValueError, match="Failed to load manifest"):
            SemanticRepresentationManifest.load_from_path(manifest_path)

    def test_load_from_path_with_dense_normalization(self, tmp_path: Path, sample_manifest_data: dict) -> None:
        """Test loading manifest from JSON with dense normalization."""
        sample_manifest_data["dense"] = {
            "enabled": True,
            "model_id": "TechWolf/JobBERT-v2",
            "normalization": {
                "auto_match_threshold": 0.85,
                "uncertain_min_threshold": 0.55,
                "calibration": {
                    "calibration_model_id": "TechWolf/JobBERT-v2",
                    "calibration_pairs_count": 100,
                    "calibration_date": "2026-01-01",
                    "max_fp_similarity": 0.80,
                },
            },
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(sample_manifest_data))

        manifest = SemanticRepresentationManifest.load_from_path(manifest_path)
        assert manifest.dense.normalization.auto_match_threshold == pytest.approx(0.85)
        assert manifest.dense.normalization.uncertain_min_threshold == pytest.approx(0.55)
        assert manifest.dense.normalization.calibration is not None
        assert manifest.dense.normalization.calibration.calibration_pairs_count == 100


class TestEntityResolution:
    """Tests for entity type resolution (string and enum)."""

    def test_get_entity_version(self) -> None:
        """Test get_entity_version returns correct version for each entity type."""
        dense_schema = QdrantCollectionSchema(
            vectors={"default": QdrantVectorDefinition(size=1024)}, primary_dense_name="default"
        )
        collections = CollectionsConfig(
            jobs=CollectionConfig(
                version="v2",
                qdrant=QdrantCollectionSchema(
                    vectors={"muvera": QdrantVectorDefinition(size=8192)}, primary_dense_name="muvera"
                ),
            ),
            profiles=CollectionConfig(
                version="v3",
                qdrant=QdrantCollectionSchema(
                    vectors={"muvera": QdrantVectorDefinition(size=8192)}, primary_dense_name="muvera"
                ),
            ),
            skills=CollectionConfig(version="v1", qdrant=dense_schema),
            occupations=CollectionConfig(version="v4", qdrant=dense_schema),
        )
        manifest = SemanticRepresentationManifest(collections=collections)

        assert manifest.get_entity_version("job") == "v2"
        assert manifest.get_entity_version("jobs") == "v2"
        assert manifest.get_entity_version("profile") == "v3"
        assert manifest.get_entity_version("profiles") == "v3"
        assert manifest.get_entity_version("skill") == "v1"
        assert manifest.get_entity_version("skills") == "v1"
        assert manifest.get_entity_version("occupation") == "v4"
        assert manifest.get_entity_version("occupations") == "v4"

    def test_get_entity_version_with_enum(self) -> None:
        """Test get_entity_version works with EntityType enum."""
        from nohiki.ml.v1 import EntityType

        manifest = SemanticRepresentationManifest(collections=_create_minimal_collections())

        assert manifest.get_entity_version(EntityType.JOB) == "v1"
        assert manifest.get_entity_version(EntityType.PROFILE) == "v1"
        assert manifest.get_entity_version(EntityType.SKILL) == "v1"
        assert manifest.get_entity_version(EntityType.OCCUPATION) == "v1"

    def test_get_entity_version_invalid(self) -> None:
        """Test get_entity_version raises ValueError for unknown entity type."""
        manifest = SemanticRepresentationManifest(collections=_create_minimal_collections())

        with pytest.raises(ValueError, match="Unknown entity type"):
            manifest.get_entity_version("unknown")

    def test_get_collection_name(self) -> None:
        """Test get_collection_name returns correct collection name."""
        dense_schema = QdrantCollectionSchema(
            vectors={"default": QdrantVectorDefinition(size=1024)}, primary_dense_name="default"
        )
        collections = CollectionsConfig(
            jobs=CollectionConfig(
                version="v2",
                qdrant=QdrantCollectionSchema(
                    vectors={"muvera": QdrantVectorDefinition(size=8192)}, primary_dense_name="muvera"
                ),
            ),
            profiles=CollectionConfig(
                version="v1",
                qdrant=QdrantCollectionSchema(
                    vectors={"muvera": QdrantVectorDefinition(size=8192)}, primary_dense_name="muvera"
                ),
            ),
            skills=CollectionConfig(version="v3", qdrant=dense_schema),
            occupations=CollectionConfig(version="v2", qdrant=dense_schema),
        )
        manifest = SemanticRepresentationManifest(collections=collections)

        assert manifest.get_collection_name("job") == "jobs_v2"
        assert manifest.get_collection_name("profile") == "profiles_v1"
        assert manifest.get_collection_name("skill") == "skills_v3"
        assert manifest.get_collection_name("occupation") == "occupations_v2"

    def test_get_collection_config(self) -> None:
        """Test get_collection_config returns correct config."""
        manifest = SemanticRepresentationManifest(collections=_create_minimal_collections())

        job_config = manifest.get_collection_config("job")
        assert job_config.version == "v1"
        assert "muvera" in job_config.qdrant.vectors


class TestQdrantCollectionSchema:
    """Tests for QdrantCollectionSchema role-reference validation."""

    def test_valid_schema_with_primary_dense_name(self) -> None:
        """Test valid schema where primary_dense_name references an existing vector."""
        schema = QdrantCollectionSchema(
            vectors={"muvera": QdrantVectorDefinition(size=8192)},
            primary_dense_name="muvera",
        )
        assert schema.primary_dense_name == "muvera"

    def test_primary_dense_name_not_in_vectors_raises(self) -> None:
        """Test that primary_dense_name referencing a non-existent vector raises ValueError."""
        with pytest.raises(ValidationError, match="primary_dense_name"):
            QdrantCollectionSchema(
                vectors={"muvera": QdrantVectorDefinition(size=8192)},
                primary_dense_name="nonexistent",
            )

    def test_colbert_name_not_in_vectors_raises(self) -> None:
        """Test that colbert_name referencing a non-existent vector raises ValueError."""
        with pytest.raises(ValidationError, match="colbert_name"):
            QdrantCollectionSchema(
                vectors={"muvera": QdrantVectorDefinition(size=8192)},
                primary_dense_name="muvera",
                colbert_name="nonexistent",
            )

    def test_colbert_name_without_multivector_config_raises(self) -> None:
        """Test that colbert_name pointing to a vector without multivector_config raises ValueError."""
        with pytest.raises(ValidationError, match="multivector_config"):
            QdrantCollectionSchema(
                vectors={"colbert": QdrantVectorDefinition(size=48)},
                primary_dense_name="colbert",
                colbert_name="colbert",
            )

    def test_valid_schema_with_colbert_and_multivector_config(self) -> None:
        """Test valid schema where colbert_name has multivector_config."""
        schema = QdrantCollectionSchema(
            vectors={
                "muvera": QdrantVectorDefinition(size=8192),
                "colbert": QdrantVectorDefinition(
                    size=48,
                    multivector_config={"comparator": "max_sim"},
                ),
            },
            primary_dense_name="muvera",
            colbert_name="colbert",
        )
        assert schema.colbert_name == "colbert"


class TestCollectionVersionValidation:
    """Tests for collection version format validation."""

    def test_invalid_version_missing_prefix(self) -> None:
        r"""Test collection version must match pattern ^v\d+$."""
        with pytest.raises(ValidationError):
            CollectionConfig(
                version="1",
                qdrant=QdrantCollectionSchema(
                    vectors={"muvera": QdrantVectorDefinition(size=8192)}, primary_dense_name="muvera"
                ),
            )

    def test_invalid_version_wrong_format(self) -> None:
        """Test version rejects wrong format."""
        with pytest.raises(ValidationError):
            CollectionConfig(
                version="version1",
                qdrant=QdrantCollectionSchema(
                    vectors={"muvera": QdrantVectorDefinition(size=8192)}, primary_dense_name="muvera"
                ),
            )

    def test_valid_versions(self) -> None:
        """Test valid version strings are accepted."""
        CollectionConfig(
            version="v1",
            qdrant=QdrantCollectionSchema(
                vectors={"muvera": QdrantVectorDefinition(size=8192)}, primary_dense_name="muvera"
            ),
        )
        CollectionConfig(
            version="v999",
            qdrant=QdrantCollectionSchema(
                vectors={"muvera": QdrantVectorDefinition(size=8192)}, primary_dense_name="muvera"
            ),
        )


class TestManifestNumericBoundaries:
    """Reject nonsensical dimensions, timeouts, and admission thresholds."""

    @pytest.mark.parametrize(
        ("config_type", "kwargs"),
        [
            (QdrantVectorDefinition, {"size": 0}),
            (QdrantSparseConfig, {"full_scan_threshold": 0}),
            (LateInteractionConfig, {"token_dim": 0}),
            (LateInteractionConfig, {"max_length": 0}),
            (LateInteractionConfig, {"tei_timeout_seconds": 0}),
            (MuveraConfig, {"k_sim": 0}),
            (DenseConfig, {"embedding_dim": 0}),
            (DenseConfig, {"max_length": 0}),
            (DenseConfig, {"tei_timeout_seconds": 0}),
        ],
        ids=[
            "qdrant-vector-size",
            "qdrant-scan-threshold",
            "colbert-token-dimension",
            "colbert-max-length",
            "colbert-tei-timeout",
            "muvera-projection-count",
            "dense-dimension",
            "dense-max-length",
            "dense-tei-timeout",
        ],
    )
    def test_nonpositive_values_are_rejected(self, config_type: type, kwargs: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            config_type(**kwargs)


class TestNormalizationConfigs:
    """Tests for normalization config schemas."""

    def test_maxsim_normalization_defaults(self) -> None:
        """Test MaxSim normalization config defaults match production-calibrated values."""
        manifest = SemanticRepresentationManifest(collections=_create_minimal_collections())
        norm = manifest.late_interaction.normalization

        assert norm.per_token_sim_p5 == pytest.approx(0.8634)
        assert norm.per_token_sim_p95 == pytest.approx(0.9999)
        assert norm.per_token_sim_mean == pytest.approx(0.9355)
        assert norm.per_token_sim_std == pytest.approx(0.0396)
        assert norm.averaged_score_min == pytest.approx(0.92)
        assert norm.averaged_score_max == pytest.approx(0.95)
        assert norm.averaged_score_range == pytest.approx(0.03)
        assert norm.calibration is None

    def test_maxsim_normalization_custom(self) -> None:
        """Test MaxSim normalization with custom values."""
        manifest = SemanticRepresentationManifest(
            collections=_create_minimal_collections(),
            late_interaction=LateInteractionConfig(
                normalization=MaxSimNormalizationConfig(
                    per_token_sim_p5=0.85,
                    per_token_sim_p95=0.99,
                    averaged_score_min=0.90,
                    averaged_score_max=0.96,
                ),
            ),
        )
        norm = manifest.late_interaction.normalization

        assert norm.per_token_sim_p5 == pytest.approx(0.85)
        assert norm.per_token_sim_p95 == pytest.approx(0.99)
        assert norm.averaged_score_min == pytest.approx(0.90)
        assert norm.averaged_score_max == pytest.approx(0.96)
        assert norm.averaged_score_range == pytest.approx(0.06)

    def test_sparse_normalization_defaults(self) -> None:
        """Test SparseNormalizationConfig defaults."""
        manifest = SemanticRepresentationManifest(collections=_create_minimal_collections())
        norm = manifest.sparse.normalization

        assert norm.score_p10 == pytest.approx(1.5)
        assert norm.score_p90 == pytest.approx(5.5)
        assert norm.score_range == pytest.approx(4.0)

    def test_sparse_normalization_custom(self) -> None:
        """Test SparseNormalizationConfig with custom values."""
        manifest = SemanticRepresentationManifest(
            collections=_create_minimal_collections(),
            sparse=SparseConfig(normalization=SparseNormalizationConfig(score_p10=2.0, score_p90=8.0)),
        )
        norm = manifest.sparse.normalization

        assert norm.score_p10 == pytest.approx(2.0)
        assert norm.score_p90 == pytest.approx(8.0)
        assert norm.score_range == pytest.approx(6.0)

    def test_sparse_normalization_validation(self) -> None:
        """Test SparseNormalizationConfig validates bounds."""
        with pytest.raises(ValidationError):
            SparseNormalizationConfig(score_p10=-1.0)


class TestDenseNormalizationConfig:
    """Tests for DenseNormalizationConfig."""

    def test_default_values(self) -> None:
        """Test that default threshold values are correct."""
        config = DenseNormalizationConfig()
        assert config.auto_match_threshold == pytest.approx(0.83)
        assert config.uncertain_min_threshold == pytest.approx(0.50)
        assert config.calibration is None

    def test_auto_match_threshold_bounds_valid(self) -> None:
        """Test that auto_match_threshold accepts valid boundary values."""
        DenseNormalizationConfig(auto_match_threshold=0.0)
        DenseNormalizationConfig(auto_match_threshold=1.0)

    def test_auto_match_threshold_bounds_invalid_high(self) -> None:
        """Test that auto_match_threshold rejects values above 1.0."""
        with pytest.raises(ValidationError):
            DenseNormalizationConfig(auto_match_threshold=1.5)

    def test_auto_match_threshold_bounds_invalid_low(self) -> None:
        """Test that auto_match_threshold rejects values below 0.0."""
        with pytest.raises(ValidationError):
            DenseNormalizationConfig(auto_match_threshold=-0.1)

    def test_uncertain_min_threshold_bounds_valid(self) -> None:
        """Test that uncertain_min_threshold accepts valid boundary values."""
        DenseNormalizationConfig(uncertain_min_threshold=0.0)
        DenseNormalizationConfig(uncertain_min_threshold=1.0)

    def test_uncertain_min_threshold_bounds_invalid_high(self) -> None:
        """Test that uncertain_min_threshold rejects values above 1.0."""
        with pytest.raises(ValidationError):
            DenseNormalizationConfig(uncertain_min_threshold=1.1)

    def test_uncertain_min_threshold_bounds_invalid_low(self) -> None:
        """Test that uncertain_min_threshold rejects values below 0.0."""
        with pytest.raises(ValidationError):
            DenseNormalizationConfig(uncertain_min_threshold=-0.5)

    def test_custom_thresholds(self) -> None:
        """Test that custom threshold values are accepted."""
        config = DenseNormalizationConfig(
            auto_match_threshold=0.90,
            uncertain_min_threshold=0.60,
        )
        assert config.auto_match_threshold == pytest.approx(0.90)
        assert config.uncertain_min_threshold == pytest.approx(0.60)


class TestDenseConfigWithNormalization:
    """Tests for DenseConfig with embedded normalization."""

    def test_normalization_included_by_default(self) -> None:
        """Test that normalization is included in DenseConfig by default."""
        config = DenseConfig()
        assert config.normalization is not None
        assert isinstance(config.normalization, DenseNormalizationConfig)
        assert config.normalization.auto_match_threshold == pytest.approx(0.83)

    def test_custom_normalization(self) -> None:
        """Test that custom normalization can be provided."""
        config = DenseConfig(
            normalization=DenseNormalizationConfig(
                auto_match_threshold=0.90,
                uncertain_min_threshold=0.55,
            ),
        )
        assert config.normalization.auto_match_threshold == pytest.approx(0.90)
        assert config.normalization.uncertain_min_threshold == pytest.approx(0.55)

    def test_serialization_includes_normalization(self) -> None:
        """Test that serialization includes normalization object."""
        config = DenseConfig()
        data = config.model_dump()
        assert "normalization" in data
        assert data["normalization"]["auto_match_threshold"] == pytest.approx(0.83)
        assert "calibration" in data["normalization"]
        assert data["normalization"]["calibration"] is None

    def test_dense_config_defaults(self) -> None:
        """Test DenseConfig retains all expected defaults."""
        config = DenseConfig()
        assert config.enabled is True
        assert config.model_id == "TechWolf/JobBERT-v2"
        assert config.embedding_dim == 1024
        assert config.max_length == 64
        assert config.trust_remote_code is False
        assert config.normalization is not None


class TestSemanticRepresentationManifestWithDenseNormalization:
    """Tests for full manifest loading with dense normalization."""

    def test_manifest_loads_dense_normalization(self) -> None:
        """Test that manifest default loads dense normalization."""
        manifest = SemanticRepresentationManifest(collections=_create_minimal_collections())
        assert manifest.dense.normalization is not None
        assert manifest.dense.normalization.auto_match_threshold == pytest.approx(0.83)
        assert manifest.dense.normalization.uncertain_min_threshold == pytest.approx(0.50)

    def test_manifest_custom_dense_normalization(self) -> None:
        """Test that manifest accepts custom dense normalization."""
        manifest = SemanticRepresentationManifest(
            collections=_create_minimal_collections(),
            dense=DenseConfig(
                normalization=DenseNormalizationConfig(
                    auto_match_threshold=0.85,
                    uncertain_min_threshold=0.45,
                ),
            ),
        )
        assert manifest.dense.normalization.auto_match_threshold == pytest.approx(0.85)
        assert manifest.dense.normalization.uncertain_min_threshold == pytest.approx(0.45)

    def test_manifest_dense_normalization_serialization(self) -> None:
        """Test that manifest serialization includes dense normalization."""
        manifest = SemanticRepresentationManifest(collections=_create_minimal_collections())
        data = manifest.model_dump()
        assert "dense" in data
        assert "normalization" in data["dense"]
        assert data["dense"]["normalization"]["auto_match_threshold"] == pytest.approx(0.83)


class TestManifestCache:
    """Tests for ManifestCache singleton caching."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self) -> Generator[None]:
        """Ensure cache is clean before and after each test."""
        ManifestCache.reset()
        yield
        ManifestCache.reset()

    def test_get_loads_manifest_from_path(self, tmp_path: Path, sample_manifest_data: dict) -> None:
        """Test that get() loads a manifest from the given path."""
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(sample_manifest_data))

        result = ManifestCache.get(manifest_file)

        assert isinstance(result, SemanticRepresentationManifest)
        assert result.collections.jobs.version == "v1"

    def test_get_caches_on_repeated_calls(self, tmp_path: Path, sample_manifest_data: dict) -> None:
        """Test that get() returns the same cached instance on subsequent calls."""
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(sample_manifest_data))

        first = ManifestCache.get(manifest_file)
        second = ManifestCache.get(manifest_file)

        assert first is second

    def test_get_ignores_path_after_first_load(self, tmp_path: Path, sample_manifest_data: dict) -> None:
        """Test that path argument is ignored once manifest is cached."""
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(sample_manifest_data))

        first = ManifestCache.get(manifest_file)
        second = ManifestCache.get(tmp_path / "nonexistent.json")

        assert first is second

    def test_get_raises_on_missing_file(self, tmp_path: Path) -> None:
        """Test that get() raises FileNotFoundError for a missing manifest file."""
        with pytest.raises(FileNotFoundError, match="Manifest file not found"):
            ManifestCache.get(tmp_path / "missing.json")

    def test_reset_clears_cache(self, tmp_path: Path, sample_manifest_data: dict) -> None:
        """Test that reset() clears the cached instance."""
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(sample_manifest_data))

        first = ManifestCache.get(manifest_file)
        ManifestCache.reset()
        second = ManifestCache.get(manifest_file)

        assert first is not second
        assert isinstance(second, SemanticRepresentationManifest)

    def test_get_accepts_string_path(self, tmp_path: Path, sample_manifest_data: dict) -> None:
        """Test that get() accepts a string path in addition to Path objects."""
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(sample_manifest_data))

        result = ManifestCache.get(str(manifest_file))

        assert isinstance(result, SemanticRepresentationManifest)
