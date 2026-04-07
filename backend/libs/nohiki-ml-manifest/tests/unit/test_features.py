"""Unit tests for L2R feature schema in nohiki-ml-manifest."""

from __future__ import annotations

from nohiki_ml_manifest import (
    CRITICAL_FEATURES,
    FEATURE_COUNT,
    FEATURE_DESCRIPTIONS,
    FEATURE_NAME_LIST,
    FEATURE_NAMES,
    MONOTONE_CONSTRAINTS,
    FeatureIndex,
)


class TestFeatureIndex:
    """Tests for FeatureIndex enum."""

    def test_feature_count_matches_enum_length(self) -> None:
        """FEATURE_COUNT must match actual enum member count."""
        assert FEATURE_COUNT == 32
        assert len(FeatureIndex) == FEATURE_COUNT

    def test_all_indices_contiguous(self) -> None:
        """Feature indices must be contiguous starting from 0."""
        indices = sorted(member.value for member in FeatureIndex)
        assert indices == list(range(FEATURE_COUNT))

    def test_pipeline_scores_at_start(self) -> None:
        """Pipeline scores must be at indices 0-1."""
        assert FeatureIndex.MAXSIM_SCORE == 0
        assert FeatureIndex.RERANK_SCORE == 1

    def test_location_features(self) -> None:
        """Location features must be at indices 2-5."""
        assert FeatureIndex.DISTANCE_KM == 2
        assert FeatureIndex.IS_SAME_CITY == 3
        assert FeatureIndex.IS_REMOTE_JOB == 4
        assert FeatureIndex.USER_OPEN_TO_RELOCATION == 5

    def test_experience_features(self) -> None:
        """Experience features must be at indices 6-10."""
        assert FeatureIndex.USER_EXPERIENCE_YEARS == 6
        assert FeatureIndex.JOB_EXPERIENCE_MIN == 7
        assert FeatureIndex.JOB_EXPERIENCE_MAX == 8
        assert FeatureIndex.USER_SENIORITY_LEVEL == 9
        assert FeatureIndex.JOB_SENIORITY_LEVEL == 10

    def test_salary_features(self) -> None:
        """Salary features must be at indices 11-13."""
        assert FeatureIndex.USER_MIN_SALARY == 11
        assert FeatureIndex.USER_TARGET_SALARY == 12
        assert FeatureIndex.JOB_SALARY == 13

    def test_skill_features(self) -> None:
        """Skill features must be at indices 14-19."""
        assert FeatureIndex.SKILL_MATCH_COUNT == 14
        assert FeatureIndex.SKILL_MISSING_COUNT == 15
        assert FeatureIndex.SKILL_TOTAL_REQUIRED == 16
        assert FeatureIndex.SKILL_AVG_PROFICIENCY == 17
        assert FeatureIndex.SKILL_AVG_PROVENANCE == 18
        assert FeatureIndex.SKILL_RELATIONSHIP_COUNT == 19

    def test_semantic_features(self) -> None:
        """Semantic features must be at index 20."""
        assert FeatureIndex.SKILLS_COSINE_SIM == 20

    def test_job_metadata_features(self) -> None:
        """Job metadata features must be at indices 21-24."""
        assert FeatureIndex.JOB_AGE_HOURS == 21
        assert FeatureIndex.LISTING_FEEDBACK_COUNT == 22
        assert FeatureIndex.LISTING_QUALITY_SCORE == 23
        assert FeatureIndex.WORK_ARRANGEMENT_MATCH == 24

    def test_validity_flags(self) -> None:
        """Validity flags must be at indices 25-29."""
        assert FeatureIndex.HAS_LOCATION_DATA == 25
        assert FeatureIndex.HAS_EXPERIENCE_DATA == 26
        assert FeatureIndex.HAS_SALARY_DATA == 27
        assert FeatureIndex.HAS_SKILL_DATA == 28
        assert FeatureIndex.HAS_LISTING_QUALITY == 29

    def test_skill_graph_distance_features(self) -> None:
        """Skill graph distance features must be at indices 30-31."""
        assert FeatureIndex.SKILL_GRAPH_MIN_DISTANCE == 30
        assert FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE == 31

    def test_title_cosine_sim_removed(self) -> None:
        """TITLE_COSINE_SIM was removed from the schema; guard against regression."""
        assert not hasattr(FeatureIndex, "TITLE_COSINE_SIM")
        assert "title_cosine_sim" not in FEATURE_NAMES.values()


class TestFeatureNames:
    """Tests for FEATURE_NAMES mapping."""

    def test_all_features_have_names(self) -> None:
        """Every FeatureIndex must have a name."""
        for feature in FeatureIndex:
            assert feature in FEATURE_NAMES, f"Missing name for {feature.name}"

    def test_names_are_snake_case(self) -> None:
        """All feature names must be snake_case (lowercase with underscores)."""
        for name in FEATURE_NAMES.values():
            assert name == name.lower()
            assert " " not in name

    def test_no_duplicate_names(self) -> None:
        """Feature names must be unique."""
        names = list(FEATURE_NAMES.values())
        assert len(names) == len(set(names))

    def test_feature_name_list_length(self) -> None:
        """FEATURE_NAME_LIST must have FEATURE_COUNT entries."""
        assert len(FEATURE_NAME_LIST) == FEATURE_COUNT

    def test_feature_name_list_order(self) -> None:
        """FEATURE_NAME_LIST must be ordered by FeatureIndex value."""
        for i, name in enumerate(FEATURE_NAME_LIST):
            assert name == FEATURE_NAMES[FeatureIndex(i)]


class TestFeatureDescriptions:
    """Tests for FEATURE_DESCRIPTIONS mapping."""

    def test_all_features_have_descriptions(self) -> None:
        """Every FeatureIndex must have a description."""
        for feature in FeatureIndex:
            assert feature in FEATURE_DESCRIPTIONS, f"Missing description for {feature.name}"

    def test_descriptions_not_empty(self) -> None:
        """Descriptions must not be empty."""
        for feature, desc in FEATURE_DESCRIPTIONS.items():
            assert desc.strip(), f"Empty description for {feature.name}"


class TestMonotoneConstraints:
    """Tests for MONOTONE_CONSTRAINTS list."""

    def test_constraints_length_matches_feature_count(self) -> None:
        """MONOTONE_CONSTRAINTS must have exactly FEATURE_COUNT entries."""
        assert len(MONOTONE_CONSTRAINTS) == FEATURE_COUNT

    def test_constraints_are_valid_values(self) -> None:
        """All constraints must be -1, 0, or 1."""
        for i, constraint in enumerate(MONOTONE_CONSTRAINTS):
            assert constraint in (-1, 0, 1), f"Invalid constraint at index {i}: {constraint}"

    def test_distance_km_negative_monotonic(self) -> None:
        """DISTANCE_KM should be negative monotonic (closer is better)."""
        assert MONOTONE_CONSTRAINTS[FeatureIndex.DISTANCE_KM] == -1

    def test_job_age_hours_negative_monotonic(self) -> None:
        """JOB_AGE_HOURS should be negative monotonic (fresher is better)."""
        assert MONOTONE_CONSTRAINTS[FeatureIndex.JOB_AGE_HOURS] == -1

    def test_skill_match_count_positive_monotonic(self) -> None:
        """SKILL_MATCH_COUNT should be positive monotonic (more matches better)."""
        assert MONOTONE_CONSTRAINTS[FeatureIndex.SKILL_MATCH_COUNT] == 1

    def test_skill_missing_count_negative_monotonic(self) -> None:
        """SKILL_MISSING_COUNT should be negative monotonic (fewer missing better)."""
        assert MONOTONE_CONSTRAINTS[FeatureIndex.SKILL_MISSING_COUNT] == -1


class TestCriticalFeatures:
    """Tests for CRITICAL_FEATURES set."""

    def test_critical_features_are_valid_feature_names(self) -> None:
        """All critical feature names must be valid feature names."""
        valid_names = set(FEATURE_NAMES.values())
        for name in CRITICAL_FEATURES:
            assert name in valid_names, f"Critical feature '{name}' not in FEATURE_NAMES"

    def test_maxsim_score_is_critical(self) -> None:
        """maxsim_score must be a critical feature."""
        assert "maxsim_score" in CRITICAL_FEATURES

    def test_rerank_score_is_critical(self) -> None:
        """rerank_score must be a critical feature."""
        assert "rerank_score" in CRITICAL_FEATURES

    def test_muvera_similarity_not_in_critical(self) -> None:
        """muvera_similarity must NOT be in critical features (it is not a valid feature name)."""
        assert "muvera_similarity" not in CRITICAL_FEATURES
