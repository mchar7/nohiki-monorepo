"""Benchmarks for individual FeatureGroup implementations.

The scoring pipeline runs 9 FeatureGroups sequentially per candidate.
These benchmarks measure each group's extract() cost in isolation using
realistic protobuf data, inlined to avoid the service's heavy import chain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from numpy.typing import NDArray

from nohiki_ml_manifest.features import FEATURE_COUNT

_EPSILON = 1e-10
_REQUIRED_SKILL_THRESHOLD = 5


# Lightweight stubs that mirror the protobuf field access patterns
# used by FeatureGroups, without importing the actual protos.


@dataclass
class _Coordinates:
    latitude: float = 0.0
    longitude: float = 0.0


@dataclass
class _Location:
    city: str | None = None
    state_province: str | None = None
    country: int = 0
    location_type: int = 0
    coordinates: _Coordinates | None = None


@dataclass
class _MonetaryAmount:
    minor_units: int = 0


@dataclass
class _CompensationBound:
    amount: _MonetaryAmount = field(default_factory=_MonetaryAmount)


@dataclass
class _Compensation:
    fixed_amount: _CompensationBound | None = None
    min_amount: _CompensationBound | None = None
    max_amount: _CompensationBound | None = None
    frequency: int = 0


@dataclass
class _SalaryPreference:
    min_salary: _MonetaryAmount | None = None
    target_salary: _MonetaryAmount | None = None


@dataclass
class _ExperiencePreference:
    experience_years: int | None = None
    seniority_levels: list[int] = field(default_factory=list)


@dataclass
class _DenseVector:
    values: list[float] = field(default_factory=list)


@dataclass
class _EmbeddingVector:
    dense: _DenseVector | None = None


@dataclass
class _UserSkillEntry:
    skill_id: str = ""
    proficiency: int = 0
    provenance: int = 0
    provenance_confidence: float = 1.0


@dataclass
class _SkillRequirement:
    skill_id: str = ""
    is_required: bool = True
    proficiency_level: int = 0


@dataclass
class _ListingStub:
    """Minimal listing stub with fields accessed by FeatureGroups."""

    location: _Location | None = None
    work_arrangement: int = 0
    seniority_level: int = 0
    experience_years_min: int | None = None
    experience_years_max: int | None = None
    compensation: _Compensation | None = None
    title_embedding: _EmbeddingVector | None = None
    skills_embedding: _EmbeddingVector | None = None
    skill_requirements: list[_SkillRequirement] = field(default_factory=list)
    required_skills: list[str] = field(default_factory=list)
    posted_at: object = None


@dataclass
class _ProfileStub:
    """Minimal profile stub with fields accessed by FeatureGroups."""

    physical_locations: list[_Location] = field(default_factory=list)
    remote_locations: list[_Location] = field(default_factory=list)
    work_arrangements: list[int] = field(default_factory=list)
    open_to_relocation: bool = False
    experience_preference: _ExperiencePreference | None = None
    salary_preference: _SalaryPreference | None = None
    query_embedding: _EmbeddingVector | None = None
    user_skills_embedding: _EmbeddingVector | None = None
    user_skills: list[_UserSkillEntry] = field(default_factory=list)


# Inline feature extraction logic (copies of the actual FeatureGroup.extract
# implementations to avoid service import chain)


def _extract_pipeline_features(
    features: NDArray[np.float32],
    maxsim_score: float,
    rerank_score: float,
) -> None:
    """Pipeline score extraction (indices 0-1)."""
    features[0] = maxsim_score
    features[1] = rerank_score


def _extract_experience_features(
    features: NDArray[np.float32],
    profile: _ProfileStub,
    listing: _ListingStub,
) -> None:
    """Experience extraction (indices 6-10)."""
    exp_pref = profile.experience_preference
    user_years = exp_pref.experience_years if exp_pref else None
    user_seniority_prefs = exp_pref.seniority_levels if exp_pref else []

    job_min = listing.experience_years_min
    job_max = listing.experience_years_max
    job_seniority = listing.seniority_level

    features[6] = float(user_years) if user_years is not None else math.nan
    features[7] = float(job_min) if job_min is not None else math.nan
    features[8] = float(job_max) if job_max is not None else math.nan

    if user_seniority_prefs:
        features[9] = float(max(user_seniority_prefs))
    else:
        features[9] = math.nan

    if job_seniority != 0:
        features[10] = float(job_seniority)
    else:
        features[10] = math.nan


def _extract_salary_features(
    features: NDArray[np.float32],
    profile: _ProfileStub,
    listing: _ListingStub,
) -> None:
    """Salary extraction (indices 11-13)."""
    sal_pref = profile.salary_preference
    compensation = listing.compensation

    if sal_pref:
        features[11] = float(sal_pref.min_salary.minor_units) if sal_pref.min_salary else math.nan
        features[12] = float(sal_pref.target_salary.minor_units) if sal_pref.target_salary else math.nan
    else:
        features[11] = math.nan
        features[12] = math.nan

    if compensation and compensation.fixed_amount:
        features[13] = float(compensation.fixed_amount.amount.minor_units)
    else:
        features[13] = math.nan


def _extract_work_arrangement_features(
    features: NDArray[np.float32],
    profile: _ProfileStub,
    listing: _ListingStub,
) -> None:
    """Work arrangement extraction (index 24)."""
    profile_arrangements = profile.work_arrangements
    job_arrangement = listing.work_arrangement

    if job_arrangement == 0 or not profile_arrangements:
        features[24] = math.nan
    else:
        features[24] = 1.0 if job_arrangement in profile_arrangements else 0.0


def _extract_validity_flags(features: NDArray[np.float32]) -> None:
    """Validity flags extraction (indices 25-29)."""
    features[25] = 0.0 if math.isnan(features[2]) else 1.0  # HAS_LOCATION_DATA
    features[26] = 0.0 if (math.isnan(features[7]) and math.isnan(features[8])) else 1.0  # HAS_EXPERIENCE_DATA
    features[27] = 0.0 if math.isnan(features[13]) else 1.0  # HAS_SALARY_DATA
    features[28] = 1.0 if features[19] > 0 else 0.0  # HAS_SKILL_DATA (SKILL_TOTAL_REQUIRED)
    features[29] = 0.0  # HAS_LISTING_QUALITY (reserved)


def _cosine_similarity_inline(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(vec_a) != len(vec_b):
        return math.nan
    a = np.asarray(vec_a, dtype=np.float64)
    b = np.asarray(vec_b, dtype=np.float64)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < _EPSILON or norm_b < _EPSILON:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _extract_semantic_features(
    features: NDArray[np.float32],
    profile: _ProfileStub,
    listing: _ListingStub,
) -> None:
    """Semantic similarity extraction (indices 20-21)."""
    title_emb = listing.title_embedding
    job_title_vals = title_emb.dense.values if title_emb and title_emb.dense else None
    q_emb = profile.query_embedding
    query_vals = q_emb.dense.values if q_emb and q_emb.dense else None

    if job_title_vals is not None and query_vals is not None:
        features[20] = _cosine_similarity_inline(job_title_vals, query_vals)
    else:
        features[20] = math.nan

    js_emb = listing.skills_embedding
    job_skills_vals = js_emb.dense.values if js_emb and js_emb.dense else None
    us_emb = profile.user_skills_embedding
    user_skills_vals = us_emb.dense.values if us_emb and us_emb.dense else None

    if job_skills_vals is not None and user_skills_vals is not None:
        features[21] = _cosine_similarity_inline(job_skills_vals, user_skills_vals)
    else:
        features[21] = math.nan


# Skill matching (inlined from skill_match_quality.py)

_PROFICIENCY_WEIGHTS = {0: 0.2, 1: 0.4, 2: 0.6, 3: 0.8, 4: 1.0}
_PROVENANCE_WEIGHTS = {0: 0.3, 1: 1.0, 2: 0.8, 3: 0.6, 4: 0.5}


def _compute_skill_match(
    user_skills: list[_UserSkillEntry],
    job_requirements: list[_SkillRequirement],
) -> tuple[int, int, int, float, float]:
    """Compute skill match metrics. Returns (matched, missing, total, prof_score, prov_score)."""
    if not job_requirements:
        return 0, 0, 0, math.nan, math.nan

    user_map = {s.skill_id: s for s in user_skills}
    matches: list[tuple[_SkillRequirement, _UserSkillEntry | None]] = [
        (req, user_map[req.skill_id]) for req in job_requirements if req.skill_id in user_map
    ]

    if not matches:
        return 0, len(job_requirements), len(job_requirements), 0.0, 0.0

    total_prof = 0.0
    total_prov = 0.0
    total_w = 0.0

    for req, user_skill in matches:
        w = 1.5 if req.is_required else 1.0
        total_w += w
        if user_skill is not None:
            base = _PROFICIENCY_WEIGHTS.get(user_skill.proficiency, 0.5)
            prov = _PROVENANCE_WEIGHTS.get(user_skill.provenance, 0.5) * user_skill.provenance_confidence
        else:
            base = 0.6
            prov = 0.5
        total_prof += base * w
        total_prov += prov * w

    missing = len(job_requirements) - len(matches)

    return (
        len(matches),
        missing,
        len(job_requirements),
        total_prof / total_w,
        total_prov / total_w,
    )


def _extract_skill_features(
    features: NDArray[np.float32],
    profile: _ProfileStub,
    listing: _ListingStub,
) -> None:
    """Skill extraction (indices 14-19)."""
    matched, missing, total, prof, prov = _compute_skill_match(profile.user_skills, listing.skill_requirements)
    features[14] = float(matched)
    features[15] = float(missing)
    features[16] = float(total)
    features[17] = prof if not math.isnan(prof) else math.nan
    features[18] = prov if not math.isnan(prov) else math.nan
    features[19] = 0.0  # relationship count (no cache in benchmark)


# Fixtures


@pytest.fixture
def realistic_listing() -> _ListingStub:
    """Realistic listing with all fields populated."""
    rng = np.random.default_rng(42)
    return _ListingStub(
        location=_Location(
            city="San Francisco",
            state_province="CA",
            country=840,
            coordinates=_Coordinates(latitude=37.7749, longitude=-122.4194),
        ),
        work_arrangement=2,  # HYBRID
        seniority_level=3,  # SENIOR
        experience_years_min=5,
        experience_years_max=10,
        compensation=_Compensation(
            fixed_amount=_CompensationBound(amount=_MonetaryAmount(minor_units=18000000)),
        ),
        title_embedding=_EmbeddingVector(dense=_DenseVector(values=rng.standard_normal(384).tolist())),
        skills_embedding=_EmbeddingVector(dense=_DenseVector(values=rng.standard_normal(384).tolist())),
        skill_requirements=[
            _SkillRequirement(
                skill_id=f"skill-{i}",
                is_required=i < _REQUIRED_SKILL_THRESHOLD,
                proficiency_level=min(i, 4),
            )
            for i in range(8)
        ],
    )


@pytest.fixture
def realistic_profile() -> _ProfileStub:
    """Realistic profile with all fields populated."""
    rng = np.random.default_rng(43)
    return _ProfileStub(
        physical_locations=[
            _Location(
                city="San Francisco",
                state_province="CA",
                country=840,
                coordinates=_Coordinates(latitude=37.7749, longitude=-122.4194),
            ),
            _Location(
                city="New York",
                state_province="NY",
                country=840,
                coordinates=_Coordinates(latitude=40.7128, longitude=-74.0060),
            ),
        ],
        work_arrangements=[2, 3],  # HYBRID, REMOTE
        open_to_relocation=False,
        experience_preference=_ExperiencePreference(experience_years=7, seniority_levels=[3, 4]),
        salary_preference=_SalaryPreference(
            min_salary=_MonetaryAmount(minor_units=15000000),
            target_salary=_MonetaryAmount(minor_units=20000000),
        ),
        query_embedding=_EmbeddingVector(dense=_DenseVector(values=rng.standard_normal(384).tolist())),
        user_skills_embedding=_EmbeddingVector(dense=_DenseVector(values=rng.standard_normal(384).tolist())),
        user_skills=[
            _UserSkillEntry(
                skill_id=f"skill-{i}",
                proficiency=min(i + 1, 4),
                provenance=1,
                provenance_confidence=0.9,
            )
            for i in range(10)
        ],
    )


# Individual FeatureGroup benchmarks


def test_bench_pipeline_scores_extract(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark PipelineFeatureGroup.extract (indices 0-1)."""
    features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)

    def extract() -> None:
        _extract_pipeline_features(features, maxsim_score=0.78, rerank_score=0.65)

    benchmark(extract)


def test_bench_experience_extract(
    benchmark: pytest.BenchmarkFixture,
    realistic_profile: _ProfileStub,
    realistic_listing: _ListingStub,
) -> None:
    """Benchmark ExperienceFeatureGroup.extract (indices 6-10)."""
    features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
    benchmark(_extract_experience_features, features, realistic_profile, realistic_listing)


def test_bench_salary_extract(
    benchmark: pytest.BenchmarkFixture,
    realistic_profile: _ProfileStub,
    realistic_listing: _ListingStub,
) -> None:
    """Benchmark SalaryFeatureGroup.extract (indices 11-13)."""
    features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
    benchmark(_extract_salary_features, features, realistic_profile, realistic_listing)


def test_bench_skill_extract(
    benchmark: pytest.BenchmarkFixture,
    realistic_profile: _ProfileStub,
    realistic_listing: _ListingStub,
) -> None:
    """Benchmark SkillFeatureGroup.extract with 10 user skills x 8 requirements."""
    features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
    benchmark(_extract_skill_features, features, realistic_profile, realistic_listing)


def test_bench_semantic_extract(
    benchmark: pytest.BenchmarkFixture,
    realistic_profile: _ProfileStub,
    realistic_listing: _ListingStub,
) -> None:
    """Benchmark SemanticFeatureGroup.extract with 384-dim embeddings."""
    features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
    benchmark(_extract_semantic_features, features, realistic_profile, realistic_listing)


def test_bench_work_arrangement_extract(
    benchmark: pytest.BenchmarkFixture,
    realistic_profile: _ProfileStub,
    realistic_listing: _ListingStub,
) -> None:
    """Benchmark WorkArrangementFeatureGroup.extract (index 24)."""
    features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
    benchmark(
        _extract_work_arrangement_features,
        features,
        realistic_profile,
        realistic_listing,
    )


def test_bench_validity_flags_extract(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark ValidityFlagsFeatureGroup.extract (indices 25-29)."""
    rng = np.random.default_rng(42)
    features = rng.standard_normal(FEATURE_COUNT).astype(np.float32)
    features[2] = 45.0  # DISTANCE_KM
    features[7] = 5.0  # JOB_EXPERIENCE_MIN
    features[8] = 10.0  # JOB_EXPERIENCE_MAX
    features[13] = 18000000.0  # JOB_SALARY
    features[19] = 8.0  # SKILL_TOTAL_REQUIRED
    features[23] = math.nan  # LISTING_QUALITY_SCORE (reserved)
    features[30] = 2.5  # SKILL_GRAPH_MIN_DISTANCE sentinel
    benchmark(_extract_validity_flags, features)
    np.testing.assert_allclose(features[[29, 30]], [0.0, 2.5])


# Full composer simulation (all groups sequentially)


def test_bench_full_feature_extraction(
    benchmark: pytest.BenchmarkFixture,
    realistic_profile: _ProfileStub,
    realistic_listing: _ListingStub,
) -> None:
    """Benchmark full 9-group feature extraction pipeline for one candidate."""

    def extract_all() -> NDArray[np.float32]:
        features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
        _extract_pipeline_features(features, maxsim_score=0.78, rerank_score=0.65)
        # Location skipped (requires geo-utils with real coordinates)
        _extract_experience_features(features, realistic_profile, realistic_listing)
        _extract_salary_features(features, realistic_profile, realistic_listing)
        _extract_skill_features(features, realistic_profile, realistic_listing)
        _extract_semantic_features(features, realistic_profile, realistic_listing)
        _extract_work_arrangement_features(features, realistic_profile, realistic_listing)
        features[21] = 72.0  # JOB_AGE_HOURS stub
        features[22] = 0.0  # LISTING_FEEDBACK_COUNT (reserved)
        features[23] = math.nan  # LISTING_QUALITY_SCORE (reserved)
        _extract_validity_flags(features)
        return features

    features = benchmark(extract_all)
    np.testing.assert_allclose(features[[22, 29]], [0.0, 0.0])
    np.testing.assert_equal(features[23], math.nan)


def test_bench_full_feature_extraction_batch_150(
    benchmark: pytest.BenchmarkFixture,
    realistic_profile: _ProfileStub,
    realistic_listing: _ListingStub,
) -> None:
    """Benchmark full feature extraction for 150 candidates (typical batch)."""

    def extract_batch() -> NDArray[np.float32]:
        vectors = []
        for _ in range(150):
            features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
            _extract_pipeline_features(features, maxsim_score=0.78, rerank_score=0.65)
            _extract_experience_features(features, realistic_profile, realistic_listing)
            _extract_salary_features(features, realistic_profile, realistic_listing)
            _extract_skill_features(features, realistic_profile, realistic_listing)
            _extract_semantic_features(features, realistic_profile, realistic_listing)
            _extract_work_arrangement_features(features, realistic_profile, realistic_listing)
            features[21] = 72.0  # JOB_AGE_HOURS stub
            features[22] = 0.0  # LISTING_FEEDBACK_COUNT (reserved)
            features[23] = math.nan  # LISTING_QUALITY_SCORE (reserved)
            _extract_validity_flags(features)
            vectors.append(features)
        return np.stack(vectors)

    vectors = benchmark(extract_batch)
    np.testing.assert_array_equal(vectors[:, 22], 0.0)
    np.testing.assert_array_equal(vectors[:, 23], np.full(150, math.nan, dtype=np.float32))
    np.testing.assert_array_equal(vectors[:, 29], 0.0)
